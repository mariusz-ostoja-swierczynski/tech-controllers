"""Platform for switch entities backed by Tech menu parameters.

Two menu item types map onto switches:

* **ON_OFF** (type 10) -- one boolean parameter, one switch.
* **CHECKBOX** (type 15) -- several independent options held in a single
  bitmask, one switch per option so that toggling one of them leaves the
  others as the user set them.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_NAME,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    MENU_DEPTH_DEFAULT_ENABLED_LIMIT,
    MENU_DEPTH_REGISTRATION_LIMIT,
    MENU_ITEM_TYPE_CHECKBOX,
    MENU_ITEM_TYPE_ON_OFF,
    UDID,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech switch entities from menu on/off parameters.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller data.
        async_add_entities: Callback to register entities with Home Assistant.

    """
    controller = config_entry.data[CONTROLLER]
    coordinator: TechCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = controller[UDID]

    menus = await coordinator.api.get_module_menus(controller_udid)
    zones = await coordinator.api.get_module_zones(controller_udid)
    ctx = assets.build_menu_context(menus, zones, coordinator.translations)
    zone_names = assets.build_zone_names(
        zones,
        config_entry.title,
        config_entry.data.get(INCLUDE_HUB_IN_NAME, False),
    )

    entities = _build_menu_switches(menus, ctx, coordinator, config_entry, zone_names)

    async_add_entities(entities, True)


def _build_menu_switches(
    menus: dict[str, dict[str, Any]],
    ctx: assets.MenuContext,
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
    zone_names: dict[int, str],
) -> list[MenuSwitchEntity]:
    """Build the switch entities this controller's menu trees carry.

    An item only becomes an entity when it is accessible and sits no deeper than
    :data:`const.MENU_DEPTH_REGISTRATION_LIMIT` -- on L-12 there are 650 ON_OFF
    items, most of them deep under per-zone subgroups.

    Args:
        menus: Mapping of menu key (``MU_3550``) to menu item payload.
        ctx: Lookups shared by the menu platform setups.
        coordinator: Shared Tech data coordinator instance.
        config_entry: Config entry that owns the coordinator.
        zone_names: Mapping of zone ID to zone device name.

    Returns:
        One :class:`MenuSwitchEntity` per on/off item, and one
        :class:`MenuCheckboxEntity` per option of a checkbox item.

    """
    entities: list[MenuSwitchEntity] = []
    for key, item in menus.items():
        if not item.get("access", False):
            continue
        if ctx.depths[key] > MENU_DEPTH_REGISTRATION_LIMIT:
            continue
        item_type = item.get("type")
        if item_type == MENU_ITEM_TYPE_ON_OFF:
            entities.append(
                MenuSwitchEntity(
                    item,
                    key,
                    coordinator,
                    config_entry,
                    ctx.group_names,
                    depth=ctx.depths[key],
                    zone_id=ctx.zone_assignments.get(key),
                    zone_names=zone_names,
                )
            )
        elif item_type == MENU_ITEM_TYPE_CHECKBOX:
            # One switch per option, so each can be toggled on its own. The
            # options share the item's mask, so they get one holder for it.
            mask = _CheckboxMask(item.get("params", {}).get("value") or 0)
            for option_index in range(len(_checkbox_options(item))):
                entities.append(
                    MenuCheckboxEntity(
                        item,
                        key,
                        coordinator,
                        config_entry,
                        ctx.group_names,
                        option_index,
                        mask,
                        depth=ctx.depths[key],
                        zone_id=ctx.zone_assignments.get(key),
                        zone_names=zone_names,
                    )
                )
    return entities


def _checkbox_options(item: dict[str, Any]) -> list[int]:
    """Return the options a checkbox menu item carries.

    The payload lists them in bit order -- the option at index *i* is bit *i* of
    ``params.value``, which is how the eModul app renders and rewrites the group
    (``checked = (value & 1 << i) > 0``) -- and each entry is the subtitle id of
    the option label.
    """
    options = item.get("params", {}).get("options") or []
    return [option for option in options if isinstance(option, int)]


