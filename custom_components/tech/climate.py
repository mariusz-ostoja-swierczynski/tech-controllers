"""Support for Tech HVAC system."""
import logging
from typing import Any, Optional

from custom_components.tech import TechCoordinator
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_TEMPERATURE,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_MODEL,
    CONF_NAME,
    CONF_ZONE,
    STATE_OFF,
    STATE_ON,
    UnitOfTemperature,
)
from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROLLER, DOMAIN, MANUFACTURER, UDID, VER

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVACMode.HEAT, HVACMode.OFF]


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up entry."""
    udid = config_entry.data[CONTROLLER][UDID]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up entry, controller udid: %s", udid)
    model = (
        config_entry.data[CONTROLLER][CONF_NAME]
        + ": "
        + config_entry.data[CONTROLLER][VER]
    )
    zones = await coordinator.api.get_module_zones(udid)
    thermostats = [
        TechThermostat(zones[zone], coordinator, udid, model) for zone in zones
    ]

    async_add_entities(thermostats, True)


class TechThermostat(ClimateEntity, CoordinatorEntity):
    """Representation of a Tech climate."""

    def __init__(self, device, coordinator: TechCoordinator, udid, model):
        """Initialize the Tech device."""
        _LOGGER.debug("Init TechThermostat...")
        super().__init__(coordinator)
        self._udid = udid
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = udid + "_" + str(device[CONF_ZONE][CONF_ID])
        self.device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self.manufacturer = MANUFACTURER
        self.model = model
        self._temperature = None
        self.update_properties(device)
        # Remove the line below after HA 2025.1
        self._enable_turn_on_off_backwards_compatibility = False

    @property
    def device_info(self):
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self.device_name)
            },  # Unique identifiers for the device
            CONF_NAME: self.device_name,  # Name of the device
            CONF_MODEL: self.model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }

    def update_properties(self, device):
        """Update the properties of the HVAC device based on the data from the device.

        Args:
        self (object): instance of the class
        device (dict): The device data containing information about the device's properties.

        Returns:
        None

        """
        # Update device name
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update target temperature
        if device[CONF_ZONE]["setTemperature"] is not None:
            self._target_temperature = device[CONF_ZONE]["setTemperature"] / 10
        else:
            self._target_temperature = None

        # Update current temperature
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._temperature = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._temperature = None

        # Update humidity
        if device[CONF_ZONE]["humidity"] is not None and device[CONF_ZONE]["humidity"] >= 0:
            self._humidity = device[CONF_ZONE]["humidity"]
        else:
            self._humidity = None

        # Update HVAC state
        state = device[CONF_ZONE]["flags"]["relayState"]
        hvac_mode = device[CONF_ZONE]["flags"]["algorithm"]
        if state == STATE_ON:
            if hvac_mode == "heating":
                self._state = HVACAction.HEATING
            elif hvac_mode == "cooling":
                self._state = HVACAction.COOLING
        elif state == STATE_OFF:
            self._state = HVACAction.IDLE
        else:
            self._state = HVACAction.OFF

        # Update HVAC mode
        mode = device[CONF_ZONE]["zoneState"]
        if mode in ("zoneOn", "noAlarm"):
            self._mode = HVACMode.HEAT
        else:
            self._mode = HVACMode.OFF

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

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
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

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

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

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
            await self._coordinator.api.set_const_temp(
                self._udid, self._id, temperature
            )

    async def async_set_hvac_mode(self, hvac_mode):
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self._name, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._coordinator.api.set_zone(self._udid, self._id, False)
        elif hvac_mode == HVACMode.HEAT:
            await self._coordinator.api.set_zone(self._udid, self._id, True)
