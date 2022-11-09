"""Platform for sensor integration."""
import logging
from homeassistant.components import sensor
from homeassistant.const import TEMP_CELSIUS, PERCENTAGE
from homeassistant.helpers.entity import Entity
from . import assets
from .entity import TileEntity
from .const import (
    DOMAIN,
    TYPE_TEMPERATURE,
    TYPE_TEMPERATURE_CH,
    TYPE_FAN,
    TYPE_VALVE,
    TYPE_FUEL_SUPPLY,
    TYPE_TEXT,
    VALVE_SENSOR_RETURN_TEMPERATURE,
    VALVE_SENSOR_SET_TEMPERATURE,
    VALVE_SENSOR_CURRENT_TEMPERATURE,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    _LOGGER.debug("Setting up entry for sensors, module udid: " + config_entry.data["udid"])
    api = hass.data[DOMAIN][config_entry.entry_id]
    tiles = await api.get_tiles(config_entry.data["udid"])

    entities = []
    for t in tiles:
        tile = tiles[t]
        if tile["visibility"] == False:
            continue
        if tile["type"] == TYPE_TEMPERATURE:
            entities.append(TileTemperatureSensor(tile, api, config_entry))
        if tile["type"] == TYPE_TEMPERATURE_CH:
            entities.append(TileWidgetSensor(tile, api, config_entry))
        if tile["type"] == TYPE_FAN:
            entities.append(TileFanSensor(tile, api, config_entry))
        if tile["type"] == TYPE_VALVE:
            entities.append(TileValveSensor(tile, api, config_entry))
            entities.append(TileValveTemperatureSensor(tile, api, config_entry, VALVE_SENSOR_RETURN_TEMPERATURE))
            entities.append(TileValveTemperatureSensor(tile, api, config_entry, VALVE_SENSOR_SET_TEMPERATURE))
            entities.append(TileValveTemperatureSensor(tile, api, config_entry, VALVE_SENSOR_CURRENT_TEMPERATURE))
        if tile["type"] == TYPE_FUEL_SUPPLY:
            entities.append(TileFuelSupplySensor(tile, api, config_entry))
        if tile["type"] == TYPE_TEXT:
            entities.append(TileTextSensor(tile, api, config_entry))
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


class TileSensor(TileEntity, Entity):
    """Representation of a TileSensor."""

    def __init__(self, device, api, config_entry):
        """Initialize the tile sensor."""
        super().__init__(device, api, config_entry)


class TileTemperatureSensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)

    @property
    def device_class(self):
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        return TEMP_CELSIUS

    def get_state(self, device):
        return device["params"]["value"] / 10


class TileFuelSupplySensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)

    @property
    def device_class(self):
        return sensor.DEVICE_CLASS_BATTERY

    @property
    def unit_of_measurement(self):
        return PERCENTAGE

    def get_state(self, device):
        return device["params"]["percentage"]


class TileFanSensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._attr_icon = assets.get_icon_by_type(device["type"])

    @property
    def unit_of_measurement(self):
        return PERCENTAGE

    def get_state(self, device):
        return device["params"]["gear"]


class TileTextSensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._name = assets.get_text(device["params"]["headerId"])
        self._attr_icon = assets.get_icon(device["params"]["iconId"])

    def get_state(self, device):
        return assets.get_text(device["params"]["statusId"])


class TileWidgetSensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._name = assets.get_text(device["params"]["widget2"]["txtId"])

    @property
    def device_class(self):
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        return TEMP_CELSIUS

    def get_state(self, device):
        return device["params"]["widget2"]["value"] / 10


class TileValveSensor(TileSensor):
    def __init__(self, device, api, config_entry):
        TileSensor.__init__(self, device, api, config_entry)
        self._attr_icon = assets.get_icon_by_type(device["type"])
        name = assets.get_text_by_type(device["type"])
        self._name = f"{name} {device['params']['valveNumber']}"

    @property
    def unit_of_measurement(self):
        return PERCENTAGE

    def get_state(self, device):
        return device["params"]["openingPercentage"]


class TileValveTemperatureSensor(TileSensor):
    def __init__(self, device, api, config_entry, valve_sensor):
        self._state_key = valve_sensor["state_key"]
        sensor_name = assets.get_text(valve_sensor["txt_id"])
        TileSensor.__init__(self, device, api, config_entry)
        self._id = f"{self._id}_{self._state_key}"
        name = assets.get_text_by_type(device["type"])
        self._name = f"{name} {device['params']['valveNumber']} {sensor_name}"

    @property
    def device_class(self):
        return sensor.DEVICE_CLASS_TEMPERATURE

    @property
    def unit_of_measurement(self):
        return TEMP_CELSIUS

    def get_state(self, device):
        state = device["params"][self._state_key]
        if state > 100:
            state = state / 10
        return state
