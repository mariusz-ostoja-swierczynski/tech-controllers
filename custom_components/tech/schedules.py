"""Read-only zone schedule snapshots and Monday-first weekly decoding.

These helpers never infer the controller's clock or a target for the current
time. A selected configuration and an applicable schedule are separate facts.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
SCHEDULE_MODES = ("globalSchedule", "localSchedule")


def schedule_snapshot(zones: Any) -> dict[str, Any]:
    """Copy schedule inputs from this refresh, never from the accumulated cache."""
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
    return value / 10 if type(value) is int and 50 <= value <= 350 else None


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

    The 6100/6100 and 0/0 slots are placeholders. Reversed intervals, including
    a nonzero start with stop=0, are errors rather than inferred midnight spans.
    """
    errors: list[str] = []
    week: dict[str, Any] = dict.fromkeys(DAYS)
    result = {"valid": False, "week": week, "raw": _stable_raw(raw), "errors": errors}
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
                temp = _temperature(interval.get("temp"))
                if not (
                    type(start) is int
                    and type(stop) is int
                    and 0 <= start < stop <= 1440
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
    zone_map = snapshot.get("zones")
    zone = zone_map.get(zone_id) if isinstance(zone_map, dict) else None
    if not isinstance(zone, dict):
        return info
    mode = zone.get("mode")
    mode = mode if isinstance(mode, dict) else {}
    selected_mode = mode.get("mode")
    info["schedule_mode"] = selected_mode if isinstance(selected_mode, str) else None
    index = mode.get("scheduleIndex")
    info["schedule_index"] = index if type(index) is int and 0 <= index <= 4 else None
    if selected_mode not in SCHEDULE_MODES:
        return info
    info["configured_source"] = (
        "global" if selected_mode == "globalSchedule" else "local"
    )
    controller = snapshot.get("controllerMode")
    if not (
        isinstance(controller, dict)
        and type(controller.get("type")) is int
        and controller["type"] == 108
        and type(controller.get("value")) is int
        and controller["value"] == 0
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
        matches = [
            item
            for item in _global_templates(snapshot)
            if isinstance(item, dict)
            and type(item.get("index")) is int
            and item["index"] == index
        ]
        if len(matches) != 1:
            return info
        template = matches[0]
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
    """Publish templates once per controller, with stable raw/error provenance."""
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
        if type(index) is not int or not 0 <= index <= 4:
            template["errors"].append("index:invalid_global_index")
        elif index in indices:
            errors.append(f"globalSchedules:duplicate_index:{index}")
        else:
            indices.add(index)
        if not settled or not _settled(raw):
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
    partial = (
        errors
        or any(item["errors"] for item in global_schedules)
        or any(item["local_schedule"]["errors"] for item in zones.values())
    )
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
