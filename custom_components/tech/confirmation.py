"""Confirm menu commands against fresh eModul observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Any

from aiohttp import ClientError

from homeassistant.exceptions import HomeAssistantError

from .tech import Tech, TechError

_COMMAND_TIMEOUT = 180.0
_POLL_INTERVAL = 15.0
_ACTIVE = {"sending", "pending"}

type MenuKey = tuple[str, int]


@dataclass(frozen=True)
class _Cursor:
    """A comparable timestamp, preserving the API's original encoding."""

    timestamp: datetime
    text: str

    @classmethod
    def parse(cls, value: object) -> _Cursor:
        """Parse a mandatory, timezone-aware cursor."""
        if not isinstance(value, str):
            raise TypeError("Missing menu update cursor")
        timestamp = datetime.fromisoformat(value)
        if timestamp.tzinfo is None:
            raise ValueError("Menu update cursor has no timezone")
        return cls(timestamp, value)


def _wire_value(value: object) -> int | float | None:
    if type(value) is int or (type(value) is float and math.isfinite(value)):
        return value
    return None


@dataclass
class MenuCommand:
    """A single request and the evidence for its outcome."""

    command_id: int
    key: MenuKey
    requested_value: int
    deadline: float
    notify: Callable[[MenuCommand], None] | None
    previous_command_id: int | None
    previous_status: str | None
    status: str = "sending"
    observed_value: int | float | None = None
    posted_at: datetime | None = None
    confirmed_at: datetime | None = None
    reason: str | None = None
    cursor: _Cursor | None = None
    timer: asyncio.TimerHandle | None = None

    def attributes(self) -> dict[str, Any]:
        """Expose the request and outcome of this generation."""
        return {
            "command_id": self.command_id,
            "command_status": self.status,
            "pending_confirm": self.status == "pending",
            "requested_value": self.requested_value,
            "observed_value": self.observed_value,
            "posted_at": self.posted_at.isoformat() if self.posted_at else None,
            "last_confirmed_at": (
                self.confirmed_at.isoformat() if self.confirmed_at else None
            ),
            "command_reason": self.reason,
            "previous_command_id": self.previous_command_id,
            "previous_command_status": self.previous_status,
        }

    def finish(self, status: str, reason: str | None = None) -> None:
        """Resolve an active request once and release its listener and timer."""
        if self.status not in _ACTIVE:
            return
        self.status = status
        self.reason = reason
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        notify, self.notify = self.notify, None
        if notify is not None:
            notify(self)


