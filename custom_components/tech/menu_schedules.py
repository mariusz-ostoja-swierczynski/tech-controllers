"""Read-only weekly menu configuration, separate from zone schedules.

Wire days are Sunday=0. Public days are Monday first and intervals are
half-open controller-clock minutes, with 1440 denoting the end of the day.
These profiles describe configuration, never the current pump command.
"""

from __future__ import annotations

from collections.abc import Iterator
from itertools import chain
from typing import Any, cast

# Per full menu tree, including unrelated controls. These ceilings bound the weekly
# decoder even on a controller with thousands of settings. Values include containers, scalars and object keys; depth counts
# nested containers including the tree itself. Text counts characters, not
# encoded bytes. Reaching a ceiling is allowed; exceeding one rejects the tree.
MAX_MENU_ELEMENTS = 32_768
MAX_MENU_JSON_VALUES = 1_048_576
MAX_MENU_JSON_DEPTH = 64
MAX_MENU_TEXT_CHARS = 8 * 1024 * 1024

PROFILES = (
    {
        "menu_type": "MU",
        "parent_id": 30028,
        "type": 12,
        "name": "DHW weekly schedule",
        "base_item_id": 3203,
        "mode_item_id": 3200,
        "weekly_item_id": 3205,
    },
    {
        "menu_type": "MI",
        "parent_id": 30666,
        "type": 13,
        "name": "Circulation weekly schedule",
        "mode_item_id": 10370,
    },
)
_DAYS = (
    (1, "monday"),
    (2, "tuesday"),
    (3, "wednesday"),
    (4, "thursday"),
    (5, "friday"),
    (6, "saturday"),
    (0, "sunday"),
)
_SEVERITY = {"ready": 0, "pending": 1, "missing": 2, "invalid": 3}


def _integer(value: Any) -> bool:
    return type(value) is int


def _settled(item: dict[str, Any]) -> str:
    value = item.get("duringChange")
    if value is None or value is False or value == "f":
        return "ready"
    if value is True or value == "t":
        return "pending"
    return "invalid"


def _resource_limit_exceeded(tree: dict[str, Any]) -> bool:
    """Bound traversal without recursion or a work list the size of the input."""
    elements = tree.get("elements")
    if isinstance(elements, list) and len(elements) > MAX_MENU_ELEMENTS:
        return True
    values = text_chars = 0
    stack: list[Iterator[Any]] = [iter((tree,))]
    while stack:
        try:
            value = next(stack[-1])
        except StopIteration:
            stack.pop()
            continue
        values += 1
        if values > MAX_MENU_JSON_VALUES:
            return True
        if isinstance(value, str):
            text_chars += len(value)
            if text_chars > MAX_MENU_TEXT_CHARS:
                return True
        elif isinstance(value, (dict, list)):
            if len(stack) > MAX_MENU_JSON_DEPTH:
                return True
            stack.append(
                iter(chain.from_iterable(value.items()))
                if isinstance(value, dict)
                else iter(value)
            )
    return False


