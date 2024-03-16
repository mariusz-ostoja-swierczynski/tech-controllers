"""Support for Tech HVAC system."""
import itertools
import logging
from typing import TYPE_CHECKING, Any

from _collections_abc import Generator

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
    CONF_ZONE,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator, assets
from .const import (
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
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
)
from .entity import TileEntity

if TYPE_CHECKING:
    from functools import cached_property
else:
    from homeassistant.backports.functools import cached_property

_LOGGER = logging.getLogger(__name__)


class TechBatterySensor(CoordinatorEntity[TechCoordinator], SensorEntity):
    """Representation of a Tech battery sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device: dict[str, Any],
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the Tech battery sensor."""
        super().__init__(coordinator)
        self._config_entry: ConfigEntry = config_entry
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ZONE][CONF_ID]
        self._device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self._model: str = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer: str = MANUFACTURER
        self.update_properties(device)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },  # Unique identifiers for the device
            name=self._device_name,  # Name of the device
            model=self._model,  # Model of the device
            manufacturer=self._manufacturer,  # Manufacturer of the device
        )

    def update_properties(self, device: dict[str, Any]):
        """Update properties from the TechBatterySensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE]["batteryLevel"]

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_battery"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} battery"


class TechTemperatureSensor(CoordinatorEntity[TechCoordinator], SensorEntity):
    """Representation of a Tech temperature sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device: dict[str, Any],
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the Tech temperature sensor."""
        super().__init__(coordinator)
        self._config_entry: ConfigEntry = config_entry
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ZONE][CONF_ID]
        self._unique_id: str = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self._model: str = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer: str = MANUFACTURER
        self.update_properties(device)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },  # Unique identifiers for the device
            name=self._device_name,  # Name of the device
            model=self._model,  # Model of the device
            manufacturer=self._manufacturer,  # Manufacturer of the device
        )

    def update_properties(self, device: dict[str, Any]) -> None:
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

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_temperature"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} temperature"


class TechOutsideTempTile(CoordinatorEntity[TechCoordinator], SensorEntity):
    """Representation of a Tech outside temperature tile sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device: dict[Any, Any],
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the Tech temperature sensor."""
        super().__init__(coordinator)
        self._config_entry: ConfigEntry = config_entry
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ID]
        self._device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self._model: str = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer: str = MANUFACTURER
        self.update_properties(device)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },  # Unique identifiers for the device
            name=self._device_name,  # Name of the device
            model=self._model,  # Model of the device
            manufacturer=self._manufacturer,  # Manufacturer of the device
        )

    def update_properties(self, device: dict[str, Any]) -> None:
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

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_out_temperature"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} temperature"


class TechHumiditySensor(CoordinatorEntity[TechCoordinator], SensorEntity):
    """Representation of a Tech humidity sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device: dict[Any, Any],
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the Tech humidity sensor."""
        _LOGGER.debug("Init TechHumiditySensor... ")
        super().__init__(coordinator)
        self._config_entry: ConfigEntry = config_entry
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ZONE][CONF_ID]
        self._device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self._model: str = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer: str = MANUFACTURER
        self.update_properties(device)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },  # Unique identifiers for the device
            name=self._device_name,  # Name of the device
            model=self._model,  # Model of the device
            manufacturer=self._manufacturer,  # Manufacturer of the device
        )

    def update_properties(self, device: dict[str, Any]) -> None:
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

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_humidity"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} humidity"


class ZoneSensor(CoordinatorEntity[TechCoordinator], SensorEntity):
    """Representation of a Zone Sensor."""

    def __init__(
        self,
        device: dict[Any, Any],
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry: ConfigEntry = config_entry
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ZONE][CONF_ID]
        self._unique_id: str = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self._model: str = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer: str = MANUFACTURER
        self.update_properties(device)
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._device_name)
            },  # Unique identifiers for the device
            name=self._device_name,  # Name of the device
            model=self._model,  # Model of the device
            manufacturer=self._manufacturer,  # Manufacturer of the device
        )

    def update_properties(self, device: dict[str, Any]) -> None:
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        # Update name property
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

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

    @cached_property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name


class ZoneTemperatureSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @cached_property
    def name(self) -> str:
        """Return the name of the sensor."""
        return f"{self._name} Temperature"

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_battery"

    def update_properties(self, device: dict[str, Any]) -> None:
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

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} battery"

    def update_properties(self, device: dict[str, Any]) -> None:
        """Update properties from the TechBatterySensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE]["batteryLevel"]


class ZoneHumiditySensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_humidity"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} humidity"

    def update_properties(self, device: dict[Any, Any]):
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


