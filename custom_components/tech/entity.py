from abc import abstractmethod
import logging
from homeassistant.helpers import entity
from . import assets
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class TileEntity(entity.Entity):
    """Representation of a TileEntity."""

    def __init__(self, device, api, controller_uid):
        """Initialize the tile entity"""
        _LOGGER.debug("Init TileEntity...")
        self._controller_uid = controller_uid
        self._api = api
        _LOGGER.debug("TileEntity: %s", device)
        self._id = device["id"]
        self._model = device["params"].get("description")
        self._state = self.get_state(device)
        txt_id = device["params"].get("txtId")
        if txt_id:
            self._name = assets.get_text(txt_id)
        else:
            self._name = assets.get_text_by_type(device["type"])

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.unique_id)},
            "name": self.name,
            "manufacturer": "Tech",
            "model": self._model,
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._id

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
        raise NotImplementedError("Must override get_state")

    async def async_update(self):
        device = await self._api.get_tile(self._controller_uid, self.unique_id)
        self._state = self.get_state(device)
