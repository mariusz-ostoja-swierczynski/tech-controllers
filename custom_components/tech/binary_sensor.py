"""Platform for binary sensor integration."""
import logging
from typing import TYPE_CHECKING, Any, Optional

from homeassistant import core
from homeassistant.components import binary_sensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PARAMS, CONF_TYPE
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import TechCoordinator, assets
from .const import (
    CONTROLLER,
    DOMAIN,
    TYPE_ADDITIONAL_PUMP,
    TYPE_FIRE_SENSOR,
    TYPE_RELAY,
    UDID,
    VISIBILITY,
)
from .entity import TileEntity

if TYPE_CHECKING:
    from functools import cached_property
else:
    from homeassistant.backports.functools import cached_property

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    _LOGGER.debug("Setting up entry for binary sensors")
    controller: dict[str, Any] = config_entry.data[CONTROLLER]
    coordinator: TechCoordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities: list[RelaySensor] = []
    # for controller in controllers:
    controller_udid: str = controller[UDID]
    tiles: dict[str, Any] = await coordinator.api.get_module_tiles(controller_udid)
    # _LOGGER.debug("Setting up entry for binary sensors...tiles: %s", tiles)
    for t in tiles:
        tile = tiles[t]
        if tile[VISIBILITY] is False:
            continue
        if tile[CONF_TYPE] == TYPE_RELAY:
            entities.append(RelaySensor(tile, coordinator, controller_udid))
        if tile[CONF_TYPE] == TYPE_FIRE_SENSOR:
            entities.append(
                RelaySensor(
                    tile,
                    coordinator,
                    controller_udid,
                    binary_sensor.BinarySensorDeviceClass.MOTION,
                )
            )
        if tile[CONF_TYPE] == TYPE_ADDITIONAL_PUMP:
            entities.append(RelaySensor(tile, coordinator, controller_udid))

    async_add_entities(entities, True)


class TileBinarySensor(binary_sensor.BinarySensorEntity, TileEntity):
    """Representation of a TileBinarySensor."""

    @cached_property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""
        return bool(self._state)

    def get_state(self, device: dict[str, Any]) -> Any:
        """Get the state of the device.

        Args:
            device: The device to get the state of.

        Returns:
            The state of the device (True if on, False if off).

        """


class RelaySensor(TileBinarySensor):
    """Representation of a RelaySensor."""

    def __init__(
        self,
        device: dict[str, Any],
        coordinator: TechCoordinator,
        controller_udid: str,
        device_class: Optional[binary_sensor.BinarySensorDeviceClass] = None,
    ) -> None:
        """Initialize the tile relay sensor.

        Args:
            device: The device to represent.
            coordinator: The coordinator for the controller.
            controller_udid: The UDID of the controller the device belongs to.
            device_class: The device class if any (e.g. "door").

        """
        TileBinarySensor.__init__(self, device, coordinator, controller_udid)
        self._attr_device_class = device_class
        self._coordinator = coordinator
        icon_id = device[CONF_PARAMS].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)
        else:
            self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    def get_state(self, device: dict[str, Any]) -> str:
        """Get device state.

        Args:
            device: The device to get the state of.

        Returns:
            The state of the device.

        """
        return device[CONF_PARAMS]["workingStatus"]
