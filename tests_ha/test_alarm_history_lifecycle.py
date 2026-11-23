"""Exercise the opt-in archive using real HA registry, states and scheduling."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from aiohttp import ClientConnectionError
from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant.common import MockConfigEntry, async_fire_time_changed

from custom_components.tech.alarm_history import TechAlarmHistoryCoordinator
from custom_components.tech.assets import Translations
from custom_components.tech.config_flow import ConfigFlow
from custom_components.tech.const import (
    ALARM_HISTORY_INTERVAL,
    CONTROLLER,
    DOMAIN,
    TYPE_TEMPERATURE,
    USER_ID,
    VER,
)
from custom_components.tech.sensor import AlarmHistorySensor
from custom_components.tech.tech import Tech, TechError, TechLoginError
from homeassistant.components.sensor import DATA_COMPONENT
from homeassistant.config_entries import RELOAD_AFTER_UPDATE_DELAY, ConfigEntryState
from homeassistant.const import CONF_TOKEN, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_UDID = "synthetic-alarm-controller"
_UNIQUE_ID = f"{_UDID}_alarm_history"
_ROW = {
    "id": 7,
    "alarmType": "alarm",
    "startAlarm": "2028-02-28T11:00:00+03:00",
    "clearAlarm": None,
    "txtId": 120,
    "value": 0,
    "unit": "°C",
}
_EMPTY_MENU = {"status": "success", "data": {"elements": []}}
_MODULE = {
    "tiles": [
        {
            "id": 1,
            "type": TYPE_TEMPERATURE,
            "visibility": True,
            "workingStatus": True,
            "params": {"value": 210},
        }
    ],
    "zones": {"elements": []},
}


def _entry() -> MockConfigEntry:
    """Describe one invented controller without account or household fixtures."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic controller",
        version=ConfigFlow.VERSION,
        unique_id=_UDID,
        data={
            USER_ID: "synthetic-user",
            CONF_TOKEN: "synthetic-token",
            CONTROLLER: {
                "id": 1,
                "name": "Synthetic controller",
                "udid": _UDID,
                "version": "1.0.0",
            },
            VER: "1.0.0: Synthetic controller",
        },
    )


async def _set_up(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    history: AsyncMock,
    *,
    enabled: bool = False,
    wait_initial: bool = True,
) -> tuple[MockConfigEntry, er.RegistryEntry]:
    """Set up the integration through HA with both API routes mocked."""

    async def _get(_self: Tech, path: str) -> dict[str, Any]:
        if path.startswith("i18n/"):
            return {"data": {"120": "Synthetic alarm title"}}
        if "/menu/" in path:
            return _EMPTY_MENU
        return _MODULE

    monkeypatch.setattr(Tech, "get", _get)
    monkeypatch.setattr(Tech, "get_module_alarm_history", history)
    post = AsyncMock(side_effect=AssertionError("Archive setup must never write"))
    monkeypatch.setattr(Tech, "post", post)
    entry = _entry()
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    if enabled:
        registry.async_get_or_create(
            "sensor", DOMAIN, _UNIQUE_ID, config_entry=entry, disabled_by=None
        )

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=wait_initial)

    entity_id = registry.async_get_entity_id("sensor", DOMAIN, _UNIQUE_ID)
    assert entity_id is not None
    row = registry.async_get(entity_id)
    assert row is not None
    post.assert_not_awaited()
    return entry, row


async def _advance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, delta: timedelta
) -> None:
    """Advance HA's timers without sleeping or using any real network."""
    freezer.tick(delta)
    async_fire_time_changed(hass, datetime.now(UTC))
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_disabled_registry_entry_does_not_fetch_even_when_primary_polls(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Register the diagnostic entity without spending any optional API reads."""
    freezer.move_to("2028-03-01T12:00:00+00:00")
    history = AsyncMock(return_value=[])
    entry, row = await _set_up(hass, monkeypatch, history)

    assert row.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert row.entity_category is EntityCategory.DIAGNOSTIC
    assert row.device_id == entry.runtime_data.controller_device_id
    assert hass.states.get(row.entity_id) is None
    history.assert_not_awaited()

    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL * 2)

    history.assert_not_awaited()
    assert entry.runtime_data.last_update_success
    assert entry.state is ConfigEntryState.LOADED


async def test_registry_enable_poll_disable_reenable_and_unload_own_the_polling(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Use HA's actual enable reload and timer cleanup, including re-enabling."""
    freezer.move_to("2028-03-01T12:00:00+00:00")
    history = AsyncMock(return_value=[])
    entry, row = await _set_up(hass, monkeypatch, history)
    registry = er.async_get(hass)

    registry.async_update_entity(row.entity_id, disabled_by=None)
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1))

    assert history.await_count == 1
    state = hass.states.get(row.entity_id)
    assert state is not None and state.state == "empty"
    assert state.attributes["returned_count"] == 0

    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL - timedelta(seconds=2))
    assert history.await_count == 1, "no archive read on the telemetry cadence"
    await _advance(hass, freezer, timedelta(seconds=4))
    assert history.await_count == 2

    registry.async_update_entity(
        row.entity_id, disabled_by=er.RegistryEntryDisabler.USER
    )
    await hass.async_block_till_done()
    assert hass.states.get(row.entity_id) is None
    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL * 2)
    assert history.await_count == 2

    registry.async_update_entity(row.entity_id, disabled_by=None)
    await hass.async_block_till_done()
    await _advance(hass, freezer, timedelta(seconds=RELOAD_AFTER_UPDATE_DELAY + 1))
    assert history.await_count == 3
    assert registry.async_get_entity_id("sensor", DOMAIN, _UNIQUE_ID) == row.entity_id

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    history.reset_mock()
    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL * 2)
    history.assert_not_awaited()


