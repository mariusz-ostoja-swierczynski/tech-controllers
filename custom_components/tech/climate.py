"""Climate platform for the Tech Controllers integration."""

import logging
from typing import Any, cast

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_ZONE,
    STATE_OFF,
    STATE_ON,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import ChildDeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import CONTROLLER, DOMAIN, INCLUDE_HUB_IN_NAME, UDID, scaled_number
from .coordinator import TechConfigEntry, TechCoordinator
from .entity import ReportedEntity, add_later
from .schedules import climate_schedule_attributes

_LOGGER = logging.getLogger(__name__)

# Climate changes (mode, setpoint) go to the same cloud account as the menu
# writes, so they are serialised with them. Home Assistant reads
# PARALLEL_UPDATES from the platform module.
PARALLEL_UPDATES = 1

DEFAULT_MIN_TEMP = 5
DEFAULT_MAX_TEMP = 35
SUPPORT_HVAC = [HVACMode.HEAT, HVACMode.OFF]


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TechConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech climate entities for the provided config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller data.
        async_add_entities: Callback to register entities with Home Assistant.

    """
    udid = config_entry.data[CONTROLLER][UDID]
    coordinator = config_entry.runtime_data
    _LOGGER.debug("Setting up entry, controller udid: %s", udid)

    # Only usable zone payloads: a controller without zones, or one whose payload
    # carries entries that are not zone payloads, must not take the whole climate
    # platform down with it.
    def _build() -> list[TechThermostat]:
        # Read from the coordinator's payload rather than fetching: this runs
        # again on every poll, to pick up a zone the controller starts reporting.
        zones = assets.zone_payloads(coordinator.data.get("zones"))
        return [
            TechThermostat(zone, coordinator, config_entry) for zone in zones.values()
        ]

    add_later(config_entry, coordinator, async_add_entities, _build)


class TechThermostat(ReportedEntity, ClimateEntity, CoordinatorEntity[TechCoordinator]):
    """Representation of a Tech climate."""

    _attr_has_entity_name = True
    _attr_name = None

    def __init__(
        self,
        device: dict[str, Any],
        coordinator: TechCoordinator,
        config_entry: TechConfigEntry,
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
            if not self._config_entry.options.get(INCLUDE_HUB_IN_NAME, False)
            else f"{self._config_entry.title} {device[CONF_DESCRIPTION][CONF_NAME]}"
        )

        self._temperature: float | None = None
        self._target_temperature: float | None = None
        self.update_properties(device)
        # Remove the line below after HA 2025.1
        self._enable_turn_on_off_backwards_compatibility = False

    @property
    def source_key(self) -> str:
        """Return the zone this thermostat was built from."""
        return f"zone_{self._id}"

    @property
    def device_info(self) -> ChildDeviceInfo | None:
        """Return Home Assistant ``ChildDeviceInfo`` for this zone."""
        return ChildDeviceInfo(
            identifiers={(DOMAIN, self._unique_id)},
            name=self.device_name,
            # A zone is a logical part of the controller, so it is a child
            # device, not a separate product reached through it.
            parent_device_id=assets.parent_controller(self.coordinator),
        )

    def update_properties(self, device: dict[str, Any]) -> None:
        """Populate state attributes from the latest zone payload.

        Args:
            device: Zone dictionary retrieved from the Tech API.

        """
        # Update target temperature
        if device[CONF_ZONE]["setTemperature"] is not None:
            if device[CONF_ZONE]["duringChange"] is False:
                self._target_temperature = scaled_number(
                    device[CONF_ZONE]["setTemperature"], 10
                )
            else:
                _LOGGER.debug(
                    "Zone ID %s is duringChange so ignore to update target temperature",
                    device[CONF_ZONE]["id"],
                )
        else:
            self._target_temperature = None

        # Update current temperature
        self._temperature = scaled_number(
            device[CONF_ZONE].get("currentTemperature"), 10
        )

        # Update humidity
        if (
            device[CONF_ZONE]["humidity"] is not None
            and device[CONF_ZONE]["humidity"] >= 0
        ):
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
        return f"{self._unique_id}_zone_climate"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Describe schedule selection without inferring a current target."""
        return climate_schedule_attributes(
            (self._coordinator.data or {}).get("schedules"),
            self._id,
            self._coordinator.last_update_success,
        )

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

    # Home Assistant 2026.11 renamed these temperature properties with a
    # ``native_`` prefix and took ownership of the ``temperature_unit`` state
    # attribute. The old names remain deprecated until 2027.11; this entity
    # targets 2026.11, so it implements only the native properties.
    # See https://developers.home-assistant.io/blog/2026/10/08/climate-native-temperature
    @property
    def native_temperature_unit(self) -> str:
        """Return the unit of measurement."""
        return UnitOfTemperature.CELSIUS

    @property
    def target_temperature_step(self) -> float | None:
        """Return the supported step of target temperature."""
        return 0.1

    @property
    def native_current_temperature(self) -> float | None:
        """Return the current temperature."""
        return self._temperature

    @property
    def current_humidity(self) -> float | None:
        """Return current humidity."""
        return cast("float | None", self._humidity)

    @property
    def min_temp(self) -> float:
        """Return the minimal allowed temperature value."""
        return DEFAULT_MIN_TEMP

    @property
    def max_temp(self) -> float:
        """Return the maximum allowed temperature value."""
        return DEFAULT_MAX_TEMP

    @property
    def native_target_temperature(self) -> float | None:
        """Return the temperature we try to reach."""
        return self._target_temperature

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
