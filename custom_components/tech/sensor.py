"""Support for Tech HVAC system."""
import itertools
import logging
from typing import Any, Dict

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
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
from homeassistant.helpers.icon import icon_for_signal_level
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator, assets
from .const import (
    ACTUATORS,
    ACTUATORS_OPEN,
    BATTERY_LEVEL,
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
    SIGNAL_STRENGTH,
    TYPE_FAN,
    TYPE_FUEL_SUPPLY,
    TYPE_MIXING_VALVE,
    TYPE_TEMPERATURE,
    TYPE_TEMPERATURE_CH,
    TYPE_TEXT,
    TYPE_VALVE,
    UDID,
    VALUE,
    VER,
    VISIBILITY,
    WORKING_STATUS,
)
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, config_entry: ConfigEntry, async_add_entities
) -> None:
    """Set up entry."""
    _LOGGER.debug(
        "Setting up sensor entry, controller udid: %s",
        config_entry.data[CONTROLLER][UDID],
    )
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = config_entry.data[CONTROLLER][UDID]

    zones = await coordinator.api.get_module_zones(controller_udid)
    tiles = await coordinator.api.get_module_tiles(controller_udid)

    entities = []
    for t in tiles:
        tile = tiles[t]
        if tile[VISIBILITY] is False or tile.get(WORKING_STATUS, True) is False:
            continue
        if tile[CONF_TYPE] == TYPE_TEMPERATURE:
            signal_strength = tile[CONF_PARAMS][SIGNAL_STRENGTH]
            battery_level = tile[CONF_PARAMS][BATTERY_LEVEL]
            if signal_strength not in (None, "null"):
                entities.append(
                    TileTemperatureSignalSensor(tile, coordinator, config_entry)
                )
            if battery_level not in (None, "null"):
                entities.append(
                    TileTemperatureBatterySensor(tile, coordinator, config_entry)
                )
            entities.append(TileTemperatureSensor(tile, coordinator, config_entry))

        if tile[CONF_TYPE] == TYPE_TEMPERATURE_CH:
            entities.append(TileWidgetSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_FAN:
            entities.append(TileFanSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_VALVE:
            entities.append(TileValveSensor(tile, coordinator, config_entry))
            # TODO: this class _init_ definition needs to be fixed. See comment below.
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_RETURN_TEMPERATURE))
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_SET_TEMPERATURE))
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_CURRENT_TEMPERATURE))
        if tile[CONF_TYPE] == TYPE_MIXING_VALVE:
            entities.append(TileMixingValveSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_FUEL_SUPPLY:
            entities.append(TileFuelSupplySensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_TEXT:
            entities.append(TileTextSensor(tile, coordinator, config_entry))

    async_add_entities(entities, True)

    # async_add_entities(
    #     [
    #         ZoneTemperatureSensor(zones[zone], coordinator, controller_udid, model)
    #         for zone in zones
    #     ],
    #     True,
    # )

    battery_devices = map_to_battery_sensors(zones, coordinator, config_entry)
    temperature_sensors = map_to_temperature_sensors(zones, coordinator, config_entry)
    humidity_sensors = map_to_humidity_sensors(zones, coordinator, config_entry)
    actuator_sensors = map_to_actuator_sensors(zones, coordinator, config_entry)
    signal_strength_sensors = map_to_signal_strength_sensors(
        zones, coordinator, config_entry
    )
    # tile_sensors = map_to_tile_sensors(tiles, api, config_entry)

    async_add_entities(
        itertools.chain(
            battery_devices,
            temperature_sensors,
            humidity_sensors,  # , tile_sensors
            actuator_sensors,
            signal_strength_sensors,
        ),
        True,
    )


def map_to_battery_sensors(zones, coordinator, config_entry):
    """Map the battery-operating devices in the zones to TechBatterySensor objects.

    Args:
    zones: list of devices
    coordinator: the api object
    config_entry: the config entry object
    model: device model

    Returns:
    - list of TechBatterySensor objects

    """
    devices = filter(
        lambda deviceIndex: is_battery_operating_device(zones[deviceIndex]), zones
    )
    return (
        ZoneBatterySensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_battery_operating_device(device) -> bool:
    """Check if the device is operating on battery.

    Args:
    device: dict - The device information.

    Returns:
    bool - True if the device is operating on battery, False otherwise.

    """
    return device[CONF_ZONE][BATTERY_LEVEL] is not None


def map_to_temperature_sensors(zones, coordinator, config_entry):
    """Map the zones to temperature sensors using the provided API and config entry.

    Args:
    zones (list): List of zones
    coordinator (object): The API object
    config_entry (object): The config entry object
    model: device model

    Returns:
    list: List of TechTemperatureSensor objects

    """
    devices = filter(
        lambda deviceIndex: is_temperature_operating_device(zones[deviceIndex]), zones
    )
    return (
        ZoneTemperatureSensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_temperature_operating_device(device) -> bool:
    """Check if the device's current temperature is available.

    Args:
        device (dict): The device information.

    Returns:
        bool: True if the current temperature is available, False otherwise.

    """
    return device[CONF_ZONE]["currentTemperature"] is not None


def map_to_humidity_sensors(zones, coordinator, config_entry):
    """Map zones to humidity sensors.

    Args:
    zones: list of zones
    coordinator: API to interact with humidity sensors
    config_entry: configuration entry for the sensors
    model: device model

    Returns:
    list of TechHumiditySensor instances

    """
    # Filter devices that are humidity operating devices
    devices = filter(
        lambda deviceIndex: is_humidity_operating_device(zones[deviceIndex]), zones
    )
    # Map devices to TechHumiditySensor instances
    return (
        ZoneHumiditySensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_humidity_operating_device(device) -> bool:
    """Check if the device is operating based on the humidity level in its zone.

    Args:
    device: dict - The device information containing the zone and humidity level.

    Returns:
    bool - True if the device is operating based on the humidity level, False otherwise.

    """
    return (
        device[CONF_ZONE]["humidity"] is not None and device[CONF_ZONE]["humidity"] >= 0
    )


def map_to_actuator_sensors(zones, coordinator, config_entry):
    """Map zones to actuator sensors.

    Args:
    zones: list of zones
    coordinator: API to interact with actuators
    config_entry: configuration entry for the sensors

    Returns:
    list of ZoneActuatorSensor instances

    """
    # Filter devices that are actuator operating devices
    devices = [
        deviceIndex
        for deviceIndex in zones
        if is_actuator_operating_device(zones[deviceIndex])
    ]

    return [
        ZoneActuatorSensor(zones[deviceIndex], coordinator, config_entry, idx)
        for deviceIndex in devices
        for idx in range(len(zones[deviceIndex][ACTUATORS]))
    ]


def is_actuator_operating_device(device) -> bool:
    """Check if the device has any actuators.

    Args:
    device: dict - The device information containing the zone and humidity level.

    Returns:
    bool - True if the device has any actuators, False otherwise.

    """
    return len(device[ACTUATORS]) > 0


def map_to_tile_sensors(tiles, coordinator, config_entry):
    """Map tiles to corresponding sensor objects based on the device type and create a list of sensor objects.

    Args:
    tiles: List of tiles
    coordinator: API object
    config_entry: Configuration entry object
    model: device model

    Returns:
    List of sensor objects

    """
    # Filter devices with outside temperature
    devices_outside_temperature = filter(
        lambda deviceIndex: is_outside_temperature_tile(tiles[deviceIndex]), tiles
    )

    # Create sensor objects for devices with outside temperature
    devices_objects = (
        ZoneOutsideTempTile(tiles[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices_outside_temperature
    )

    return devices_objects


def is_outside_temperature_tile(device) -> bool:
    """Check if the device is a temperature sensor.

    Args:
    device (dict): The device information.

    Returns:
    bool: True if the device is a temperature sensor, False otherwise.

    """
    return device[CONF_PARAMS][CONF_DESCRIPTION] == "Temperature sensor"


def map_to_signal_strength_sensors(zones, coordinator, config_entry):
    """Map the signal strength operating devices in the zones to ZoneSignalStrengthSensor objects.

    Args:
    zones: list of devices
    coordinator: the api object
    config_entry: the config entry object
    model: device model

    Returns:
    - list of TechBatterySensor objects

    """
    devices = filter(
        lambda deviceIndex: is_signal_strength_operating_device(zones[deviceIndex]),
        zones,
    )
    return (
        ZoneSignalStrengthSensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_signal_strength_operating_device(device) -> bool:
    """Check if the device is operating on battery.

    Args:
    device: dict - The device information.

    Returns:
    bool - True if the device is operating on battery, False otherwise.

    """
    return device[CONF_ZONE][SIGNAL_STRENGTH] is not None


class TechBatterySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech battery sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator: TechCoordinator, config_entry):
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
        """Update properties from the TechBatterySensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} battery"

    @property
    def device_info(self):
        """Get device information.

        Returns:
        dict: A dictionary containing device information.

        """
        # Return device information
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
        self, device: Dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ):
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
        """Update the properties of the TechTemperatureSensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        # Set the name of the device
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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self):
        """Get device information.

        Returns:
        dict: A dictionary containing device information.

        """
        # Return device information
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
        self, device: Dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ):
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
        """Update the properties of the TechOutsideTempTile object.

        Args:
        device: dict containing information about the device

        Returns:
        None

        """
        # Set the name based on the device id
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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self):
        """Get device information.

        Returns:
        dict: A dictionary containing device information.

        """
        # Return device information
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
        self, device: Dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ):
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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} humidity"

    @property
    def device_info(self):
        """Get device information.

        Returns:
        dict: A dictionary containing device information.

        """
        # Return device information
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

    def __init__(
        self, device: Dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ):
        """Initialize the sensor."""
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
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        # Update name property
        self._name = (
            self._config_entry.data[CONTROLLER][CONF_NAME]
            + " "
            + device[CONF_DESCRIPTION][CONF_NAME]
        )

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
    def device_info(self):
        """Get device information.

        Returns:
        dict: A dictionary containing device information.

        """
        # Return device information
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

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name


class ZoneTemperatureSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self):
        """Return the name of the sensor."""
        return f"{self._name} temperature"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_temperature"

    def update_properties(self, device):
        """Update the properties of the TechTemperatureSensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        # Set the name of the device
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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} battery"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_battery"

    def update_properties(self, device):
        """Update properties from the TechBatterySensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][BATTERY_LEVEL]


class ZoneSignalStrengthSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    @property
    def name(self):
        """Return the name of the device."""
        return f"{self._name} signal strength"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    def update_properties(self, device):
        """Update properties from the ZoneSignalStrengthSensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} humidity"

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

    def __init__(self, device, coordinator, config_entry, actuator_index):
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _actuator_index already.

        """
        self._actuator_index = actuator_index
        self.attrs: Dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self.attrs[BATTERY_LEVEL] = device[ACTUATORS][self._actuator_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[ACTUATORS][self._actuator_index][
            SIGNAL_STRENGTH
        ]

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_actuator_{str(self._actuator_index + 1)}"

    @property
    def name(self):
        """Return the name of the entity."""
        return f"{self._name} actuator {str(self._actuator_index + 1)}"

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update the properties of the ZoneActuatorSensor object.

        Args:
        device (dict): The device information.

        Returns:
        None

        """
        # Update the name of the device
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
    def name(self):
        """Return the name of the device."""
        return f"{self._name} temperature"

    def update_properties(self, device):
        """Update the properties of the TechOutsideTempTile object.

        Args:
        device: dict containing information about the device

        Returns:
        None

        """
        # Set the name based on the device id
        self._name = "outside_" + str(device[CONF_ID])

        if device[CONF_PARAMS][VALUE] is not None:
            # Update the native value based on the device params
            self._attr_native_value = device[CONF_PARAMS][VALUE] / 10
        else:
            # Set native value to None if device params value is None
            self._attr_native_value = None


class TileSensor(TileEntity, CoordinatorEntity):
    """Representation of a TileSensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_state(self, device):
        """Get the state of the device."""


class TileTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Sensor."""

    def __init__(self, device, coordinator: TechCoordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature"

    @property
    def name(self):
        """Return the name of the device."""
        return f"{self._name}"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS][VALUE] / 10


class TileTemperatureBatterySensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Battery Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator: TechCoordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_battery"

    @property
    def name(self):
        """Return the name of the device."""
        return f"{self._name} battery"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS][BATTERY_LEVEL]


class TileTemperatureSignalSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Signal Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    def __init__(self, device, coordinator: TechCoordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    @property
    def name(self):
        """Return the name of the device."""
        return f"{self._name} signal strength"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS][SIGNAL_STRENGTH]


class TileFuelSupplySensor(TileSensor):
    """Representation of a Tile Fuel Supply Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fuel_supply"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS]["percentage"]


class TileFanSensor(TileSensor):
    """Representation of a Tile Fan Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fan"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS]["gear"]


class TileTextSensor(TileSensor):
    """Representation of a Tile Text Sensor."""

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = assets.get_text(device[CONF_PARAMS]["headerId"])
        self._attr_icon = assets.get_icon(device[CONF_PARAMS]["iconId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_text"

    def get_state(self, device):
        """Get the state of the device."""
        return assets.get_text(device[CONF_PARAMS]["statusId"])


class TileWidgetSensor(TileSensor):
    """Representation of a Tile Widget Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = assets.get_text(device[CONF_PARAMS]["widget1"]["txtId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_widget"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS]["widget1"][VALUE] / 10


class TileValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Sensor."""

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        name = assets.get_text_by_type(device[CONF_TYPE])
        self._name = f"{name} {device[CONF_PARAMS]['valveNumber']}"
        self.attrs: Dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_valve"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
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
        self.attrs["currentTemp"] = device[CONF_PARAMS]["currentTemp"] / 10
        self.attrs["returnTemp"] = device[CONF_PARAMS]["returnTemp"] / 10
        self.attrs["setTempCorrection"] = device[CONF_PARAMS]["setTempCorrection"]
        self.attrs["valvePump"] = (
            STATE_ON if device[CONF_PARAMS]["valvePump"] == "1" else STATE_OFF
        )
        self.attrs["boilerProtection"] = (
            STATE_ON if device[CONF_PARAMS]["boilerProtection"] == "1" else STATE_OFF
        )
        self.attrs["returnProtection"] = (
            STATE_ON if device[CONF_PARAMS]["returnProtection"] == "1" else STATE_OFF
        )
        self.attrs["setTemp"] = device[CONF_PARAMS]["setTemp"]


class TileMixingValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Mixing Valve Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry):
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        name = assets.get_text_by_type(device[CONF_TYPE])
        self._name = f"{name} {device[CONF_PARAMS]['valveNumber']}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_mixing_valve"

    def get_state(self, device):
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]


# TODO: this sensor's ID assignment needs to be fixed as base on such ID
#  tech api doesn't return value and we get KeyError
#
# class TileValveTemperatureSensor(TileSensor):
#     def __init__(self, device, api, controller_udid, valve_sensor):
#         self._state_key = valve_sensor["state_key"]
#         sensor_name = assets.get_text(valve_sensor["txt_id"])
#         TileSensor.__init__(self, device, api, controller_udid)
#         self._id = f"{self._id}_{self._state_key}"
#         name = assets.get_text_by_type(device[CONF_TYPE])
#         self._name = f"{name} {device[CONF_PARAMS]['valveNumber']} {sensor_name}"

#     @property
#     def device_class(self):
#         return sensor.DEVICE_CLASS_TEMPERATURE

#     @property
#     def unit_of_measurement(self):
#         return TEMP_CELSIUS

#     def get_state(self, device):
#         state = device[CONF_PARAMS][self._state_key]
#         if state > 100:
#             state = state / 10
#         return state
