"""Read-only heating curves reported by the user menu."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONTROLLER, UDID
from .coordinator import TechConfigEntry, TechCoordinator
from .entity import ReportedEntity, controller_device_info

# The installer menu can report the same curves under different ids.
WEATHER_CURVE_TYPE = 30
OUTDOOR_POINTS = {-20, -10, 0, 10}


def weather_curve(item: dict[str, Any]) -> dict[str, Any] | None:
    """Decode the four degree-Celsius points of the observed menu format."""
    if (
        item.get("type") != WEATHER_CURVE_TYPE
        or item.get("menuType") != "MU"
        or item.get("access") is not True
    ):
        return None
    change = item.get("duringChange")
    if change is not None and change is not False and change != "f":
        return None
    params = item.get("params")
    if not isinstance(params, dict):
        return None
    low, high, points = params.get("min"), params.get("max"), params.get("points")
    if (
        type(low) is not int
        or type(high) is not int
        or low > high
        or not isinstance(points, list)
        or len(points) != len(OUTDOOR_POINTS)
    ):
        return None

    targets = {}
    for point in points:
        if not isinstance(point, dict):
            return None
        outdoor, target = point.get("position"), point.get("value")
        if (
            type(outdoor) is not int
            or outdoor not in OUTDOOR_POINTS
            or outdoor in targets
            or type(target) is not int
            or not low <= target <= high
        ):
            return None
        targets[outdoor] = target
    return {
        "points": [
            {"outdoor_temperature": outdoor, "target_temperature": targets[outdoor]}
            for outdoor in sorted(targets)
        ],
        "minimum_target_temperature": low,
        "maximum_target_temperature": high,
    }


class WeatherCurveSensor(
    ReportedEntity, CoordinatorEntity[TechCoordinator], SensorEntity
):
    """Expose the configured points from the latest menu payload."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chart-line"

    def __init__(
        self, coordinator: TechCoordinator, entry: TechConfigEntry, key: str, name: str
    ) -> None:
        """Associate the curve with its existing menu source."""
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_name = name
        self._attr_unique_id = (
            f"{entry.data[CONTROLLER][UDID]}_menu_{key}_weather_curve"
        )

    @property
    def source_key(self) -> str:
        """Use the menu item for its existing removal and restoration lifecycle."""
        return f"menu_{self._key}"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the existing controller device."""
        return controller_device_info(self._entry)

    def _curve(self) -> dict[str, Any] | None:
        """Break the link to the accumulated cache when a poll omits the item."""
        data = self.coordinator.data
        if self._key not in data["reported"]["menus"]:
            return None
        return weather_curve(data["menus"][self._key])

    @property
    def available(self) -> bool:
        """Require a valid, current and settled curve."""
        return super().available and self._curve() is not None

    @property
    def native_value(self) -> int | None:
        """Return the number of configured points."""
        curve = self._curve()
        return len(curve["points"]) if curve else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Report points and target bounds in Celsius."""
        return self._curve()