async def test_success_two_consecutive_failures_and_recovery_reach_the_ha_state(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Every failure replaces rows and metadata without reauth or telemetry loss."""
    freezer.move_to("2028-03-01T12:00:00+00:00")
    history = AsyncMock(
        side_effect=[
            [_ROW],
            TechError(503, "synthetic failure"),
            TechError(401, "synthetic failure"),
            [],
        ]
    )
    entry, row = await _set_up(hass, monkeypatch, history, enabled=True)
    state = hass.states.get(row.entity_id)
    assert state is not None and state.state == "ready"
    assert state.attributes["events"][0]["title"] == "Synthetic alarm title"
    assert state.attributes["events"][0]["start"] == _ROW["startAlarm"]
    last_success = state.attributes["last_success"]
    telemetry = [
        candidate.entity_id
        for candidate in er.async_get(hass).entities.values()
        if candidate.config_entry_id == entry.entry_id
        and candidate.entity_id != row.entity_id
    ]
    assert telemetry
    telemetry_before = {
        entity_id: hass.states.get(entity_id).state for entity_id in telemetry
    }
    previous_attempt = state.attributes["last_attempt"]

    for status in (503, 401):
        await _advance(hass, freezer, ALARM_HISTORY_INTERVAL + timedelta(seconds=1))
        state = hass.states.get(row.entity_id)
        assert state is not None and state.state == "error"
        assert state.attributes["http_status"] == status
        assert state.attributes["error_type"] == "http"
        assert state.attributes["events"] == []
        assert state.attributes["latest"] is None
        assert state.attributes["returned_count"] is None
        assert state.attributes["last_success"] == last_success
        assert state.attributes["last_attempt"] != previous_attempt
        previous_attempt = state.attributes["last_attempt"]
        assert entry.runtime_data.last_update_success
        assert entry.state is ConfigEntryState.LOADED
        assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
        assert {
            entity_id: hass.states.get(entity_id).state for entity_id in telemetry
        } == telemetry_before

    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL + timedelta(seconds=1))
    state = hass.states.get(row.entity_id)
    assert state is not None and state.state == "empty"
    assert state.attributes["http_status"] == 200
    assert state.attributes["error_type"] is None
    assert state.attributes["returned_count"] == 0
    assert state.attributes["last_success"] != last_success


async def test_window_uses_ha_local_date_and_exactly_365_days_across_leap_day(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    """UTC can be a different day; raw event offsets still remain untouched."""
    monkeypatch.setattr(hass.config, "time_zone", "America/Los_Angeles")
    freezer.move_to("2028-03-01T00:30:00+00:00")
    history = AsyncMock(return_value=[_ROW])
    _, row = await _set_up(hass, monkeypatch, history, enabled=True)

    history.assert_awaited_once_with(_UDID, date(2027, 3, 1), date(2028, 2, 29))
    state = hass.states.get(row.entity_id)
    assert state is not None
    assert state.attributes["request_from"] == "2027-03-01"
    assert state.attributes["request_to"] == "2028-02-29"
    assert state.attributes["window_timezone"] == "America/Los_Angeles"
    assert state.attributes["filter"] == "all"
    assert state.attributes["lookback_days"] == 365
    assert state.attributes["events"][0]["start"] == _ROW["startAlarm"]


@pytest.mark.parametrize(
    ("failure", "status", "http_status", "error_type"),
    [
        (TechLoginError(403, "synthetic private failure"), "error", 403, "http"),
        (TimeoutError("synthetic private failure"), "error", None, "timeout"),
        (ClientConnectionError("synthetic private failure"), "error", None, "network"),
        (TypeError("synthetic private failure"), "invalid", None, "invalid_response"),
        (ValueError("synthetic private failure"), "invalid", None, "invalid_response"),
        (
            RecursionError("synthetic private failure"),
            "invalid",
            None,
            "invalid_response",
        ),
        (
            OverflowError("synthetic private failure"),
            "invalid",
            None,
            "invalid_response",
        ),
    ],
)
async def test_optional_failures_are_bounded_snapshots_without_private_exception_text(
    hass: HomeAssistant,
    failure: Exception,
    status: str,
    http_status: int | None,
    error_type: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The optional coordinator owns failures even before its first success."""
    entry = _entry()
    entry.add_to_hass(hass)
    primary = SimpleNamespace(
        api=SimpleNamespace(get_module_alarm_history=AsyncMock(side_effect=failure))
    )
    coordinator = TechAlarmHistoryCoordinator(hass, primary, entry)
    try:
        await coordinator.async_refresh()
        snapshot = coordinator.data
        assert snapshot["status"] == status
        assert snapshot["http_status"] == http_status
        assert snapshot["error_type"] == error_type
        assert snapshot["last_success"] is None
        assert snapshot["last_attempt"] is not None
        assert snapshot["events"] == []
        assert snapshot["latest"] is None
        assert snapshot["chronology_complete"] is False
        assert "synthetic private failure" not in caplog.text
        assert hass.config_entries.flow.async_progress_by_handler(DOMAIN) == []
    finally:
        await coordinator.async_shutdown()


async def test_invalid_payload_and_title_fallback_are_visible_on_the_entity(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Fallback titles and validation failures are reflected in the real state."""
    freezer.move_to("2028-03-01T12:00:00+00:00")
    history = AsyncMock(return_value=[_ROW])
    entry, row = await _set_up(hass, monkeypatch, history, enabled=True)
    entity = hass.data[DATA_COMPONENT].get_entity(row.entity_id)
    assert isinstance(entity, AlarmHistorySensor)

    entry.runtime_data.translations = Translations({"data": {"120": ""}})
    await entity.coordinator.async_refresh()
    state = hass.states.get(row.entity_id)
    assert state is not None
    assert state.attributes["events"][0]["title"] == "txtId 120"

    entry.runtime_data.translations = Translations({"data": {"120": "x" * 300}})
    await entity.coordinator.async_refresh()
    state = hass.states.get(row.entity_id)
    assert state is not None
    assert len(state.attributes["events"][0]["title"]) == 256

    history.return_value = {"error": "synthetic server error"}
    await entity.coordinator.async_refresh()
    state = hass.states.get(row.entity_id)
    assert state is not None and state.state == "invalid"
    assert state.attributes["http_status"] == 200
    assert state.attributes["error_type"] == "invalid_response"
    assert state.attributes["events"] == []


@pytest.mark.parametrize("remove", ["disable", "unload"])
async def test_removal_cancels_an_inflight_initial_read_without_resurrecting_state(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    freezer: FrozenDateTimeFactory,
    remove: str,
) -> None:
    """Slow optional startup neither holds setup open nor outlives its entity."""
    freezer.move_to("2028-03-01T12:00:00+00:00")
    started = asyncio.Event()
    release = asyncio.Event()
    cancelled = asyncio.Event()

    async def _blocked(*args: Any) -> list[Any]:
        started.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return [_ROW]

    history = AsyncMock(side_effect=_blocked)
    entry, row = await _set_up(
        hass, monkeypatch, history, enabled=True, wait_initial=False
    )
    await started.wait()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.last_update_success
    try:
        if remove == "disable":
            er.async_get(hass).async_update_entity(
                row.entity_id, disabled_by=er.RegistryEntryDisabler.USER
            )
        else:
            assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        assert cancelled.is_set(), "the initial request belongs to the enabled entity"
        assert hass.data[DATA_COMPONENT].get_entity(row.entity_id) is None
        removed_state = hass.states.get(row.entity_id)
        if remove == "disable":
            assert removed_state is None
        else:
            # HA retains an unavailable placeholder for an enabled registry
            # row whose config entry was unloaded. It must never become live.
            assert removed_state is not None and removed_state.state == "unavailable"
            assert removed_state.attributes["restored"] is True
    finally:
        release.set()

    await _advance(hass, freezer, ALARM_HISTORY_INTERVAL * 2)
    history.assert_awaited_once()
    assert hass.data[DATA_COMPONENT].get_entity(row.entity_id) is None
    assert hass.states.get(row.entity_id) == removed_state
