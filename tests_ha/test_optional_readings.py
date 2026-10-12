"""Set a controller up whose payload carries the optional parts of a Tech payload.

The recorded controllers in ``tests/fixtures`` are what two reporters' accounts
answered, and none of them carries a zone battery, a window sensor, an
underfloor set or a menu tree whose groups match the zones. The classes behind
those readings therefore never run. This file writes payloads in the API's own
shape to reach them: the fields are taken from the integration's own constants,
so a renamed key shows up here rather than silently skipping a class.
"""

from __future__ import annotations

from typing import Any

from common import EMPTY_MENU, entity_counts, entry_for
import pytest

from custom_components.tech import const
from custom_components.tech.tech import Tech
from homeassistant.const import CONF_DESCRIPTION, CONF_NAME, CONF_ZONE
from homeassistant.core import HomeAssistant

_ACTUATOR = {const.BATTERY_LEVEL: 80, const.SIGNAL_STRENGTH: 60}
_WINDOW = {
    const.WINDOW_STATE: "open",
    const.BATTERY_LEVEL: 70,
    const.SIGNAL_STRENGTH: 50,
}
_UNDERFLOOR = {
    "temperature": 210,
    const.BATTERY_LEVEL: 80,
    const.MODE: 1,
    const.CURRENT_STATE: 0,
    const.FLOOR_PUMP: False,
    const.SENSOR_TYPE: 0,
    const.SIGNAL_STRENGTH: 40,
    const.EVENTS: {
        const.CORRECT_WORK: True,
        const.NO_COMMUNICATION: False,
        const.SENSOR_DAMAGED: False,
        const.LOW_BATTERY: False,
        const.LOW_SIGNAL: False,
        const.TEMP_TOO_HIGH: False,
        const.TEMP_TOO_LOW: False,
        const.SERVICE_ERROR: False,
    },
}


def _zone(index: int, **overrides: Any) -> dict[str, Any]:
    """Return a zone payload with every optional reading present."""
    state = {
        "id": index,
        "index": index,
        "visibility": True,
        const.ZONE_STATE: "zoneOn",
        "currentTemperature": 215,
        "setTemperature": 220,
        "duringChange": False,
        "humidity": 55,
        const.BATTERY_LEVEL: 80,
        const.SIGNAL_STRENGTH: 60,
        const.ACTUATORS_OPEN: 100,
        "flags": {"relayState": "on", "algorithm": "heating"},
    }
    state.update(overrides)
    return {
        CONF_ZONE: state,
        CONF_DESCRIPTION: {CONF_NAME: f"Zone {index}"},
        const.ACTUATORS: [dict(_ACTUATOR)],
        const.WINDOW_SENSORS: [dict(_WINDOW)],
        const.UNDERFLOOR: dict(_UNDERFLOOR),
    }


