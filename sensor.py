"""Platform for sensor integration."""
from dataclasses import dataclass
from typing import Any, Callable, Optional, Union
import logging
import json
from typing import List, Optional
from homeassistant.const import (
    TEMP_CELSIUS,
    SIGNAL_STRENGTH_DECIBELS,
    PERCENTAGE
)
from homeassistant.helpers.entity import Entity
from .const import DOMAIN
from homeassistant.components import sensor

_LOGGER = logging.getLogger(__name__)

@dataclass
class BlockAttributeDescription:
    """Class to describe a sensor."""

    name: str
    # Callable = lambda attr_info: unit
    icon: Optional[str] = None
    unit: Union[None, str, Callable[[dict], str]] = None
    value: Callable[[Any], Any] = lambda val: val
    device_class: Optional[str] = None
    default_enabled: bool = True
    available: Optional[bool] = None

SENSORS = {
    ("device", "deviceTemp"): BlockAttributeDescription(
        name="Device Temperature",
        unit=TEMP_CELSIUS,
        value=lambda value: round(value, 1),
        device_class=sensor.DEVICE_CLASS_TEMPERATURE,
        default_enabled=False,
    )
}

def setup_platform(hass, config, add_entities, discovery_info=None):
    """Set up the sensor platform."""
    # add_entities([RemoteSensor()])

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    _LOGGER.debug("Setting up entry for sensors, module udid: " + config_entry.data["udid"])
    api = hass.data[DOMAIN][config_entry.entry_id]
    tiles = await api.get_tiles(config_entry.data["udid"])

    _LOGGER.debug("Tiles %s", tiles)
    [
        _LOGGER.debug("Tile.id %s", tiles[tile])
        for tile in tiles
    ]

    entities = []
    for tile in tiles:
        if tiles[tile]["type"] == 1: #Temperature sensor
            entities.append(TileTemperatureSensor(tiles[tile], api, config_entry))
            entities.append(TileBatteryLevelSensor(tiles[tile], api, config_entry))
            entities.append(TileSignalStrengthSensor(tiles[tile], api, config_entry))
            entities.append(TileSensor(tiles[tile], api, config_entry))
        if tiles[tile]["type"] == 11: #Relay
            entities.append(TileSensor(tiles[tile], api, config_entry))
        if tiles[tile]["type"] == 23: #Built in valve
            entities.append(TileSensorValve(tiles[tile], api, config_entry))
            entities.append(TileSensorValveTemp(tiles[tile], api, config_entry))
            entities.append(TileSensorValveReturnTemp(tiles[tile], api, config_entry))
    async_add_entities(entities)

    zones = await api.get_zones(config_entry.data["udid"])        
    async_add_entities(
        [
            ZoneTemperatureSensor(
                zones[zone],
                api,
                config_entry,
            )
            for zone in zones
        ],
        True,
    )


class ZoneSensor(Entity):
    """Representation of a Sensor."""

    def __init__(self, device, api, config_entry):
        """Initialize the sensor."""
        _LOGGER.debug("Init ZoneSensor...")
        self._config_entry = config_entry
        self._api = api
        _LOGGER.debug('device["zone"]["id"] = %s', device["zone"]["id"])
        self._id = device["zone"]["id"]
        self._name = device["description"]["name"]
        self._target_temperature = device["zone"]["setTemperature"] / 10
        self._temperature = device["zone"]["currentTemperature"] / 10
        

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (self._config_entry.data["udid"], self.unique_id)
            },
            "name": self.name,
            "manufacturer": "Tech",
            "model": self._config_entry.data["type"],
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._temperature

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    async def async_update(self):
        device = await self._api.get_zone(self._config_entry.data["udid"], self._id)
        self._temperature = device["zone"]["setTemperature"] / 10


class ZoneTemperatureSensor(ZoneSensor):
    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name + " Temperature"

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._temperature



class TileSensor(Entity):
    """Representation of a TileSensor."""

    def __init__(self, device, api, config_entry):
        """Initialize the tile sensor."""
        _LOGGER.debug("Init TileSensor...")
        self._config_entry = config_entry
        self._api = api
        _LOGGER.debug('Sensor device["id"] = %s', device)
        self._id = device["id"]
        self._name = device["params"]["description"]
        self._workingStatus = device["params"]["workingStatus"]
        
    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (self._config_entry.data["udid"], self._id)
            },
            "name": self._name,
            "manufacturer": "Tech",
            "model": self._config_entry.data["type"],
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._workingStatus

    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._workingStatus = device["params"]["workingStatus"]

class TileSensorValve(Entity):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._openingPercentage = device["params"]["openingPercentage"]

    @property 
    def name(self):
        return self._name + " Built-in Valve"

    @property
    def state(self):
        return self._openingPercentage 
    
    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 1

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_POWER_FACTOR

    @property
    def unit_of_measurement(self):
        return PERCENTAGE
    
    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._openingPercentage = device["params"]["openingPercentage"]

class TileSensorValveTemp(Entity):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._temperature = device["params"]["currentTemp"] / 10    

    @property 
    def name(self):
        return self._name + " Valve temperature"

    @property
    def state(self):
        return self._temperature 

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 2

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS
    
    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._temperature = device["params"]["currentTemp"] / 10


class TileSensorValveReturnTemp(Entity):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._temperature = device["params"]["returnTemp"] / 10    

    @property 
    def name(self):
        return self._name + " Valve return temperature"

    @property
    def state(self):
        return self._temperature 

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 3

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS
    
    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._temperature = device["params"]["returnTemp"] / 10

class TileTemperatureSensor(TileSensor):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._temperature = device["params"]["value"] / 10    

    @property 
    def name(self):
        return self._name

    @property
    def state(self):
        return self._temperature 

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 4

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS
    
    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._temperature = device["params"]["value"] / 10

class TileBatteryLevelSensor(TileSensor):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._batteryLevel = device["params"]["batteryLevel"]

    @property 
    def name(self):
        return self._name + " Battery Level"

    @property
    def state(self):
        return self._batteryLevel 
    
    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 5

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_BATTERY

    @property
    def unit_of_measurement(self):
        return PERCENTAGE
    
    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._batteryLevel = device["params"]["batteryLevel"]

class TileSignalStrengthSensor(TileSensor):

    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._signalStrength = device["params"]["signalStrength"]

    @property 
    def name(self):
        return self._name + " Signal strenght"

    @property
    def state(self):
        return self._signalStrength 

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id * 10 + 6

    @property
    def device_class(self):
        """Return the device class of the sensor."""
        return sensor.DEVICE_CLASS_SIGNAL_STRENGTH        

    @property
    def unit_of_measurement(self):
        return SIGNAL_STRENGTH_DECIBELS

    async def async_update(self):
        device = await self._api.get_tile(self._config_entry.data["udid"], self._id)
        self._signalStrength = device["params"]["signalStrength"]