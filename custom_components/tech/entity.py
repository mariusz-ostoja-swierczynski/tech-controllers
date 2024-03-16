"""TileEntity."""
from abc import abstractmethod
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import CONF_DESCRIPTION, CONF_ID, CONF_PARAMS, CONF_TYPE
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.typing import StateType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator, assets
from .const import DOMAIN, MANUFACTURER

if TYPE_CHECKING:
    from functools import cached_property
else:
    from homeassistant.backports.functools import cached_property

_LOGGER = logging.getLogger(__name__)


class TileEntity(CoordinatorEntity[TechCoordinator]):
    """Representation of a TileEntity."""

    def __init__(
        self, device: dict[str, Any], coordinator: TechCoordinator, controller_udid: str
    ) -> None:
        """Initialize the tile entity.

        Args:
            device: dict, the device information
            coordinator: TechCoordinator, the data update coordinator
            controller_udid: str, the unique id of the controller

        """
        _LOGGER.debug("Init TileEntity, device: %s", device)
        super().__init__(coordinator)
        self.controller_udid: str = controller_udid
        self._coordinator: TechCoordinator = coordinator
        self._id: str = device[CONF_ID]
        self._unique_id: str = controller_udid + "_" + str(device[CONF_ID])
        self.model: str = device[CONF_PARAMS].get(CONF_DESCRIPTION, "")
        self._state: StateType = self.get_state(device)
        self.manufacturer: str = MANUFACTURER
        txt_id: int = device[CONF_PARAMS].get("txtId")
        self._name: str = ""
        if txt_id:
            self._name = assets.get_text(txt_id)
        else:
            self._name = assets.get_text_by_type(device[CONF_TYPE])
        self._attr_device_info = DeviceInfo(
            identifiers={
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            name=self._name,  # Name of the device
            model=self.model,  # Model of the device
            manufacturer=self.manufacturer,  # Manufacturer of the device
        )

    @cached_property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @cached_property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @cached_property
    def state(self) -> StateType:
        """Return the state of the sensor."""
        return self._state

    @abstractmethod
    def get_state(self, device: dict[str, Any]) -> Any:
        """Get device state.

        Args:
            device: dict, the device information

        Returns:
            Optional[str], the state of the device

        """
        raise NotImplementedError("Must override get_state")

    def update_properties(self, device: dict[str, Any]) -> None:
        """Update the properties of the device based on the provided device information.

        Args:
            device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
            None

        """
        # Update _state property
        self._state = self.get_state(device)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["tiles"][self._id])
        self.async_write_ha_state()
