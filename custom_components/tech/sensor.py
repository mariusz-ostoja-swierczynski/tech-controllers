"""Support for Tech HVAC system."""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_MODEL,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
    CONF_ZONE,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_signal_level
from homeassistant.helpers.typing import UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    ACTUATORS,
    ACTUATORS_OPEN,
    BATTERY_LEVEL,
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    OPENTHERM_CURRENT_TEMP,
    OPENTHERM_CURRENT_TEMP_DHW,
    OPENTHERM_SET_TEMP,
    OPENTHERM_SET_TEMP_DHW,
    SIGNAL_STRENGTH,
    TYPE_FAN,
    TYPE_FUEL_SUPPLY,
    TYPE_MIXING_VALVE,
    TYPE_OPEN_THERM,
    TYPE_TEMPERATURE,
    TYPE_TEMPERATURE_CH,
    TYPE_TEXT,
    TYPE_VALVE,
    UDID,
    VALUE,
    VALVE_SENSOR_CURRENT_TEMPERATURE,
    VALVE_SENSOR_RETURN_TEMPERATURE,
    VALVE_SENSOR_SET_TEMPERATURE,
    VER,
    VISIBILITY,
    WINDOW_SENSORS,
    WINDOW_STATE,
    WORKING_STATUS,
    ZONE_STATE,
)
from .coordinator import TechCoordinator
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech sensor entities for the provided config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller metadata.
        async_add_entities: Callback used to register entities with Home Assistant.

    """
    controller_udid = config_entry.data[CONTROLLER][UDID]
    _LOGGER.debug("Setting up sensor entry, controller udid: %s", controller_udid)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    zones = await coordinator.api.get_module_zones(controller_udid)
    tiles = await coordinator.api.get_module_tiles(controller_udid)

    zone_entities = [
        entity
        for zone in _iter_mapping(zones)
        for entity in _build_zone_entities(zone, coordinator, config_entry)
    ]

    tile_entities = [
        entity
        for tile in _iter_mapping(tiles)
        for entity in _build_tile_entities(tile, coordinator, config_entry)
    ]

    async_add_entities([*tile_entities, *zone_entities], True)


def _iter_mapping(mapping: dict[Any, Any] | Iterable[Any]) -> Iterable[Any]:
    """Yield mapping values regardless of whether ``mapping`` is a dict or list."""
    if not mapping:
        return ()
    if isinstance(mapping, dict):
        return mapping.values()
    return mapping


def _build_zone_entities(
    zone: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create coordinator entities for a single zone payload."""

    entities: list[CoordinatorEntity] = []
    zone_state = zone.get(CONF_ZONE, {})

    if zone_state.get(BATTERY_LEVEL) is not None:
        entities.append(ZoneBatterySensor(zone, coordinator, config_entry))

    if zone_state.get("currentTemperature") is not None:
        entities.append(ZoneTemperatureSensor(zone, coordinator, config_entry))

    if zone_state.get(ZONE_STATE) is not None:
        entities.append(ZoneStateSensor(zone, coordinator, config_entry))

    humidity = zone_state.get("humidity")
    if humidity is not None and humidity >= 0:
        entities.append(ZoneHumiditySensor(zone, coordinator, config_entry))

    if zone_state.get(SIGNAL_STRENGTH) is not None:
        entities.append(ZoneSignalStrengthSensor(zone, coordinator, config_entry))

    for idx, _ in enumerate(zone.get(ACTUATORS, [])):
        entities.append(ZoneActuatorSensor(zone, coordinator, config_entry, idx))

    for idx, _ in enumerate(zone.get(WINDOW_SENSORS, [])):
        entities.append(ZoneWindowSensor(zone, coordinator, config_entry, idx))

    return entities


TileBuilder = Callable[
    [dict[str, Any], TechCoordinator, ConfigEntry], list[CoordinatorEntity]
]


