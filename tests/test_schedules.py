"""Synthetic checks of production schedule decoding, cache and HA entities.

The transport and HA base classes are fake; production methods do all parsing,
refreshing, selection and entity setup. No credentials or household data are used.
"""

from __future__ import annotations

from copy import deepcopy
from enum import IntFlag
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from . import test_platform_device_info as support

schedules = support._load_tech_module("schedules")
tech = support._load_tech_module("tech")
sensor = support.sensor
const = support.const


class _ClimateEntity(support._Entity):
    """Supply the additional HA base used by the production climate platform."""


class _ClimateFeature(IntFlag):
    """Support the feature combination returned by the real entity."""

    TARGET_TEMPERATURE = 1
    TURN_ON = 2
    TURN_OFF = 4


_climate_module = ModuleType("homeassistant.components.climate")
_climate_module.ClimateEntity = _ClimateEntity
_climate_const = ModuleType("homeassistant.components.climate.const")
_climate_const.ClimateEntityFeature = _ClimateFeature
_climate_const.HVACAction = support._AutoNamespace()
_climate_const.HVACMode = support._AutoNamespace()
sys.modules["homeassistant.components.climate"] = _climate_module
sys.modules["homeassistant.components.climate.const"] = _climate_const
sys.modules["homeassistant.const"].ATTR_TEMPERATURE = "temperature"
climate = support._load_tech_module("climate")

_UDID = "synthetic-controller"


@pytest.fixture(autouse=True)
def _entity_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the HA stand-ins limited to availability and state notifications."""
    monkeypatch.setattr(
        support.CoordinatorEntity,
        "available",
        property(lambda entity: entity.coordinator.last_update_success),
        raising=False,
    )
    monkeypatch.setattr(
        support._Entity,
        "async_write_ha_state",
        lambda entity: None,
        raising=False,
    )


def _schedule(index: int = 1, name: str = "Synthetic global") -> dict[str, Any]:
    """Build two complementary profiles using the public zone schedule schema."""
    return {
        "index": index,
        "name": name,
        "p0Days": ["1", "1", "1", "1", "1", "0", "0"],
        "p1Days": ["0", "0", "0", "0", "0", "1", "1"],
        "p0Intervals": [
            {"start": 0, "stop": 480, "temp": 180},
            {"start": 480, "stop": 1440, "temp": 235},
        ],
        "p1Intervals": [{"start": 6100, "stop": 6100, "temp": 200}],
        "p0SetbackTemp": 200,
        "p1SetbackTemp": 190,
    }


def _zone(zone_id: int = 101, mode: str = "globalSchedule", index: Any = 1) -> dict:
    """Provide the minimal normal zone telemetry used by actual HA entities."""
    local = _schedule(-1)
    local.pop("name")
    return {
        "zone": {
            "id": zone_id,
            "visibility": True,
            "zoneState": "noAlarm",
            "duringChange": False,
            "setTemperature": 235,
            "currentTemperature": 210,
            "humidity": None,
            "batteryLevel": None,
            "signalStrength": None,
            "flags": {"relayState": "off", "algorithm": "heating"},
        },
        "description": {"name": f"Synthetic zone {zone_id}"},
        "mode": {"mode": mode, "scheduleIndex": index},
        "schedule": local,
    }


def _payload(zone: dict | None = None) -> dict:
    """Return one synthetic module; a model name is not required for capability."""
    return {
        "zones": {
            "elements": [_zone() if zone is None else zone],
            "globalSchedules": {
                "time": "synthetic-server-time",
                "duringChange": False,
                "elements": [_schedule()],
            },
            "controllerParameters": {"controllerMode": {"type": 108, "value": 0}},
        },
        "tiles": [],
    }


def _snapshot(payload: dict | None = None) -> dict:
    """Run the production extraction on a synthetic response."""
    return schedules.schedule_snapshot((payload or _payload())["zones"])


def _context(snapshot: dict) -> tuple[SimpleNamespace, SimpleNamespace]:
    """Construct entry metadata and the shared coordinator's fresh data."""
    entry = SimpleNamespace(
        data={
            const.CONTROLLER: {
                const.UDID: _UDID,
                "name": "Schema capable",
                const.VER: "1",
            }
        },
        entry_id="synthetic-entry",
        title="Synthetic controller",
    )
    coordinator = SimpleNamespace(
        data={"schedules": snapshot, "zones": {101: _zone()}, "tiles": {}},
        last_update_success=True,
        translations=support._Translations(),
    )
    return entry, coordinator


def test_week_is_monday_first_with_temperatures_boundaries_and_setback() -> None:
    """Weekday intervals and weekend fallback retain both profiles and raw slots."""
    raw = _schedule()
    raw["p1Intervals"].append({"start": 0, "stop": 0, "temp": 200})
    decoded = schedules.normalize_schedule(raw)
    assert decoded["valid"] is True
    assert tuple(decoded["week"]) == (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    assert decoded["week"]["monday"]["intervals"] == [
        {"start": 0, "stop": 480, "temperature": 18.0},
        {"start": 480, "stop": 1440, "temperature": 23.5},
    ]
    assert decoded["week"]["saturday"] == {
        "profile": 1,
        "intervals": [],
        "setback_temperature": 19.0,
    }
    assert decoded["raw"] == raw
    assert decoded["errors"] == []


@pytest.mark.parametrize(
    "interval",
    [
        {"start": 480, "stop": 0, "temp": 200},
        {"start": -1, "stop": 480, "temp": 200},
        {"start": 0, "stop": 1441, "temp": 200},
        {"start": True, "stop": 480, "temp": 200},
        {"start": "0", "stop": 480, "temp": 200},
        {"start": 0, "stop": 480, "temp": 49},
        {"start": 0, "stop": 480, "temp": 351},
        {"start": 0, "stop": 480, "temp": True},
        {"start": 6100, "stop": 0, "temp": 200},
        None,
    ],
)
def test_bad_interval_never_creates_a_plausible_day(interval: Any) -> None:
    """Malformed active intervals invalidate their days rather than filling gaps."""
    raw = _schedule()
    raw["p0Intervals"] = [interval]
    decoded = schedules.normalize_schedule(raw)
    assert decoded["valid"] is False
    assert decoded["week"]["monday"] is None
    assert decoded["week"]["saturday"] is not None
    assert decoded["errors"]
    assert decoded["raw"] == raw


def test_overlapping_intervals_and_conflicting_days_are_reported() -> None:
    """An overlap cannot become fallback, and a shared day has no chosen profile."""
    raw = _schedule()
    raw["p0Intervals"][1]["start"] = 400
    raw["p0Days"][5] = "1"
    decoded = schedules.normalize_schedule(raw)
    assert "p0Intervals:overlap" in decoded["errors"]
    assert "saturday:conflicting_profiles" in decoded["errors"]
    assert decoded["week"]["monday"] is None
    assert decoded["week"]["saturday"] is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("p0Days", ["1"] * 6),
        ("p1Days", [0] * 7),
        ("p0Intervals", None),
        ("p0SetbackTemp", None),
        ("p0SetbackTemp", 351),
        ("p0SetbackTemp", True),
    ],
)
def test_missing_or_invalid_profile_fields_are_safe(field: str, value: Any) -> None:
    """Missing masks and malformed profile values never raise or manufacture heat."""
    raw = _schedule()
    raw[field] = value
    result = schedules.normalize_schedule(raw)
    assert result["valid"] is False
    assert result["errors"]


def test_unused_malformed_profile_does_not_erase_valid_selected_days() -> None:
    """Diagnostics retain the unused profile error, but the actual week is valid."""
    raw = _schedule()
    raw["p0Days"], raw["p1Days"] = ["1"] * 7, ["0"] * 7
    raw["p1Intervals"] = [{"start": 480, "stop": 0, "temp": 200}]
    decoded = schedules.normalize_schedule(raw)
    assert decoded["valid"] is True
    assert all(day["profile"] == 0 for day in decoded["week"].values())
    assert decoded["errors"] == ["p1Intervals[0]:invalid_range"]


def test_four_valid_intervals_do_not_acquire_an_artificial_count_limit() -> None:
    """Read-only decoding accepts valid spans despite the schema's 3/4 ambiguity."""
    raw = _schedule()
    raw["p0Intervals"] = [
        {"start": 0, "stop": 360, "temp": 180},
        {"start": 360, "stop": 720, "temp": 200},
        {"start": 720, "stop": 1080, "temp": 220},
        {"start": 1080, "stop": 1440, "temp": 235},
    ]
    decoded = schedules.normalize_schedule(raw)
    assert decoded["valid"] is True
    assert len(decoded["week"]["monday"]["intervals"]) == 4
    assert decoded["errors"] == []


def test_global_selection_uses_declared_index_and_never_uses_local_name() -> None:
    """Index zero and out-of-order templates work independently of the local copy."""
    payload = _payload(_zone(index=0))
    payload["zones"]["globalSchedules"]["elements"] = [
        _schedule(4, "Last"),
        _schedule(0, "First"),
    ]
    payload["zones"]["elements"][0]["schedule"]["name"] = "Local only"
    entry, coordinator = _context(_snapshot(payload))
    entity = climate.TechThermostat(_zone(), coordinator, entry)
    assert entity.extra_state_attributes == {
        "schedule_mode": "globalSchedule",
        "schedule_index": 0,
        "active_schedule_name": "First",
    }
    assert entity.unique_id == f"{_UDID}_101_zone_climate"
    assert entity.target_temperature == 23.5
    assert entity.current_temperature == 21.0
    assert entity.hvac_mode == "heat"
    assert not any("interval" in key for key in entity.extra_state_attributes)


@pytest.mark.parametrize("mode", ["constantTemp", "timeLimit", "unknownMode"])
def test_nonschedule_modes_preserve_raw_choice_without_active_template(
    mode: str,
) -> None:
    """A stored schedule index does not make constant or unknown modes applicable."""
    info = schedules.zone_schedule_info(_snapshot(_payload(_zone(mode=mode))), 101)
    assert info["schedule_mode"] == mode
    assert info["schedule_index"] == 1
    assert info["active_schedule_name"] is None
    assert info["schedule_applicable"] is False


def test_local_is_explicitly_configured_and_uses_only_local_template() -> None:
    """A nameless local template cannot acquire the global name at a stored index."""
    info = schedules.zone_schedule_info(
        _snapshot(_payload(_zone(mode="localSchedule"))), 101
    )
    assert info["configured_source"] == "local"
    assert info["schedule_applicable"] is True
    assert info["active_schedule_name"] is None


@pytest.mark.parametrize(
    "controller",
    [
        {"type": 108, "value": 1},
        {"type": 108, "value": 2},
        {"type": 108, "value": 3},
        {"type": 108, "value": False},
        {"type": 108, "value": "0"},
        {"type": 999, "value": 0},
        None,
        {"type": 108, "value": 0, "duringChange": True},
    ],
)
def test_controller_override_or_unknown_never_claims_active(controller: Any) -> None:
    """Holiday and other overrides retain configuration but suppress applicability."""
    snapshot = _snapshot()
    snapshot["controllerMode"] = controller
    info = schedules.zone_schedule_info(snapshot, 101)
    assert info["configured_source"] == "global"
    assert info["schedule_applicable"] is False
    assert info["active_schedule_name"] is None
    diagnostic = schedules.schedule_diagnostics(snapshot)
    assert diagnostic["zones"]["101"]["schedule_applicable"] is False


@pytest.mark.parametrize(
    "target,value",
    [
        ("zone", True),
        ("zone", None),
        ("global", True),
        ("global", None),
        ("mode", True),
        ("template", True),
    ],
)
def test_changes_and_missing_required_flags_suppress_applicability(
    target: str, value: Any
) -> None:
    """A transitional or unproven snapshot never names a completed active template."""
    snapshot = _snapshot()
    locations = {
        "zone": snapshot["zones"][101]["zone"],
        "mode": snapshot["zones"][101]["mode"],
        "global": snapshot["globalSchedules"],
        "template": snapshot["globalSchedules"]["elements"][0],
    }
    locations[target]["duringChange"] = value
    assert schedules.zone_schedule_info(snapshot, 101)["schedule_applicable"] is False
    assert (
        schedules.climate_schedule_attributes(snapshot, 101, True)[
            "active_schedule_name"
        ]
        is None
    )


@pytest.mark.parametrize("index", [None, -1, 5, True, "1"])
def test_invalid_schedule_indices_are_unknown(index: Any) -> None:
    """Falsy zero works elsewhere, but booleans and invalid slots are not indices."""
    info = schedules.zone_schedule_info(_snapshot(_payload(_zone(index=index))), 101)
    assert info["schedule_index"] is None
    assert info["active_schedule_name"] is None
    diagnostic = schedules.schedule_diagnostics(_snapshot(_payload(_zone(index=index))))
    assert diagnostic["zones"]["101"]["mode_raw"]["scheduleIndex"] == index


def test_duplicate_deleted_or_invalid_template_cannot_be_active() -> None:
    """Ambiguous lookup and decoding failure never fall back to the local copy."""
    snapshot = _snapshot()
    templates = snapshot["globalSchedules"]["elements"]
    templates.append(deepcopy(templates[0]))
    assert schedules.zone_schedule_info(snapshot, 101)["active_schedule_name"] is None
    assert (
        "globalSchedules:duplicate_index:1"
        in schedules.schedule_diagnostics(snapshot)["errors"]
    )
    templates.clear()
    assert schedules.zone_schedule_info(snapshot, 101)["active_schedule_name"] is None
    templates.append(_schedule())
    templates[0]["p0Intervals"] = [{"start": 480, "stop": 0, "temp": 200}]
    assert schedules.zone_schedule_info(snapshot, 101)["active_schedule_name"] is None


@pytest.mark.parametrize(
    "envelope",
    [None, [], {}, {"elements": None}, {"elements": [None, {}, {"zone": []}]}],
)
def test_missing_and_malformed_zone_envelopes_clear_schedule_state(
    envelope: Any,
) -> None:
    """A new empty snapshot cannot resurrect a zone from the legacy entity cache."""
    snapshot = schedules.schedule_snapshot(envelope)
    assert snapshot["zones"] == {}
    assert schedules.climate_schedule_attributes(snapshot, 101, True) == {
        "schedule_mode": None,
        "schedule_index": None,
        "active_schedule_name": None,
    }


@pytest.mark.parametrize("raw", [None, [], "invalid", 0, {"p0Days": None}])
def test_malformed_template_is_preserved_as_raw_without_raising(raw: Any) -> None:
    """Decoder failures keep their source shape for diagnosis."""
    result = schedules.normalize_schedule(raw)
    assert result["valid"] is False
    assert result["raw"] == raw
    assert result["errors"]


def test_pending_global_template_has_raw_provenance_but_no_completed_week() -> None:
    """During change the diagnostic graph cannot look finalized."""
    snapshot = _snapshot()
    snapshot["globalSchedules"]["duringChange"] = True
    result = schedules.schedule_diagnostics(snapshot)["global_schedules"][0]
    assert result["valid"] is False
    assert result["week"] is None
    assert result["raw"] == _schedule()
    assert "globalSchedules:during_change_or_unknown" in result["errors"]


def test_missing_snapshot_is_distinct_from_coordinator_failure() -> None:
    """An absent cache cannot masquerade as a fresh graph or a transport error."""
    assert schedules.schedule_diagnostics(None) == {
        "status": "missing",
        "errors": ["schedule_snapshot_missing"],
    }


def test_snapshot_is_detached_and_clears_one_removed_zone() -> None:
    """A surviving zone cannot cause a deleted zone's old selection to persist."""
    payload = _payload()
    payload["zones"]["elements"].append(_zone(102))
    snapshot = _snapshot(payload)
    payload["zones"]["globalSchedules"]["elements"][0]["name"] = "Changed later"
    assert (
        schedules.zone_schedule_info(snapshot, 101)["active_schedule_name"]
        == "Synthetic global"
    )
    payload["zones"]["elements"] = [payload["zones"]["elements"][1]]
    refreshed = _snapshot(payload)
    assert schedules.zone_schedule_info(refreshed, 101)["schedule_mode"] is None
    assert (
        schedules.zone_schedule_info(refreshed, 102)["active_schedule_name"]
        == "Changed later"
    )


def test_failed_coordinator_clears_public_values_and_diagnostic_graphs() -> None:
    """Last good templates stay out of state attributes during a failed poll."""
    entry, coordinator = _context(_snapshot())
    entity = climate.TechThermostat(_zone(), coordinator, entry)
    diagnostic = sensor.ControllerSchedulesSensor(coordinator, entry)
    coordinator.last_update_success = False
    assert entity.extra_state_attributes == {
        "schedule_mode": None,
        "schedule_index": None,
        "active_schedule_name": None,
    }
    assert diagnostic.available is False
    assert diagnostic.native_value is None
    assert diagnostic.extra_state_attributes == {"errors": ["coordinator_unavailable"]}


def test_diagnostics_are_stable_and_publish_five_global_templates_only_once() -> None:
    """Polling metadata and per-zone duplication cannot inflate recorder state."""
    payload = _payload()
    payload["zones"]["elements"] = [_zone(zone_id=i) for i in range(101, 116)]
    payload["zones"]["globalSchedules"]["elements"] = [_schedule(i) for i in range(5)]
    before = schedules.schedule_diagnostics(_snapshot(payload))
    payload["zones"]["globalSchedules"]["time"] = "next-server-poll"
    after = schedules.schedule_diagnostics(_snapshot(payload))
    assert before == after
    assert len(before["global_schedules"]) == 5
    assert len(before["zones"]) == 15
    assert all("global_schedules" not in zone for zone in before["zones"].values())


