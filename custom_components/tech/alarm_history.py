"""Bounded, optional snapshots of a controller's alarm archive."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging
import math
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError

from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import ALARM_HISTORY_INTERVAL, ALARM_HISTORY_TIMEOUT, CONTROLLER, UDID
from .tech import TechError, TechLoginError

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import TechConfigEntry, TechCoordinator

_LOGGER = logging.getLogger(__name__)

LOOKBACK_DAYS = 365
DISPLAY_LIMIT = 10
TEXT_LIMIT = 256


def _empty_snapshot(status: str | None) -> dict[str, Any]:
    """Represent a failed read without turning it into an empty archive."""
    return {
        "status": status,
        "returned_count": None,
        "displayed_count": 0,
        "truncated": False,
        "chronology_complete": False,
        "ordering": None,
        "latest": None,
        "events": [],
    }


def _scalar(value: Any, limit: int = TEXT_LIMIT) -> str | int | float | None:
    """Accept bounded display scalars, retaining zero and rejecting booleans."""
    if value is None:
        return None
    if isinstance(value, str) and len(value) <= limit:
        return value
    if type(value) is int and value.bit_length() <= 64:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("Invalid alarm history scalar")


def _event(row: Any) -> dict[str, Any]:
    """Keep only the archive fields used for display, without source ids."""
    if not isinstance(row, dict):
        raise TypeError("Invalid alarm history row")
    category, start, clear, text_id = (
        row.get("alarmType"),
        row.get("startAlarm"),
        row.get("clearAlarm"),
        row.get("txtId"),
    )
    if (
        not isinstance(category, str)
        or not category.strip()
        or len(category) > 64
        or not isinstance(start, str)
        or not start.strip()
        or len(start) > 128
        or (clear is not None and (not isinstance(clear, str) or len(clear) > 128))
        or type(text_id) is not int
        or not 0 <= text_id <= 2**63 - 1
    ):
        raise ValueError("Invalid alarm history fields")
    return {
        "alarm_type": category,
        "start": start,
        "clear": clear,
        "txt_id": text_id,
        "value": _scalar(row.get("value")),
        "unit": _scalar(row.get("unit"), 64),
    }


def _aware_start(raw: str) -> datetime | None:
    """Use an event's own offset for ordering; never infer one from HA's zone."""
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.utcoffset() is not None:
            return parsed.astimezone(UTC)
    except ValueError, OverflowError:
        pass
    return None


def history_snapshot(payload: Any) -> dict[str, Any]:
    """Validate the whole response and expose at most ten rows, without dedupe."""
    if not isinstance(payload, list):
        raise TypeError("Alarm history must be an array")
    first: list[dict[str, Any]] = []
    newest: list[tuple[datetime, dict[str, Any]]] = []
    chronology_complete = True
    for row in payload:
        event = _event(row)
        if len(first) < DISPLAY_LIMIT:
            first.append(event)
        started = _aware_start(event["start"])
        if started is None:
            chronology_complete = False
        elif chronology_complete:
            newest.append((started, event))
            newest.sort(key=lambda item: item[0], reverse=True)
            del newest[DISPLAY_LIMIT:]
    events = [event for _, event in newest] if chronology_complete else first
    return {
        "status": "ready" if payload else "empty",
        "returned_count": len(payload),
        "displayed_count": len(events),
        "truncated": len(payload) > DISPLAY_LIMIT,
        "chronology_complete": chronology_complete,
        "ordering": "start_descending" if chronology_complete and payload else "source",
        "latest": dict(events[0]) if chronology_complete and events else None,
        "events": events,
    }


class TechAlarmHistoryCoordinator(DataUpdateCoordinator):
    """Poll the optional archive only while its diagnostic entity is enabled."""

    def __init__(
        self,
        hass: HomeAssistant,
        primary: TechCoordinator,
        config_entry: TechConfigEntry,
    ) -> None:
        """Reuse the account's client; let HA own scheduling and entry shutdown."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="Tech alarm history",
            update_interval=ALARM_HISTORY_INTERVAL,
        )
        self._primary = primary
        self._udid: str = config_entry.data[CONTROLLER][UDID]
        self._last_success: str | None = None
        self.data = _empty_snapshot(None)

    async def _async_update_data(self) -> dict[str, Any]:
        """Replace one archive window, keeping all failures local to history."""
        timezone_name = self.hass.config.time_zone
        today = datetime.now(ZoneInfo(timezone_name)).date()
        start = today - timedelta(days=LOOKBACK_DAYS)
        metadata: dict[str, Any] = {
            "request_from": start.isoformat(),
            "request_to": today.isoformat(),
            "window_timezone": timezone_name,
            "filter": "all",
            "lookback_days": LOOKBACK_DAYS,
            "last_attempt": datetime.now(UTC).isoformat(),
            "last_success": self._last_success,
        }
        http_status: int | None = None
        status = "error"
        try:
            async with asyncio.timeout(ALARM_HISTORY_TIMEOUT):
                payload = await self._primary.api.get_module_alarm_history(
                    self._udid, start, today
                )
            http_status = 200
            snapshot = history_snapshot(payload)
        except (TechError, TechLoginError) as err:
            # An optional endpoint rejecting the token must not start reauth
            # or change the primary coordinator's availability.
            http_status = err.status_code
            error_type = "http"
        except TimeoutError:
            error_type = "timeout"
        except ClientError:
            error_type = "network"
        except TypeError, ValueError, RecursionError, OverflowError:
            status = "invalid"
            error_type = "invalid_response"
        else:
            self._last_success = datetime.now(UTC).isoformat()
            return {
                **snapshot,
                **metadata,
                "last_success": self._last_success,
                "http_status": 200,
                "error_type": None,
            }

        # Expected optional-endpoint failures are data, so every attempt reaches
        # listeners, including consecutive failures. Raising UpdateFailed would
        # suppress those notifications after the first failed refresh.
        return {
            **_empty_snapshot(status),
            **metadata,
            "http_status": http_status,
            "error_type": error_type,
        }