class MenuCommands:
    """Serialize writes per item and share one readback task per controller."""

    def __init__(self, api: Tech, udid: str) -> None:
        """Initialize an idle tracker for a config entry."""
        self._api = api
        self._udid = udid
        self._sequence = 0
        self._commands: dict[MenuKey, MenuCommand] = {}
        self._locks: dict[MenuKey, asyncio.Lock] = {}
        self._senders: dict[asyncio.Task[None], MenuKey] = {}
        self._worker: asyncio.Task[None] | None = None
        self._removing: set[MenuKey] = set()
        self._closed = False

    async def async_write(
        self, key: MenuKey, value: int, notify: Callable[[MenuCommand], None]
    ) -> None:
        """Send a request once and check the acknowledgement before returning."""
        if self._closed or key in self._removing:
            raise HomeAssistantError("The Tech menu control is being unloaded")
        previous = self._commands.get(key)
        if previous is not None:
            previous.finish("superseded", "newer_command")
        self._sequence += 1
        command = MenuCommand(
            self._sequence,
            key,
            value,
            asyncio.get_running_loop().time() + _COMMAND_TIMEOUT,
            notify,
            previous.command_id if previous else None,
            previous.status if previous else None,
        )
        self._commands[key] = command
        notify(command)
        sender = asyncio.create_task(self._async_send(command))
        self._senders[sender] = key
        try:
            await sender
        except asyncio.CancelledError:
            command.finish("error", "cancelled")
            raise
        finally:
            self._senders.pop(sender, None)

    async def _async_send(self, command: MenuCommand) -> None:
        key = command.key
        try:
            async with asyncio.timeout_at(command.deadline):
                async with self._locks.setdefault(key, asyncio.Lock()):
                    if command.status != "sending":
                        return
                    now = datetime.now(UTC)
                    command.cursor = _Cursor(now, now.isoformat())
                    reply = await self._api.set_menu_value(
                        self._udid, *key, {"value": command.requested_value}
                    )
        except TimeoutError:
            command.finish("timed_out", "deadline")
            raise HomeAssistantError("The Tech menu write timed out") from None
        except TechError, ClientError, ValueError:
            command.finish("error", "post_failed")
            raise HomeAssistantError("The Tech menu write failed") from None

        if command.status != "sending":
            return
        loop = asyncio.get_running_loop()
        if loop.time() >= command.deadline:
            command.finish("timed_out", "deadline")
            raise HomeAssistantError("The Tech menu write timed out")
        status = reply.get("status") if isinstance(reply, dict) else None
        if status == "success":
            command.status = "pending"
            command.posted_at = datetime.now(UTC)
            command.timer = loop.call_at(
                command.deadline, command.finish, "timed_out", "deadline"
            )
            if command.notify is not None:
                command.notify(command)
            self._start_worker()
            return
        if not isinstance(status, str):
            command.finish("error", "ambiguous_acknowledgement")
            raise HomeAssistantError("The Tech menu write did not return a status")
        command.finish("rejected", "api_rejected")
        raise HomeAssistantError("The Tech API rejected the menu write")

    def _pending(self) -> list[MenuCommand]:
        return [c for c in self._commands.values() if c.status == "pending"]

    def _start_worker(self) -> None:
        if self._worker is None or self._worker.done():
            self._worker = asyncio.create_task(self._async_poll())

    async def _async_poll(self) -> None:
        while self._pending():
            await asyncio.sleep(_POLL_INTERVAL)
            # Snapshot after the acknowledgement and before starting the GET.
            # An ACK arriving during this GET keeps its own cursor for replay.
            commands = self._pending()
            cursors = [c.cursor for c in commands if c.cursor is not None]
            if not cursors:
                return
            cursor = min(cursors, key=lambda entry: entry.timestamp)
            deadline = max(command.deadline for command in commands)
            try:
                async with asyncio.timeout_at(deadline):
                    reply = await self._api.get_menu_updates(self._udid, cursor.text)
                self._observe(reply, commands)
            except TechError, ClientError, TypeError, ValueError, TimeoutError:
                now = asyncio.get_running_loop().time()
                for command in commands:
                    if now >= command.deadline:
                        command.finish("timed_out", "deadline")
                    else:
                        command.finish("error", "poll_failed")

    @staticmethod
    def _observe(reply: object, commands: list[MenuCommand]) -> None:
        if not isinstance(reply, dict) or not isinstance(reply.get("menu"), list):
            raise TypeError("Invalid menu update response")
        cursor = _Cursor.parse(reply.get("lastUpdate"))
        now = asyncio.get_running_loop().time()
        for command in commands:
            if command.status != "pending" or command.cursor is None:
                continue
            if now >= command.deadline:
                command.finish("timed_out", "deadline")
                continue
            if cursor.timestamp <= command.cursor.timestamp:
                continue
            command.cursor = cursor
            candidates = [
                item
                for item in reply["menu"]
                if isinstance(item, dict)
                and (item.get("menuType"), item.get("id")) == command.key
            ]
            if len(candidates) != 1 or type(candidates[0]["id"]) is not int:
                continue
            _observe_item(command, candidates[0])

    async def async_remove(self, key: MenuKey) -> None:
        """Detach an entity and wait for its in-flight submissions to stop."""
        self._removing.add(key)
        try:
            command = self._commands.pop(key, None)
            if command is not None:
                command.notify = None
                command.finish("error", "removed")
            await _cancel_tasks(
                task for task, owned_key in self._senders.items() if owned_key == key
            )
            self._locks.pop(key, None)
            worker = self._worker
            if worker is not None and not self._pending():
                await _cancel_tasks((worker,))
                if self._pending() and not self._closed:
                    self._start_worker()
        finally:
            self._removing.discard(key)

    async def async_close(self) -> None:
        """Detach all listeners and stop work on an unloaded entry."""
        self._closed = True
        for command in self._commands.values():
            command.notify = None
            command.finish("error", "unloaded")
        self._commands.clear()
        tasks = list(self._senders)
        if self._worker is not None:
            tasks.append(self._worker)
            self._worker = None
        await _cancel_tasks(tasks)


def _observe_item(command: MenuCommand, item: dict[str, Any]) -> None:
    params = item.get("params")
    value = _wire_value(params.get("value")) if isinstance(params, dict) else None
    settling = item.get("duringChange")
    if settling is not False and settling != "f":
        if value is not None:
            command.observed_value = value
            if command.notify is not None:
                command.notify(command)
        return
    if value is None:
        command.finish("error", "invalid_observation")
        return
    command.observed_value = value
    if value == command.requested_value:
        command.confirmed_at = datetime.now(UTC)
        command.finish("confirmed")
    else:
        command.finish("mismatch", "different_value")


async def _cancel_tasks(tasks: Iterable[asyncio.Task[None]]) -> None:
    tasks = list(tasks)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
