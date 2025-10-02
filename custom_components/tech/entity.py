"""Shared base entity helpers for Tech tile-derived devices."""

from abc import abstractmethod
import logging
from typing import Any

from homeassistant.const import CONF_DESCRIPTION, CONF_ID, CONF_PARAMS, CONF_TYPE
from homeassistant.core import callback
from homeassistant.helpers import entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import CONTROLLER, INCLUDE_HUB_IN_NAME, MANUFACTURER, UDID
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


class TileEntity(
    CoordinatorEntity,
    entity.Entity,
):
    """Representation of a TileEntity."""

    _attr_has_entity_name = True

    def __init__(self, device, coordinator: TechCoordinator, config_entry) -> None:
        """Initialise common attributes for a Tech tile entity.

        Args:
            device: Tile payload returned by the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._id = device[CONF_ID]
        self._unique_id = self._udid + "_" + str(device[CONF_ID])
        self._model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._state = self.get_state(device)
        self.manufacturer = MANUFACTURER
        txt_id = device[CONF_PARAMS].get("txtId")
        if self._config_entry.data[INCLUDE_HUB_IN_NAME]:
            self._name = self._config_entry.title + " "
        else:
            self._name = ""
        if txt_id:
            self._name += assets.get_text(txt_id)
        else:
            self._name += assets.get_text_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def state(self):
        """Return the cached state reported by the Tech API."""
        return self._state

    @abstractmethod
    def get_state(self, device):
        """Extract the integration-specific state from ``device`` data."""
        raise NotImplementedError("Must override get_state")

    def update_properties(self, device):
        """Refresh entity attributes using the latest tile payload.

        Args:
            device: Tile dictionary with the most recent values.

        """
        # Update _state property
        self._state = self.get_state(device)

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self.coordinator.data["tiles"][self._id])
        self.async_write_ha_state()
