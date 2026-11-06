"""Read-only zone schedule snapshots and Monday-first weekly decoding.

These helpers never infer the controller's clock or a target for the current
time. A selected configuration and an applicable schedule are separate facts.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SCHEDULE_MODES = ("globalSchedule", "localSchedule")

# The controller exposes up to five global templates, indexed 0..4. The same
# slots are used by the value type's `scheduleIndex`, so an index outside this
# range is not a schedule selection.
GLOBAL_SCHEDULE_SLOTS = 5
SCHEDULE_INDEX_MIN = 0
SCHEDULE_INDEX_MAX = GLOBAL_SCHEDULE_SLOTS - 1

# Temperatures in this payload are tenths of a degree, in the controller's
# public 5.0..35.0 C range.
SCHEDULE_TEMPERATURE_MIN = 50
SCHEDULE_TEMPERATURE_MAX = 350
SCHEDULE_TEMPERATURE_DIVISOR = 10
MINUTES_IN_A_DAY = 24 * 60

# `controllerMode` is the same type-108/value-0 "normal operation" marker the
# eModul app reads. Anything else (holiday, eco, manual override, a pending
# change) means the selected schedule is not proven applicable.
SCHEDULE_CONTROLLER_MODE_TYPE = 108
SCHEDULE_CONTROLLER_MODE_NORMAL = 0


def schedule_snapshot(zones: Any) -> dict[str, Any]:
    """Copy schedule inputs from this refresh, never from the accumulated cache.

    ``supported`` describes schema capability, not the current selection: the
    controller is capable when it returns global template elements or any zone
    carries a mode/schedule object, even when every zone is currently in
    constant-temperature mode.
    """
    envelope = zones if isinstance(zones, dict) else {}
    elements = envelope.get("elements")
    current = {}
    for item in elements if isinstance(elements, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("zone"), dict):
            continue
        zone = item["zone"]
        zone_id = zone.get("id")
        if (
            type(zone_id) is not int
            or not zone.get("visibility")
            or zone.get("zoneState") == "zoneUnregistered"
        ):
            continue
        current[zone_id] = deepcopy(
            {
                "zone": {key: zone.get(key) for key in ("duringChange", "zoneState")},
                "mode": item.get("mode"),
                "schedule": item.get("schedule"),
            }
        )
    parameters = envelope.get("controllerParameters")
    globals_ = deepcopy(envelope.get("globalSchedules"))
    supported = (isinstance(globals_, dict) and bool(globals_.get("elements"))) or any(
        item["mode"] is not None or item["schedule"] is not None
        for item in current.values()
    )
    return {
        "supported": supported,
        "globalSchedules": globals_,
        "controllerMode": deepcopy(parameters.get("controllerMode"))
        if isinstance(parameters, dict)
        else None,
        "zones": current,
    }


def _temperature(value: Any) -> float | None:
    """Decode the public zone-schedule range without accepting booleans."""
    return (
        value / SCHEDULE_TEMPERATURE_DIVISOR
        if type(value) is int
        and SCHEDULE_TEMPERATURE_MIN <= value <= SCHEDULE_TEMPERATURE_MAX
        else None
    )


def _clock_time(minutes: int) -> str:
    """Render an end-exclusive schedule offset as a clock time.

    The payload counts minutes from midnight, so 1440 is the end of the day
    and is rendered as ``24:00`` rather than wrapping to ``00:00``.
    """
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _stable_raw(value: Any) -> Any:
    """Keep source values but omit polling metadata from recorder attributes."""
    if isinstance(value, dict):
        return deepcopy(
            {
                key: item
                for key, item in value.items()
                if key not in ("time", "transaction_time")
            }
        )
    return deepcopy(value)


def normalize_schedule(raw: Any) -> dict[str, Any]:
    """Decode complete days; errors in an unused profile do not erase valid days.

    The 6100/6100 and 0/0 slots are placeholders. A nonzero start with stop=0
    is the controller's midnight endpoint and is normalized to 1440; other
    reversed intervals are errors rather than inferred spans.
    """
    errors: list[str] = []
    week: dict[str, Any] = dict.fromkeys(DAYS)
    result = {"valid": False, "week": week, "errors": errors}
    if not isinstance(raw, dict):
        errors.append("schedule:missing_or_invalid")
        return result

    profiles = []
    masks = []
    for profile in range(2):
        prefix = f"p{profile}"
        mask = raw.get(f"{prefix}Days")
        if not (
            isinstance(mask, list)
            and len(mask) == 7
            and all(type(day) is str and day in ("0", "1") for day in mask)
        ):
            errors.append(f"{prefix}Days:invalid_mask")
            mask = None
        masks.append(mask)
        setback = _temperature(raw.get(f"{prefix}SetbackTemp"))
        valid = setback is not None
        if not valid:
            errors.append(f"{prefix}SetbackTemp:invalid_temperature")
        intervals = raw.get(f"{prefix}Intervals")
        decoded = []
        if not isinstance(intervals, list):
            errors.append(f"{prefix}Intervals:invalid_list")
            valid = False
        else:
            for index, interval in enumerate(intervals):
                path = f"{prefix}Intervals[{index}]"
                if not isinstance(interval, dict):
                    errors.append(f"{path}:invalid_interval")
                    valid = False
                    continue
                start, stop = interval.get("start"), interval.get("stop")
                if (
                    type(start) is int
                    and type(stop) is int
                    and (start, stop) in ((6100, 6100), (0, 0))
                ):
                    continue
                if type(start) is int and type(stop) is int and stop == 0:
                    stop = MINUTES_IN_A_DAY
                temp = _temperature(interval.get("temp"))
                if not (
                    type(start) is int
                    and type(stop) is int
                    and 0 <= start < stop <= MINUTES_IN_A_DAY
                ):
                    errors.append(f"{path}:invalid_range")
                    valid = False
                elif temp is None:
                    errors.append(f"{path}:invalid_temperature")
                    valid = False
                else:
                    decoded.append({"start": start, "stop": stop, "temperature": temp})
            decoded.sort(key=lambda interval: interval["start"])
            if any(a["stop"] > b["start"] for a, b in zip(decoded, decoded[1:])):
                errors.append(f"{prefix}Intervals:overlap")
                valid = False
            decoded = [
                {
                    "start": _clock_time(item["start"]),
                    "stop": _clock_time(item["stop"]),
                    "temperature": item["temperature"],
                }
                for item in decoded
            ]
        profiles.append(
            {"profile": profile, "intervals": decoded, "setback_temperature": setback}
            if valid
            else None
        )
    if all(mask is not None for mask in masks):
        for index, day in enumerate(DAYS):
            if masks[0][index] == masks[1][index]:
                errors.append(f"{day}:conflicting_profiles")
            else:
                week[day] = profiles[0 if masks[0][index] == "1" else 1]
    result["valid"] = all(day is not None for day in week.values())
    return result


def _settled(raw: Any, *, required: bool = False) -> bool:
    """Missing required change flags and unknown flag values are not settled."""
    return isinstance(raw, dict) and (
        ("duringChange" not in raw and not required) or raw.get("duringChange") is False
    )


def _global_templates(snapshot: dict[str, Any]) -> list[Any]:
    """Return only an actual template list, without guessing envelope shapes."""
    globals_ = snapshot.get("globalSchedules")
    elements = globals_.get("elements") if isinstance(globals_, dict) else None
    return elements if isinstance(elements, list) else []


def _zone_entry(snapshot: Any, zone_id: int) -> dict[str, Any] | None:
    """Return one zone snapshot entry, or ``None`` for a missing/removed zone."""
    if not isinstance(snapshot, dict):
        return None
    zone_map = snapshot.get("zones")
    zone = zone_map.get(zone_id) if isinstance(zone_map, dict) else None
    return zone if isinstance(zone, dict) else None


def _global_template(snapshot: Any, index: int | None) -> dict[str, Any] | None:
    """Return the one global template at ``index``, or ``None`` when ambiguous."""
    if type(index) is not int:
        return None
    matches = [
        item
        for item in _global_templates(snapshot if isinstance(snapshot, dict) else {})
        if isinstance(item, dict)
        and type(item.get("index")) is int
        and item["index"] == index
    ]
    return matches[0] if len(matches) == 1 else None


def _template_details(raw: Any, *, settled: bool, label: str) -> dict[str, Any]:
    """Normalize one template and keep its pending/missing state explicit."""
    result = normalize_schedule(raw)
    result["found"] = raw is not None
    if not settled:
        result.update(valid=False, week=None)
        result["errors"].append(f"{label}:during_change_or_unknown")
    result["settled"] = settled
    return result


def global_schedule_details(snapshot: Any, index: int | None) -> dict[str, Any]:
    """Return the normalized state of one global template slot."""
    raw = _global_template(snapshot, index)
    settled = _settled(raw) and _settled(
        snapshot.get("globalSchedules") if isinstance(snapshot, dict) else None,
        required=True,
    )
    result = _template_details(raw, settled=settled, label="globalSchedules")
    name = raw.get("name") if isinstance(raw, dict) else None
    return {
        "index": index,
        "name": name if isinstance(name, str) and name else None,
        **result,
    }


def local_schedule_details(snapshot: Any, zone_id: int) -> dict[str, Any]:
    """Return the normalized state of one zone's local template."""
    zone = _zone_entry(snapshot, zone_id)
    raw = zone.get("schedule") if zone is not None else None
    settled = _settled(raw) and _settled(
        zone.get("zone") if zone is not None else None, required=True
    )
    result = _template_details(raw, settled=settled, label="zone")
    name = raw.get("name") if isinstance(raw, dict) else None
    return {
        "zone_id": zone_id,
        "name": name if isinstance(name, str) and name else None,
        **result,
    }


