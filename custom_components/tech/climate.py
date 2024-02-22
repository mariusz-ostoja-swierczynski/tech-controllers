"""Support for Tech HVAC system."""
import logging
import json
from typing import List, Optional
from homeassistant.components.climate import ClimateEntity

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)

from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVACMode.HEAT, HVACMode.OFF]

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    _LOGGER.debug("Setting up entry, module udid: " + config_entry.data["udid"])
    api = hass.data[DOMAIN][config_entry.entry_id]
    zones = await api.get_module_zones(config_entry.data["udid"])

    async_add_entities(
        [
            TechThermostat(
                zones[zone],
                api,
                config_entry,
            )
            for zone in zones
        ],
        True,
    )


class TechThermostat(ClimateEntity):
    """Representation of a Tech climate."""

    def __init__(self, device, api, config_entry):
        """Initialize the Tech device."""
        _LOGGER.debug("Init TechThermostat...")
        self._config_entry = config_entry
        self._api = api
        self._id = device["zone"]["id"]
        self.update_properties(device)
        # Remove the line below after HA 2025.1
        self._enable_turn_on_off_backwards_compatibility = False

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
        state = device["zone"]["flags"]["relayState"]
        if state == "on":
            self._state = HVACAction.HEATING
        elif state == "off":
            self._state = HVACAction.IDLE
        else:
            self._state = HVACAction.OFF
        mode = device["zone"]["zoneState"]
        if mode == "zoneOn" or mode == "noAlarm":
            self._mode = HVACMode.HEAT
        else:
            self._mode = HVACMode.OFF

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
        return ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON | ClimateEntityFeature.TURN_OFF

    @property
    def hvac_mode(self):
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVACMode.*.
        """
        return self._mode

    @property
    def hvac_modes(self):
        """Return the list of available hvac operation modes.

        Need to be a subset of HVACModes.
        """
        return SUPPORT_HVAC

    @property
    def hvac_action(self) -> Optional[str]:
        """Return the current running hvac operation if supported.

        Need to be one of HVACAction.*.
        """
        return self._state

    async def async_update(self):
        """Call by the Tech device callback to update state."""
        _LOGGER.debug("Updating Tech zone: %s, udid: %s, id: %s", self._name, self._config_entry.data["udid"], self._id)
        device = await self._api.get_zone(self._config_entry.data["udid"], self._id)
        self.update_properties(device)

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def current_temperature(self):
        """Return the current temperature."""
        return self._temperature

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
            await self._api.set_const_temp(self._config_entry.data["udid"], self._id, temperature)

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self._name, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._api.set_zone(self._config_entry.data["udid"], self._id, False)
        elif hvac_mode == HVACMode.HEAT:
            await self._api.set_zone(self._config_entry.data["udid"], self._id, True)