def _build_tile_entities(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create coordinator entities for a single tile payload."""

    if not tile.get(VISIBILITY, False) or not tile.get(WORKING_STATUS, True):
        return []

    builder = _TILE_ENTITY_BUILDERS.get(tile[CONF_TYPE])
    if builder is None:
        return []
    return builder(tile, coordinator, config_entry)


def _build_temperature_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create entities for a temperature tile and its optional sensors."""
    params = tile.get(CONF_PARAMS, {})

    def _has_value(value: Any) -> bool:
        return value not in (None, "null")

    create_device = any(
        _has_value(params.get(key)) for key in (SIGNAL_STRENGTH, BATTERY_LEVEL)
    )

    entities: list[CoordinatorEntity] = [
        TileTemperatureSensor(tile, coordinator, config_entry, create_device)
    ]

    if _has_value(params.get(SIGNAL_STRENGTH)):
        entities.append(
            TileTemperatureSignalSensor(tile, coordinator, config_entry, create_device)
        )
    if _has_value(params.get(BATTERY_LEVEL)):
        entities.append(
            TileTemperatureBatterySensor(tile, coordinator, config_entry, create_device)
        )

    return entities


def _build_valve_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create valve-related entities for a tile payload."""
    entities: list[CoordinatorEntity] = [
        TileValveSensor(tile, coordinator, config_entry)
    ]

    for valve_sensor in (
        VALVE_SENSOR_RETURN_TEMPERATURE,
        VALVE_SENSOR_SET_TEMPERATURE,
        VALVE_SENSOR_CURRENT_TEMPERATURE,
    ):
        if tile[CONF_PARAMS].get(valve_sensor["state_key"]) is not None:
            entities.append(
                TileValveTemperatureSensor(
                    tile, coordinator, config_entry, valve_sensor
                )
            )

    return entities


def _build_open_therm_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create OpenTherm entities for a tile payload."""
    entities: list[CoordinatorEntity] = []
    for description in (
        OPENTHERM_CURRENT_TEMP,
        OPENTHERM_SET_TEMP,
        OPENTHERM_CURRENT_TEMP_DHW,
        OPENTHERM_SET_TEMP_DHW,
    ):
        if tile[CONF_PARAMS].get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermSensor(tile, coordinator, config_entry, description)
            )
    return entities


_TILE_ENTITY_BUILDERS: dict[int, TileBuilder] = {
    TYPE_TEMPERATURE: _build_temperature_tile,
    TYPE_TEMPERATURE_CH: lambda tile, coordinator, config_entry: [
        TileWidgetSensor(tile, coordinator, config_entry)
    ],
    TYPE_FAN: lambda tile, coordinator, config_entry: [
        TileFanSensor(tile, coordinator, config_entry)
    ],
    TYPE_VALVE: _build_valve_tile,
    TYPE_MIXING_VALVE: lambda tile, coordinator, config_entry: [
        TileMixingValveSensor(tile, coordinator, config_entry)
    ],
    TYPE_FUEL_SUPPLY: lambda tile, coordinator, config_entry: [
        TileFuelSupplySensor(tile, coordinator, config_entry)
    ],
    TYPE_TEXT: lambda tile, coordinator, config_entry: [
        TileTextSensor(tile, coordinator, config_entry)
    ],
    TYPE_OPEN_THERM: _build_open_therm_tile,
}


class TechBatterySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech battery sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator: TechCoordinator, config_entry) -> None:
        """Initialize the Tech battery sensor."""
        _LOGGER.debug("Init TechBatterySensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][BATTERY_LEVEL]

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_battery"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "battery_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} battery"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech temperature sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech temperature sensor."""
        _LOGGER.debug("Init TechTemperatureSensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the current temperature is available, and update the native value accordingly
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._attr_native_value = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "temperature_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechOutsideTempTile(CoordinatorEntity, SensorEntity):
    """Representation of a Tech outside temperature tile sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech temperature sensor."""
        _LOGGER.debug("Init TechOutsideTemperatureTile... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)
        _LOGGER.debug(
            "Init TechOutsideTemperatureTile...: %s, udid: %s, id: %s",
            self._name,
            self._config_entry.data[CONTROLLER][UDID],
            self._id,
        )

    def update_properties(self, device):
        """Update native values from an outside temperature tile payload.

        Args:
            device: Tile dictionary containing temperature information.

        """
        self._name = "outside_" + str(device[CONF_ID])

        if device[CONF_PARAMS][VALUE] is not None:
            # Update the native value based on the device params
            self._attr_native_value = device[CONF_PARAMS][VALUE] / 10
        else:
            # Set native value to None if device params value is None
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["tiles"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_out_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "ext_temperature_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechHumiditySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech humidity sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech humidity sensor."""
        _LOGGER.debug("Init TechHumiditySensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the humidity value is not zero and update the native value attribute accordingly
        if device[CONF_ZONE]["humidity"] != 0:
            self._attr_native_value = device[CONF_ZONE]["humidity"]
        else:
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_humidity"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "humidity_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} humidity"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class ZoneSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Zone Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = (
            device[CONF_DESCRIPTION][CONF_NAME]
            if not self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else f"{self._config_entry.title} {device[CONF_DESCRIPTION][CONF_NAME]}"
        )
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self._attr_translation_placeholders = {"entity_name": ""}
        self.update_properties(device)

    def update_properties(self, device):
        """Update cached zone values from the latest coordinator payload.

        Args:
            device: Zone dictionary containing description and telemetry data.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update target_temperature property
        if device[CONF_ZONE]["setTemperature"] is not None:
            self._target_temperature = device[CONF_ZONE]["setTemperature"] / 10
        else:
            self._target_temperature = None

        # Update temperature property
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._temperature = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._temperature = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id


class ZoneTemperatureSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "temperature_entity"

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the current temperature is available, and update the native value accordingly
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._attr_native_value = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._attr_native_value = None


class ZoneBatterySensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "battery_entity"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_battery"

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][BATTERY_LEVEL]


class ZoneSignalStrengthSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "signal_strength_entity"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][SIGNAL_STRENGTH]


class ZoneHumiditySensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_humidity"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "humidity_entity"

    def update_properties(self, device):
        """Update the properties of the TechHumiditySensor object.

        Args:
        device (dict): The device information.

        Returns:
        None

        """
        # Update the name of the device
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the humidity value is not zero and update the native value attribute accordingly
        if device[CONF_ZONE]["humidity"] != 0:
            self._attr_native_value = device[CONF_ZONE]["humidity"]
        else:
            self._attr_native_value = None


class ZoneActuatorSensor(ZoneSensor):
    """Representation of a Zone Actuator Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = assets.get_icon_by_type(TYPE_VALVE)

    def __init__(self, device, coordinator, config_entry, actuator_index) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _actuator_index already.

        """
        self._actuator_index = actuator_index
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "actuator_entity"
        self._attr_translation_placeholders = {
            "actuator_number": f"{cast(int, self._actuator_index) + 1}"
        }
        self.attrs[BATTERY_LEVEL] = device[ACTUATORS][self._actuator_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[ACTUATORS][self._actuator_index][
            SIGNAL_STRENGTH
        ]

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_actuator_{self._actuator_index + 1!s}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update the native value attribute
        self._attr_native_value = device[CONF_ZONE][ACTUATORS_OPEN]

        # Update battery and signal strength
        self.attrs[BATTERY_LEVEL] = device[ACTUATORS][self._actuator_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[ACTUATORS][self._actuator_index][
            SIGNAL_STRENGTH
        ]


class ZoneWindowSensor(BinarySensorEntity, ZoneSensor):
    """Representation of a Zone Window Sensor."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, device, coordinator, config_entry, window_index) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _window_index already.

        """
        self._window_index = window_index
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "window_sensor_entity"
        self._attr_translation_placeholders = {
            "window_number": f"{cast(int, self._window_index) + 1}"
        }
        self.attrs[BATTERY_LEVEL] = device[WINDOW_SENSORS][self._window_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[WINDOW_SENSORS][self._window_index][
            SIGNAL_STRENGTH
        ]
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_window_{self._window_index + 1!s}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update battery and signal strength
        self.attrs[BATTERY_LEVEL] = device[WINDOW_SENSORS][self._window_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[WINDOW_SENSORS][self._window_index][
            SIGNAL_STRENGTH
        ]
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )


class ZoneOutsideTempTile(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_out_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "ext_temperature_entity"

    def update_properties(self, device):
        """Update native attributes from the provided tile payload.

        Args:
            device: Tile dictionary containing temperature information.

        """
        self._name = "outside_" + str(device[CONF_ID])

        if device[CONF_PARAMS][VALUE] is not None:
            # Update the native value based on the device params
            self._attr_native_value = device[CONF_PARAMS][VALUE] / 10
        else:
            # Set native value to None if device params value is None
            self._attr_native_value = None


class ZoneStateSensor(BinarySensorEntity, ZoneSensor):
    """Representation of a Zone State (alarm) Sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _window_index already.

        """
        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "zone_state_entity"
        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_state"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        self.attrs[ZONE_STATE] = device[CONF_ZONE][ZONE_STATE]

        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"


class TileSensor(TileEntity, CoordinatorEntity):
    """Representation of a TileSensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_state(self, device) -> Any:
        """Get the state of the device."""


class TileTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT
        # self.device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "temperature_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][VALUE] / 10

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""

        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        return None


class TileTemperatureBatterySensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Battery Sensor."""

    _attr_has_entity_name = True

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "battery_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_battery"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][BATTERY_LEVEL]

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""

        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        return None


class TileTemperatureSignalSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Signal Sensor."""

    _attr_has_entity_name = True

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "signal_strength_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][SIGNAL_STRENGTH]

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        return None


class TileFuelSupplySensor(TileSensor, SensorEntity):
    """Representation of a Tile Fuel Supply Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fuel_supply"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["percentage"]


class TileFanSensor(TileSensor, SensorEntity):
    """Representation of a Tile Fan Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fan"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["gear"]


class TileTextSensor(TileSensor, SensorEntity):
    """Representation of a Tile Text Sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(device[CONF_PARAMS]["headerId"])

        self._attr_icon = assets.get_icon(device[CONF_PARAMS]["iconId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_text"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return assets.get_text(device[CONF_PARAMS]["statusId"])


class TileWidgetSensor(TileSensor, SensorEntity):
    """Representation of a Tile Widget Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(device[CONF_PARAMS]["widget1"]["txtId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_widget"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["widget1"][VALUE] / 10


class TileValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])

        self.attrs: dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_valve"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} {self._valve_number}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        self._state = self.get_state(device)
        self.attrs["setTempCorrection"] = device[CONF_PARAMS]["setTempCorrection"]
        self.attrs["valvePump"] = (
            STATE_ON if device[CONF_PARAMS]["valvePump"] == 1 else STATE_OFF
        )
        self.attrs["boilerProtection"] = (
            STATE_ON if device[CONF_PARAMS]["boilerProtection"] == 1 else STATE_OFF
        )
        self.attrs["returnProtection"] = (
            STATE_ON if device[CONF_PARAMS]["returnProtection"] == 1 else STATE_OFF
        )


class TileValveTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Temperature Sensor."""

    def __init__(self, device, coordinator, config_entry, valve_sensor):
        """Initialize the sensor."""
        self._state_key = valve_sensor["state_key"]
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        sensor_name = assets.get_text(valve_sensor["txt_id"])
        name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])
        self._name = f"{name} {device[CONF_PARAMS]['valveNumber']} {sensor_name}"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_valve_{self._state_key}"

    def get_state(self, device):
        """Get the state of the device."""
        state = device[CONF_PARAMS][self._state_key]
        if self._state_key in ("returnTemp", "currentTemp"):
            state /= 10
        return state


class TileMixingValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Mixing Valve Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_mixing_valve"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} {self._valve_number}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]


class TileOpenThermSensor(TileSensor, SensorEntity):
    """Representation of config_OpenTherm Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        open_therm_sensor,
    ) -> None:
        """Initialize the sensor."""

        # It is needed to store following variables before TileSensor.__init__
        self._txt_id = open_therm_sensor["txt_id"]
        self._state_key = open_therm_sensor["state_key"]

        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT
        self.manufacturer = MANUFACTURER
        self.device_name = (
            f"{self._config_entry.title} {assets.get_text_by_type(device[CONF_TYPE])}"
        )
        self.model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(self._txt_id)

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_opentherm_{self._state_key}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][self._state_key] / 10

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self.device_name,  # Name of the device
            CONF_MODEL: self.model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }
