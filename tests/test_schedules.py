"""Synthetic checks of production schedule decoding, cache and HA entities.

The transport and HA base classes are fake; production methods do all parsing,
refreshing, selection and entity setup. No credentials or household data are used.
"""

from __future__ import annotations

from copy import deepcopy
from enum import IntFlag
import json
import sys
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from . import test_platform_device_info as support

schedules = support._load_tech_module("schedules")
tech = support._load_tech_module("tech")
sensor = support.sensor
binary_sensor = support.binary_sensor
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
        forget_callbacks=[],
    )
    coordinator.async_add_listener = lambda callback, context=None: (lambda: None)
    # The platforms read the coordinator from the entry, as production does.
    entry.runtime_data = coordinator
    entry.options = {}
    entry.async_on_unload = lambda callback: None
    return entry, coordinator


def test_schedule_support_is_schema_capability() -> None:
    """Capability means the fields exist, not that a schedule is selected."""
    global_only = schedules.schedule_snapshot(
        {"elements": [], "globalSchedules": {"elements": [_schedule()]}}
    )
    assert global_only["supported"] is True

    zone = _zone(mode="constantTemp")
    zone_only = schedules.schedule_snapshot(
        {"elements": [zone], "globalSchedules": {"elements": []}}
    )
    assert zone_only["supported"] is True

    zone["mode"] = None
    zone["schedule"] = None
    no_schema = schedules.schedule_snapshot(
        {"elements": [zone], "globalSchedules": {"elements": []}}
    )
    assert no_schema["supported"] is False
    assert schedules.schedule_snapshot({})["supported"] is False


def test_week_is_monday_first_with_temperatures_boundaries_and_setback() -> None:
    """Weekday intervals and weekend fallback retain both decoded profiles."""
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
        {
            "start": "00:00",
            "stop": "08:00",
            "temperature": 18.0,
        },
        {
            "start": "08:00",
            "stop": "24:00",
            "temperature": 23.5,
        },
    ]
    assert decoded["week"]["saturday"] == {
        "profile": 1,
        "intervals": [],
        "setback_temperature": 19.0,
    }
    assert "raw" not in decoded
    assert decoded["errors"] == []