class _Transport:
    """Record actual Tech request paths while only returning local dictionaries."""

    def __init__(self, payload: dict) -> None:
        """Keep the replaceable module response and an empty request log."""
        self.payload = payload
        self.fail = False
        self.requests: list[tuple[str, str]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        """Implement the async context manager consumed by production Tech.get."""
        self.requests.append(("GET", url))
        if self.fail:
            raise tech.TechError(503, "synthetic offline failure")
        return _Response(
            {"data": {"elements": []}} if "/menu/" in url else self.payload
        )

    def post(self, *args: Any, **kwargs: Any) -> None:
        """Fail immediately if the read-only path tries to control a device."""
        raise AssertionError("schedule inspection must never POST")


class _Response:
    """Minimal successful HTTP response for the production async GET method."""

    status = 200

    def __init__(self, payload: dict) -> None:
        """Keep a detached payload for this request."""
        self.payload = deepcopy(payload)

    async def __aenter__(self) -> _Response:
        """Enter the fake HTTP response context."""
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Exit without suppressing exceptions."""

    async def json(self) -> dict:
        """Return the recorded synthetic JSON."""
        return self.payload


@pytest.mark.asyncio
async def test_real_cache_and_setup_share_existing_gets_and_clear_removed_zones() -> (
    None
):
    """One module plus the existing menu GETs support both platforms and refresh."""
    transport = _Transport(_payload())
    api = tech.Tech(
        transport, "synthetic-user", "synthetic-token", "https://synthetic.invalid/"
    )
    data = await api.module_data(_UDID, force=True)
    expected_gets = 1 + len(const.MENU_TYPES)
    assert len(transport.requests) == expected_gets
    entry, coordinator = _context(data["schedules"])
    coordinator.api, coordinator.data = api, data
    hass = SimpleNamespace(data={const.DOMAIN: {entry.entry_id: coordinator}})
    added = []
    await sensor.async_setup_entry(
        hass, entry, lambda entities, update: added.extend(entities)
    )
    thermostats = []
    await climate.async_setup_entry(
        hass, entry, lambda entities, update: thermostats.extend(entities)
    )
    diagnostics = [
        entity
        for entity in added
        if isinstance(entity, sensor.ControllerSchedulesSensor)
    ]
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.unique_id == f"{_UDID}_schedules"
    assert diagnostic._attr_entity_registry_enabled_default is False
    assert diagnostic._attr_entity_category == "diagnostic"
    assert diagnostic.device_info["identifiers"] == {(const.DOMAIN, _UDID)}
    assert len(transport.requests) == expected_gets
    assert (
        thermostats[0].extra_state_attributes["active_schedule_name"]
        == "Synthetic global"
    )

    transport.payload = {"zones": {"elements": []}, "tiles": []}
    coordinator.data = await api.module_data(_UDID, force=True)
    assert len(transport.requests) == 2 * expected_gets
    assert (
        101 in coordinator.data["zones"]
    )  # Legacy consumers retain their original cache.
    assert coordinator.data["schedules"]["zones"] == {}
    assert coordinator.data["schedules"]["globalSchedules"] is None
    assert thermostats[0].extra_state_attributes["schedule_mode"] is None
    assert diagnostic.extra_state_attributes["zones"] == {}
    assert diagnostic.extra_state_attributes["global_schedules"] == []


@pytest.mark.asyncio
async def test_zoneless_controller_does_not_gain_a_schedule_entity() -> None:
    """An empty schedule envelope is not enough to claim controller capability."""
    transport = _Transport(
        {"zones": {"elements": [], "globalSchedules": {"elements": []}}, "tiles": []}
    )
    api = tech.Tech(
        transport, "synthetic-user", "synthetic-token", "https://synthetic.invalid/"
    )
    data = await api.module_data(_UDID, force=True)
    entry, coordinator = _context(data["schedules"])
    coordinator.api, coordinator.data = api, data
    hass = SimpleNamespace(data={const.DOMAIN: {entry.entry_id: coordinator}})
    added = []
    await sensor.async_setup_entry(
        hass, entry, lambda entities, update: added.extend(entities)
    )
    assert added == []
    assert len(transport.requests) == 1 + len(const.MENU_TYPES)


@pytest.mark.asyncio
async def test_failed_refresh_leaves_no_public_stale_template() -> None:
    """A real cache refresh failure is gated by coordinator availability."""
    transport = _Transport(_payload())
    api = tech.Tech(
        transport, "synthetic-user", "synthetic-token", "https://synthetic.invalid/"
    )
    data = await api.module_data(_UDID, force=True)
    entry, coordinator = _context(data["schedules"])
    coordinator.data = data
    thermostat = climate.TechThermostat(_zone(), coordinator, entry)
    diagnostic = sensor.ControllerSchedulesSensor(coordinator, entry)
    transport.fail = True
    with pytest.raises(tech.TechError):
        await api.module_data(_UDID, force=True)
    coordinator.last_update_success = False
    assert thermostat.extra_state_attributes["active_schedule_name"] is None
    assert diagnostic.native_value is None
    assert "global_schedules" not in diagnostic.extra_state_attributes
    assert len(transport.requests) == 2 + len(const.MENU_TYPES)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope", [None, [], {"elements": None}, {"elements": [None, {}, {"zone": []}]}]
)
async def test_real_cache_handles_missing_or_malformed_zones(envelope: Any) -> None:
    """The production module path clears its schedule snapshot on bad envelopes."""
    transport = _Transport({"zones": envelope, "tiles": []})
    api = tech.Tech(
        transport, "synthetic-user", "synthetic-token", "https://synthetic.invalid/"
    )
    data = await api.module_data(_UDID, force=True)
    assert data["schedules"]["zones"] == {}
    assert data["schedules"]["globalSchedules"] is None
    assert len(transport.requests) == 1 + len(const.MENU_TYPES)
