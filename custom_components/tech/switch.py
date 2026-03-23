"""Platform for switch entities backed by Tech menu on/off parameters."""

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
    group_names = assets.build_menu_group_names(menus)

    entities: list[MenuSwitchEntity] = []
    for key, item in menus.items():
        if item.get("type") != MENU_ITEM_TYPE_ON_OFF:
            continue
        if not item.get("access", False):
            continue
        entities.append(
            MenuSwitchEntity(item, key, coordinator, config_entry, group_names)
        )

    async_add_entities(entities, True)


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
    ) -> None:
        """Initialise a menu switch entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MU_3550``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.
            group_names: Mapping of ``(menu_type, group_id)`` to group label.

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

        prefix = (config_entry.title + " ") if config_entry.data[INCLUDE_HUB_IN_NAME] else ""
        self._name = assets.menu_entity_name(item, group_names, prefix)

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
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` describing the controller."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._udid)},  # Unique identifiers for the device
            CONF_NAME: self._config_entry.title,  # Name of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }

    def _update_from_item(self, item: dict[str, Any]) -> None:
        """Refresh entity properties from a menu item payload.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        params = item.get("params", {})
        self._attr_is_on = params.get("value", 0) == 1

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": 1}
        )
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": 0}
        )
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        menus = self._coordinator.data.get("menus", {})
        item = menus.get(self._menu_key)
        if item:
            self._update_from_item(item)
        self.async_write_ha_state()
