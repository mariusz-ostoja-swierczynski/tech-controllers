"""Platform for binary sensor integration."""
import logging
from homeassistant.components import binary_sensor
from homeassistant.const import STATE_OFF, STATE_ON
from . import assets
from .entity import TileEntity
from .const import (
    DOMAIN,
    TYPE_FIRE_SENSOR,
    TYPE_RELAY,
    TYPE_ADDITIONAL_PUMP,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    _LOGGER.debug("Setting up entry for sensors...")
    api = hass.data[DOMAIN][config_entry.entry_id]
    controllers = config_entry.data["controllers"]
    
    entities = []
    for controller in controllers:
        controller_udid = controller["udid"]
        _LOGGER.debug("Controller UDID: %s", controller_udid)
        data = await api.module_data(controller_udid)
        tiles = data['tiles']
        for t in tiles:
            tile = tiles[t]
            if tile["visibility"] == False:
                continue
            if tile["type"] == TYPE_RELAY:
                entities.append(RelaySensor(tile, api, controller_udid))
            if tile["type"] == TYPE_FIRE_SENSOR:
                entities.append(RelaySensor(tile, api, controller_udid, binary_sensor.DEVICE_CLASS_MOTION))
            if tile["type"] == TYPE_ADDITIONAL_PUMP:
                entities.append(RelaySensor(tile, api, controller_udid))
    
    async_add_entities(entities)


class TileBinarySensor(TileEntity, binary_sensor.BinarySensorEntity):
    """Representation of a TileBinarySensor."""

    def __init__(self, device, api, controller_udid):
        """Initialize the tile binary sensor."""
        super().__init__(device, api, controller_udid)

    @property
    def state(self):
        return STATE_ON if self._state else STATE_OFF


class RelaySensor(TileBinarySensor):
    def __init__(self, device, api, controller_udid, device_class=None):
        TileBinarySensor.__init__(self, device, api, controller_udid)
        self._attr_device_class = device_class
        icon_id = device["params"].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)
        else:
            self._attr_icon = assets.get_icon_by_type(device["type"])

    def get_state(self, device):
        return device["params"]["workingStatus"]