def _id_key(item_id: int) -> bytes:
    """Use randomized byte hashing even for attacker-chosen integer ids."""
    return item_id.to_bytes((item_id.bit_length() + 8) // 8, signed=True)


def _id_counts(elements: list[dict[str, Any]]) -> dict[bytes, int]:
    """Count integer aliases once, preserving the old numeric equality rules."""
    counts: dict[bytes, int] = {}
    for item in elements:
        item_id = item.get("id")
        # Floats/bools equal to a valid integer id are still collisions. Other
        # JSON ids cannot equal an integer and may be unhashable; skip those.
        if type(item_id) not in (int, float, bool) or (
            type(item_id) is float and not item_id.is_integer()
        ):
            continue
        key = _id_key(int(cast("int | float | bool", item_id)))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _inconsistent_range(group: list[dict[str, Any]]) -> bool:
    """Compare ranges once without building a set of untrusted integers."""
    first = None
    for item in group:
        params = item.get("params")
        if not isinstance(params, dict):
            continue
        low, high = params.get("min"), params.get("max")
        if not _integer(low) or not _integer(high):
            continue
        if first is None:
            first = low, high
        elif (low, high) != first:
            return True
    return False


def supported_profiles(snapshot: Any) -> list[dict[str, Any]]:
    """Discover only the two adopted groups from accessible schedule items."""
    if not isinstance(snapshot, dict):
        return []
    result = []
    for profile in PROFILES:
        tree = snapshot.get(profile["menu_type"], {})
        elements = tree.get("elements", []) if isinstance(tree, dict) else []
        if (
            not isinstance(tree, dict)
            or not isinstance(elements, list)
            or _resource_limit_exceeded(tree)
        ):
            continue
        if any(
            isinstance(item, dict)
            and item.get("menuType") == profile["menu_type"]
            and type(item.get("parentId")) is int
            and item["parentId"] == profile["parent_id"]
            and type(item.get("type")) is int
            and item["type"] == profile["type"]
            and item.get("access") is True
            for item in elements
        ):
            result.append(profile)
    return result


def _find(
    elements: list[dict[str, Any]], item_id: int, item_type: int, menu_type: str
) -> tuple[Any, str]:
    # Count numeric aliases before checking the type. A matching float in
    # addition to the integer is an ambiguous menu item, not a second setting.
    matches = [item for item in elements if item.get("id") == item_id]
    if not matches:
        return None, "missing"
    item = matches[0]
    if (
        len(matches) != 1
        or type(item["id"]) is not int
        or type(item.get("type")) is not int
        or item["type"] != item_type
    ):
        return None, "invalid"
    if (
        item.get("access") is not True
        or item.get("menuType") != menu_type
        or not isinstance(item.get("params"), dict)
    ):
        return None, "invalid"
    status = _settled(item)
    return item, status


def _control(
    elements: list[dict[str, Any]],
    item_id: int,
    item_type: int,
    values: set[int],
    menu_type: str,
) -> tuple[Any, str]:
    item, status = _find(elements, item_id, item_type, menu_type)
    if item is None:
        return None, status
    value = item["params"].get("value")
    if not _integer(value) or value not in values:
        return None, "invalid"
    return (value if status == "ready" else None), status


def _periods(values: list[dict[str, Any]], step: int) -> list[dict[str, Any]]:
    periods: list[dict[str, Any]] = []
    for index, value in enumerate(values):
        if periods and all(periods[-1].get(key) == data for key, data in value.items()):
            periods[-1]["stop"] = (index + 1) * step
        else:
            periods.append({"start": index * step, "stop": (index + 1) * step, **value})
    return periods


def _base(
    elements: list[dict[str, Any]], profile: dict[str, Any]
) -> tuple[int | None, int | None, str]:
    """Read only the declared whole-degree base and reject sentinel values."""
    base, base_format = None, None
    item, state = _find(elements, profile["base_item_id"], 1, profile["menu_type"])
    if item is not None:
        params = item["params"]
        value = params.get("value")
        low, high = params.get("min"), params.get("max")
        base_format = params.get("format") if _integer(params.get("format")) else None
        if (
            not _integer(value)
            or not _integer(low)
            or not _integer(high)
            or not low <= value <= high
            or type(params.get("format")) is not int
            or params["format"] != 1
        ):
            state = "invalid"
        elif state == "ready":
            base = value
    return base, base_format, state


def _decode_day(
    item: dict[str, Any],
    profile: dict[str, Any],
    id_counts: dict[bytes, int],
    base: int | None,
    target: dict[str, Any],
    *,
    inconsistent_range: bool,
) -> str:
    """Validate one day before returning any configured periods."""
    target["item_id"] = item.get("id")
    params = item["params"]
    error = _settled(item)
    if (
        item.get("access") is not True
        or item.get("menuType") != profile["menu_type"]
        or not _integer(item.get("id"))
        or id_counts.get(_id_key(item["id"]), 0) != 1
    ):
        error = "invalid"
    intervals: list[dict[str, Any]] = []
    if profile["type"] == 12:
        low, high, values = (
            params.get("min"),
            params.get("max"),
            params.get("values"),
        )
        if (
            inconsistent_range
            or params.get("valueObjId") != profile["base_item_id"]
            or not _integer(params.get("valueObjId"))
            or not _integer(low)
            or not _integer(high)
            or low > high
            or not isinstance(values, list)
            or len(values) > 24
            or any(not _integer(raw) or raw < 0 or raw > high - low for raw in values)
        ):
            error = "invalid"
        elif error == "ready" and base is not None:
            offsets = [low + raw for raw in values] + [0] * (24 - len(values))
            intervals = _periods(
                [{"offset": offset, "target": base + offset} for offset in offsets],
                60,
            )
    else:
        width, mask = params.get("noZones"), params.get("value")
        target["no_zones"] = width if _integer(width) and width in (24, 48) else None
        subtitles = params.get("daySubtitles", 0)
        if (
            not _integer(width)
            or width not in (24, 48)
            or not _integer(mask)
            or mask < 0
            or mask >= 1 << width
            or not _integer(subtitles)
            or subtitles != 0
        ):
            error = "invalid"
        elif error == "ready":
            periods = _periods(
                [{"allowed": bool(mask & (1 << slot))} for slot in range(width)],
                1440 // width,
            )
            intervals = [period for period in periods if period["allowed"]]
    if error != "ready":
        target["errors"] = ["during_change" if error == "pending" else "invalid_day"]
    else:
        target["valid"] = base is not None if profile["type"] == 12 else True
        target["intervals"] = intervals
        if not target["valid"]:
            target["errors"] = ["base_unavailable"]
    return error


def weekly_schedule(
    snapshot: Any, profile: dict[str, Any], successful: bool = True
) -> dict[str, Any]:
    """Decode one current full-GET snapshot without falling back to old menus."""
    result: dict[str, Any] = {
        key: profile[key] for key in ("menu_type", "parent_id", "type")
    }
    result.update(
        {
            "status": None,
            "source_status": "missing",
            "errors": [],
            "schema_version": 1,
            "time_basis": "controller_local",
            "timezone_verified": False,
            "schedule_type": "temperature_correction"
            if profile["type"] == 12
            else "on_off",
            "base_value": None,
            "weekly_enabled": None,
            "operating_mode": None,
            "schedule_selected": None,
            "days": {
                name: {
                    "day_id": day,
                    "item_id": None,
                    "valid": False,
                    "intervals": [],
                    "errors": [],
                }
                for day, name in _DAYS
            },
        }
    )
    if "base_item_id" in profile:
        result["base_item_id"] = profile["base_item_id"]
        result["base_format"] = None
    else:
        result["mode_value"] = None
    tree = snapshot.get(profile["menu_type"]) if isinstance(snapshot, dict) else None
    if not successful:
        result["source_status"] = "coordinator_error"
        return result
    if not isinstance(tree, dict):
        return result
    result["source_status"] = tree.get("status", "malformed")
    elements = tree.get("elements")
    if result["source_status"] == "malformed":
        result["status"] = "invalid"
        result["errors"] = ["menu_malformed"]
        return result
    if result["source_status"] != "ok":
        return result
    if isinstance(elements, list) and _resource_limit_exceeded(tree):
        result["source_status"] = "malformed"
        result["status"] = "invalid"
        result["errors"] = ["menu_resource_limit"]
        return result
    if not isinstance(elements, list) or any(
        not isinstance(item, dict) for item in elements
    ):
        result["source_status"] = "malformed"
        result["status"] = "invalid"
        result["errors"] = ["menu_malformed"]
        return result
    status = "ready"

    def issue(problem: str, detail: str) -> None:
        nonlocal status
        if _SEVERITY[problem] > _SEVERITY[status]:
            status = problem
        result["errors"].append(detail)

    base = None
    if profile["type"] == 12:
        base, result["base_format"], state = _base(elements, profile)
        if state != "ready":
            issue(state, f"base_{state}")
        result["base_value"] = base

    mode_values = {1, 2, 3} if profile["type"] == 12 else {0, 1, 2}
    mode, state = _control(
        elements, profile["mode_item_id"], 11, mode_values, profile["menu_type"]
    )
    result["operating_mode"] = mode
    if profile["type"] == 13:
        result["mode_value"] = mode
    if state != "ready":
        issue(state, f"operating_mode_{state}")
    if profile["type"] == 12:
        weekly, state = _control(
            elements, profile["weekly_item_id"], 10, {0, 1}, profile["menu_type"]
        )
        result["weekly_enabled"] = bool(weekly) if weekly is not None else None
        if state != "ready":
            issue(state, f"weekly_enabled_{state}")
        if mode is not None and weekly is not None:
            result["schedule_selected"] = mode == 2 and weekly == 1
    elif mode is not None:
        result["schedule_selected"] = mode == 0

    group = [
        item
        for item in elements
        if isinstance(item, dict)
        and type(item.get("parentId")) is int
        and item["parentId"] == profile["parent_id"]
        and type(item.get("type")) is int
        and item["type"] == profile["type"]
    ]
    id_counts = _id_counts(elements)
    if any(
        not _integer(item.get("id")) or id_counts.get(_id_key(item["id"]), 0) != 1
        for item in group
    ):
        issue("invalid", "duplicate_or_invalid_item_id")
    inconsistent_range = profile["type"] == 12 and _inconsistent_range(group)
    if inconsistent_range:
        issue("invalid", "inconsistent_range")
    for item in group:
        params = item.get("params")
        day = params.get("dayId") if isinstance(params, dict) else None
        if not _integer(day) or day not in range(7):
            issue("invalid", "unsupported_day")

    for day, name in _DAYS:
        target = result["days"][name]
        matches = [
            item
            for item in group
            if isinstance(item.get("params"), dict)
            and _integer(item["params"].get("dayId"))
            and item["params"]["dayId"] == day
        ]
        if len(matches) != 1:
            error = "missing" if not matches else "invalid"
            target["errors"] = ["missing_day" if not matches else "duplicate_day"]
            issue(error, f"{name}_{target['errors'][0]}")
            continue
        error = _decode_day(
            matches[0],
            profile,
            id_counts,
            base,
            target,
            inconsistent_range=inconsistent_range,
        )
        if error != "ready":
            issue(error, f"{name}_{target['errors'][0]}")
    result["status"] = status
    return result
