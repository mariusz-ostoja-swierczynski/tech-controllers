"""Support for Tech HVAC number controls."""

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    CONTROLLER,
    DEFAULT_SPEED_VALUES,
    DOMAIN,
    FILTER_ALARM_IDO_ID,
    FILTER_ALARM_MAX_DAYS,
    FILTER_ALARM_MIN_DAYS,
    HUMIDITY_SENSOR_TXT_IDS,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    PARTY_MODE_IDO_ID,
    PARTY_MODE_MAX_MINUTES,
    PARTY_MODE_MIN_MINUTES,
    RECUPERATION_EXHAUST_FLOW,
    RECUPERATION_SUPPLY_FLOW,
    RECUPERATION_SUPPLY_FLOW_ALT,
    SPEED_CONFIG_KEYS,
    SPEED_RANGES,
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
        "Setting up number entry, controller udid: %s",
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

    # Create controls if we have recuperation
    if has_recuperation_flow:
        _LOGGER.debug("Creating recuperation number controls - party mode and speed configs")
        # Add party mode control
        entities.append(RecuperationPartyModeNumber(coordinator, config_entry))

        # Add speed configuration controls
        for speed_level in [1, 2, 3]:
            entities.append(RecuperationSpeedConfigNumber(coordinator, config_entry, speed_level))

        # Add filter alarm control for recuperation systems
        entities.append(FilterAlarmNumber(coordinator, config_entry))

        # Add ventilation parameters
        entities.append(VentilationRoomParameterNumber(coordinator, config_entry))
        entities.append(VentilationBathroomParameterNumber(coordinator, config_entry))
        entities.append(Co2ThresholdNumber(coordinator, config_entry))
        entities.append(HysteresisNumber(coordinator, config_entry))
    else:
        _LOGGER.debug("No recuperation flow detected, skipping number controls")

    async_add_entities(entities, True)


class RecuperationPartyModeNumber(CoordinatorEntity, NumberEntity):
    """Representation of recuperation party mode number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_native_min_value = PARTY_MODE_MIN_MINUTES
    _attr_native_max_value = PARTY_MODE_MAX_MINUTES  # Full recuperator range 15-720 minutes
    _attr_native_step = 15  # 15-minute increments for easier selection
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:party-popper"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the party mode number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_recuperation_party_mode"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Party Mode Duration"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        # For party mode, always return the minimum as default
        # The actual value would need to be tracked separately in HA storage
        return float(PARTY_MODE_MIN_MINUTES)

    async def async_set_native_value(self, value: float) -> None:
        """Set the party mode duration."""
        duration_minutes = int(value)
        _LOGGER.debug("Setting party mode to %s minutes", duration_minutes)

        await self._coordinator.api.set_party_mode(self._udid, duration_minutes)
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


class RecuperationSpeedConfigNumber(CoordinatorEntity, NumberEntity):
    """Representation of recuperation speed flow configuration."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m³/h"
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:speedometer"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        speed_level: int,
    ) -> None:
        """Initialize the speed config number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._speed_level = speed_level
        self._attr_unique_id = f"{self._udid}_recuperation_speed_{speed_level}_config"

        # Set min/max values based on speed level
        speed_range = SPEED_RANGES.get(speed_level, {"min": 50, "max": 500, "step": 10})
        self._attr_native_min_value = speed_range["min"]
        self._attr_native_max_value = speed_range["max"]
        self._attr_native_step = speed_range["step"]

        speed_names = {
            1: f"Speed 1 (Low) {speed_range['min']}-{speed_range['max']} m³/h",
            2: f"Speed 2 (Medium) {speed_range['min']}-{speed_range['max']} m³/h",
            3: f"Speed 3 (High) {speed_range['min']}-{speed_range['max']} m³/h"
        }

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + f"Recuperation {speed_names[speed_level]}"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current configured flow value."""
        # Get from Home Assistant configuration storage
        # For now, use default values
        return float(DEFAULT_SPEED_VALUES[self._speed_level])

    async def async_set_native_value(self, value: float) -> None:
        """Set the configured flow value."""
        flow_value = int(value)
        _LOGGER.debug("Setting speed %s flow config to %s m³/h", self._speed_level, flow_value)

        # Store the value in Home Assistant's data storage
        # This would need to be implemented with hass.data or config entries
        # For now, just log the change
        _LOGGER.info("Speed %s flow configured to %s m³/h", self._speed_level, flow_value)

        # Note: The actual storage implementation would go here
        # We'd need to update the coordinator or config entry data

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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