def selected_schedule(
    snapshot: Any, zone_id: int, available: bool = True
) -> dict[str, Any] | None:
    """Return the template the zone is configured to use, even when invalid."""
    info = zone_schedule_info(snapshot, zone_id, available)
    if info["configured_source"] == "global":
        return {
            "source": "global",
            "index": info["schedule_index"],
            **global_schedule_details(snapshot, info["schedule_index"]),
        }
    if info["configured_source"] == "local":
        return {
            "source": "local",
            "index": info["schedule_index"],
            **local_schedule_details(snapshot, zone_id),
        }
    return None


def zone_schedule_attributes(
    snapshot: Any, zone_id: int, available: bool = True
) -> dict[str, Any]:
    """Return the compact per-zone schedule view used by its sensor."""
    info = zone_schedule_info(snapshot, zone_id, available)
    return {
        **info,
        "selected_schedule": selected_schedule(snapshot, zone_id, available),
        "local_schedule": local_schedule_details(snapshot, zone_id)
        if available and isinstance(snapshot, dict)
        else None,
    }


def schedule_problem(snapshot: Any, available: bool = True) -> bool | None:
    """Return whether a *selected* schedule is missing or fails to decode.

    Unused templates are deliberately ignored: controllers routinely carry
    placeholder local schedules while all zones run in constant-temperature
    mode, and those placeholders must not raise a problem. A selected template
    that is still changing is pending rather than broken.
    """
    if not available:
        return None
    if not isinstance(snapshot, dict) or not snapshot.get("supported"):
        return None
    zone_map = snapshot.get("zones")
    for zone_id in zone_map if isinstance(zone_map, dict) else {}:
        info = zone_schedule_info(snapshot, zone_id)
        if info["configured_source"] is None:
            continue
        selected = selected_schedule(snapshot, zone_id)
        if selected is None or not selected["found"]:
            return True
        if not selected["settled"]:
            continue
        if not selected["valid"]:
            return True
    return False


