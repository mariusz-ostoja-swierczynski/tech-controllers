"""Number entity that sets the time limit of a zone's constant temperature.

The controller's zone mode carries a ``constTempTime`` field, but the app only
offers it while the user picks "with a time limit". The per-zone **Schedule**
select applies a constant temperature, so this number holds the minutes that
selection uses: zero keeps the temperature until it is changed, and a positive
value holds it for that many minutes before the zone returns to its previous
mode.

The value is a local preference for that select, not a reading from the
controller: it is never written on its own, it survives a restart through the
entity's restored state, and the select reads it when it is chosen.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberMode, RestoreNumber
from homeassistant.const import (
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_ZONE,
    EntityCategory,
    UnitOfTime,
)
from homeassistant.helpers.device_registry import ChildDeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import CONTROLLER, DOMAIN, UDID
from .coordinator import TechConfigEntry, TechCoordinator
from .entity import ReportedEntity
from .schedules import PERMANENT_CONST_TEMP_TIME, TIME_LIMIT_MINUTES_MAX


class ZoneConstantDurationNumber(
    ReportedEntity, CoordinatorEntity[TechCoordinator], RestoreNumber
):
    """Minutes the zone's constant-temperature select holds the temperature for."""

    _attr_has_entity_name = True
    _attr_translation_key = "zone_constant_duration"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_native_min_value = PERMANENT_CONST_TEMP_TIME
    _attr_native_max_value = TIME_LIMIT_MINUTES_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        zone: dict[str, Any],
        coordinator: TechCoordinator,
        config_entry: TechConfigEntry,
    ) -> None:
        """Bind the duration to one zone and the coordinator's latest snapshot.

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
        self._unique_id = f"{self._udid}_{self._id}_zone_constant_duration"
        self._device_name = zone[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = float(
            self._coordinator.zone_constant_durations.get(self._id, 0)
        )

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

    async def async_added_to_hass(self) -> None:
        """Restore the duration the user last chose for this zone."""
        await super().async_added_to_hass()
        restored = await self.async_get_last_number_data()
        if restored is not None and restored.native_value is not None:
            self._store(restored.native_value)

    async def async_set_native_value(self, value: float) -> None:
        """Store the duration for the zone's next constant-temperature choice."""
        self._store(value)
        self.async_write_ha_state()

    def _store(self, value: float) -> None:
        """Clamp and keep the duration where the select reads it.

        Args:
            value: Minutes entered by the user or restored from the last state.

        """
        duration = max(
            PERMANENT_CONST_TEMP_TIME, min(TIME_LIMIT_MINUTES_MAX, int(value))
        )
        self._coordinator.zone_constant_durations[self._id] = duration
        self._attr_native_value = float(duration)
