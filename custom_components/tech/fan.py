"""Support for Tech HVAC fans."""

import logging
from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_DESCRIPTION,
    CONF_MODEL,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    int_states_in_range,
    percentage_to_ranged_value,
    ranged_value_to_percentage,
)

from . import assets
from .const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    TYPE_FAN,
    TYPE_RECUPERATION,
    TYPE_TEMPERATURE_CH,
    UDID,
    VER,
)
from .coordinator import TechCoordinator
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)

SPEED_RANGE = (1, 3)  # Recuperation typically has 3 speeds


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    _LOGGER.debug(
        "Setting up fan entry, controller udid: %s",
        config_entry.data[CONTROLLER][UDID],
    )
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = config_entry.data[CONTROLLER][UDID]

    tiles = await coordinator.api.get_module_tiles(controller_udid)

    entities = []
    for t in tiles:
        tile = tiles[t]
        if not tile.get("visibility", False):
            continue

        # Check if this is a fan tile that could be a recuperation unit
        if tile[CONF_TYPE] == TYPE_FAN:
            # Check if it has recuperation-like characteristics
            description = tile[CONF_PARAMS].get(CONF_DESCRIPTION, "").lower()
            if any(keyword in description for keyword in ["recuperation", "rekuperacja", "ventilation", "wentylacja"]):
                entities.append(TileRecuperationFanEntity(tile, coordinator, config_entry))
            else:
                entities.append(TileFanEntity(tile, coordinator, config_entry))
        elif tile[CONF_TYPE] == TYPE_RECUPERATION:
            entities.append(TileRecuperationFanEntity(tile, coordinator, config_entry))

    # Check if we found any recuperation flow sensors and create a virtual fan control
    has_recuperation_flow = False
    for t in tiles:
        tile = tiles[t]
        if tile[CONF_TYPE] == TYPE_TEMPERATURE_CH:
            widget1_txt_id = tile[CONF_PARAMS].get("widget1", {}).get("txtId", 0)
            widget2_txt_id = tile[CONF_PARAMS].get("widget2", {}).get("txtId", 0)
            from .const import RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT
            for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                    has_recuperation_flow = True
                    break
            if has_recuperation_flow:
                break

    # Create recuperation fan control if we detected flow sensors
    if has_recuperation_flow:
        # Create a virtual tile for recuperation control
        virtual_tile = {
            "id": 9999,  # Virtual ID
            "type": TYPE_RECUPERATION,
            "params": {"description": "Recuperation Control"}
        }
        entities.append(VirtualRecuperationFanEntity(virtual_tile, coordinator, config_entry))

    async_add_entities(entities, True)