class ZoneOutsideTempTile(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"climate_{self._id}_out_temperature"

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return f"{self._name} temperature"

    def update_properties(self, device: dict[str, Any]) -> None:
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


class TileSensor(TileEntity, CoordinatorEntity[TechCoordinator]):
    """Representation of a TileSensor."""

    def get_state(self, device: dict[str, Any]) -> Any:
        """Get the state of the device."""


class TileTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Sensor."""

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT

    def get_state(self, device: dict[str, Any]) -> float:
        """Get the state of the device."""
        return device[CONF_PARAMS][VALUE] / 10


class TileFuelSupplySensor(TileSensor):
    """Representation of a Tile Fuel Supply Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)

    def get_state(self, device: dict[str, Any]) -> int:
        """Get the state of the device."""
        return device[CONF_PARAMS]["percentage"]


class TileFanSensor(TileSensor):
    """Representation of a Tile Fan Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    def get_state(self, device: dict[str, Any]) -> int:
        """Get the state of the device."""
        return device[CONF_PARAMS]["gear"]


class TileTextSensor(TileSensor):
    """Representation of a Tile Text Sensor."""

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self._name = assets.get_text(device[CONF_PARAMS]["headerId"])
        self._attr_icon = assets.get_icon(device[CONF_PARAMS]["iconId"])

    def get_state(self, device: dict[str, Any]) -> str:
        """Get the state of the device."""
        return assets.get_text(device[CONF_PARAMS]["statusId"])


class TileWidgetSensor(TileSensor):
    """Representation of a Tile Widget Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self._name = assets.get_text(device[CONF_PARAMS]["widget2"]["txtId"])

    def get_state(self, device: dict[str, Any]) -> str:
        """Get the state of the device."""
        return device[CONF_PARAMS]["widget2"][VALUE] / 10


class TileValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Sensor."""

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        name: str = assets.get_text_by_type(device[CONF_TYPE])
        self._name: str = f"{name} {device[CONF_PARAMS]['valveNumber']}"
        self.attrs: dict[str, Any] = {}

    def get_state(self, device: dict[str, Any]) -> int:
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]

    @cached_property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes: dict[str, Any] = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device: dict[str, Any]) -> None:
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        self._state = str(self.get_state(device))
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

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, controller_udid)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        name: str = assets.get_text_by_type(device[CONF_TYPE])
        self._name: str = f"{name} {device[CONF_PARAMS]['valveNumber']}"

    def get_state(self, device: dict[str, Any]) -> int:
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


def map_to_battery_sensors(
    zones: dict[str, Any], coordinator: TechCoordinator, config_entry: ConfigEntry
) -> Generator[ZoneBatterySensor, None, None]:
    """Map the battery-operating devices in the zones to TechBatterySensor objects.

    Args:
    zones: list of devices
    coordinator: the api object
    config_entry: the config entry object
    model: device model

    Returns:
    - list of TechBatterySensor objects

    """
    devices: filter[str] = filter(
        lambda deviceIndex: is_battery_operating_device(zones[deviceIndex]), zones
    )
    return (
        ZoneBatterySensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_battery_operating_device(device: dict[str, Any]) -> bool:
    """Check if the device is operating on battery.

    Args:
    device: dict - The device information.

    Returns:
    bool - True if the device is operating on battery, False otherwise.

    """
    return device[CONF_ZONE]["batteryLevel"] is not None


def map_to_temperature_sensors(
    zones: dict[str, Any], coordinator: TechCoordinator, config_entry: ConfigEntry
) -> Generator[ZoneTemperatureSensor, None, None]:
    """Map the zones to temperature sensors using the provided API and config entry.

    Args:
    zones (list): list of zones
    coordinator (object): The API object
    config_entry (object): The config entry object
    model: device model

    Returns:
    list: list of TechTemperatureSensor objects

    """
    devices: filter[str] = filter(
        lambda deviceIndex: is_temperature_operating_device(zones[deviceIndex]), zones
    )
    return (
        ZoneTemperatureSensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_temperature_operating_device(device: dict[str, Any]) -> bool:
    """Check if the device's current temperature is available.

    Args:
        device (dict): The device information.

    Returns:
        bool: True if the current temperature is available, False otherwise.

    """
    return device[CONF_ZONE]["currentTemperature"] is not None


def map_to_humidity_sensors(
    zones: dict[str, Any], coordinator: TechCoordinator, config_entry: ConfigEntry
) -> Generator[ZoneHumiditySensor, None, None]:
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
    devices: filter[str] = filter(
        lambda deviceIndex: is_humidity_operating_device(zones[deviceIndex]), zones
    )
    # Map devices to TechHumiditySensor instances
    return (
        ZoneHumiditySensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_humidity_operating_device(device: dict[str, Any]) -> bool:
    """Check if the device is operating based on the humidity level in its zone.

    Args:
    device: dict - The device information containing the zone and humidity level.

    Returns:
    bool - True if the device is operating based on the humidity level, False otherwise.

    """
    return (
        device[CONF_ZONE]["humidity"] is not None and device[CONF_ZONE]["humidity"] >= 0
    )


def map_to_tile_sensors(
    tiles: dict[str, Any], coordinator: TechCoordinator, config_entry: ConfigEntry
) -> Generator[ZoneOutsideTempTile, None, None]:
    """Map tiles to corresponding sensor objects based on the device type and create a list of sensor objects.

    Args:
    tiles: list of tiles
    coordinator: API object
    config_entry: Configuration entry object
    model: device model

    Returns:
    list of sensor objects

    """
    # Filter devices with outside temperature
    devices_outside_temperature: filter[str] = filter(
        lambda deviceIndex: is_outside_temperature_tile(tiles[deviceIndex]), tiles
    )

    # Create sensor objects for devices with outside temperature
    return (
        ZoneOutsideTempTile(tiles[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices_outside_temperature
    )


def is_outside_temperature_tile(device: dict[str, Any]) -> bool:
    """Check if the device is a temperature sensor.

    Args:
    device (dict): The device information.

    Returns:
    bool: True if the device is a temperature sensor, False otherwise.

    """
    return device[CONF_PARAMS][CONF_DESCRIPTION] == "Temperature sensor"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    _LOGGER.debug(
        "Setting up sensor entry, controller udid: %s",
        config_entry.data[CONTROLLER][UDID],
    )
    coordinator: TechCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid: str = config_entry.data[CONTROLLER][UDID]

    zones: dict[str, Any] = await coordinator.api.get_module_zones(controller_udid)
    tiles: dict[str, Any] = await coordinator.api.get_module_tiles(controller_udid)

    entities: list[TileSensor] = []
    for t in tiles:
        tile = tiles[t]
        if tile[VISIBILITY] is False:
            continue
        if int(tile[CONF_TYPE]) == TYPE_TEMPERATURE:
            entities.append(TileTemperatureSensor(tile, coordinator, controller_udid))
        if int(tile[CONF_TYPE]) == TYPE_TEMPERATURE_CH:
            entities.append(TileWidgetSensor(tile, coordinator, controller_udid))
        if int(tile[CONF_TYPE]) == TYPE_FAN:
            entities.append(TileFanSensor(tile, coordinator, controller_udid))
        if int(tile[CONF_TYPE]) == TYPE_VALVE:
            entities.append(TileValveSensor(tile, coordinator, controller_udid))
            # TODO: this class _init_ definition needs to be fixed. See comment below.
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_RETURN_TEMPERATURE))
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_SET_TEMPERATURE))
            # entities.append(TileValveTemperatureSensor(tile, api, controller_udid, VALVE_SENSOR_CURRENT_TEMPERATURE))
        if int(tile[CONF_TYPE]) == TYPE_MIXING_VALVE:
            entities.append(TileMixingValveSensor(tile, coordinator, controller_udid))
        if int(tile[CONF_TYPE]) == TYPE_FUEL_SUPPLY:
            entities.append(TileFuelSupplySensor(tile, coordinator, controller_udid))
        if int(tile[CONF_TYPE]) == TYPE_TEXT:
            entities.append(TileTextSensor(tile, coordinator, controller_udid))
    _LOGGER.debug("Setting up sensor entities: %s", entities)
    async_add_entities(entities, True)

    # async_add_entities(
    #     [
    #         ZoneTemperatureSensor(zones[zone], coordinator, controller_udid, model)
    #         for zone in zones
    #     ],
    #     True,
    # )

    battery_devices: Generator[ZoneBatterySensor, None, None] = map_to_battery_sensors(
        zones, coordinator, config_entry
    )
    temperature_sensors: Generator[
        ZoneTemperatureSensor, None, None
    ] = map_to_temperature_sensors(zones, coordinator, config_entry)
    humidity_sensors: Generator[
        ZoneHumiditySensor, None, None
    ] = map_to_humidity_sensors(zones, coordinator, config_entry)
    # tile_sensors = map_to_tile_sensors(tiles, api, config_entry)

    async_add_entities(
        itertools.chain(
            battery_devices,
            temperature_sensors,
            humidity_sensors,  # , tile_sensors
        ),
        True,
    )
