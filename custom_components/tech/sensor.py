"""Support for Tech HVAC system."""
import itertools
import logging
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import TEMP_CELSIUS, PERCENTAGE
from homeassistant.core import HomeAssistant
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities
) -> None:
    """Set up entry."""
    _LOGGER.debug("Setting up sensor entry, module udid: %s", config_entry.data["udid"])
    api = hass.data[DOMAIN][config_entry.entry_id]
    zones = await api.get_module_zones(config_entry.data["udid"])

    battery_devices = map_to_battery_sensors(zones, api, config_entry)
    temperature_sensors = map_to_temperature_sensors(zones, api, config_entry)
    humidity_sensors = map_to_humidity_sensors(zones, api, config_entry)


    async_add_entities(
        itertools.chain(battery_devices, temperature_sensors,humidity_sensors),
        True,
    )

def map_to_battery_sensors(zones, api, config_entry):
    devices = filter(lambda deviceIndex: is_battery_operating_device(zones[deviceIndex]), zones)
    return map(lambda deviceIndex: TechBatterySensor(zones[deviceIndex], api, config_entry), devices)

def is_battery_operating_device(device) -> bool:
    return device['zone']['batteryLevel'] is not None

def map_to_temperature_sensors(zones, api, config_entry):
    devices = filter(lambda deviceIndex: is_humidity_operating_device(zones[deviceIndex]), zones)
    return map(lambda deviceIndex: TechTemperatureSensor(zones[deviceIndex], api, config_entry), zones)

def map_to_humidity_sensors(zones, api, config_entry):
    devices = filter(lambda deviceIndex: is_humidity_operating_device(zones[deviceIndex]), zones)
    return map(lambda deviceIndex: TechHumiditySensor(zones[deviceIndex], api, config_entry), devices)

def is_humidity_operating_device(device) -> bool:
    return device['zone']['humidity'] != 0

class TechBatterySensor(SensorEntity):
    """Representation of a Tech battery sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, api, config_entry):
        """Initialize the Tech battery sensor."""
        _LOGGER.debug("Init TechBatterySensor... ")
        self._config_entry = config_entry
        self._api = api
        self._id = device["zone"]["id"]
        self.update_properties(device)

    def update_properties(self, device):
        self._name = device["description"]["name"]
        self._attr_native_value = device["zone"]["batteryLevel"]

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return "climate_{}_battery".format(self._id)

    @property
    def name(self):
        """Return the name of the device."""
        return "{} battery".format(self._name)

    async def async_update(self):
        """Call by the Tech device callback to update state."""
        _LOGGER.debug(
            "Updating Tech battery sensor: %s, udid: %s, id: %s",
            self._name,
            self._config_entry.data["udid"],
            self._id,
        )
        device = await self._api.get_zone(self._config_entry.data["udid"], self._id)
        self.update_properties(device)

class TechTemperatureSensor(SensorEntity):
    """Representation of a Tech temperature sensor."""

    _attr_native_unit_of_measurement = TEMP_CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, api, config_entry):
        """Initialize the Tech temperature sensor."""
        _LOGGER.debug("Init TechTemperatureSensor... ")
        self._config_entry = config_entry
        self._api = api
        self._id = device["zone"]["id"]
        self.update_properties(device)

    def update_properties(self, device):
        self._name = device["description"]["name"]
        if device["zone"]["currentTemperature"] is not None:
            self._attr_native_value =  device["zone"]["currentTemperature"] / 10
        else:
            self._attr_native_value = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return "climate_{}_temperature".format(self._id)

    @property
    def name(self):
        """Return the name of the device."""
        return "{} temperature".format(self._name)

    async def async_update(self):
        """Call by the Tech device callback to update state."""
        _LOGGER.debug(
            "Updating Tech temp. sensor: %s, udid: %s, id: %s",
            self._name,
            self._config_entry.data["udid"],
            self._id,
        )
        device = await self._api.get_zone(self._config_entry.data["udid"], self._id)
        self.update_properties(device)

class TechHumiditySensor(SensorEntity):
    """Representation of a Tech humidity sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, api, config_entry):
        """Initialize the Tech humidity sensor."""
        _LOGGER.debug("Init TechHumiditySensor... ")
        self._config_entry = config_entry
        self._api = api
        self._id = device["zone"]["id"]
        self.update_properties(device)

    def update_properties(self, device):
        self._name = device["description"]["name"]
        if device["zone"]["humidity"] != 0:
            self._attr_native_value =  device["zone"]["humidity"]
        else:
            self._attr_native_value = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return "climate_{}_humidity".format(self._id)

    @property
    def name(self):
        """Return the name of the device."""
        return "{} humidity".format(self._name)

    async def async_update(self):
        """Call by the Tech device callback to update state."""
        _LOGGER.debug(
            "Updating Tech hum. sensor: %s, udid: %s, id: %s",
            self._name,
            self._config_entry.data["udid"],
            self._id,
        )
        device = await self._api.get_zone(self._config_entry.data["udid"], self._id)
        self.update_properties(device)