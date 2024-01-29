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
    ATTR_CURRENT_HUMIDITY
)
from homeassistant.const import ATTR_TEMPERATURE, TEMP_CELSIUS
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVAC_MODE_HEAT, HVAC_MODE_OFF]

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    udid = config_entry.data["module"]["udid"]
    _LOGGER.debug("Setting up entry, module udid: " + udid)
    api = hass.data[DOMAIN][config_entry.entry_id]
    zones = await api.get_module_zones(udid)
    thermostats = [
                TechThermostat(
                    zones[zone],
                    api,
                    udid
                ) 
                for zone in zones
            ]
    
    async_add_entities(thermostats, True)


class TechThermostat(ClimateEntity):
    """Representation of a Tech climate."""

    def __init__(self, device, api, udid):
        """Initialize the Tech device."""
        _LOGGER.debug("Init TechThermostat...")
        self._udid = udid
        self._api = api
        self._id = device["zone"]["id"]
        self._unique_id = udid + "_" + str(device["zone"]["id"])
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
            self._humidity = device["zone"]["humidity"]
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
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id
    
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
        _LOGGER.debug("Updating Tech zone: %s, udid: %s, id: %s", self._name, self._udid, self._id)
        device = await self._api.get_zone(self._udid, self._id)
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
    def current_humidity(self):
        """Return current humidity."""
        return self._humidity

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temperature

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            _LOGGER.debug("%s: Setting temperature to %s", self._name, temperature)
            self._temperature = temperature
            await self._api.set_const_temp(self._udid, self._id, temperature)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self._name, hvac_mode)
        if hvac_mode == HVAC_MODE_OFF:
            await self._api.set_zone(self._udid, self._id, False)
        elif hvac_mode == HVAC_MODE_HEAT:
            await self._api.set_zone(self._udid, self._id, True)