@pytest.mark.parametrize(
    "interval",
    [
        {"start": 480, "stop": 400, "temp": 200},
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
    assert "raw" not in decoded


def test_stop_zero_means_midnight() -> None:
    """A nonzero start with stop zero ends at midnight, not at the start."""
    raw = _schedule()
    raw["p0Intervals"] = [{"start": 1380, "stop": 0, "temp": 200}]
    raw["p1Intervals"] = [{"start": 6100, "stop": 6100, "temp": 200}]
    decoded = schedules.normalize_schedule(raw)
    assert decoded["valid"] is True
    assert decoded["errors"] == []
    assert decoded["week"]["monday"]["intervals"] == [
        {"start": "23:00", "stop": "24:00", "temperature": 20.0}
    ]


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
    raw["p1Intervals"] = [{"start": 480, "stop": 400, "temp": 200}]
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
    assert entity.native_target_temperature == 23.5
    assert entity.native_current_temperature == 21.0
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
    templates[0]["p0Intervals"] = [{"start": 480, "stop": 400, "temp": 200}]
    assert schedules.zone_schedule_info(snapshot, 101)["active_schedule_name"] is None


def test_unused_local_placeholders_do_not_make_the_controller_partial() -> None:
    """The L-8 shape: constant-temp zones with broken but unused local templates."""
    zone = _zone(mode="constantTemp")
    zone["schedule"]["p0Intervals"][0] = {"start": 480, "stop": 400, "temp": 200}
    snapshot = _snapshot(_payload(zone))
    assert schedules.zone_schedule_info(snapshot, 101)["configured_source"] is None
    assert schedules.schedule_problem(snapshot) is False
    assert schedules.schedule_diagnostics(snapshot)["status"] == "ready"


def test_a_broken_selected_local_schedule_is_a_problem() -> None:
    """A selected local template that fails decoding is a real controller problem."""
    zone = _zone(mode="localSchedule")
    zone["schedule"]["p0Intervals"][0] = {"start": 480, "stop": 400, "temp": 200}
    snapshot = _snapshot(_payload(zone))
    assert schedules.selected_schedule(snapshot, 101)["valid"] is False
    assert schedules.schedule_problem(snapshot) is True
    assert schedules.schedule_diagnostics(snapshot)["status"] == "partial"


def test_a_broken_selected_global_schedule_is_a_problem() -> None:
    """A selected global template that fails decoding is a real problem."""
    payload = _payload()
    payload["zones"]["globalSchedules"]["elements"][0]["p0Intervals"][0] = {
        "start": 480,
        "stop": 0,
        "temp": 200,
    }
    snapshot = _snapshot(payload)
    assert schedules.selected_schedule(snapshot, 101)["valid"] is False
    assert schedules.schedule_problem(snapshot) is True
    assert schedules.schedule_diagnostics(snapshot)["status"] == "partial"


def test_a_pending_selected_schedule_is_partial_but_not_a_problem() -> None:
    """A write in progress is incomplete, not a configuration error."""
    payload = _payload()
    payload["zones"]["globalSchedules"]["elements"][0]["duringChange"] = True
    snapshot = _snapshot(payload)
    assert schedules.selected_schedule(snapshot, 101)["settled"] is False
    assert schedules.schedule_problem(snapshot) is False
    assert schedules.schedule_diagnostics(snapshot)["status"] == "partial"


def test_zone_schedule_attributes_include_selected_and_local_templates() -> None:
    """The per-zone sensor carries both its configured template and its local copy."""
    attributes = schedules.zone_schedule_attributes(_snapshot(), 101)
    assert attributes["selected_schedule"]["source"] == "global"
    assert attributes["selected_schedule"]["name"] == "Synthetic global"
    assert attributes["selected_schedule"]["valid"] is True
    assert attributes["local_schedule"]["valid"] is True
    assert attributes["local_schedule"]["week"]["monday"] is not None


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
def test_malformed_template_decodes_without_raising(raw: Any) -> None:
    """Decoder failures report errors without echoing the source payload."""
    result = schedules.normalize_schedule(raw)
    assert result["valid"] is False
    assert "raw" not in result
    assert result["errors"]


def test_pending_global_template_has_no_completed_week() -> None:
    """During change the diagnostic graph cannot look finalized."""
    snapshot = _snapshot()
    snapshot["globalSchedules"]["duringChange"] = True
    result = schedules.schedule_diagnostics(snapshot)["global_schedules"][0]
    assert result["valid"] is False
    assert result["week"] is None
    assert result["index"] == 1
    assert result["name"] == "Synthetic global"
    assert "raw" not in result
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
    assert diagnostic._attr_translation_key == "controller_schedules"
    assert diagnostic.device_info["identifiers"] == {(const.DOMAIN, _UDID)}
    zone_schedules = [
        entity for entity in added if isinstance(entity, sensor.ZoneScheduleSensor)
    ]
    local_schedules = [
        entity for entity in added if isinstance(entity, sensor.ZoneLocalScheduleSensor)
    ]
    global_schedules = [
        entity
        for entity in added
        if isinstance(entity, sensor.ControllerGlobalScheduleSensor)
    ]
    assert len(zone_schedules) == 1
    assert zone_schedules[0].unique_id == f"{_UDID}_101_zone_schedule"
    assert zone_schedules[0].native_value == "Synthetic global"
    assert zone_schedules[0]._attr_translation_key == "zone_schedule_entity"
    assert zone_schedules[0]._attr_entity_registry_enabled_default is True
    assert len(local_schedules) == 1
    assert local_schedules[0].unique_id == f"{_UDID}_101_zone_schedule_local"
    assert local_schedules[0].native_value == "valid"
    assert local_schedules[0]._attr_translation_key == "local_schedule_entity"
    assert local_schedules[0]._attr_entity_registry_enabled_default is False
    assert len(global_schedules) == schedules.GLOBAL_SCHEDULE_SLOTS
    by_index = {entity._index: entity for entity in global_schedules}
    assert sorted(by_index) == list(range(schedules.GLOBAL_SCHEDULE_SLOTS))
    assert by_index[1].unique_id == f"{_UDID}_schedule_global_1"
    assert by_index[1].native_value == "valid"
    assert by_index[1]._attr_translation_key == "global_schedule_entity"
    assert by_index[1]._attr_entity_registry_enabled_default is False
    assert by_index[4].native_value == "missing"

    coordinator.data["schedules"]["globalSchedules"]["elements"].append(
        _schedule(4, "Later")
    )
    assert by_index[4].native_value == "valid"
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


def test_template_sensors_report_missing_pending_and_invalid() -> None:
    """Each template sensor reports its own decode state."""
    entry, coordinator = _context(_snapshot())
    global_sensor = sensor.ControllerGlobalScheduleSensor(coordinator, entry, 1)
    assert global_sensor.native_value == "valid"

    payload = _payload()
    payload["zones"]["globalSchedules"]["elements"][0]["p0Intervals"][0] = {
        "start": 480,
        "stop": 0,
        "temp": 200,
    }
    coordinator.data["schedules"] = _snapshot(payload)
    assert global_sensor.native_value == "invalid"

    payload["zones"]["globalSchedules"]["elements"][0]["duringChange"] = True
    coordinator.data["schedules"] = _snapshot(payload)
    assert global_sensor.native_value == "pending"

    missing = sensor.ControllerGlobalScheduleSensor(coordinator, entry, 4)
    assert missing.native_value == "missing"

    zone = _zone()
    local = sensor.ZoneLocalScheduleSensor(zone, coordinator, entry)
    assert local.native_value == "valid"
    zone["schedule"]["p0Intervals"][0] = {
        "start": 480,
        "stop": 0,
        "temp": 200,
    }
    coordinator.data["schedules"] = _snapshot(_payload(zone))
    assert local.native_value == "invalid"


@pytest.mark.parametrize(
    ("mode", "translation_key", "expected"),
    [
        ("constantTemp", "constant-temp", "Constant Temperature"),
        ("localSchedule", "local-schedule", "Local Schedule"),
    ],
)
def test_zone_schedule_mode_is_translated(
    mode: str,
    translation_key: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured mode without an active name is translated for display."""
    zone = _zone(mode=mode)
    entry, coordinator = _context(_snapshot(_payload(zone)))
    entity = sensor.ZoneScheduleSensor(zone, coordinator, entry)
    entity.hass = SimpleNamespace(config=SimpleNamespace(language="en"))

    def translate(hass, state, domain, platform, key, *tail):
        assert hass is entity.hass
        assert domain == "sensor"
        assert platform == const.DOMAIN
        assert key == "zone_schedule_entity"
        assert state == translation_key
        assert tail == (None,)
        return expected

    monkeypatch.setattr(sensor, "async_translate_state", translate)
    assert entity.native_value == expected


def test_constant_temperature_zone_has_no_selected_schedule() -> None:
    """A constant-temp zone still exposes its local template without inventing one."""
    zone = _zone(mode="constantTemp")
    entry, coordinator = _context(_snapshot(_payload(zone)))
    zone_sensor = sensor.ZoneScheduleSensor(zone, coordinator, entry)
    assert zone_sensor.native_value == "constantTemp"
    attributes = zone_sensor.extra_state_attributes
    assert attributes["selected_schedule"] is None
    assert attributes["local_schedule"]["valid"] is True


def test_controller_status_ignores_an_unused_broken_local_template() -> None:
    """The L-8 case must not turn the controller diagnostic partial."""
    zone = _zone(mode="constantTemp")
    zone["schedule"]["p0Intervals"][0] = {
        "start": 480,
        "stop": 0,
        "temp": 200,
    }
    entry, coordinator = _context(_snapshot(_payload(zone)))
    diagnostic = sensor.ControllerSchedulesSensor(coordinator, entry)
    assert diagnostic.native_value == "ready"
    assert diagnostic.extra_state_attributes["zones"]["101"]["local_errors"]


def test_controller_attributes_stay_below_recorder_limit() -> None:
    """The controller summary must not duplicate every template's raw/week graph."""
    payload = _payload()
    payload["zones"]["elements"] = [_zone(zone_id=i) for i in range(101, 109)]
    payload["zones"]["globalSchedules"]["elements"] = [_schedule(i) for i in range(5)]
    entry, coordinator = _context(_snapshot(payload))
    diagnostic = sensor.ControllerSchedulesSensor(coordinator, entry)
    attributes = diagnostic.extra_state_attributes
    assert len(json.dumps(attributes)) < 16384
    assert all(
        "raw" not in item and "week" not in item
        for item in attributes["global_schedules"]
    )
    assert all(
        "local_schedule" not in zone for zone in attributes["zones"].values()
    )


def test_zone_attributes_stay_below_recorder_limit() -> None:
    """A fully populated zone still fits both selected and local weekly graphs."""
    def intervals() -> list[dict[str, Any]]:
        return [
            {"start": index * 180, "stop": (index + 1) * 180, "temp": 200 + index}
            for index in range(4)
        ]

    zone = _zone()
    zone["schedule"]["p0Intervals"] = intervals()
    zone["schedule"]["p1Intervals"] = intervals()
    payload = _payload(zone)
    global_schedule = payload["zones"]["globalSchedules"]["elements"][0]
    global_schedule["p0Intervals"] = intervals()
    global_schedule["p1Intervals"] = intervals()

    attributes = schedules.zone_schedule_attributes(_snapshot(payload), 101)
    assert len(json.dumps(attributes)) < 16384
    assert attributes["selected_schedule"]["valid"] is True
    assert attributes["local_schedule"]["valid"] is True
    assert "raw" not in attributes["selected_schedule"]
    assert "raw" not in attributes["local_schedule"]


@pytest.mark.asyncio
async def test_schedule_problem_sensor_tracks_only_selected_templates() -> None:
    """A broken selected global template turns the problem sensor on."""
    payload = _payload()
    transport = _Transport(payload)
    api = tech.Tech(
        transport, "synthetic-user", "synthetic-token", "https://synthetic.invalid/"
    )
    data = await api.module_data(_UDID, force=True)
    entry, coordinator = _context(data["schedules"])
    coordinator.api, coordinator.data = api, data
    hass = SimpleNamespace(data={const.DOMAIN: {entry.entry_id: coordinator}})
    added = []
    await binary_sensor.async_setup_entry(
        hass, entry, lambda entities, update: added.extend(entities)
    )
    problems = [
        entity
        for entity in added
        if isinstance(entity, binary_sensor.ScheduleProblemSensor)
    ]
    assert len(problems) == 1
    assert problems[0].unique_id == f"{_UDID}_schedule_problem"
    assert problems[0]._attr_translation_key == "schedule_problem_entity"
    assert problems[0].available is True
    assert problems[0].is_on is False

    payload["zones"]["globalSchedules"]["elements"][0]["p0Intervals"] = [
        {"start": 480, "stop": 400, "temp": 200}
    ]
    coordinator.data = {"schedules": _snapshot(payload), "tiles": {}}
    assert problems[0].is_on is True

    coordinator.last_update_success = False
    assert problems[0].available is False
    assert problems[0].is_on is None


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