def zone_schedule_info(
    snapshot: Any, zone_id: int, available: bool = True
) -> dict[str, Any]:
    """Resolve configured selection separately from proven applicability."""
    info = {
        "schedule_mode": None,
        "schedule_index": None,
        "active_schedule_name": None,
        "configured_source": None,
        "schedule_applicable": False,
    }
    if not available or not isinstance(snapshot, dict):
        return info
    zone = _zone_entry(snapshot, zone_id)
    if zone is None:
        return info
    mode = zone.get("mode")
    mode = mode if isinstance(mode, dict) else {}
    selected_mode = mode.get("mode")
    info["schedule_mode"] = selected_mode if isinstance(selected_mode, str) else None
    index = mode.get("scheduleIndex")
    info["schedule_index"] = (
        index
        if type(index) is int and SCHEDULE_INDEX_MIN <= index <= SCHEDULE_INDEX_MAX
        else None
    )
    if selected_mode not in SCHEDULE_MODES:
        return info
    info["configured_source"] = (
        "global" if selected_mode == "globalSchedule" else "local"
    )
    controller = snapshot.get("controllerMode")
    if not (
        isinstance(controller, dict)
        and type(controller.get("type")) is int
        and controller["type"] == SCHEDULE_CONTROLLER_MODE_TYPE
        and type(controller.get("value")) is int
        and controller["value"] == SCHEDULE_CONTROLLER_MODE_NORMAL
        and _settled(controller)
        and _settled(zone.get("zone"), required=True)
        and zone["zone"].get("zoneState") in ("zoneOn", "noAlarm")
        and _settled(mode)
    ):
        return info
    if selected_mode == "globalSchedule":
        if info["schedule_index"] is None or not _settled(
            snapshot.get("globalSchedules"), required=True
        ):
            return info
        template = _global_template(snapshot, info["schedule_index"])
        if template is None:
            return info
    else:
        template = zone.get("schedule")
    if _settled(template) and normalize_schedule(template)["valid"]:
        info["schedule_applicable"] = True
        name = template.get("name")
        info["active_schedule_name"] = name if isinstance(name, str) and name else None
    return info


def climate_schedule_attributes(
    snapshot: Any, zone_id: int, available: bool
) -> dict[str, Any]:
    """Return only the compact read-only climate attributes."""
    info = zone_schedule_info(snapshot, zone_id, available)
    return {
        key: info[key]
        for key in ("schedule_mode", "schedule_index", "active_schedule_name")
    }


