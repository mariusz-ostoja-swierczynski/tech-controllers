"""Drive the per-zone schedule select the way a user does.

The fixture carries zones in constant-temperature, global and local schedule
modes plus one whose controller reports no mode. The select shows the names of
the controller's five global slots and routes a choice through one of the two
zone-mode actions, never straight to the API.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

from common import UDID, set_up
import pytest

from custom_components.tech.const import DOMAIN
from homeassistant.components.select.const import DATA_COMPONENT
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

CONSTANT = "Constant Temperature"
LOCAL = "Local Schedule"
GLOBAL_OPTIONS = [
    "Global Schedule 1: Global 0",
    "Global Schedule 2: Global 1",
    "Global Schedule 3: Global 2",
    "Global Schedule 4: Duplicate",
    "Global Schedule 5: Duplicate",
]


def _select_entity(hass: HomeAssistant, zone_id: int) -> str:
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


def _options(hass: HomeAssistant, zone_id: int) -> list[str]:
    """Return the options the zone's select currently publishes."""
    state = hass.states.get(_select_entity(hass, zone_id))
    assert state is not None
    return list(state.attributes["options"])


def _state(hass: HomeAssistant, zone_id: int) -> str:
    """Return the zone select's current option."""
    state = hass.states.get(_select_entity(hass, zone_id))
    assert state is not None
    return state.state


def _body(call: Any) -> dict[str, Any]:
    """Return the JSON body a recorded write was made with."""
    return json.loads(call.args[1])


async def _choose(hass: HomeAssistant, zone_id: int, option: str) -> None:
    """Select one option through the Home Assistant service."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": _select_entity(hass, zone_id), "option": option},
        blocking=True,
    )


async def test_select_entities_exist_for_every_schedule_capable_zone(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each zone the snapshot carries gets its own schedule select."""
    await set_up(hass, "zone_modes", monkeypatch)

    for zone_id in (1, 2, 3, 4):
        assert hass.states.get(_select_entity(hass, zone_id)) is not None


async def test_options_are_the_constant_local_and_named_global_slots(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The options carry the controller names, including duplicate ones."""
    await set_up(hass, "zone_modes", monkeypatch)

    assert _options(hass, 1) == [CONSTANT, LOCAL, *GLOBAL_OPTIONS]


async def test_current_option_follows_the_zone_mode(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Constant, global and local zones report their configured selection."""
    await set_up(hass, "zone_modes", monkeypatch)

    assert _state(hass, 1) == CONSTANT
    assert _state(hass, 2) == "Global Schedule 3: Global 2"
    assert _state(hass, 3) == LOCAL
    assert _state(hass, 4) == STATE_UNKNOWN


async def test_selecting_a_global_slot_calls_the_schedule_action(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A named slot sends its index, so duplicate names stay unambiguous."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    option = "Global Schedule 3: Global 2"

    await _choose(hass, 1, option)

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones/1/global_schedule"
    body = _body(call)
    assert body["modeId"] == 101
    assert body["schedule"]["index"] == 2
    assert body["scheduleName"] == "Global 2"
    assert body["setInZones"] == [
        {"zoneId": 1, "modeId": 101},
        {"zoneId": 2, "modeId": 102},
    ]
    assert _state(hass, 1) == option


async def test_a_poll_during_the_change_window_keeps_the_chosen_option(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A poll inside the controller's change window must not undo the choice."""
    post = AsyncMock(return_value={"status": "success"})
    entry = await set_up(hass, "zone_modes", monkeypatch, post=post)
    option = "Global Schedule 3: Global 2"

    await _choose(hass, 1, option)

    # The controller still reports the previous constant mode, marked pending.
    zone = entry.runtime_data.data["schedules"]["zones"][1]
    zone["zone"]["duringChange"] = "t"
    entry.runtime_data.async_set_updated_data(entry.runtime_data.data)
    await hass.async_block_till_done()

    assert _state(hass, 1) == option


async def test_selecting_local_calls_the_local_schedule_action(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The local option writes the zone's own template."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)

    await _choose(hass, 1, LOCAL)

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones/1/local_schedule"
    body = _body(call)
    assert body["modeId"] == 101
    assert body["schedule"]["id"] == 201
    assert _state(hass, 1) == LOCAL


async def test_selecting_constant_uses_the_zone_setpoint(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The constant option holds the zone's current temperature permanently."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)

    await _choose(hass, 1, CONSTANT)

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones"
    mode = _body(call)["mode"]
    assert mode["mode"] == "constantTemp"
    assert mode["constTempTime"] == 0
    assert mode["setTemperature"] == 215
    assert _state(hass, 1) == CONSTANT


async def test_selecting_constant_without_a_zone_mode_raises(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone whose mode has no id is refused before any write."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)

    with pytest.raises(HomeAssistantError) as excinfo:
        await _choose(hass, 4, CONSTANT)

    assert excinfo.value.translation_key == "zone_mode_missing"
    assert post.await_count == 0


async def test_selecting_constant_without_a_setpoint_raises(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone without a reported setpoint cannot be held at a temperature."""
    post = AsyncMock(return_value={"status": "success"})
    entry = await set_up(hass, "zone_modes", monkeypatch, post=post)
    entry.runtime_data.data["zones"][1]["zone"]["setTemperature"] = None

    with pytest.raises(HomeAssistantError) as excinfo:
        await _choose(hass, 1, CONSTANT)

    assert excinfo.value.translation_key == "zone_temperature_missing"
    assert post.await_count == 0


async def test_renaming_a_global_schedule_refreshes_the_options(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A renamed template reaches the options on the next coordinator update."""
    entry = await set_up(hass, "zone_modes", monkeypatch)
    elements = entry.runtime_data.data["schedules"]["globalSchedules"]["elements"]
    elements[2]["name"] = "Weekend"

    entry.runtime_data.async_set_updated_data(entry.runtime_data.data)
    await hass.async_block_till_done()

    assert "Global Schedule 3: Weekend" in _options(hass, 1)
    assert "Global Schedule 3: Global 2" not in _options(hass, 1)


async def test_a_global_slot_without_a_name_keeps_its_number(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unnamed template is still offered, without an empty name suffix."""
    entry = await set_up(hass, "zone_modes", monkeypatch)
    elements = entry.runtime_data.data["schedules"]["globalSchedules"]["elements"]
    elements[0]["name"] = ""

    entry.runtime_data.async_set_updated_data(entry.runtime_data.data)
    await hass.async_block_till_done()

    assert "Global Schedule 1" in _options(hass, 1)


async def test_an_option_outside_the_snapshot_is_refused(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An option the entity never published is rejected without a write.

    The select service itself refuses an option that is not in the entity's
    options, so this branch is only reachable by calling the entity directly.
    """
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    component = hass.data[DATA_COMPONENT]
    entity = component.get_entity(_select_entity(hass, 1))
    assert entity is not None

    with pytest.raises(HomeAssistantError) as excinfo:
        await entity.async_select_option("Not an option")

    assert excinfo.value.translation_key == "schedule_invalid"
    assert post.await_count == 0
