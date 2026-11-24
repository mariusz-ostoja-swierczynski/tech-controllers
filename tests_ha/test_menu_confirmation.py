"""Exercise menu confirmation with a controlled API and real HA services."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import datetime, timedelta
import json
import time
from typing import Any
from unittest.mock import AsyncMock, Mock
from urllib.parse import unquote

from aiohttp import ClientError
from common import EMPTY_MENU, UDID, entry_for
import pytest

from custom_components.tech import confirmation
from custom_components.tech.confirmation import MenuCommands, MenuKey
from custom_components.tech.const import DOMAIN
from custom_components.tech.tech import Tech, TechError
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

CHOICE = ("MU", 801)
NUMBER = ("MU", 802)


def _item(
    key: MenuKey, value: Any, settling: Any = "f", **metadata: Any
) -> dict[str, Any]:
    return {
        "menuType": key[0],
        "id": key[1],
        "duringChange": settling,
        "params": {"value": value, **metadata},
    }


def _later(cursor: str) -> str:
    return (datetime.fromisoformat(cursor) + timedelta(seconds=30)).isoformat()


class FakeAPI:
    """Provide separately gated reads and recorded, simulated writes."""

    def __init__(self) -> None:
        """Use successful writes by default."""
        self.post = AsyncMock(return_value={"status": "success"})
        self.reads: asyncio.Queue[tuple[str, asyncio.Future]] = asyncio.Queue()

    async def poll(self, _udid: str, cursor: str) -> dict[str, Any]:
        """Expose the request cursor and wait for the test to answer it."""
        result = asyncio.get_running_loop().create_future()
        self.reads.put_nowait((cursor, result))
        return await result

    async def next_read(self) -> tuple[str, asyncio.Future]:
        """Wait for the worker to start its next read."""
        return await asyncio.wait_for(self.reads.get(), 2)


class Scenario:
    """Observe the tracker through its public submission and state callback."""

    def __init__(self) -> None:
        """Create a tracker using the fake transport."""
        self.api = FakeAPI()
        self.commands = MenuCommands(
            Mock(
                spec=Tech, set_menu_value=self.api.post, get_menu_updates=self.api.poll
            ),
            UDID,
        )
        self.states: dict[MenuKey, dict[str, Any]] = {}

    async def send(self, key: MenuKey = NUMBER, value: int = 25) -> None:
        """Submit a write and record snapshots of its diagnostic attributes."""
        await self.commands.async_write(
            key, value, lambda record: self.states.__setitem__(key, record.attributes())
        )


@pytest.fixture
async def scenario(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[Scenario]:
    """Allow deterministic readback without waiting the production interval."""
    monkeypatch.setattr(confirmation, "_POLL_INTERVAL", 0)
    scenario = Scenario()
    try:
        yield scenario
    finally:
        await scenario.commands.async_close()


@pytest.mark.parametrize("observed,status", [(25.0, "confirmed"), (19, "mismatch")])
async def test_only_fresh_settled_value_resolves_command(scenario, observed, status):
    """An old or settling response provides no confirmation."""
    await scenario.send()
    cursor, result = await scenario.api.next_read()
    result.set_result({"lastUpdate": cursor, "menu": [_item(NUMBER, 25)]})
    cursor, result = await scenario.api.next_read()
    assert scenario.states[NUMBER]["pending_confirm"]
    advancing = _later(cursor)
    result.set_result({"lastUpdate": advancing, "menu": [_item(NUMBER, 12, "t")]})
    cursor, result = await scenario.api.next_read()
    assert cursor == advancing
    assert scenario.states[NUMBER]["observed_value"] == 12
    assert scenario.states[NUMBER]["last_confirmed_at"] is None

    result.set_result(
        {"lastUpdate": _later(cursor), "menu": [_item(NUMBER, observed, False)]}
    )
    await asyncio.sleep(0)
    attrs = scenario.states[NUMBER]
    assert attrs["command_status"] == status
    assert attrs["requested_value"] == 25
    assert attrs["observed_value"] == observed
    assert bool(attrs["last_confirmed_at"]) == (status == "confirmed")
    assert attrs["posted_at"] and not attrs["pending_confirm"]
    scenario.api.post.assert_awaited_once_with(UDID, *NUMBER, {"value": 25})


@pytest.mark.parametrize(
    "items",
    [
        [_item(("MS", NUMBER[1]), 25)],
        [_item(NUMBER, 25), _item(NUMBER, 25)],
        [_item(NUMBER, 25), _item(("MU", float(NUMBER[1])), 25)],
        [_item(("MU", float(NUMBER[1])), 25)],
        [_item(NUMBER, 25, None)],
        [_item(NUMBER, 25, 0)],
        [_item(NUMBER, None, True)],
    ],
)
async def test_unmatched_ambiguous_or_unsettled_rows_stay_pending(scenario, items):
    """Ignore a row unless it uniquely identifies the settled target."""
    await scenario.send()
    cursor, result = await scenario.api.next_read()
    result.set_result({"lastUpdate": _later(cursor), "menu": items})
    await scenario.api.next_read()
    assert scenario.states[NUMBER]["command_status"] == "pending"
    assert scenario.states[NUMBER]["last_confirmed_at"] is None


@pytest.mark.parametrize("value", [None, True, float("nan"), float("inf"), "25"])
async def test_invalid_settled_values_cannot_confirm(scenario, value):
    """Reject invalid values even when a row says it has settled."""
    await scenario.send()
    cursor, result = await scenario.api.next_read()
    result.set_result({"lastUpdate": _later(cursor), "menu": [_item(NUMBER, value)]})
    await asyncio.sleep(0)
    assert scenario.states[NUMBER]["command_reason"] == "invalid_observation"
    assert scenario.states[NUMBER]["last_confirmed_at"] is None


@pytest.mark.parametrize(
    "reply",
    [
        None,
        {"menu": {}},
        {"menu": [], "lastUpdate": None},
        {"menu": [], "lastUpdate": "invalid"},
        {"menu": [], "lastUpdate": "2026-01-01"},
    ],
)
async def test_malformed_poll_fails_with_a_safe_reason(scenario, reply):
    """Reject malformed responses before looking for command evidence."""
    await scenario.send()
    _, result = await scenario.api.next_read()
    result.set_result(reply)
    await asyncio.sleep(0)
    assert scenario.states[NUMBER]["command_reason"] == "poll_failed"
    assert not scenario.states[NUMBER]["pending_confirm"]


@pytest.mark.parametrize(
    "reply,status,reason",
    [
        (None, "error", "ambiguous_acknowledgement"),
        ({"status": True}, "error", "ambiguous_acknowledgement"),
        ({"status": "refused"}, "rejected", "api_rejected"),
    ],
)
async def test_unsuccessful_ack_never_starts_readback(scenario, reply, status, reason):
    """Require the cloud to explicitly accept the POST."""
    scenario.api.post.return_value = reply
    with pytest.raises(HomeAssistantError, match="Tech"):
        await scenario.send()
    assert scenario.states[NUMBER]["command_status"] == status
    assert scenario.states[NUMBER]["command_reason"] == reason
    assert scenario.api.reads.empty()


@pytest.mark.parametrize("failure", [TechError(422, "private"), ClientError("private")])
async def test_post_failure_hides_response_and_never_retries(scenario, failure):
    """Report submission failure without surfacing the response body."""
    scenario.api.post.side_effect = failure
    with pytest.raises(HomeAssistantError, match="^The Tech menu write failed$"):
        await scenario.send()
    assert scenario.states[NUMBER]["command_reason"] == "post_failed"
    assert scenario.api.post.await_count == 1
    assert scenario.api.reads.empty()


async def test_an_ack_during_another_get_replays_its_delta(scenario):
    """A command accepted mid-read can recover its delta on a later read."""
    await scenario.send()
    first_cursor, first_read = await scenario.api.next_read()
    await scenario.send(CHOICE, 1)
    reply = {
        "lastUpdate": _later(first_cursor),
        "menu": [_item(NUMBER, 25), _item(CHOICE, 1)],
    }
    first_read.set_result(reply)
    second_cursor, second_read = await scenario.api.next_read()
    assert scenario.states[NUMBER]["command_status"] == "confirmed"
    assert scenario.states[CHOICE]["command_status"] == "pending"
    assert first_cursor < second_cursor < reply["lastUpdate"]
    second_read.set_result(reply)
    await asyncio.sleep(0)
    assert scenario.states[CHOICE]["command_status"] == "confirmed"


async def test_new_generation_ignores_older_in_flight_read(scenario):
    """A result for a superseded command cannot affect its successor."""
    await scenario.send()
    cursor, first = await scenario.api.next_read()
    await scenario.send(value=26)
    first.set_result({"lastUpdate": _later(cursor), "menu": [_item(NUMBER, 25)]})
    new_cursor, second = await scenario.api.next_read()
    attrs = scenario.states[NUMBER]
    assert attrs["previous_command_status"] == "superseded"
    assert attrs["previous_command_id"] == 1
    assert attrs["observed_value"] is None
    second.set_result({"lastUpdate": _later(new_cursor), "menu": [_item(NUMBER, 26)]})
    await asyncio.sleep(0)
    assert scenario.states[NUMBER]["command_status"] == "confirmed"
    assert scenario.states[NUMBER]["command_id"] == 2


async def test_serialized_writes_skip_a_superseded_queued_value(scenario):
    """Keep accepted writes in order and skip superseded queued writes."""
    ready = asyncio.Event()
    release = asyncio.Event()

    async def post(_udid, _menu_type, _item_id, payload):
        if payload["value"] == 25:
            ready.set()
            await release.wait()
        return {"status": "success"}

    scenario.api.post.side_effect = post
    first = asyncio.create_task(scenario.send())
    await ready.wait()
    queued = asyncio.create_task(scenario.send(value=26))
    await asyncio.sleep(0)
    latest = asyncio.create_task(scenario.send(value=27))
    await asyncio.sleep(0)
    assert scenario.api.post.await_count == 1
    release.set()
    await asyncio.gather(first, queued, latest)
    assert [call.args[-1]["value"] for call in scenario.api.post.await_args_list] == [
        25,
        27,
    ]
    assert scenario.states[NUMBER]["requested_value"] == 27


async def test_remove_cancels_sender_and_refuses_commands_after_close(scenario):
    """Removal drains the child's POST and the closed tracker stays closed."""
    started = asyncio.Event()

    async def post(*_args):
        started.set()
        await asyncio.Future()

    scenario.api.post.side_effect = post
    send = asyncio.create_task(scenario.send())
    await started.wait()
    await scenario.commands.async_remove(NUMBER)
    with pytest.raises(asyncio.CancelledError):
        await send
    assert scenario.api.reads.empty()
    await scenario.commands.async_close()
    with pytest.raises(HomeAssistantError, match="unloaded"):
        await scenario.send()


