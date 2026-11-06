"""Synthetic checks of production TYPE_TEMPERATURE entities and setup.

Only Home Assistant's base entity contract is stubbed. Temperature parsing,
availability, setup and coordinator callbacks execute the integration's code.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from . import test_platform_device_info as support

sensor = support.sensor
const = support.const
binary_sensor = support.binary_sensor

_UDID = "synthetic-controller"
_TILE_ID = 101


@pytest.fixture(autouse=True)
def _ha_entity_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Supply HA coordinator availability and state writes to the import stubs."""

    def write_state(entity: Any) -> None:
        entity.state_writes = getattr(entity, "state_writes", 0) + 1

    monkeypatch.setattr(
        support.CoordinatorEntity,
        "available",
        property(lambda entity: entity.coordinator.last_update_success),
        raising=False,
    )
    monkeypatch.setattr(
        support._Entity, "async_write_ha_state", write_state, raising=False
    )


class _RecordingApi:
    """Return synthetic cached payloads and record every requested API read."""

    def __init__(self, tiles: dict[int, dict[str, Any]]) -> None:
        """Keep the tile payload and an initially empty read log."""
        self.tiles = tiles
        self.reads: list[tuple[str, str]] = []

    async def get_module_zones(self, udid: str) -> dict:
        """Return no zones for a tile-only controller."""
        self.reads.append(("zones", udid))
        return {}

    async def get_module_tiles(self, udid: str) -> dict:
        """Return the current cached tiles without performing any transport."""
        self.reads.append(("tiles", udid))
        return self.tiles


def _tile(params: dict[str, Any], tile_type: int | None = None) -> dict[str, Any]:
    """Build a public-schema-shaped tile with no household identifiers."""
    return {
        "id": _TILE_ID,
        "type": const.TYPE_TEMPERATURE if tile_type is None else tile_type,
        "visibility": True,
        "params": {"txtId": 1, **params},
    }


