"""Helper utilities for working with integration assets."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.const import CONF_DESCRIPTION, CONF_NAME

from .const import (
    DEFAULT_ICON,
    ICON_BY_ID,
    ICON_BY_TYPE,
    MENU_ITEM_TYPE_GROUP,
    TXT_ID_BY_TYPE,
)

_LOGGER = logging.getLogger(__name__)


class Translations:
    """Translated subtitle strings fetched from the Tech API.

    One instance lives on each :class:`TechCoordinator`; entities resolve
    their labels through it instead of a module-level cache so that the
    lifetime of the translation data is tied to the config entry.
    """

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        """Wrap a raw ``get_translations`` API response (or nothing).

        Args:
            data: Raw API payload; its ``data`` key maps stringified text
                ids to translated strings. ``None`` yields an empty catalog
                so lookups degrade to the ``txtId ...`` fallback.

        """
        self._texts: dict[str, str] = (data or {}).get("data", {})

    @classmethod
    async def load(cls, language: str, api) -> Translations:
        """Fetch the subtitle catalog for ``language`` from the API.

        Args:
            language: Home Assistant language code to retrieve from the API.
            api: Authenticated Tech API client exposing ``get_translations``.

        """
        return cls(await api.get_translations(language))

    def get_text(self, text_id: int) -> str:
        """Return the translated string for a subtitle identifier."""
        if text_id != 0:
            return self._texts.get(str(text_id), f"txtId {text_id}")
        return f"txtId {text_id}"

    def get_text_by_type(self, text_type: int) -> str:
        """Return the translated label associated with a tile type."""
        text_id = TXT_ID_BY_TYPE.get(text_type)
        if text_id is None:
            return f"type {text_type}"
        return self.get_text(text_id)


def get_icon(icon_id: int) -> str:
    """Return the Material Design icon name mapped to ``icon_id``."""
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type: int) -> str:
    """Return the default icon assigned to the provided tile type."""
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)


@dataclass(frozen=True)
class MenuContext:
    """Precomputed lookups shared by the menu-based platform setups."""

    group_names: dict[tuple[str, int], str]
    zone_assignments: dict[str, int]
    depths: dict[str, int]


def build_menu_context(
    menus: dict[str, dict[str, Any]],
    zones: dict[int, dict[str, Any]],
    translations: Translations,
) -> MenuContext:
    """Build every menu lookup needed by a platform ``async_setup_entry``.

    Args:
        menus: Flat mapping of menu key to menu item payload.
        zones: Mapping of zone ID to zone payload (as cached by the API client).
        translations: Subtitle catalog used to resolve group labels.

    Returns:
        A :class:`MenuContext` bundling group names, zone assignments and
        item depths for ``menus``.

    """
    return MenuContext(
        group_names=build_menu_group_names(menus, translations),
        zone_assignments=build_menu_zone_assignments(menus, zones),
        depths=compute_menu_depths(menus),
    )


def compute_menu_depths(
    menus: dict[str, dict[str, Any]],
) -> dict[str, int]:
    """Compute the nesting depth of every menu item.

    Depth 0 is a top-level item (``parentId == 0``). Each parent traversal
    adds one. Used by the menu setup functions in :mod:`switch`, :mod:`number`,
    :mod:`select` and :mod:`button` to skip deeply-nested items (issue #187)
    and to drive the ``entity_registry_enabled_default`` decision (issue #189
    is satisfied because OpenTherm items sit at depth 1-3 and remain
    registered for users to enable explicitly).

    The traversal is bounded by an internal cycle guard and a hard cap of 20
    levels so that pathological data cannot hang setup.

    Args:
        menus: Flat mapping of ``{menu_type}_{item_id}`` to menu item payload.

    Returns:
        Mapping of the same keys to the integer depth of each item.

    """
    # Index items by (menuType, id) for O(1) parent lookup.
    by_key: dict[tuple[str, int], dict[str, Any]] = {
        (item["menuType"], item["id"]): item for item in menus.values()
    }
    depths: dict[str, int] = {}
    for menu_key, item in menus.items():
        depth = 0
        cur = item
        seen: set[tuple[str, int]] = set()
        while cur is not None and cur.get("parentId", 0) != 0:
            cur_key = (cur["menuType"], cur["id"])
            if cur_key in seen or depth >= 20:
                break
            seen.add(cur_key)
            depth += 1
            cur = by_key.get((cur["menuType"], cur["parentId"]))
        depths[menu_key] = depth
    return depths


def build_menu_group_names(
    menus: dict[str, dict[str, Any]],
    translations: Translations,
) -> dict[tuple[str, int], str]:
    """Build a mapping of ``(menu_type, group_id)`` to translated group name.

    Args:
        menus: Flat mapping of menu key to menu item payload (as returned by
            :meth:`Tech.get_module_menus`).
        translations: Subtitle catalog used to resolve group labels.

    Returns:
        Dictionary keyed by ``(menu_type, group_id)`` with the resolved group
        label as value.

    """
    groups: dict[tuple[str, int], str] = {}
    for item in menus.values():
        if item.get("type") != MENU_ITEM_TYPE_GROUP:
            continue
        txt_id = item.get("txtId", 0)
        name = translations.get_text(txt_id) if txt_id else ""
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
    # Sort subgroups by id for stable positional matching; ``sorted`` keeps
    # the shared list inside ``children_by_parent`` untouched.
    zone_subgroups = sorted(
        children_by_parent.get((mt, zones_group["id"]), []), key=lambda g: g["id"]
    )

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
        visited: set[int] = set()
        while queue:
            parent_id = queue.pop()
            if parent_id in visited:
                continue
            visited.add(parent_id)
            for child_key in all_children.get((mt, parent_id), []):
                assignments[child_key] = zone_id
                child_item = menus[child_key]
                if child_item.get("type") == MENU_ITEM_TYPE_GROUP:
                    queue.append(child_item["id"])

    _LOGGER.debug(
        "Assigned %d menu items to %d zones", len(assignments), len(subgroup_to_zone)
    )
    return assignments


def build_zone_names(
    zones: dict[int, dict[str, Any]],
    config_entry_title: str,
    include_hub_in_name: bool = False,
) -> dict[int, str]:
    """Map zone IDs to the display names used for zone-level devices.

    Zone devices are shared by the zone sensor/climate entities and the
    menu-based platforms (switch, select, button, number); the name is taken
    from the zone payload description, optionally prefixed with the hub
    (config entry) title when ``include_hub_in_name`` is set -- the same
    convention used by :class:`sensor.ZoneSensor` and
    :class:`climate.TechThermostat`.

    Args:
        zones: Mapping of zone ID to zone payload (as cached by the API client).
        config_entry_title: Title of the owning config entry (the hub name).
        include_hub_in_name: Whether to prefix the zone name with the hub title.

    Returns:
        Mapping of zone ID to device name. Zones without a usable name are
        omitted; callers fall back to the config entry title.

    """
    zone_names: dict[int, str] = {}
    for zone_id, zone in zones.items():
        description = zone.get(CONF_DESCRIPTION)
        name = description.get(CONF_NAME) if isinstance(description, dict) else None
        if not name:
            continue
        if include_hub_in_name:
            name = f"{config_entry_title} {name}"
        zone_names[zone_id] = name
    return zone_names


def resolve_zone_device_name(
    zone_names: dict[int, str] | None,
    zone_id: int | None,
    config_entry_title: str,
) -> str | None:
    """Return the device name for a menu entity attached to a zone device.

    Menu entities attached to a zone (``zone_id`` set) must set an explicit
    device name: since Home Assistant 2026.8 an unnamed device defaults to
    the config entry title, which would change the composed entity names.
    The name falls back to the config entry title when the zone has no
    usable name, and ``None`` for entities not attached to a zone.

    Args:
        zone_names: Mapping of zone ID to zone device name (see
            :func:`build_zone_names`); may be ``None``.
        zone_id: Zone ID the entity is attached to, or ``None``.
        config_entry_title: Title of the owning config entry (the hub name).

    Returns:
        The zone device name, the config entry title as a fallback, or
        ``None`` when the entity is not attached to a zone.

    """
    if zone_id is None:
        return None
    return (zone_names or {}).get(zone_id) or config_entry_title


def menu_entity_name(
    item: dict[str, Any],
    group_names: dict[tuple[str, int], str],
    translations: Translations,
    prefix: str = "",
) -> str:
    """Return a human-readable entity name for a menu item.

    When the item belongs to a non-root parent group the group label is
    prepended so that ambiguous names like *On* gain context.

    Args:
        item: Menu item payload from the API.
        group_names: Lookup returned by :func:`build_menu_group_names`.
        translations: Subtitle catalog used to resolve the item label.
        prefix: Optional hub name prefix.

    Returns:
        Formatted entity name string.

    """
    txt_id = item.get("txtId", 0)
    label = translations.get_text(txt_id) if txt_id else f"Menu {item['id']}"
    parent_id = item.get("parentId", 0)
    if parent_id != 0:
        parent_label = group_names.get((item["menuType"], parent_id), "")
        if parent_label:
            label = f"{parent_label} - {label}"
    return prefix + label
