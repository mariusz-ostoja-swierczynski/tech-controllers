"""Select entity that chooses how a zone is heated.

The options come from the same schedule snapshot the read-only sensors use, so
a global slot shows the name the controller reports for it. A choice is made
through the zone-mode actions rather than the API client: they validate the
selection before the first write and never refresh the coordinator.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.const import (
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_ZONE,
    EntityCategory,
)
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import ChildDeviceInfo
from homeassistant.helpers.translation import async_translate_state
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import CONTROLLER, DOMAIN, UDID
from .coordinator import TechConfigEntry, TechCoordinator
from .entity import ReportedEntity
from .schedules import (
    GLOBAL_SCHEDULE_SLOTS,
    SCHEDULE_TEMPERATURE_MAX,
    SCHEDULE_TEMPERATURE_MIN,
    global_schedule_details,
    zone_mode_pending,
    zone_schedule_info,
)
from .services import SERVICE_SET_ZONE_CONSTANT, SERVICE_SET_ZONE_SCHEDULE

CONSTANT_TEMPERATURE = "constantTemp"
TIME_LIMIT = "timeLimit"
LOCAL_SCHEDULE = "localSchedule"
GLOBAL_SCHEDULE = "globalSchedule"

CONSTANT_ACTION = "constant"
LOCAL_ACTION = "local"
GLOBAL_ACTION = "global"


class ZoneScheduleSelect(
    ReportedEntity, CoordinatorEntity[TechCoordinator], SelectEntity
):
    """Choose a zone's constant temperature, local or global schedule."""

    _attr_has_entity_name = True
    _attr_translation_key = "zone_schedule_select"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        zone: dict[str, Any],
        coordinator: TechCoordinator,
        config_entry: TechConfigEntry,
    ) -> None:
        """Bind the select to one zone and the coordinator's latest snapshot.

        Args:
            zone: Zone payload the entity is built from.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._id = zone[CONF_ZONE][CONF_ID]
        self._unique_id = f"{self._udid}_{self._id}_zone_schedule_select"
        self._device_name = zone[CONF_DESCRIPTION][CONF_NAME]
        self._constant_label = "Constant temperature"
        self._local_label = "Local schedule"
        self._global_label = "Global schedule"
        self._option_actions: dict[str, tuple[str, int | None]] = {}
        self._global_options: dict[int, str] = {}
        self._attr_options: list[str] = []
        self._attr_current_option: str | None = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def source_key(self) -> str:
        """Return the zone this entity was built from."""
        return f"zone_{self._id}"

    @property
    def device_info(self) -> ChildDeviceInfo:
        """Return the zone child device shared with the climate entity."""
        return ChildDeviceInfo(
            identifiers={(DOMAIN, f"{self._udid}_{self._id}")},
            name=self._device_name,
            parent_device_id=assets.parent_controller(self.coordinator),
        )

    @property
    def available(self) -> bool:
        """Become unavailable when the schedule snapshot disappears."""
        return super().available and isinstance(self._schedule_data(), dict)

    async def async_added_to_hass(self) -> None:
        """Load the translated labels before the first options are published."""
        await super().async_added_to_hass()
        self._load_labels()
        self._refresh_options()

    def _load_labels(self) -> None:
        """Read the labels the schedule sensor already translates."""
        constant = async_translate_state(
            self.hass,
            "constant-temp",
            "sensor",
            DOMAIN,
            "zone_schedule_entity",
            None,
        )
        if constant != "constant-temp":
            self._constant_label = constant
        local = async_translate_state(
            self.hass,
            "local-schedule",
            "sensor",
            DOMAIN,
            "zone_schedule_entity",
            None,
        )
        if local != "local-schedule":
            self._local_label = local
        global_ = async_translate_state(
            self.hass,
            "global-schedule",
            "sensor",
            DOMAIN,
            "zone_schedule_entity",
            None,
        )
        if global_ != "global-schedule":
            self._global_label = global_

    def _schedule_data(self) -> Any:
        """Return the current schedule snapshot."""
        return (self.coordinator.data or {}).get("schedules")

    def _refresh_options(self, *, hold_current: bool = False) -> None:
        """Rebuild the options from the names the snapshot carries now.

        Args:
            hold_current: Keep the option this entity last published. The
                controller reports the previous mode while it applies a write,
                so a poll that lands inside that window must not undo the
                selection the user just made.

        """
        snapshot = self._schedule_data()
        options = [self._constant_label, self._local_label]
        actions: dict[str, tuple[str, int | None]] = {
            self._constant_label: (CONSTANT_ACTION, None),
            self._local_label: (LOCAL_ACTION, None),
        }
        global_options: dict[int, str] = {}
        for index in range(GLOBAL_SCHEDULE_SLOTS):
            name = global_schedule_details(snapshot, index)["name"]
            label = f"{self._global_label} {index + 1}"
            if isinstance(name, str) and name:
                label = f"{label}: {name}"
            global_options[index] = label
            actions[label] = (GLOBAL_ACTION, index)
            options.append(label)
        self._global_options = global_options
        self._option_actions = actions
        self._attr_options = options
        if not hold_current:
            self._attr_current_option = self._current_option(snapshot)

    def _current_option(self, snapshot: Any) -> str | None:
        """Map the zone's configured mode to one of the published labels."""
        info = zone_schedule_info(snapshot, self._id)
        mode = info["schedule_mode"]
        if mode in (CONSTANT_TEMPERATURE, TIME_LIMIT):
            return self._constant_label
        if mode == LOCAL_SCHEDULE:
            return self._local_label
        if mode == GLOBAL_SCHEDULE and type(info["schedule_index"]) is int:
            return self._global_options.get(info["schedule_index"])
        return None

    def _current_setpoint(self) -> int | None:
        """Return the zone's current setpoint in tenths of a degree."""
        zones = (self._coordinator.data or {}).get("zones")
        zone = zones.get(self._id) if isinstance(zones, dict) else None
        value = zone.get(CONF_ZONE, {}).get("setTemperature") if zone else None
        if (
            type(value) is int
            and SCHEDULE_TEMPERATURE_MIN <= value <= SCHEDULE_TEMPERATURE_MAX
        ):
            return value
        return None

    def _constant_duration(self) -> int:
        """Return the minutes the duration number set for this zone."""
        duration = self._coordinator.zone_constant_durations.get(self._id)
        return duration if type(duration) is int and duration > 0 else 0

    async def async_select_option(self, option: str) -> None:
        """Route the chosen option through the matching zone-mode action."""
        action = self._option_actions.get(option)
        if action is None:
            raise HomeAssistantError(
                f"Unknown schedule option: {option}",
                translation_domain=DOMAIN,
                translation_key="schedule_invalid",
            )
        source, index = action
        if source == CONSTANT_ACTION:
            setpoint = self._current_setpoint()
            if setpoint is None:
                raise HomeAssistantError(
                    "The controller did not report a temperature for this zone.",
                    translation_domain=DOMAIN,
                    translation_key="zone_temperature_missing",
                )
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_SET_ZONE_CONSTANT,
                {
                    "entity_id": self.entity_id,
                    "temperature": setpoint / 10,
                    "duration_minutes": self._constant_duration(),
                },
                blocking=True,
            )
        elif source == LOCAL_ACTION:
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_SET_ZONE_SCHEDULE,
                {"entity_id": self.entity_id, "source": "local"},
                blocking=True,
            )
        else:
            await self.hass.services.async_call(
                DOMAIN,
                SERVICE_SET_ZONE_SCHEDULE,
                {"entity_id": self.entity_id, "source": "global", "index": index},
                blocking=True,
            )
        self._attr_current_option = option
        self.async_write_ha_state()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the option labels from the coordinator's latest snapshot."""
        self._refresh_options(
            hold_current=zone_mode_pending(self._schedule_data(), self._id)
        )
        self.async_write_ha_state()
