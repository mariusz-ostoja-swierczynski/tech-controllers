"""Platform for number entities backed by Tech menu parameters."""

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
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
    MANUFACTURER,
    MENU_ITEM_TYPE_UNIVERSAL_VALUE,
    MENU_ITEM_TYPE_VALUE,
    UDID,
    VALUE_FORMAT_TENTH,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

_EDITABLE_TYPES = MENU_ITEM_TYPE_VALUE | {MENU_ITEM_TYPE_UNIVERSAL_VALUE}


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech number entities from menu parameters.

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
    group_names = assets.build_menu_group_names(menus)
    zone_assignments = assets.build_menu_zone_assignments(menus, zones)

    entities: list[MenuNumberEntity] = []
    for key, item in menus.items():
        item_type = item.get("type")
        if item_type not in _EDITABLE_TYPES:
            continue
        if not item.get("access", False):
            continue
        entities.append(
            MenuNumberEntity(
                item,
                key,
                coordinator,
                config_entry,
                group_names,
                zone_id=zone_assignments.get(key),
            )
        )

    async_add_entities(entities, True)


class MenuNumberEntity(CoordinatorEntity, NumberEntity):
    """A numeric menu parameter exposed as a Home Assistant number entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        item: dict[str, Any],
        menu_key: str,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        group_names: dict[tuple[str, int], str],
        zone_id: int | None = None,
    ) -> None:
        """Initialise a menu number entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MU_2089``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.
            group_names: Mapping of ``(menu_type, group_id)`` to group label.
            zone_id: Optional zone ID to associate this entity with a zone device.

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

        params = item.get("params", {})
        self._format = params.get("format", 1)

        self._attr_mode = NumberMode.BOX

        # ``_attr_has_entity_name = True`` lets HA prepend the device name; the
        # entity name itself is the menu label only.
        self._name = assets.menu_entity_name(item, group_names, "")

        self._disabled = item.get("parentId", 0) != 0

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
        self._format = params.get("format", 1)
        raw_value = params.get("value", 0)
        raw_min = params.get("min", 0)
        raw_max = params.get("max", 100)
        step = params.get("jump", 1)

        if self._format == VALUE_FORMAT_TENTH:
            self._attr_native_value = raw_value / 10.0
            self._attr_native_min_value = raw_min / 10.0
            self._attr_native_max_value = raw_max / 10.0
            self._attr_native_step = step / 10.0
        else:
            self._attr_native_value = float(raw_value)
            self._attr_native_min_value = float(raw_min)
            self._attr_native_max_value = float(raw_max)
            self._attr_native_step = float(step)

    async def async_set_native_value(self, value: float) -> None:
        """Set the menu parameter to the requested value."""
        if self._format == VALUE_FORMAT_TENTH:
            api_value = int(value * 10)
        else:
            api_value = int(value)

        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": api_value}
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
