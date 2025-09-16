"""Support for Tech HVAC select controls."""

import logging
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.core import callback

from . import assets
from .const import (
    CONTROLLER,
    DOMAIN,
    FAN_MODE_IDO_ID,
    FAN_MODE_OPTIONS,
    FAN_MODE_OPTIONS_REVERSE,
    GEAR_CONTROL_IDO_ID,
    GEAR_OPTIONS,
    GEAR_OPTIONS_REVERSE,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    RECUPERATION_EXHAUST_FLOW,
    RECUPERATION_SUPPLY_FLOW,
    RECUPERATION_SUPPLY_FLOW_ALT,
    TYPE_TEMPERATURE_CH,
    UDID,
    VER,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    _LOGGER.debug(
        "Setting up select entry, controller udid: %s",
        config_entry.data[CONTROLLER][UDID],
    )
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = config_entry.data[CONTROLLER][UDID]

    tiles = await coordinator.api.get_module_tiles(controller_udid)

    entities = []

    # Check if we have recuperation system (detected by flow sensors)
    has_recuperation_flow = False
    for t in tiles:
        tile = tiles[t]
        if tile.get("type") == TYPE_TEMPERATURE_CH:
            widget1_txt_id = tile.get("params", {}).get("widget1", {}).get("txtId", 0)
            widget2_txt_id = tile.get("params", {}).get("widget2", {}).get("txtId", 0)
            for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                    has_recuperation_flow = True
                    break
        if has_recuperation_flow:
            break

    # Create select controls if we have recuperation
    if has_recuperation_flow:
        _LOGGER.debug("Creating recuperation select controls")
        entities.append(RecuperationGearSelect(coordinator, config_entry))  # Direct gear control
        entities.append(RecuperationModeSelect(coordinator, config_entry))  # Timed fan mode
    else:
        _LOGGER.debug("No recuperation flow detected, skipping select controls")

    async_add_entities(entities, True)


class RecuperationModeSelect(CoordinatorEntity, SelectEntity):
    """Representation of recuperation fan mode select control (timed mode changes)."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:fan-speed"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the fan mode select."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_recuperation_fan_mode"

        # Define options with Polish names
        self._attr_options = [
            "Zatrzymaj wentylator",
            "1 bieg",
            "2 bieg",
            "3 bieg"
        ]

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Fan Mode (Timed)"

    @property
    def name(self) -> str:
        """Return the name of the select."""
        return self._name

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        # For now, always return default - the actual state tracking
        # would need more complex implementation with HA storage
        return "Zatrzymaj wentylator"

    async def async_select_option(self, option: str) -> None:
        """Select the fan mode option."""
        _LOGGER.debug("Selecting fan mode option: %s", option)

        # Map option name to value
        option_value_map = {
            "Zatrzymaj wentylator": 0,
            "1 bieg": 1,
            "2 bieg": 2,
            "3 bieg": 3
        }

        mode_value = option_value_map.get(option)
        if mode_value is None:
            _LOGGER.error("Unknown fan mode option: %s", option)
            return

        await self._coordinator.api.set_fan_mode(self._udid, mode_value)
        await self._coordinator.async_request_refresh()

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_recuperation")
            },  # Unique identifiers for the device
            CONF_NAME: f"{self._config_entry.title} Recuperation",  # Name of the device
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),  # Model of the device
            ATTR_MANUFACTURER: MANUFACTURER,  # Manufacturer of the device
        }


class RecuperationGearSelect(CoordinatorEntity, SelectEntity):
    """Representation of direct recuperation gear control."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:speedometer"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the gear select."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_recuperation_gear"
        self._attr_options = ["Zatrzymaj", "1 bieg", "2 bieg", "3 bieg"]

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Recuperation Gear"

        # Initialize with default, will be updated by coordinator data
        self._last_selected_gear = "Zatrzymaj"

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        # Update current gear from tiles data when coordinator updates
        if self._coordinator.data and "tiles" in self._coordinator.data:
            for tile_data in self._coordinator.data["tiles"].values():
                if tile_data.get("type") in [22, 122]:  # TYPE_FAN or TYPE_RECUPERATION
                    current_gear = tile_data.get("params", {}).get("gear", 0)
                    gear_mapping = {
                        0: "Zatrzymaj",
                        1: "1 bieg",
                        2: "2 bieg",
                        3: "3 bieg"
                    }
                    new_gear = gear_mapping.get(current_gear, "Zatrzymaj")
                    if new_gear != self._last_selected_gear:
                        self._last_selected_gear = new_gear
                        _LOGGER.debug("Updated gear from coordinator: %s", new_gear)
                    break

        super()._handle_coordinator_update()

    @property
    def name(self) -> str:
        """Return the name of the select."""
        return self._name

    @property
    def current_option(self) -> str | None:
        """Return the current selected gear."""
        # First try to get from tiles data (faster)
        if self._coordinator.data and "tiles" in self._coordinator.data:
            for tile_id, tile_data in self._coordinator.data["tiles"].items():
                # Look for recuperation fan tile or similar
                if tile_data.get("type") in [22, 122]:  # TYPE_FAN or TYPE_RECUPERATION
                    current_gear = tile_data.get("params", {}).get("gear", 0)
                    gear_mapping = {
                        0: "Zatrzymaj",
                        1: "1 bieg",
                        2: "2 bieg",
                        3: "3 bieg"
                    }
                    return gear_mapping.get(current_gear, "Zatrzymaj")

        # Fallback: check stored state from last API call
        return getattr(self, '_last_selected_gear', "Zatrzymaj")

    async def async_select_option(self, option: str) -> None:
        """Change the selected gear."""
        gear_mapping = {
            "Zatrzymaj": 0,
            "1 bieg": 1,
            "2 bieg": 2,
            "3 bieg": 3,
        }

        gear_value = gear_mapping.get(option, 0)
        _LOGGER.debug("Setting recuperation gear to: %s (value: %d)", option, gear_value)

        try:
            # Use the direct gear control API
            await self._coordinator.api.set_gear_direct(self._udid, gear_value)

            # Store the selected option for immediate display
            self._last_selected_gear = option

            # Refresh coordinator data
            await self._coordinator.async_request_refresh()

            _LOGGER.info("Successfully set recuperation gear to: %s", option)

        except Exception as err:
            _LOGGER.error("Failed to set recuperation gear to %s: %s", option, err)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_recuperation")
            },
            CONF_NAME: f"{self._config_entry.title} Recuperation",
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),
            ATTR_MANUFACTURER: MANUFACTURER,
        }