class MenuSwitchEntity(CoordinatorEntity, SwitchEntity):
    """An on/off menu parameter exposed as a Home Assistant switch entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        item: dict[str, Any],
        menu_key: str,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        group_names: dict[tuple[str, int], str],
        depth: int = 0,
        zone_id: int | None = None,
        zone_names: dict[int, str] | None = None,
    ) -> None:
        """Initialise a menu switch entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MU_3550``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.
            group_names: Mapping of ``(menu_type, group_id)`` to group label.
            depth: Nesting depth of this item in the Tech menu tree
                (0 = top-level). Drives ``entity_registry_enabled_default``.
            zone_id: Optional zone ID to associate this entity with a zone device.
            zone_names: Mapping of zone ID to zone device name, used to name
                the zone device when ``zone_id`` is set.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._menu_key = menu_key
        self._item_id = item["id"]
        self._menu_type = item["menuType"]
        self._unique_id = f"{self._udid}_menu_{menu_key}"
        self.manufacturer = MANUFACTURER
        self._zone_id = zone_id
        # Explicit zone device name -- without it the device registry falls back
        # to the config entry title and changes composed entity names; see
        # https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes
        # (core PR #179397).
        self._zone_name = assets.resolve_zone_device_name(
            zone_names, zone_id, config_entry.title
        )

        # ``_attr_has_entity_name = True`` lets HA prepend the device name from
        # ``device_info`` automatically -- the entity name is the menu label only.
        self._name = assets.menu_entity_name(
            item, group_names, coordinator.translations
        )

        self._disabled = depth > MENU_DEPTH_DEFAULT_ENABLED_LIMIT

        self._update_from_item(item)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the display name of this entity."""
        return self._name

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return whether the entity should be enabled by default."""
        return not self._disabled

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for the zone or controller this entity belongs to."""
        if self._zone_id is not None:
            return {
                ATTR_IDENTIFIERS: {(DOMAIN, f"{self._udid}_{self._zone_id}")},
                CONF_NAME: self._zone_name,
                ATTR_MANUFACTURER: self.manufacturer,
            }
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._udid)},
            CONF_NAME: self._config_entry.title,
            ATTR_MANUFACTURER: self.manufacturer,
        }

    def _update_from_item(self, item: dict[str, Any]) -> None:
        """Refresh entity properties from a menu item payload.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        params = item.get("params", {})
        self._attr_is_on = params.get("value", 0) == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on.

        Update local state optimistically after the API call returns success
        so HA reflects the change immediately. We deliberately do NOT request
        an immediate coordinator refresh here -- the eModul API has a
        ``duringChange: "t"`` window during which it still reports the old
        value, so an immediate refresh would clobber the optimistic state.
        The regular 60 s polling cadence reconciles eventually; if the
        controller rejected the change the entity will revert by then.
        """
        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": 1}
        )
        self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off.

        See :meth:`async_turn_on` for the optimistic-update rationale.
        """
        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": 0}
        )
        self._attr_is_on = False
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        menus = self._coordinator.data.get("menus", {})
        item = menus.get(self._menu_key)
        if item and not assets.menu_item_is_settling(item):
            self._update_from_item(item)
        elif item:
            _LOGGER.debug(
                "Menu item %s is duringChange; keeping the optimistic state",
                self._menu_key,
            )
        self.async_write_ha_state()


class _CheckboxMask:
    """The bitmask of one checkbox menu item, shared by its option switches.

    The options of a type 15 item live in a single value, so the switches built
    from that item share this holder: a write updates it at once, which keeps a
    sibling option correct in the window before the next coordinator refresh
    replaces the menu payload.
    """

    def __init__(self, value: int = 0) -> None:
        """Store the last known mask.

        Args:
            value: The item's ``params.value`` bitmask.

        """
        self.value = value


class MenuCheckboxEntity(MenuSwitchEntity):
    """One option of a checkbox menu parameter (menu item type 15).

    These items hold several independent options in a single bitmask
    (``params.value``): the option at index *i* is bit *i*, which is how the
    eModul app ties the group's checkboxes to the value. Each option therefore
    becomes its own switch, and turning one on or off rewrites the whole option
    table -- the shape the app sends for these items,
    ``{"many_of_many": [{"id": index, "value": 0 | 1}, ...]}`` -- with the other
    options left exactly as the controller last reported them.
    """

    def __init__(
        self,
        item: dict[str, Any],
        menu_key: str,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        group_names: dict[tuple[str, int], str],
        option_index: int,
        mask: _CheckboxMask | None = None,
        depth: int = 0,
        zone_id: int | None = None,
        zone_names: dict[int, str] | None = None,
    ) -> None:
        """Initialise one option of a checkbox menu item.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MU_3550``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.
            group_names: Mapping of ``(menu_type, group_id)`` to group label.
            option_index: Position of this option in ``params.options``, which
                is also its bit in ``params.value``.
            mask: Holder shared with the item's other option switches; a private
                one is created when an option switch stands on its own.
            depth: Nesting depth of this item in the Tech menu tree.
            zone_id: Optional zone ID to associate this entity with a zone device.
            zone_names: Mapping of zone ID to zone device name.

        """
        # The base initialiser reads the mask this option selects a bit from, so
        # the index and the holder have to be in place before it runs.
        self._option_index = option_index
        self._mask = mask if mask is not None else _CheckboxMask()
        super().__init__(
            item,
            menu_key,
            coordinator,
            config_entry,
            group_names,
            depth=depth,
            zone_id=zone_id,
            zone_names=zone_names,
        )

        self._options = _checkbox_options(item)
        option_txt_id = self._options[option_index]
        # The option label names this switch and identifies it: the group's own
        # label belongs to the item, which several switches now share.
        self._name = coordinator.translations.get_text(option_txt_id)
        self._unique_id = f"{self._udid}_menu_{menu_key}_option_{option_txt_id}"

    def _update_from_item(self, item: dict[str, Any]) -> None:
        """Refresh this option's state from the item's bitmask.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        self._mask.value = item.get("params", {}).get("value") or 0
        self._attr_is_on = self._is_set(self._option_index)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn this option on, leaving the other options untouched."""
        await self._write_option(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn this option off, leaving the other options untouched."""
        await self._write_option(False)

    async def _write_option(self, enabled: bool) -> None:
        """Send the option table with only this option's state changed.

        The whole table goes out rather than a mask, because that is what the
        eModul app sends for a checkbox item and it cannot drop an option the
        controller knows about. See :meth:`MenuSwitchEntity.async_turn_on` for
        why the result is applied locally without asking for a refresh.

        Args:
            enabled: State this option should end up in.

        """
        table = []
        for index in range(len(self._options)):
            is_on = enabled if index == self._option_index else self._is_set(index)
            table.append({"id": index, "value": 1 if is_on else 0})
        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"many_of_many": table}
        )

        bit = 1 << self._option_index
        self._mask.value = self._mask.value | bit if enabled else self._mask.value & ~bit
        self._attr_is_on = enabled
        self.async_write_ha_state()

    def _is_set(self, index: int) -> bool:
        """Return whether an option of this item is currently set.

        Args:
            index: Position of the option in ``params.options``.

        Returns:
            ``True`` when that option's bit is set in the last known mask.

        """
        return bool(self._mask.value & (1 << index))
