"""Drive the per-zone constant-temperature duration the schedule select uses.

The number holds a local preference for the **Schedule** select: zero keeps a
constant temperature permanent, a positive value holds it for that many minutes.
The fixture carries four schedule-capable zones, so every zone gets its own
number and its own entry in the coordinator's duration map.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from common import UDID, set_up
import pytest

from custom_components.tech.const import DOMAIN
from custom_components.tech.zone_constant_duration import ZoneConstantDurationNumber
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

CONSTANT = "Constant Temperature"


def _entity_id(hass: HomeAssistant, zone_id: int) -> str:
    """Return the one duration number a zone's unique id names."""
    registry = er.async_get(hass)
    matches = [
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
        and entry.unique_id == f"{UDID}_{zone_id}_zone_constant_duration"
    ]
    assert len(matches) == 1
    return matches[0]


def _state(hass: HomeAssistant, zone_id: int) -> Any:
    """Return the zone duration number's state."""
    state = hass.states.get(_entity_id(hass, zone_id))
    assert state is not None
    return state.state


async def _set(hass: HomeAssistant, zone_id: int, value: float) -> None:
    """Set the duration through the Home Assistant number service."""
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": _entity_id(hass, zone_id), "value": value},
        blocking=True,
    )


def _select_entity_id(hass: HomeAssistant, zone_id: int) -> str:
    """Return the one schedule select a zone's unique id names."""
    registry = er.async_get(hass)
    matches = [
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
        and entry.unique_id == f"{UDID}_{zone_id}_zone_schedule_select"
    ]
    assert len(matches) == 1
    return matches[0]


async def test_every_schedule_capable_zone_gets_a_duration_number(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each zone the schedule snapshot carries has one number, defaulting to 0."""
    await set_up(hass, "zone_modes", monkeypatch)

    for zone_id in (1, 2, 3, 4):
        state = hass.states.get(_entity_id(hass, zone_id))
        assert state is not None
        assert float(state.state) == 0
        assert state.attributes["min"] == 0
        assert state.attributes["max"] == 1440
        assert state.attributes["step"] == 1
        assert state.attributes["unit_of_measurement"] == "min"


async def test_setting_the_duration_keeps_it_for_the_select_without_a_write(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The number is a local preference, so setting it sends nothing to the API."""
    post = AsyncMock(return_value={"status": "success"})
    entry = await set_up(hass, "zone_modes", monkeypatch, post=post)

    await _set(hass, 1, 45)

    assert float(_state(hass, 1)) == 45
    assert entry.runtime_data.zone_constant_durations[1] == 45
    assert post.await_count == 0


async def test_setting_the_duration_to_zero_keeps_a_permanent_constant(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Zero is stored as the permanent selection the select already used."""
    entry = await set_up(hass, "zone_modes", monkeypatch)

    await _set(hass, 2, 30)
    await _set(hass, 2, 0)

    assert float(_state(hass, 2)) == 0
    assert entry.runtime_data.zone_constant_durations[2] == 0


async def test_selecting_constant_uses_the_configured_duration(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The select sends a time limit when the number holds one."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)

    await _set(hass, 1, 45)
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _select_entity_id(hass, 1), "option": CONSTANT},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    mode = json.loads(call.args[1])["mode"]
    assert mode["mode"] == "timeLimit"
    assert mode["constTempTime"] == 45
    assert mode["setTemperature"] == 215


@pytest.mark.parametrize(
    ("restored", "expected"), [(75, 75.0), (5000, 1440.0)], ids=["minutes", "clamped"]
)
async def test_a_restored_duration_comes_back_and_is_clamped_to_a_day(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    restored: int,
    expected: float,
) -> None:
    """The entity's restored state seeds the select, within the accepted range."""
    monkeypatch.setattr(
        ZoneConstantDurationNumber,
        "async_get_last_number_data",
        AsyncMock(return_value=SimpleNamespace(native_value=restored)),
    )

    entry = await set_up(hass, "zone_modes", monkeypatch)

    assert float(_state(hass, 1)) == expected
    assert entry.runtime_data.zone_constant_durations[1] == int(expected)
