"""Platform for recuperator fan speed select entity (MU 2070)."""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
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

from .const import (
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
    UDID,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech recuperator fan speed select entity.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller data.
        async_add_entities: Callback to register entities with Home Assistant.

    """
    controller = config_entry.data[CONTROLLER]
    coordinator: TechCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = controller[UDID]

    menus = await coordinator.api.get_module_menus(controller_udid)

    key = "MU_2070"
    item = menus.get(key)
    if item is None:
        _LOGGER.warning(
            "Menu item %s not found — fan speed control unavailable", key
        )
        return

    async_add_entities(
        [MenuFanSpeedSelectEntity(item, key, coordinator, config_entry)], True
    )


class MenuFanSpeedSelectEntity(CoordinatorEntity, SelectEntity):
    """Fan speed selector for Karino recuperation units (MU 2070)."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:fan"

    def __init__(
        self,
        item: dict[str, Any],
        menu_key: str,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialise the recuperator fan speed select entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (``MU_2070``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._menu_key = "MU_2070"
        self._item_id = 2070
        self._menu_type = "MU"
        self._unique_id = f"{self._udid}_menu_MU_2070"
        self.manufacturer = MANUFACTURER

        self._name = coordinator.translations.get_text(459) or "Fan speed"

        self._value_to_label: dict[int, str] = {}
        self._label_to_value: dict[str, int] = {}
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
        """Return device info for the controller this entity belongs to."""
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._udid)},
            CONF_NAME: self._config_entry.title,
            ATTR_MANUFACTURER: self.manufacturer,
        }

    def _build_option_maps(self, options: list[dict[str, Any]]) -> None:
        """Build label/value mappings from the API options list.

        Args:
            options: List of option dictionaries containing ``value`` and ``txtId``.

        """
        self._value_to_label = {}
        self._label_to_value = {}
        ha_options: list[str] = []

        for opt in options:
            if isinstance(opt, dict):
                val = opt.get("value", 0)
                txt_id = opt.get("txtId", 0)
            else:
                continue
            label = (
                self.coordinator.translations.get_text(txt_id) if txt_id else str(val)
            )
            # Ensure unique labels
            if label in self._label_to_value:
                label = f"{label} ({val})"
            self._value_to_label[val] = label
            self._label_to_value[label] = val
            ha_options.append(label)

        self._attr_options = ha_options

    def _update_from_item(self, item: dict[str, Any]) -> None:
        """Refresh entity properties from a menu item payload.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        params = item.get("params", {})
        options = params.get("options", [])
        self._build_option_maps(options)

        current_value = params.get("value", 0)
        current_label = self._value_to_label.get(current_value)
        if current_label and current_label in self._attr_options:
            self._attr_current_option = current_label
        elif self._attr_options:
            self._attr_current_option = self._attr_options[0]
        else:
            self._attr_current_option = None

    async def async_select_option(self, option: str) -> None:
        """Change the selected option.

        Update local state optimistically after the API call returns success
        so HA reflects the change immediately. We deliberately do NOT request
        an immediate coordinator refresh here -- the eModul API has a
        ``duringChange: "t"`` window during which it still reports the old
        value, so an immediate refresh would clobber the optimistic state.
        The regular 60 s polling cadence reconciles eventually; if the
        controller rejected the change the entity will revert by then.
        """
        value = self._label_to_value.get(option)
        if value is None:
            _LOGGER.warning("Unknown option %s for menu item %s", option, self._item_id)
            return

        await self.coordinator.api.set_menu_value(
            self._udid, self._menu_type, self._item_id, {"value": value}
        )
        self._attr_current_option = option
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        menus = self._coordinator.data.get("menus", {})
        item = menus.get(self._menu_key)
        if item:
            self._update_from_item(item)
        self.async_write_ha_state()