async def test_remove_drains_last_pending_read(scenario):
    """Removing the last participant cancels its in-flight read."""
    await scenario.send()
    _, read = await scenario.api.next_read()
    await scenario.commands.async_remove(NUMBER)
    assert read.cancelled()


async def test_deadline_covers_slow_post_and_pending_readback(scenario, monkeypatch):
    """Both a blocked write and a blocked read reach their deadline."""
    monkeypatch.setattr(confirmation, "_COMMAND_TIMEOUT", 0.1)

    async def slow_post(*_args):
        await asyncio.Future()

    scenario.api.post.side_effect = slow_post
    with pytest.raises(HomeAssistantError, match="timed out"):
        await scenario.send()
    assert scenario.states[NUMBER]["command_status"] == "timed_out"
    scenario.api.post.side_effect = None
    await scenario.send()
    _, read = await scenario.api.next_read()
    async with asyncio.timeout(2):
        while scenario.states[NUMBER]["pending_confirm"]:
            await asyncio.sleep(0.01)
    assert scenario.states[NUMBER]["command_status"] == "timed_out"
    assert read.cancelled()


@pytest.mark.parametrize("domain,key", [("select", CHOICE), ("number", NUMBER)])
async def test_home_assistant_services_publish_confirmation(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, domain: str, key: MenuKey
):
    """Test registration, actual service, PIN payload, and fresh readback."""
    api = FakeAPI()
    monkeypatch.setattr(confirmation, "_POLL_INTERVAL", 0)
    monkeypatch.setattr(Tech, "post", api.post)
    choice = {
        **_item(CHOICE, 0, options=[{"value": 0}, {"value": 1}]),
        "type": 11,
        "txtId": 801,
        "access": True,
    }
    number = {
        **_item(NUMBER, 200, format=2, min=100, max=300, jump=1),
        "type": 1,
        "txtId": 802,
        "access": True,
    }
    menus = {"data": {"elements": [choice, number]}}

    async def get(_self: Tech, path: str) -> dict[str, Any]:
        if "/update/data/" in path:
            assert "/parents/%5B%5D/alarm_ids/%5B%5D/" in path
            return await api.poll(UDID, unquote(path.rsplit("/", 1)[1]))
        if path.endswith("/menu/MU/"):
            return menus
        if "/menu/" in path:
            return EMPTY_MENU
        return {"zones": {"elements": []}, "tiles": []}

    monkeypatch.setattr(Tech, "get", get)
    entry = entry_for("Menu confirmation", menu_codes={"MU": "2468"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(domain, DOMAIN, f"{UDID}_menu_MU_{key[1]}")
    assert entity_id
    assert hass.states.get(entity_id).attributes["command_status"] == "idle"

    if domain == "select":
        service, data, requested, optimistic = "select_option", {"option": "1"}, 1, "1"
    else:
        service, data, requested, optimistic = (
            "set_value",
            {"value": 22.55},
            225,
            "22.5",
        )
    await hass.services.async_call(
        domain, service, {"entity_id": entity_id, **data}, blocking=True
    )
    (path, body), _ = api.post.await_args
    assert path.endswith(f"/menu/MU/ido/{key[1]}")
    assert json.loads(body) == {"pin": "2468", "value": requested}
    state = hass.states.get(entity_id)
    assert state.state == optimistic
    assert state.attributes["pending_confirm"]
    assert state.attributes["assumed_state"]

    coordinator = entry.runtime_data
    old = deepcopy(coordinator.data)
    coordinator.async_set_updated_data(deepcopy(old))
    assert hass.states.get(entity_id).state == optimistic

    cursor, result = await api.next_read()
    observed = 99 if domain == "select" else requested
    result.set_result({"lastUpdate": _later(cursor), "menu": [_item(key, observed)]})
    await asyncio.sleep(0)
    state = hass.states.get(entity_id)
    assert state.state == (STATE_UNKNOWN if domain == "select" else optimistic)
    assert state.attributes["command_status"] == (
        "mismatch" if domain == "select" else "confirmed"
    )
    assert state.attributes["observed_value"] == observed
    assert not state.attributes["pending_confirm"]

    coordinator.async_set_updated_data(old)
    assert hass.states.get(entity_id).state == state.state
    current = deepcopy(old)
    current["menu_read_started"] = time.monotonic()
    coordinator.async_set_updated_data(current)
    assert hass.states.get(entity_id).state == ("0" if domain == "select" else "20.0")
    assert await hass.config_entries.async_unload(entry.entry_id)
