"""TileEntity."""
from abc import abstractmethod
import logging
from typing import Any

from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_MODEL,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
)
from homeassistant.core import callback
from homeassistant.helpers import entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator, assets
from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)


class TileEntity(
    CoordinatorEntity,
    entity.Entity,
):
    """Representation of a TileEntity."""

    def __init__(self, device, coordinator: TechCoordinator, controller_uid):
        """Initialize the tile entity."""
        super().__init__(coordinator)
        self._controller_uid = controller_uid
        self._coordinator = coordinator
        self._id = device[CONF_ID]
        self._unique_id = controller_uid + "_" + str(device[CONF_ID])
        self._model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._state = self.get_state(device)
        self.manufacturer = MANUFACTURER
        txt_id = device[CONF_PARAMS].get("txtId")
        if txt_id:
            self._name = assets.get_text(txt_id)
        else:
            self._name = assets.get_text_by_type(device[CONF_TYPE])

    @property
    def device_info(self):
        """Get device info."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self.unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self.name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self):
        """Return the name of the sensor."""
        return self._name

    @property
    def state(self):
        """Return the state of the sensor."""
        return self._state

    @abstractmethod
    def get_state(self, device):
        """Get device state."""
        raise NotImplementedError("Must override get_state")

    def update_properties(self, device):
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        # Update _state property
        self._state = self.get_state(device)

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["tiles"][self._id])
        self.async_write_ha_state()
