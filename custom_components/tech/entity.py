"""Shared base entity helpers for Tech tile-derived devices.

Almost every entity created by the integration ultimately derives from
:class:`TileEntity` (or its subclass :class:`sensor.TileSensor`), which
encapsulates three responsibilities common to every tile:

1. **Identity** -- ``unique_id`` is built from the controller UDID and the
   tile id, guaranteeing global uniqueness even across multiple Tech
   accounts paired to the same HA instance.
2. **Naming** -- the tile's localised label is resolved from a small
   precedence chain (per-tile ``txtId`` -> :data:`const.TXT_ID_BY_TYPE`
   -> :func:`assets.get_text_by_type`). Tiles whose per-tile txtId is a
   *status* string rather than a label (additional pump, disinfection)
   skip the per-tile entry. A negative or zero txtId is treated as
   "no label".
3. **Device grouping** -- :meth:`TileEntity.device_info` returns the
   controller's :class:`DeviceInfo` so that all tile entities for a given
   controller cluster under one device in the HA Devices view, instead of
   appearing as orphan entries. Subclasses that need their own device
   (e.g. wireless temperature sensors carrying battery/signal sub-entities)
   override the method but should call ``super().device_info`` to fall
   back to the controller device when create_device=False.

``_attr_has_entity_name = True`` lets HA prepend the device name to the
entity name automatically. ``self._name`` therefore stores the *bare*
tile label without any hub prefix; the prefix HA adds via the device
becomes the single source of "Wisniowa 13 X" naming.
"""

from abc import abstractmethod
import logging
from typing import Any

from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
)
from homeassistant.core import callback
from homeassistant.helpers import entity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
    TXT_ID_BY_TYPE,
    TXT_ID_IS_STATUS_FOR_TYPES,
    UDID,
    VER,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


class TileEntity(
    CoordinatorEntity,
    entity.Entity,
):
    """Base class for every Tech tile-derived Home Assistant entity.

    Subclasses must override :meth:`get_state` to extract the entity-specific
    state from the tile payload. They should *not* override ``unique_id``
    (the base implementation guarantees ``{udid}_{tile_id}`` uniqueness)
    unless they also append a sub-key like ``_tile_temperature`` to keep the
    namespace flat across multiple sensors emitted from the same tile.

    See the module docstring for the naming and device-grouping protocol.
    """

    # _attr_has_entity_name = True tells Home Assistant to compose the final
    # friendly_name as "<device.name> <self._name>". Setting this on the base
    # class means every TileEntity descendant participates in the protocol --
    # disabling it on a subclass would re-introduce the double-prefix bug
    # this integration spent considerable effort eliminating.
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
        # The Tech UDID is the stable identity of the *physical controller*
        # behind this entity; it is reused as the controller's device id.
        self._udid = config_entry.data[CONTROLLER][UDID]
        # ``_id`` is the per-tile id, used by the coordinator update callback
        # to look the tile up in the refreshed payload (see
        # :meth:`_handle_coordinator_update` below).
        self._id = device[CONF_ID]
        # ``_unique_id`` is the *root* identifier; subclasses append a
        # discriminator suffix (e.g. ``_tile_temperature_widget1``) when a
        # single tile produces multiple entities.
        self._unique_id = f"{self._udid}_{device[CONF_ID]}"
        self._model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._state = self.get_state(device)
        self.manufacturer = MANUFACTURER

        # ``_attr_has_entity_name = True`` makes Home Assistant prepend the
        # owning device's name automatically, so the entity name is just the
        # tile's localised label. Some tiles (additional pump, disinfection)
        # use ``txtId`` as a *status* string rather than a label, and a few
        # use ``-1`` to mean "no label" -- for both cases we fall back to the
        # type-default txtId in ``TXT_ID_BY_TYPE``.
        tile_type = device[CONF_TYPE]
        txt_id = device[CONF_PARAMS].get("txtId") or 0
        if txt_id <= 0 or tile_type in TXT_ID_IS_STATUS_FOR_TYPES:
            txt_id = TXT_ID_BY_TYPE.get(tile_type, 0)
        if txt_id > 0:
            self._name = assets.get_text(txt_id)
        else:
            self._name = assets.get_text_by_type(tile_type)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Group all tile entities under the controller's device.

        Subclasses that need to live on a separate device (e.g. wireless
        temperature sensors that own their own battery/signal sub-entities)
        override this; everything else falls back here so zone-less
        controllers (ST-491, ST-505, ST-976...) still produce a single
        device with grouped entities instead of orphaned, ungrouped entries.
        """
        controller = self._config_entry.data[CONTROLLER]
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._udid)},
            CONF_NAME: self._config_entry.title,
            "model": controller.get(CONF_NAME, ""),
            "sw_version": controller.get(VER, ""),
            ATTR_MANUFACTURER: MANUFACTURER,
        }

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