def schedule_diagnostics(snapshot: Any, available: bool = True) -> dict[str, Any]:
    """Publish decoded templates once per controller with stable error provenance."""
    if not available:
        return {"status": "unavailable", "errors": ["coordinator_unavailable"]}
    if not isinstance(snapshot, dict):
        return {"status": "missing", "errors": ["schedule_snapshot_missing"]}
    errors = []
    global_schedules = []
    settled = _settled(snapshot.get("globalSchedules"), required=True)
    templates = _global_templates(snapshot)
    if not templates:
        errors.append("globalSchedules:missing_or_empty")
    indices = set()
    for raw in templates:
        template = normalize_schedule(raw)
        index = raw.get("index") if isinstance(raw, dict) else None
        template["index"] = index
        template["name"] = raw.get("name") if isinstance(raw, dict) else None
        if type(index) is not int or not SCHEDULE_INDEX_MIN <= index <= SCHEDULE_INDEX_MAX:
            template["errors"].append("index:invalid_global_index")
        elif index in indices:
            errors.append(f"globalSchedules:duplicate_index:{index}")
        else:
            indices.add(index)
        template["settled"] = settled and _settled(raw)
        if not template["settled"]:
            template.update(valid=False, week=None)
            template["errors"].append("globalSchedules:during_change_or_unknown")
        global_schedules.append(template)
    zones = {}
    zone_map = snapshot.get("zones")
    for zone_id, zone in (zone_map if isinstance(zone_map, dict) else {}).items():
        info = zone_schedule_info(snapshot, zone_id)
        local = normalize_schedule(zone.get("schedule"))
        if not _settled(zone.get("zone"), required=True) or not _settled(
            zone.get("schedule")
        ):
            local.update(valid=False, week=None)
            local["errors"].append("zone:during_change_or_unknown")
        zones[str(zone_id)] = {
            **info,
            "mode_raw": _stable_raw(zone.get("mode")),
            "zone_status_raw": _stable_raw(zone.get("zone")),
            "local_schedule": local,
        }
    # `errors` remains a complete decoding inventory, including templates a
    # zone does not use. The status is narrower: only the selected template
    # can make a controller partial. Controllers routinely keep placeholder
    # local templates while every zone runs in constant-temperature mode.
    partial = False
    for zone_id in zone_map if isinstance(zone_map, dict) else {}:
        if zone_schedule_info(snapshot, zone_id)["configured_source"] is None:
            continue
        selected = selected_schedule(snapshot, zone_id)
        if selected is None or not selected["valid"]:
            partial = True
            break
    return {
        "status": "missing"
        if not snapshot.get("supported")
        else "partial"
        if partial
        else "ready",
        "controller_mode": _stable_raw(snapshot.get("controllerMode")),
        "global_schedules": global_schedules,
        "global_during_change": (snapshot.get("globalSchedules") or {}).get(
            "duringChange"
        )
        if isinstance(snapshot.get("globalSchedules"), dict)
        else None,
        "global_metadata": _stable_raw(
            {
                key: value
                for key, value in snapshot["globalSchedules"].items()
                if key != "elements" or not isinstance(value, list)
            }
        )
        if isinstance(snapshot.get("globalSchedules"), dict)
        else _stable_raw(snapshot.get("globalSchedules")),
        "zones": zones,
        "errors": errors,
    }


def schedule_summary(snapshot: Any, available: bool = True) -> dict[str, Any]:
    """Return the compact controller-level view safe for recorder attributes.

    The full diagnostic graph keeps every template's decoded week, which grows
    past Home Assistant's 16 KiB attribute limit on a multi-zone controller.
    The per-zone and per-template sensors already carry that detail, so the
    controller entity only needs the selection, validity and error summary.
    """
    diagnostics = schedule_diagnostics(snapshot, available)
    if "global_schedules" not in diagnostics:
        return diagnostics
    global_schedules = []
    for item in diagnostics["global_schedules"]:
        global_schedules.append(
            {
                "index": item["index"],
                "name": item["name"],
                "valid": item["valid"],
                "settled": item["settled"],
                "errors": item["errors"],
            }
        )
    zones = {}
    for zone_id, zone in diagnostics["zones"].items():
        local = zone["local_schedule"]
        zones[zone_id] = {
            "schedule_mode": zone["schedule_mode"],
            "schedule_index": zone["schedule_index"],
            "active_schedule_name": zone["active_schedule_name"],
            "configured_source": zone["configured_source"],
            "schedule_applicable": zone["schedule_applicable"],
            "local_valid": local["valid"],
            "local_errors": local["errors"],
        }
    return {
        "status": diagnostics["status"],
        "controller_mode": diagnostics["controller_mode"],
        "global_during_change": diagnostics["global_during_change"],
        "global_metadata": diagnostics["global_metadata"],
        "global_schedules": global_schedules,
        "zones": zones,
        "errors": diagnostics["errors"],
    }