class FilterAlarmNumber(CoordinatorEntity, NumberEntity):
    """Representation of filter alarm interval number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "days"
    _attr_native_min_value = FILTER_ALARM_MIN_DAYS
    _attr_native_max_value = FILTER_ALARM_MAX_DAYS
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the filter alarm number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_filter_alarm_interval"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Filter Alarm Interval"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current configured alarm interval."""
        # Default to 30 days - the actual value would be stored in HA data
        return float(FILTER_ALARM_MIN_DAYS)

    async def async_set_native_value(self, value: float) -> None:
        """Set the filter alarm interval."""
        days = int(value)
        _LOGGER.debug("Setting filter alarm interval to %s days", days)

        await self._coordinator.api.set_filter_alarm(self._udid, days)
        await self._coordinator.async_request_refresh()

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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



class VentilationRoomParameterNumber(CoordinatorEntity, NumberEntity):
    """Representation of room ventilation parameter number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 10
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the room ventilation parameter number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_ventilation_room_parameter"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Room Ventilation Parameter"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return 45.0

    async def async_set_native_value(self, value: float) -> None:
        """Set the room ventilation parameter."""
        percent = int(value)
        _LOGGER.debug("Setting room ventilation parameter to %s%%", percent)

        await self._coordinator.api.set_ventilation_room_parameter(self._udid, percent)
        await self._coordinator.async_request_refresh()

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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


class VentilationBathroomParameterNumber(CoordinatorEntity, NumberEntity):
    """Representation of bathroom ventilation parameter number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 10
    _attr_native_max_value = 90
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:shower"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the bathroom ventilation parameter number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_ventilation_bathroom_parameter"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Bathroom Ventilation Parameter"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return 55.0

    async def async_set_native_value(self, value: float) -> None:
        """Set the bathroom ventilation parameter."""
        percent = int(value)
        _LOGGER.debug("Setting bathroom ventilation parameter to %s%%", percent)

        await self._coordinator.api.set_ventilation_bathroom_parameter(self._udid, percent)
        await self._coordinator.async_request_refresh()

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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


class Co2ThresholdNumber(CoordinatorEntity, NumberEntity):
    """Representation of CO2 threshold number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "ppm"
    _attr_native_min_value = 400
    _attr_native_max_value = 2000
    _attr_native_step = 50
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:molecule-co2"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the CO2 threshold number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_co2_threshold"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "CO2 Threshold"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return 1000.0

    async def async_set_native_value(self, value: float) -> None:
        """Set the CO2 threshold."""
        ppm = int(value)
        _LOGGER.debug("Setting CO2 threshold to %s ppm", ppm)

        await self._coordinator.api.set_co2_threshold(self._udid, ppm)
        await self._coordinator.async_request_refresh()

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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


class HysteresisNumber(CoordinatorEntity, NumberEntity):
    """Representation of hysteresis number control."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_native_min_value = 5
    _attr_native_max_value = 10
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune-vertical"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the hysteresis number."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_hysteresis"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Hysteresis"

    @property
    def name(self) -> str:
        """Return the name of the number."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the current value."""
        return 10.0

    async def async_set_native_value(self, value: float) -> None:
        """Set the hysteresis."""
        percent = int(value)
        _LOGGER.debug("Setting hysteresis to %s%%", percent)

        await self._coordinator.api.set_hysteresis(self._udid, percent)
        await self._coordinator.async_request_refresh()

    @property
    def entity_category(self):
        """Return the entity category for configuration entities."""
        from homeassistant.helpers.entity import EntityCategory
        return EntityCategory.CONFIG

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