class TileFanEntity(TileEntity, CoordinatorEntity, FanEntity):
    """Representation of a Tech Fan."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    _attr_preset_modes = ["Stop", "Speed 1", "Speed 2", "Speed 3", "Party Mode"]

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the fan."""
        TileEntity.__init__(self, device, coordinator, config_entry)
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fan"

    @property
    def name(self) -> str:
        """Return the name of the fan."""
        return self._name

    @property
    def is_on(self) -> bool:
        """Return true if the fan is on."""
        if self._coordinator.data and "tiles" in self._coordinator.data:
            tile_data = self._coordinator.data["tiles"].get(self._id)
            if tile_data:
                gear = tile_data[CONF_PARAMS].get("gear", 0)
                return gear > 0
        return False

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage."""
        if self._coordinator.data and "tiles" in self._coordinator.data:
            tile_data = self._coordinator.data["tiles"].get(self._id)
            if tile_data:
                gear = tile_data[CONF_PARAMS].get("gear", 0)
                if gear == 0:
                    return 0
                return ranged_value_to_percentage(SPEED_RANGE, gear)
        return 0

    @property
    def speed_count(self) -> int:
        """Return the number of speeds the fan supports."""
        return int_states_in_range(SPEED_RANGE)

    async def async_set_percentage(self, percentage: int) -> None:
        """Set the speed percentage of the fan."""
        if percentage == 0:
            await self.async_turn_off()
        else:
            speed_level = percentage_to_ranged_value(SPEED_RANGE, percentage)
            # For now, use None for configured_values (will use defaults)
            await self._coordinator.api.set_recuperation_speed(self._udid, speed_level, None)
            await self._coordinator.async_request_refresh()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on the fan."""
        if percentage is None:
            percentage = 33  # Default to speed 1 (33%)
        await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the fan."""
        await self._coordinator.api.set_recuperation_speed(self._udid, 0, None)
        await self._coordinator.async_request_refresh()

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        # Check if party mode is active
        if self._is_party_mode_active():
            return "Party Mode"

        if not self.is_on:
            return "Stop"

        percentage = self.percentage
        if percentage == 0:
            return "Stop"
        elif percentage <= 33:
            return "Speed 1"
        elif percentage <= 66:
            return "Speed 2"
        else:
            return "Speed 3"

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        _LOGGER.debug("Setting fan preset mode to %s", preset_mode)

        if preset_mode == "Party Mode":
            # Activate party mode with configured duration
            party_duration = self._get_party_mode_duration()
            await self._coordinator.api.set_party_mode(self._udid, party_duration)
            await self._coordinator.async_request_refresh()
            return

        preset_to_mode = {
            "Stop": 0,
            "Speed 1": 1,
            "Speed 2": 2,
            "Speed 3": 3
        }

        mode_value = preset_to_mode.get(preset_mode, 0)

        if mode_value == 0:
            await self.async_turn_off()
        else:
            # Use configured speed values
            configured_values = self._get_configured_speed_values()
            await self._coordinator.api.set_recuperation_speed(self._udid, mode_value, configured_values)
            await self._coordinator.async_request_refresh()

    def _get_configured_speed_values(self) -> dict:
        """Get configured speed values from number entities or use defaults."""
        from .const import DEFAULT_SPEED_VALUES

        configured_values = DEFAULT_SPEED_VALUES.copy()

        # Try to get current values from number entities via Home Assistant
        if hasattr(self._coordinator, 'hass'):
            hass = self._coordinator.hass
            for speed_level in [1, 2, 3]:
                entity_id = f"number.{self._udid}_recuperation_speed_{speed_level}_config"
                state = hass.states.get(entity_id)
                if state and state.state not in ["unavailable", "unknown"]:
                    try:
                        configured_values[speed_level] = int(float(state.state))
                        _LOGGER.debug("Got configured speed %s: %s m³/h", speed_level, configured_values[speed_level])
                    except (ValueError, TypeError):
                        _LOGGER.debug("Could not parse speed %s value: %s", speed_level, state.state)

        return configured_values

    def _is_party_mode_active(self) -> bool:
        """Check if party mode is currently active."""
        # This would need to be implemented based on how party mode state is tracked
        # For now, we can't easily detect if party mode is active without additional API calls
        # Could be enhanced by checking a stored party mode end time
        return False

    def _get_party_mode_duration(self) -> int:
        """Get configured party mode duration from number entity or use default."""
        from .const import PARTY_MODE_MIN_MINUTES

        default_duration = 60  # Default 1 hour

        # Try to get current value from party mode number entity
        if hasattr(self._coordinator, 'hass'):
            hass = self._coordinator.hass
            entity_id = f"number.{self._udid}_recuperation_party_mode"
            state = hass.states.get(entity_id)
            if state and state.state not in ["unavailable", "unknown"]:
                try:
                    duration = int(float(state.state))
                    _LOGGER.debug("Got configured party mode duration: %s minutes", duration)
                    return duration
                except (ValueError, TypeError):
                    _LOGGER.debug("Could not parse party mode duration: %s", state.state)

        return default_duration

    def update_properties(self, device):
        """Update the properties of the device."""
        self._state = self.is_on

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._name,  # Name of the device
            CONF_MODEL: self._config_entry.data[CONTROLLER][CONF_NAME] + ": " + self._config_entry.data[CONTROLLER][VER],  # Model of the device
            ATTR_MANUFACTURER: MANUFACTURER,  # Manufacturer of the device
        }


class TileRecuperationFanEntity(TileFanEntity):
    """Representation of a Tech Recuperation Unit."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    _attr_preset_modes = ["Stop", "Speed 1", "Speed 2", "Speed 3", "Party Mode"]

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the recuperation unit."""
        super().__init__(device, coordinator, config_entry)
        self._attr_icon = "mdi:air-filter"

        # Update name to indicate it's a recuperation unit
        base_name = assets.get_text_by_type(device[CONF_TYPE])
        if "recuperation" not in base_name.lower() and "rekuperacja" not in base_name.lower():
            base_name = f"Recuperation {base_name}"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + base_name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_recuperation"


class VirtualRecuperationFanEntity(TileFanEntity):
    """Virtual recuperation fan entity for systems without direct fan tiles."""

    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.PRESET_MODE
    _attr_preset_modes = ["Stop", "Speed 1", "Speed 2", "Speed 3", "Party Mode"]

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the virtual recuperation fan."""
        super().__init__(device, coordinator, config_entry)
        self._attr_icon = "mdi:air-filter"
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Recuperation"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._udid}_virtual_recuperation"

    @property
    def is_on(self) -> bool:
        """Return true if the recuperation is on."""
        # Check flow values to determine if recuperation is running
        if self._coordinator.data and "tiles" in self._coordinator.data:
            from .const import RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT

            for tile_id, tile_data in self._coordinator.data["tiles"].items():
                if tile_data.get("type") == TYPE_TEMPERATURE_CH:
                    widget1_txt_id = tile_data.get("params", {}).get("widget1", {}).get("txtId", 0)
                    widget2_txt_id = tile_data.get("params", {}).get("widget2", {}).get("txtId", 0)

                    # Check for flow values
                    for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                        if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                            widget_key = flow_sensor["widget"]
                            flow_value = tile_data.get("params", {}).get(widget_key, {}).get("value", 0)
                            if flow_value > 0:
                                return True
        return False

    @property
    def percentage(self) -> int | None:
        """Return the current speed percentage based on flow values."""
        if not self.is_on:
            return 0

        # Try to determine speed based on flow values
        if self._coordinator.data and "tiles" in self._coordinator.data:
            from .const import RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT, RECUPERATION_SPEED_ENDPOINTS

            for tile_id, tile_data in self._coordinator.data["tiles"].items():
                if tile_data.get("type") == TYPE_TEMPERATURE_CH:
                    widget1_txt_id = tile_data.get("params", {}).get("widget1", {}).get("txtId", 0)
                    widget2_txt_id = tile_data.get("params", {}).get("widget2", {}).get("txtId", 0)

                    for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                        if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                            widget_key = flow_sensor["widget"]
                            flow_value = tile_data.get("params", {}).get(widget_key, {}).get("value", 0)

                            # Map flow values to speed levels based on defaults
                            # Use more flexible ranges since users can configure speeds
                            if flow_value >= 300:  # High speed range
                                return ranged_value_to_percentage(SPEED_RANGE, 3)  # High
                            elif flow_value >= 200:  # Medium speed range
                                return ranged_value_to_percentage(SPEED_RANGE, 2)  # Medium
                            elif flow_value >= 50:   # Low speed range
                                return ranged_value_to_percentage(SPEED_RANGE, 1)  # Low

        return 33  # Default to low speed if we can't determine

    @property
    def preset_mode(self) -> str | None:
        """Return the current preset mode."""
        # Check if party mode is active
        if self._is_party_mode_active():
            return "Party Mode"

        # Determine current mode based on flow values or stored state
        if not self.is_on:
            return "Stop"

        percentage = self.percentage
        if percentage == 0:
            return "Stop"
        elif percentage <= 33:
            return "Speed 1"
        elif percentage <= 66:
            return "Speed 2"
        else:
            return "Speed 3"

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set the preset mode."""
        _LOGGER.debug("Setting recuperation preset mode to %s", preset_mode)

        if preset_mode == "Party Mode":
            # Activate party mode with configured duration
            party_duration = self._get_party_mode_duration()
            await self._coordinator.api.set_party_mode(self._udid, party_duration)
            await self._coordinator.async_request_refresh()
            return

        preset_to_mode = {
            "Stop": 0,
            "Speed 1": 1,
            "Speed 2": 2,
            "Speed 3": 3
        }

        mode_value = preset_to_mode.get(preset_mode, 0)

        if mode_value == 0:
            # Stop the fan
            await self._coordinator.api.set_fan_mode(self._udid, 0)
        else:
            # Use configured speed values from number entities
            configured_values = self._get_configured_speed_values()
            await self._coordinator.api.set_recuperation_speed(self._udid, mode_value, configured_values)

        await self._coordinator.async_request_refresh()

    def _get_configured_speed_values(self) -> dict:
        """Get configured speed values from number entities or use defaults."""
        from .const import DEFAULT_SPEED_VALUES

        configured_values = DEFAULT_SPEED_VALUES.copy()

        # Try to get current values from number entities via Home Assistant
        if hasattr(self._coordinator, 'hass'):
            hass = self._coordinator.hass
            for speed_level in [1, 2, 3]:
                entity_id = f"number.{self._udid}_recuperation_speed_{speed_level}_config"
                state = hass.states.get(entity_id)
                if state and state.state not in ["unavailable", "unknown"]:
                    try:
                        configured_values[speed_level] = int(float(state.state))
                        _LOGGER.debug("Got configured speed %s: %s m³/h", speed_level, configured_values[speed_level])
                    except (ValueError, TypeError):
                        _LOGGER.debug("Could not parse speed %s value: %s", speed_level, state.state)

        return configured_values