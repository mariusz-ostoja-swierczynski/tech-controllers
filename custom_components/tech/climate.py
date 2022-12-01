"""Support for Tech HVAC system."""
import logging
import json
from typing import List, Optional
from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    HVAC_MODE_HEAT,
    HVAC_MODE_COOL,
    HVAC_MODE_HEAT_COOL,
    HVAC_MODE_OFF,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_COOL,
    CURRENT_HVAC_IDLE,
    CURRENT_HVAC_OFF,
    SUPPORT_PRESET_MODE,
    SUPPORT_TARGET_TEMPERATURE,
)
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from . import assets
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVAC_MODE_HEAT, HVAC_MODE_OFF]

async def async_setup_entry(hass, config_entity, async_add_entities):
    """Set up entry."""
    _LOGGER.debug("Setting up entry...")
    api = hass.data[DOMAIN][config_entity.entry_id]
    _LOGGER.debug(config_entity)
    controllers = config_entity.data["controllers"]
    _LOGGER.debug("Number of controllers: %s", len(controllers))
    
    entities = []
    for controller in controllers:
        controller_udid = controller["udid"]
        _LOGGER.debug("Controller UDID: %s", controller_udid)
        data = await api.module_data(controller_udid)
        zones = data['zones']
        for zone in zones:
            entities.append(
                TechThermostat(
                    zones[zone],
                    api,
                    controller_udid
                )
            )
    _LOGGER.debug("Number of entities: %s", len(entities))
    async_add_entities(entities)


class TechThermostat(ClimateEntity):
    """Representation of a Tech climate."""

    def __init__(self, device, api, controller_udid):
        """Initialize the Tech device."""
        _LOGGER.debug("Init TechThermostat...")
        self._controller_udid = controller_udid
        self._api = api
        self._id = device["zone"]["id"]
        self._model = assets.get_text(642)
        self.update_properties(device)

    def update_properties(self, device):
        self._name = device["description"]["name"]
        if device["zone"]["setTemperature"] is not None:
            self._target_temperature = device["zone"]["setTemperature"] / 10
        else:
            self._target_temperature = None
        if device["zone"]["currentTemperature"] is not None:
            self._temperature =  device["zone"]["currentTemperature"] / 10
        else:
            self._temperature = None
        if device["zone"]["humidity"] is not None:
            self._humidity =  device["zone"]["humidity"]
            _LOGGER.debug("Tech Thermostat found humidity: %d",self._humidity)
        else:
            self._humidity = None
        state = device["zone"]["flags"]["relayState"]
        if state == "on":
            self._state = CURRENT_HVAC_HEAT
        elif state == "off":
            self._state = CURRENT_HVAC_IDLE
        else:
            self._state = CURRENT_HVAC_OFF
        mode = device["zone"]["zoneState"]
        if mode == "zoneOn" or mode == "noAlarm":
            self._mode = HVAC_MODE_HEAT
        else:
            self._mode = HVAC_MODE_OFF

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Tech",
            "model": self._model,
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id
    
    @property
    def name(self):
        """Return the name of the device."""
        return self._name

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return SUPPORT_TARGET_TEMPERATURE #| SUPPORT_PRESET_MODE

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return self._mode

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return SUPPORT_HVAC

    @property
    def hvac_action(self) -> Optional[str]:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        return self._state

    async def async_update(self):
        """Call by the Tech device callback to update state."""
        _LOGGER.debug("Updating Tech zone: %s, udid: %s, id: %s", self._name, self._controller_udid, self._id)
        device = await self._api.get_zone(self._controller_udid, self._id)
        self.update_properties(device)

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return TEMP_CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._temperature

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def current_humidity(self):
        """Return the current humidity."""
        return self._humidity

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            _LOGGER.debug("%s: Setting temperature to %s", self._name, temperature)
            self._temperature = temperature
            await self._api.set_const_temp(self._controller_udid, self._id, temperature)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self._name, hvac_mode)
        if hvac_mode == HVAC_MODE_OFF:
            await self._api.set_zone(self._controller_udid, self._id, False)
        elif hvac_mode == HVAC_MODE_HEAT:
            await self._api.set_zone(self._controller_udid, self._id, True)

