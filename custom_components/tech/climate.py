"""Climate platform for the Tech Controllers integration."""

import logging
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROLLER, DOMAIN, INCLUDE_HUB_IN_NAME, MANUFACTURER, UDID, VER
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_TEMP = 5
DEFAULT_MAX_TEMP = 35
SUPPORT_HVAC = [HVACMode.HEAT, HVACMode.OFF]


def _format_schedule_time(value: Any) -> str | None:
    if not isinstance(value, int) or value < 0 or value >= 1440:
        return None
    hours, minutes = divmod(value, 60)
    return f"{hours:02d}:{minutes:02d}"


def _serialize_schedule_period(
    schedule: dict[str, Any], prefix: str
) -> dict[str, Any] | None:
    result: dict[str, Any] = {}
    days = schedule.get(f"{prefix}Days")
    if isinstance(days, list):
        result["days"] = [
            index for index, enabled in enumerate(days) if str(enabled) == "1"
        ]

    setback_temp = schedule.get(f"{prefix}SetbackTemp")
    if isinstance(setback_temp, (int, float)):
        result["setback_temperature"] = setback_temp / 10

    intervals = []
    for interval in schedule.get(f"{prefix}Intervals", []):
        if not isinstance(interval, dict):
            continue
        start = _format_schedule_time(interval.get("start"))
        stop = _format_schedule_time(interval.get("stop"))
        temp = interval.get("temp")
        if start is None and stop is None and not isinstance(temp, (int, float)):
            continue
        serialized_interval: dict[str, Any] = {}
        if start is not None:
            serialized_interval["start"] = start
        if stop is not None:
            serialized_interval["stop"] = stop
        if isinstance(temp, (int, float)):
            serialized_interval["temperature"] = temp / 10
        if serialized_interval:
            intervals.append(serialized_interval)

    if intervals:
        result["intervals"] = intervals

    return result or None


def _serialize_schedule(schedule: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(schedule, dict):
        return None

    result: dict[str, Any] = {}
    if schedule.get("index") is not None:
        result["index"] = schedule["index"]
    if schedule.get("name") is not None:
        result["name"] = schedule["name"]

    period_0 = _serialize_schedule_period(schedule, "p0")
    period_1 = _serialize_schedule_period(schedule, "p1")
    if period_0 is not None:
        result["period_0"] = period_0
    if period_1 is not None:
        result["period_1"] = period_1

    return result or None


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech climate entities for the provided config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller data.
        async_add_entities: Callback to register entities with Home Assistant.

    """
    udid = config_entry.data[CONTROLLER][UDID]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    _LOGGER.debug("Setting up entry, controller udid: %s", udid)
    zones = await coordinator.api.get_module_zones(udid)
    thermostats = [
        TechThermostat(zones[zone], coordinator, config_entry) for zone in zones
    ]

    async_add_entities(thermostats, True)


class TechThermostat(ClimateEntity, CoordinatorEntity):
    """Representation of a Tech climate."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self, device, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialise a thermostat entity backed by a Tech zone payload.

        Args:
            device: Zone description returned by the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.

        """
        _LOGGER.debug("Init TechThermostat…")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = f"{self._udid}_{device[CONF_ZONE][CONF_ID]}"
        self.device_name = (
            device[CONF_DESCRIPTION][CONF_NAME]
            if not self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else f"{self._config_entry.title} {device[CONF_DESCRIPTION][CONF_NAME]}"
        )

        self.manufacturer = MANUFACTURER
        self.model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._temperature = None
        self._target_temperature = None
        self._zone_mode = None
        self._const_temp_time = None
        self._schedule_index = None
        self._zone_schedule = None
        self._active_global_schedule = None
        self.update_properties(device)
        # Remove the line below after HA 2025.1
        self._enable_turn_on_off_backwards_compatibility = False

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` describing the controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self.device_name,  # Name of the device
            CONF_MODEL: self.model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }

    def update_properties(self, device):
        """Populate state attributes from the latest zone payload.

        Args:
            device: Zone dictionary retrieved from the Tech API.

        """
        # Update target temperature
        if device[CONF_ZONE]["setTemperature"] is not None:
            if device[CONF_ZONE]["duringChange"] is False:
                self._target_temperature = device[CONF_ZONE]["setTemperature"] / 10
            else:
                _LOGGER.debug(
                    "Zone ID %s is duringChange so ignore to update target temperature",
                    device[CONF_ZONE]["id"],
                )
        else:
            self._target_temperature = None

        # Update current temperature
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._temperature = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._temperature = None

        # Update humidity
        if (
            device[CONF_ZONE]["humidity"] is not None
            and device[CONF_ZONE]["humidity"] >= 0
        ):
            self._humidity = device[CONF_ZONE]["humidity"]
        else:
            self._humidity = None

        zone_mode = device.get("mode", {})
        self._zone_mode = zone_mode.get("mode")
        self._const_temp_time = zone_mode.get("constTempTime")
        self._schedule_index = zone_mode.get("scheduleIndex")
        self._zone_schedule = _serialize_schedule(device.get("schedule"))
        self._active_global_schedule = _serialize_schedule(
            self._coordinator.data.get("global_schedules", {}).get(self._schedule_index)
        )

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
        device = self._coordinator.data["zones"].get(self._id)
        if device is None:
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_climate"

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Return the list of supported features."""
        return (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return hvac operation ie. heat, cool mode.

        Need to be one of HVAC_MODE_*.
        """
        return self._mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the list of available hvac operation modes.

        Need to be a subset of HVAC_MODES.
        """
        return SUPPORT_HVAC

    @property
    def hvac_action(self) -> HVACAction | None:
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        return self._state

    @property
    def temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.1

    @property
    def current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._temperature

    @property
    def current_humidity(self) -> float | None:
        """Return current humidity."""
        return self._humidity

    @property
    def min_temp(self) -> float:
        """Return the minimal allowed temperature value."""
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum allowed temperature value."""
        return DEFAULT_MAX_TEMP

    @property
    def target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temperature

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional schedule-related state attributes."""
        attributes: dict[str, Any] = {}
        if self._zone_mode is not None:
            attributes["zone_mode"] = self._zone_mode
        if self._const_temp_time is not None:
            attributes["const_temp_time"] = self._const_temp_time
        if self._schedule_index is not None:
            attributes["schedule_index"] = self._schedule_index
        if self._active_global_schedule is not None:
            attributes["active_schedule_source"] = "global"
            attributes["active_schedule"] = self._active_global_schedule
        elif self._zone_schedule is not None:
            attributes["active_schedule_source"] = "zone"
        if self._zone_schedule is not None:
            attributes["zone_schedule"] = self._zone_schedule
        return attributes

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a new target temperature on the Tech module.

        Args:
            **kwargs: Home Assistant service parameters containing
                ``ATTR_TEMPERATURE``.

        """
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature:
            _LOGGER.debug(
                "%s: Setting temperature to %s", self.device_name, temperature
            )
            self._temperature = temperature
            await self._coordinator.api.set_const_temp(
                self._udid, self._id, temperature
            )
            self._target_temperature = temperature
            await self.coordinator.async_request_refresh()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set the HVAC mode on the Tech module.

        Args:
            hvac_mode: Desired HVAC mode to apply to the zone.

        """
        _LOGGER.debug("%s: Setting hvac mode to %s", self.device_name, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._coordinator.api.set_zone(self._udid, self._id, False)
        elif hvac_mode == HVACMode.HEAT:
            await self._coordinator.api.set_zone(self._udid, self._id, True)
