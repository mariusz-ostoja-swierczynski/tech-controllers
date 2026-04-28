"""Helper utilities for working with integration assets."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from .const import (
    DEFAULT_ICON,
    ICON_BY_ID,
    ICON_BY_TYPE,
    MENU_ITEM_TYPE_GROUP,
    TXT_ID_BY_TYPE,
)

_LOGGER = logging.getLogger(__name__)

_REDACTED_VALUE = "***HIDDEN***"

TranslationsType = dict[str, Any]


TRANSLATIONS: TranslationsType | None = None


def redact(entry_data: dict[str, Any], keys: Iterable[str]) -> str:
    """Return a string representation of ``entry_data`` with selected keys masked.

    Args:
        entry_data: Source mapping that may contain sensitive values.
        keys: Sequence of keys whose values should be replaced.

    Returns:
        Stringified version of ``entry_data`` with sensitive values replaced by
        ``***HIDDEN***``.

    """
    keys_set = set(keys)
    sanitized_data = {
        k: _REDACTED_VALUE if k in keys_set else v for k, v in entry_data.items()
    }
    return str(sanitized_data)


async def load_subtitles(language: str, api) -> None:
    """Load translated subtitles for the active integration language.

    Args:
        language: Home Assistant language code to retrieve from the API.
        api: Authenticated Tech API client exposing ``get_translations``.

    """
    global TRANSLATIONS  # noqa: PLW0603 # pylint: disable=global-statement
    TRANSLATIONS = await api.get_translations(language)


def get_text(text_id: int) -> str:
    """Return the translated string for a subtitle identifier."""
    if TRANSLATIONS is not None and text_id != 0:
        return TRANSLATIONS.get("data", {}).get(str(text_id), f"txtId {text_id}")
    return f"txtId {text_id}"


def get_id_from_text(text: str) -> int:
    """Return the translation identifier for a given text value."""
    if text:
        _LOGGER.debug("Looking up translation id for text: %s", text)
        if TRANSLATIONS is not None:
            for key, value in TRANSLATIONS.get("data", {}).items():
                if value == text:
                    return int(key)
    return 0


def get_text_by_type(text_type: int) -> str:
    """Return the translated label associated with a tile type."""
    text_id = TXT_ID_BY_TYPE.get(text_type, f"type {text_type}")
    return get_text(text_id)


def get_icon(icon_id: int) -> str:
    """Return the Material Design icon name mapped to ``icon_id``."""
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type: int) -> str:
    """Return the default icon assigned to the provided tile type."""
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)


def build_menu_group_names(
    menus: dict[str, dict[str, Any]],
) -> dict[tuple[str, int], str]:
    """Build a mapping of ``(menu_type, group_id)`` to translated group name.

    Args:
        menus: Flat mapping of menu key to menu item payload (as returned by
            :meth:`Tech.get_module_menus`).

    Returns:
        Dictionary keyed by ``(menu_type, group_id)`` with the resolved group
        label as value.

    """
    groups: dict[tuple[str, int], str] = {}
    for item in menus.values():
        if item.get("type") != MENU_ITEM_TYPE_GROUP:
            continue
        txt_id = item.get("txtId", 0)
        name = get_text(txt_id) if txt_id else ""
        groups[(item["menuType"], item["id"])] = name
    return groups


def build_menu_zone_assignments(
    menus: dict[str, dict[str, Any]],
    zones: dict[int, dict[str, Any]],
) -> dict[str, int]:
    """Map menu item keys to zone IDs based on the menu tree hierarchy.

    Finds the top-level "Zones" group whose direct group-children count matches
    the number of zones, then walks the ``parentId`` tree to assign every
    descendant item to the corresponding zone.

    Args:
        menus: Flat mapping of menu key to menu item payload.
        zones: Mapping of zone ID to zone payload (as cached by the API client).

    Returns:
        Dictionary mapping menu item key (e.g. ``MI_308``) to zone ID.

    """
    if not zones:
        return {}

    # Index: (menuType, id) -> item for groups only
    groups_by_key: dict[tuple[str, int], dict[str, Any]] = {}
    # Index: (menuType, parentId) -> list of child group items
    children_by_parent: dict[tuple[str, int], list[dict[str, Any]]] = {}

    for item in menus.values():
        if item.get("type") != MENU_ITEM_TYPE_GROUP:
            continue
        mt = item["menuType"]
        groups_by_key[(mt, item["id"])] = item
        children_by_parent.setdefault((mt, item.get("parentId", 0)), []).append(item)

    # Find the "Zones" group: a top-level group (parentId=0) whose direct
    # group-children count equals the number of zones.
    zone_count = len(zones)
    zones_group = None
    for group in children_by_parent.get(("MI", 0), []) + children_by_parent.get(
        ("MU", 0), []
    ):
        mt = group["menuType"]
        direct_children = children_by_parent.get((mt, group["id"]), [])
        if len(direct_children) == zone_count:
            zones_group = group
            break

    if zones_group is None:
        _LOGGER.debug("No 'Zones' menu group found matching %d zones", zone_count)
        return {}

    mt = zones_group["menuType"]
    zone_subgroups = children_by_parent.get((mt, zones_group["id"]), [])
    # Sort subgroups by id for stable positional matching
    zone_subgroups.sort(key=lambda g: g["id"])

    # Sort zones by index for positional matching
    sorted_zone_ids = [
        zid for zid, zdata in sorted(zones.items(), key=lambda x: x[1]["zone"]["index"])
    ]

    if len(zone_subgroups) != len(sorted_zone_ids):
        _LOGGER.debug(
            "Zone subgroup count mismatch: %d groups vs %d zones",
            len(zone_subgroups),
            len(sorted_zone_ids),
        )
        return {}

    # Map zone subgroup id -> zone_id
    subgroup_to_zone: dict[int, int] = {
        sg["id"]: zid for sg, zid in zip(zone_subgroups, sorted_zone_ids)
    }

    # Build full (menuType, parentId) -> [child keys] index for all items
    all_children: dict[tuple[str, int], list[str]] = {}
    for key, item in menus.items():
        parent_key = (item["menuType"], item.get("parentId", 0))
        all_children.setdefault(parent_key, []).append(key)

    # BFS from each zone subgroup to collect all descendant menu keys
    assignments: dict[str, int] = {}
    for sg_id, zone_id in subgroup_to_zone.items():
        queue = [sg_id]
        while queue:
            parent_id = queue.pop()
            for child_key in all_children.get((mt, parent_id), []):
                assignments[child_key] = zone_id
                child_item = menus[child_key]
                if child_item.get("type") == MENU_ITEM_TYPE_GROUP:
                    queue.append(child_item["id"])

    _LOGGER.debug(
        "Assigned %d menu items to %d zones", len(assignments), len(subgroup_to_zone)
    )
    return assignments


def menu_entity_name(
    item: dict[str, Any],
    group_names: dict[tuple[str, int], str],
    prefix: str = "",
) -> str:
    """Return a human-readable entity name for a menu item.

    When the item belongs to a non-root parent group the group label is
    prepended so that ambiguous names like *On* gain context.

    Args:
        item: Menu item payload from the API.
        group_names: Lookup returned by :func:`build_menu_group_names`.
        prefix: Optional hub name prefix.

    Returns:
        Formatted entity name string.

    """
    txt_id = item.get("txtId", 0)
    label = get_text(txt_id) if txt_id else f"Menu {item['id']}"
    parent_id = item.get("parentId", 0)
    if parent_id != 0:
        parent_label = group_names.get((item["menuType"], parent_id), "")
        if parent_label:
            label = f"{parent_label} - {label}"
    return prefix + label