def _module(zones: list[dict[str, Any]], tiles: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a module payload the API would answer with."""
    return {
        "tiles": tiles,
        "tilesOrder": [tile["id"] for tile in tiles],
        "zones": {"elements": zones},
    }


def _tile(
    tile_id: int,
    tile_type: int,
    params: dict[str, Any] | None = None,
    *,
    visibility: bool = True,
) -> dict[str, Any]:
    """Return a tile payload of the given type."""
    return {
        "id": tile_id,
        "menuId": 0,
        "parentId": 0,
        "orderId": tile_id,
        "type": tile_type,
        "visibility": visibility,
        "workingStatus": True,
        "params": params if params is not None else {},
    }


async def _set_up_payload(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    module: dict[str, Any],
    menus: dict[str, Any] | None = None,
) -> None:
    """Set an entry up while the API answers with the given payload."""

    async def _get(_self: Tech, path: str) -> dict[str, Any]:
        if "/menu/" in path:
            menu_type = path.rstrip("/").rsplit("/", 1)[-1]
            return (menus or {}).get(menu_type, EMPTY_MENU)
        return module

    monkeypatch.setattr(Tech, "get", _get)
    entry = entry_for("payload")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_a_zone_with_every_reading_builds_each_zone_sensor(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Battery, temperature, state, humidity, signal, actuator, window, floor.

    The second zone carries the other side of each branch: a temperature change
    in progress, a humidity the API reports as -1 ("none"), and a relay state
    and zone state that are neither on nor heating.
    """
    zones = [
        _zone(1),
        _zone(
            2,
            duringChange=True,
            humidity=-1,
            **{
                const.ZONE_STATE: "zoneOff",
                const.BATTERY_LEVEL: None,
                const.SIGNAL_STRENGTH: None,
                "flags": {"relayState": "unknown", "algorithm": "unknown"},
            },
        ),
    ]
    await _set_up_payload(hass, monkeypatch, _module(zones, []))

    # Two thermostats and the thirteen zone sensors these zones describe: the
    # temperature, state, humidity, signal, battery, actuator, window and
    # underfloor readings of the first, and the four the second still yields.
    assert entity_counts(hass) == {"climate": 2, "sensor": 13}


async def test_a_temperature_tile_with_wireless_readings_adds_its_sensors(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tile that reports signal and battery yields three sensors for one tile."""
    tile = _tile(
        1,
        const.TYPE_TEMPERATURE,
        {
            const.VALUE: 210,
            const.SIGNAL_STRENGTH: 55,
            const.BATTERY_LEVEL: 90,
            "currentTemperature": 210,
        },
    )
    await _set_up_payload(hass, monkeypatch, _module([], [tile]))

    assert entity_counts(hass) == {"sensor": 3}


async def test_widget_tiles_cover_the_variants_the_recording_missed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pump widgets, a label borrowed from the sibling, and the skipped ones.

    One tile is a collector pump (percentage), one a DHW pump whose own label is
    missing and borrowed from its sibling, one an invisible value (unit -1), one
    a decorative zero badge (unit 6), and one a placeholder without any label.
    """
    tiles = [
        _tile(
            1,
            const.TYPE_WIDGET,
            {
                const.VALUE: 40,
                "widget1": {"txtId": 100, "type": 2, "value": 40, "unit": 8},
            },
        ),
        _tile(
            2,
            const.TYPE_WIDGET,
            {
                const.VALUE: 30,
                "widget1": {"txtId": 0, "type": const.WIDGET_DHW_PUMP, "value": 30},
                "widget2": {"txtId": 200, "type": 0, "value": 45, "unit": 1},
            },
        ),
        _tile(
            3,
            const.TYPE_WIDGET,
            {
                const.VALUE: 0,
                "widget1": {"txtId": 101, "type": 0, "value": 5, "unit": -1},
                "widget2": {"txtId": 102, "type": 0, "value": 0, "unit": 6},
            },
        ),
        _tile(
            4,
            const.TYPE_WIDGET,
            {
                const.VALUE: 10,
                "widget1": {"txtId": 0, "type": 0, "value": 10, "unit": 1},
            },
        ),
    ]
    await _set_up_payload(hass, monkeypatch, _module([], tiles))

    assert entity_counts(hass) == {"sensor": 3}


async def test_menu_groups_that_match_the_zones_are_assigned_to_them(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A "Zones" menu group whose subgroups match the zones assigns the tree.

    The recorded menus have no such group, so the walk that pairs every menu
    item with the zone it belongs to never ran. The group here holds one
    subgroup per zone, and one of them holds a nested group as well.
    """

    def _group(item_id: int, parent_id: int) -> dict[str, Any]:
        return {
            "id": item_id,
            "parentId": parent_id,
            "type": const.MENU_ITEM_TYPE_GROUP,
            "menuType": "MI",
            "access": True,
            "txtId": 300 + item_id,
            "params": {},
        }

    def _number(item_id: int, parent_id: int) -> dict[str, Any]:
        return {
            "id": item_id,
            "parentId": parent_id,
            # 5 is one of ``const.MENU_ITEM_TYPE_VALUE``, the numeric menus.
            "type": 5,
            "menuType": "MI",
            "access": True,
            "txtId": 400 + item_id,
            "params": {"value": 10, "min": 0, "max": 50, "step": 1},
        }

    elements = [
        _group(100, 0),
        _group(101, 100),
        _group(102, 100),
        _group(103, 101),
        _number(110, 103),
        _number(111, 102),
    ]
    menus = {"MI": {"status": "success", "data": {"elements": elements}}}
    zones = [_zone(1), _zone(2)]

    await _set_up_payload(hass, monkeypatch, _module(zones, []), menus)

    # Both numbers live under a zone subgroup, so both are registered.
    assert entity_counts(hass)["number"] == 2


async def test_an_open_therm_tile_builds_its_temperatures_and_modulation(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An OpenTherm boiler yields one sensor per reading it reports.

    Four temperature readings -- the boiler's and the hot water's, each current
    and target -- plus the modulation percentage, which is a power factor.
    """
    tile = _tile(
        1,
        const.TYPE_OPEN_THERM,
        {
            const.OPENTHERM_CURRENT_TEMP["state_key"]: 215,
            const.OPENTHERM_SET_TEMP["state_key"]: 220,
            const.OPENTHERM_CURRENT_TEMP_DHW["state_key"]: 480,
            const.OPENTHERM_SET_TEMP_DHW["state_key"]: 500,
            const.OPENTHERM_MODULATION["state_key"]: 45,
            "flags": {"activeDHW": True, "activeHeating": False, "communication": True},
            "alarmCode": 0,
        },
    )
    await _set_up_payload(hass, monkeypatch, _module([], [tile]))

    assert entity_counts(hass) == {"sensor": 5}


async def test_a_mixing_valve_tile_reports_its_opening(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stand-alone mixing valve reports the percentage it is open by."""
    tile = _tile(
        1,
        const.TYPE_MIXING_VALVE,
        {"valveNumber": 1, "openingPercentage": 40},
    )
    await _set_up_payload(hass, monkeypatch, _module([], [tile]))

    assert entity_counts(hass) == {"sensor": 1}


async def test_an_entry_without_zones_or_tiles_still_sets_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A controller that answers with nothing produces no entities."""
    await _set_up_payload(hass, monkeypatch, _module([], []))

    assert entity_counts(hass) == {}
