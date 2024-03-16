"""Support for Tech HVAC system."""
import logging
from typing import TYPE_CHECKING, Any

from homeassistant import core
from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
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
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator
from .const import CONTROLLER, DOMAIN, MANUFACTURER, UDID, VER

_LOGGER = logging.getLogger(__name__)

SUPPORT_HVAC = [HVACMode.HEAT, HVACMode.OFF]

if TYPE_CHECKING:
    from functools import cached_property
else:
    from homeassistant.backports.functools import cached_property


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    udid: str = config_entry.data[CONTROLLER][UDID]
    coordinator: TechCoordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up climate entry, controller udid: %s", udid)
    model: str = (
        config_entry.data[CONTROLLER][CONF_NAME]
        + ": "
        + config_entry.data[CONTROLLER][VER]
    )
    zones: dict[str, Any] = await coordinator.api.get_module_zones(udid)
    thermostats: list[TechThermostat] = [
        TechThermostat(zones[zone], coordinator, udid, model) for zone in zones
    ]

    async_add_entities(thermostats, True)


class TechThermostat(CoordinatorEntity[TechCoordinator], ClimateEntity):
    """Representation of a Tech climate."""

    def __init__(
        self,
        device: dict[str, Any],
        coordinator: TechCoordinator,
        udid: str,
        model: str,
    ) -> None:
        """Initialize the Tech device."""
        super().__init__(coordinator)
        self._udid: str = udid
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ZONE][CONF_ID]
        self._unique_id: str = udid + "_" + str(device[CONF_ZONE][CONF_ID])
        self.device_name: str = device[CONF_DESCRIPTION][CONF_NAME]
        self.manufacturer: str = MANUFACTURER
        self.model: str = model
        self._temperature: float | None = None
        self._humidity: int | None = None
        self.update_properties(device)
        # Remove the line below after HA 2025.1
        self._enable_turn_on_off_backwards_compatibility = False

    @cached_property
    def device_info(self) -> DeviceInfo:
        """Return device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self.device_name)
            },  # Unique identifiers for the device
            CONF_NAME: self.device_name,  # Name of the device
            CONF_MODEL: self.model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }

    def update_properties(self, device: dict[str, Any]) -> None:
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
        state: str = device[CONF_ZONE]["flags"]["relayState"]
        hvac_mode: str = device[CONF_ZONE]["flags"]["algorithm"]
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
        mode: str = device[CONF_ZONE]["zoneState"]
        if mode in ("zoneOn", "noAlarm"):
            self._mode = HVACMode.HEAT
        else:
            self._mode = HVACMode.OFF

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @cached_property
    def name(self) -> str:
        """Return the name of the device."""
        return self._name

    @cached_property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @cached_property
    def hvac_mode(self) -> HVACMode | None:
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return self._mode

    @cached_property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return SUPPORT_HVAC

    @cached_property
    def hvac_action(self) -> HVACAction:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        return self._state

    @cached_property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @cached_property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._temperature

    @cached_property
    def current_humidity(self) -> int | None:
        """Return current humidity."""
        return self._humidity

    @cached_property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temperature

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set new target temperatures."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            _LOGGER.debug("%s: Setting temperature to %s", self._name, temperature)
            self._temperature = temperature
            await self._coordinator.api.set_const_temp(
                self._udid, self._id, temperature
            )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set new target hvac mode."""
        _LOGGER.debug("%s: Setting hvac mode to %s", self._name, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._coordinator.api.set_zone(self._udid, self._id, False)
        elif hvac_mode == HVACMode.HEAT:
            await self._coordinator.api.set_zone(self._udid, self._id, True)
