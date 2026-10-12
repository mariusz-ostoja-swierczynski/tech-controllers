"""Shared base entity helpers for Tech tile-derived devices.

Almost every entity created by the integration ultimately derives from
:class:`TileEntity` (or its subclass :class:`sensor.TileSensor`), which
encapsulates three responsibilities common to every tile:

1. **Identity** -- ``unique_id`` is built from the controller UDID and the
   tile id, guaranteeing global uniqueness even across multiple Tech
   accounts paired to the same HA instance.
2. **Naming** -- the tile's localised label is resolved from a small
   precedence chain (per-tile ``txtId`` -> :data:`const.TXT_ID_BY_TYPE`
   -> :meth:`assets.Translations.get_text_by_type`). Tiles whose per-tile
   txtId is a *status* string rather than a label (additional pump,
   disinfection)
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
from collections.abc import Callable
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
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
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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


class ReportedEntity:
    """An entity that knows which payload entry it was built from.

    A controller can stop reporting a tile, a zone or a menu item -- the user
    removed it in the eModul app, or replaced the hardware -- and the entities
    built from it have to go with it. The coordinator keeps them under that
    source key (``tile_42``, ``zone_3``, ``menu_MU_3550``), so a poll can tell
    which of them the controller no longer reports. See
    :func:`custom_components.tech._drop_unreported_entities`.
    """

    source_key: str

    async def async_added_to_hass(self) -> None:
        """Record this entity under its source key while it is registered."""
        await super().async_added_to_hass()
        self.coordinator.reported.setdefault(self.source_key, set()).add(self)

    async def async_will_remove_from_hass(self) -> None:
        """Forget this entity, so that a returning payload can bring it back."""
        entities = self.coordinator.reported.get(self.source_key)
        if entities is not None:
            entities.discard(self)
            if not entities:
                self.coordinator.reported.pop(self.source_key, None)
        self._tell_the_platform_it_left()
        await super().async_will_remove_from_hass()

    def _tell_the_platform_it_left(self) -> None:
        """Let the platform that built this entity stop counting it as registered.

        This is the only signal that says an entity has left, and it is a
        positive one: it fires when Home Assistant removes an entity, whether the
        removal pass dropped it or the user deleted it, and never while one is
        merely being added. A platform that instead *inferred* the same thing
        from the payload bookkeeping saw the window between asking for an entity
        and Home Assistant calling it back, and registered it twice.
        """
        for forget in self.coordinator.forget_callbacks:
            forget(self.unique_id)


class TileEntity(
    ReportedEntity,
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
            self._name = coordinator.translations.get_text(txt_id)
        else:
            self._name = coordinator.translations.get_text_by_type(tile_type)

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
    def source_key(self) -> str:
        """Return the tile this entity was built from."""
        return f"tile_{self._id}"

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


def add_later(
    config_entry: ConfigEntry,
    coordinator: TechCoordinator,
    async_add_entities: AddEntitiesCallback,
    build: Callable[[], list[Any]],
) -> None:
    """Register the entities a payload produces now, and any a later one adds.

    A controller's configuration changes while Home Assistant runs: a sensor is
    paired, a zone is created in the app, a module gains a tile. A platform
    builds its entities once, so instead of that it builds them from the
    coordinator's latest payload every time the data updates and registers what
    it has not registered before. What a controller *stops* reporting is handled
    centrally, because a payload that is merely incomplete must not remove
    anything, and an entity that leaves Home Assistant reports back here, so that
    a payload bringing its entry back registers it again.

    Args:
        config_entry: The entry being set up, used to unregister again.
        coordinator: The entry's coordinator, the payload each build reads, and
            where the callback that hears about a departing entity is kept.
        async_add_entities: The platform's registration callback.
        build: Builds the entities of the coordinator's current payload.

    """
    registered: set[str] = set()

    def _forget(unique_id: str) -> None:
        registered.discard(unique_id)

    coordinator.forget_callbacks.append(_forget)

    def _add_new() -> None:
        # A source key is shared by every entity built from that payload entry,
        # across platforms -- a zone carries a thermostat and its sensors -- so
        # what tells an entity apart is its own unique id, not that key. An
        # entity that leaves Home Assistant says so through the callback above,
        # which is what lets a payload bring its entry back.
        fresh = [entity for entity in build() if entity.unique_id not in registered]
        if not fresh:
            return
        registered.update(entity.unique_id for entity in fresh)
        async_add_entities(fresh, True)

    _add_new()
    config_entry.async_on_unload(coordinator.async_add_listener(_add_new))