def _context(tile: dict[str, Any]) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Build a config entry and coordinator that only carry local data."""
    entry = SimpleNamespace(
        data={
            const.CONTROLLER: {
                const.UDID: _UDID,
                "name": "Synthetic controller",
                const.VER: "v1",
            }
        },
        entry_id="synthetic-entry",
        title="Synthetic controller",
    )
    tiles = {_TILE_ID: tile}
    coordinator = SimpleNamespace(
        api=_RecordingApi(tiles),
        data={"tiles": tiles},
        translations=support._Translations(),
        last_update_success=True,
    )
    return entry, coordinator


def _build(params: dict[str, Any]) -> tuple[Any, SimpleNamespace]:
    """Dispatch a temperature entity through the production tile builder."""
    tile = _tile(params)
    entry, coordinator = _context(tile)
    entities = sensor._build_tile_entities(tile, coordinator, entry)
    assert len(entities) == 1
    assert isinstance(entities[0], sensor.TileTemperatureSensor)
    return entities[0], coordinator


def _refresh(entity: Any, coordinator: SimpleNamespace, params: dict[str, Any]) -> None:
    """Feed a fresh tile through the actual coordinator update callback."""
    coordinator.data["tiles"][_TILE_ID] = _tile(params)
    entity._handle_coordinator_update()


@pytest.mark.asyncio
async def test_startup_failure_still_registers_and_recovers_same_entity() -> None:
    """A false nested flag registers a stable entity, then recovers on polling."""
    tile = _tile({"workingStatus": False, "value": -2030})
    entry, coordinator = _context(tile)
    hass = SimpleNamespace(data={const.DOMAIN: {entry.entry_id: coordinator}})
    added: list[Any] = []

    def add_entities(entities: list[Any], update_before_add: bool) -> None:
        assert update_before_add is True
        added.extend(entities)

    await sensor.async_setup_entry(hass, entry, add_entities)

    assert len(added) == 1
    entity = added[0]
    assert isinstance(entity, sensor.TileTemperatureSensor)
    expected_id = f"{_UDID}_{_TILE_ID}_tile_temperature"
    assert entity.unique_id == expected_id
    assert entity.available is False
    assert entity.state is None
    assert entity.native_value is None

    _refresh(entity, coordinator, {"workingStatus": True, "value": 235})
    assert entity.available is True
    assert entity.state == 23.5
    assert entity.native_value == 23.5
    assert entity.unique_id == expected_id

    _refresh(entity, coordinator, {"workingStatus": False, "value": -2030})
    assert entity.available is False
    assert entity.state is None
    assert entity.native_value is None
    assert added == [entity]
    assert entity.unique_id == expected_id
    assert entity.state_writes == 2
    assert coordinator.api.reads == [("zones", _UDID), ("tiles", _UDID)]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"workingStatus": True, "value": 235}, 23.5),
        ({"workingStatus": True, "value": -50}, -5.0),
        ({"workingStatus": True, "value": 0}, 0.0),
        ({"value": 235}, 23.5),
        ({"value": -50}, -5.0),
        ({"value": 236.5}, 23.65),
        ({"workingStatus": None, "value": 235}, 23.5),
        ({"workingStatus": "false", "value": 235}, 23.5),
        ({"workingStatus": 0, "value": 235}, 23.5),
    ],
)
def test_valid_numeric_readings_and_legacy_flags(params: dict, expected: float) -> None:
    """Only an explicit boolean false flag invalidates an otherwise valid value."""
    entity, _ = _build(params)
    assert entity.available is True
    assert entity.native_value == pytest.approx(expected)
    assert entity.state == pytest.approx(expected)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "null",
        "235",
        "invalid",
        True,
        False,
        float("nan"),
        float("inf"),
        float("-inf"),
        [],
        {},
        10**400,
    ],
    ids=[
        "none",
        "null-string",
        "numeric-string",
        "invalid-string",
        "true",
        "false",
        "nan",
        "positive-infinity",
        "negative-infinity",
        "list",
        "mapping",
        "huge-int",
    ],
)
def test_invalid_values_are_safe_at_startup_and_refresh(value: Any) -> None:
    """Malformed values neither raise nor leave a stale numeric state behind."""
    params = {"workingStatus": True, "value": value}
    entity, coordinator = _build(deepcopy(params))
    assert entity.available is False
    assert entity.state is None
    assert entity.native_value is None

    _refresh(entity, coordinator, {"workingStatus": True, "value": 235})
    assert entity.available is True
    assert entity.native_value == 23.5

    _refresh(entity, coordinator, params)
    assert entity.available is False
    assert entity.state is None
    assert entity.native_value is None


def test_missing_value_is_unavailable() -> None:
    """A payload without a value has no valid temperature to publish."""
    entity, _ = _build({"workingStatus": True})
    assert entity.available is False
    assert entity.state is None
    assert entity.native_value is None


def test_coordinator_failure_overrides_valid_temperature() -> None:
    """A cached numeric reading does not bypass failed coordinator availability."""
    entity, coordinator = _build({"workingStatus": True, "value": 235})
    assert entity.available is True
    coordinator.last_update_success = False
    assert entity.available is False
    assert entity.native_value == 23.5
    coordinator.last_update_success = True
    assert entity.available is True


@pytest.mark.parametrize("tile_type", [const.TYPE_RELAY, const.TYPE_ADDITIONAL_PUMP])
def test_relay_and_pump_off_remain_available(tile_type: int) -> None:
    """The same nested false flag still represents OFF on relay/pump entities."""
    tile = _tile({"workingStatus": False}, tile_type)
    entry, coordinator = _context(tile)
    entity = binary_sensor.RelaySensor(tile, coordinator, entry)
    assert entity.available is True
    assert entity.get_state(tile) is False
    assert entity.state == "off"
    coordinator.last_update_success = False
    assert entity.available is False


def _widget_tile(
    *,
    working: Any = True,
    unit: int = 7,
    value: Any = 235,
    widget_type: int = 0,
) -> dict[str, Any]:
    """Build a TYPE_WIDGET tile carrying one widget."""
    return {
        "id": _TILE_ID,
        "type": const.TYPE_WIDGET,
        "visibility": True,
        "params": {
            "txtId": 1,
            "workingStatus": working,
            "widget1": {
                "txtId": 2,
                "unit": unit,
                "type": widget_type,
                "value": value,
            },
        },
    }


def _build_widget(
    *, working: Any = True, unit: int = 7, value: Any = 235, widget_type: int = 0
) -> tuple[Any, SimpleNamespace]:
    """Build the widget entity the production builder creates."""
    tile = _widget_tile(
        working=working, unit=unit, value=value, widget_type=widget_type
    )
    entry, coordinator = _context(tile)
    entities = sensor._build_widget_tile(tile, coordinator, entry)
    assert len(entities) == 1
    return entities[0], coordinator


def _refresh_tile(entity: Any, coordinator: SimpleNamespace, tile: dict[str, Any]) -> None:
    """Feed a fresh tile through the production coordinator callback."""
    coordinator.data["tiles"][_TILE_ID] = tile
    entity._handle_coordinator_update()


def test_valid_number_rejects_bools_and_non_finite_values() -> None:
    """The shared helper is the one place malformed numbers are rejected."""
    assert const.valid_number(235) == 235
    assert const.valid_number(-5.0) == -5.0
    for value in (True, False, None, "235", float("nan"), float("inf"), 10**400):
        assert const.valid_number(value) is None
    assert const.scaled_number(235, 10) == 23.5
    assert const.scaled_number(5, 1) == 5
    assert const.scaled_number(10**400, 1) is None


def test_reading_is_working_only_rejects_an_explicit_false() -> None:
    """The legacy flag forms and a missing flag all mean the input works."""
    assert not const.reading_is_working({"workingStatus": False})
    for params in (
        {},
        {"workingStatus": None},
        {"workingStatus": 0},
        {"workingStatus": "false"},
        {"workingStatus": True},
    ):
        assert const.reading_is_working(params)


def test_widget_temperature_uses_the_same_working_and_finite_checks() -> None:
    """A widget temperature becomes unavailable while its input is off."""
    entity, coordinator = _build_widget(working=False, value=-2030)
    assert isinstance(entity, sensor.TileWidgetTemperatureSensor)
    assert entity.available is False
    assert entity.native_value is None

    _refresh_tile(entity, coordinator, _widget_tile(value=235))
    assert entity.available is True
    assert entity.native_value == 23.5

    _refresh_tile(entity, coordinator, _widget_tile(value="235"))
    assert entity.available is False
    assert entity.native_value is None


def test_widget_pump_keeps_off_semantics_when_the_flag_is_false() -> None:
    """A pump widget's false flag means "off", not "disconnected".

    The temperature fix must not make a pump percentage unavailable just
    because the output is off; that is a valid reading.
    """
    entity, coordinator = _build_widget(working=False, unit=8, value=0)
    assert isinstance(entity, sensor.TileWidgetPumpSensor)
    assert entity.available is True
    assert entity.native_value == 0

    _refresh_tile(entity, coordinator, _widget_tile(unit=8, value=5))
    assert entity.available is True
    assert entity.native_value == 5


def _valve_tile(*, working: Any = True, current_temp: Any = 235) -> dict[str, Any]:
    """Build a TYPE_VALVE tile with one current-temperature reading."""
    return {
        "id": _TILE_ID,
        "type": const.TYPE_VALVE,
        "visibility": True,
        "params": {
            "txtId": 1,
            "workingStatus": working,
            "valveNumber": 1,
            "currentTemp": current_temp,
            "returnTemp": 430,
            "setTemp": 57,
            "setTempCorrection": 0,
            "openingPercentage": 60,
            "valvePump": 1,
            "boilerProtection": 1,
            "returnProtection": 1,
        },
    }


def test_valve_temperature_uses_the_same_working_and_finite_checks() -> None:
    """A valve temperature is unavailable while the valve input is off."""
    tile = _valve_tile(working=False, current_temp=-2030)
    entry, coordinator = _context(tile)
    entity = sensor.TileValveTemperatureSensor(
        tile, coordinator, entry, const.VALVE_SENSOR_CURRENT_TEMPERATURE
    )
    assert entity.available is False
    assert entity.native_value is None

    _refresh_tile(entity, coordinator, _valve_tile(current_temp=235))
    assert entity.available is True
    assert entity.native_value == 23.5


def _open_therm_tile(*, working: Any = True, current_temp: Any = 235) -> dict[str, Any]:
    """Build a TYPE_OPEN_THERM tile with one current-temperature reading."""
    return {
        "id": _TILE_ID,
        "type": const.TYPE_OPEN_THERM,
        "visibility": True,
        "params": {
            "txtId": 1,
            "workingStatus": working,
            "currentTemp": current_temp,
        },
    }


def test_open_therm_temperature_uses_the_same_working_and_finite_checks() -> None:
    """An OpenTherm temperature is unavailable while its input is off."""
    tile = _open_therm_tile(working=False, current_temp=-2030)
    entry, coordinator = _context(tile)
    entity = sensor.TileOpenThermTemperatureSensor(
        tile, coordinator, entry, const.OPENTHERM_CURRENT_TEMP
    )
    assert entity.available is False
    assert entity.native_value is None

    _refresh_tile(entity, coordinator, _open_therm_tile(current_temp=235))
    assert entity.available is True
    assert entity.native_value == 23.5


def _zone(current: Any = 235) -> dict[str, Any]:
    """Build the minimum zone payload a zone temperature sensor reads."""
    return {
        "zone": {"id": 1, "currentTemperature": current, "setTemperature": 220},
        "description": {"name": "Synthetic zone"},
    }


def _zone_entry() -> SimpleNamespace:
    """Build the controller metadata ZoneSensor reads while initialising."""
    return SimpleNamespace(
        data={
            const.CONTROLLER: {
                const.UDID: _UDID,
                "name": "Synthetic controller",
                const.VER: "v1",
            }
        },
        entry_id="synthetic-entry",
        title="Synthetic controller",
    )


def test_zone_temperature_uses_the_same_finite_check() -> None:
    """A malformed zone reading is not published as a temperature."""
    entry = _zone_entry()
    coordinator = SimpleNamespace(last_update_success=True)
    entity = sensor.ZoneTemperatureSensor(_zone(current="invalid"), coordinator, entry)
    assert entity.available is False
    assert entity._attr_native_value is None

    entity.update_properties(_zone(current=235))
    assert entity.available is True
    assert entity._attr_native_value == 23.5
