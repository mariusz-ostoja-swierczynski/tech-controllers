"""Platform for time-of-day entities backed by Tech menu parameters."""

from datetime import time
import logging
from typing import Any

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_NAME,
    EntityCategory,
    Platform,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
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
    MENU_ITEM_TYPE_UNIVERSAL_VALUE,
    MENU_ITEM_TYPE_VALUE,
    MINUTES_IN_A_DAY,
    UDID,
    VALUE_FORMAT_TIME_OF_DAY,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

_EDITABLE_TYPES = MENU_ITEM_TYPE_VALUE | {MENU_ITEM_TYPE_UNIVERSAL_VALUE}


def _is_time_of_day(item: dict[str, Any]) -> bool:
    """Return whether a menu item is a time of day.

    Value type 13 is a time the controller writes as hours * 60 + min, so it
    belongs to :class:`MenuTimeEntity` and not to
    :class:`number.MenuNumberEntity`, which could only show the packed minutes
    (#224).

    Args:
        item: Menu item payload returned by the Tech API.

    Returns:
        ``True`` when the item is a time of day this platform should expose.

    """
    if item.get("type") not in _EDITABLE_TYPES:
        return False
    return item.get("params", {}).get("format") == VALUE_FORMAT_TIME_OF_DAY


def menu_time_of_day(item: dict[str, Any]) -> time | None:
    """Return the time of day a menu item holds, or ``None``.

    The API documents value type 13 as "Time written as hours * 60 + min, shown
    as 00:00 - 23:59", so the value counts minutes since midnight. The same type
    is also what the controller's run-time counters use, where that count is a
    duration and runs past a day; a count that does not land inside a day is not
    a time of day, so it reads as unknown rather than being wrapped into a wrong
    one.

    Args:
        item: Menu item payload returned by the Tech API.

    Returns:
        The time the item holds, or ``None`` when it does not hold one.

    """
    value = item.get("params", {}).get("value")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    if not 0 <= value < MINUTES_IN_A_DAY:
        return None
    return time(hour=value // 60, minute=value % 60)


def _forget_number_entity(hass: HomeAssistant, controller_udid: str, key: str) -> None:
    """Drop the number entity a time item used to be exposed as.

    Value type 13 items were numbers until this platform took them over, and an
    entity of each is keyed by the same unique id, so the old one would otherwise
    stay in the registry as an unavailable duplicate of the new one. Only the
    items this platform claims are touched.

    Args:
        hass: Home Assistant instance.
        controller_udid: Tech module identifier, part of the unique id.
        key: Menu item key, e.g. ``MI_1234``.

    """
    registry = er.async_get(hass)
    stale = registry.async_get_entity_id(
        Platform.NUMBER, DOMAIN, f"{controller_udid}_menu_{key}"
    )
    if stale is not None:
        _LOGGER.debug("Removing %s, which is a time entity now", stale)
        registry.async_remove(stale)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech time entities from menu parameters.

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

    entities: list[MenuTimeEntity] = []
    for key, item in menus.items():
        if not _is_time_of_day(item):
            continue
        if not item.get("access", False):
            continue
        if ctx.depths[key] > MENU_DEPTH_REGISTRATION_LIMIT:
            continue
        _forget_number_entity(hass, controller_udid, key)
        entities.append(
            MenuTimeEntity(
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

    async_add_entities(entities, True)


class MenuTimeEntity(CoordinatorEntity, TimeEntity):
    """A time-of-day menu parameter exposed as a Home Assistant time entity."""

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
        """Initialise a menu time entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MI_1234``).
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

        # ``_attr_has_entity_name = True`` lets HA prepend the device name; the
        # entity name itself is the menu label only.
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
        """Refresh the time from a menu item payload.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        self._attr_native_value = menu_time_of_day(item)

    async def async_set_value(self, value: time) -> None:
        """Set the menu parameter to the requested time of day.

        The controller stores the time as minutes since midnight, which is what
        the API documents for value type 13 and what it reports back, so the
        write sends exactly that. Local state is updated optimistically after the
        API call returns success, and no immediate coordinator refresh is asked
        for: the eModul API has a ``duringChange: "t"`` window during which it
        still reports the old value, so an immediate refresh would clobber the
        optimistic state. The regular polling cadence reconciles eventually, and
        if the controller rejected the change the entity reverts by then.

        Args:
            value: The time of day to set.

        """
        await self.coordinator.api.set_menu_value(
            self._udid,
            self._menu_type,
            self._item_id,
            {"value": value.hour * 60 + value.minute},
        )
        self._attr_native_value = value
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        menus = self._coordinator.data.get("menus", {})
        item = menus.get(self._menu_key)
        if item:
            self._update_from_item(item)
        self.async_write_ha_state()
