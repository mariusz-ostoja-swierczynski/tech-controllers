"""Binary sensor platform for the Tech Sterowniki integration.

Four flavours of binary entity are emitted:

* **Relays** -- TYPE_RELAY (=11) tiles ("Pompa CO", "Pompa CWU",
  "Podajnik" etc.) and TYPE_ADDITIONAL_PUMP (=21) tiles, both backed by
  :class:`RelaySensor`. The on/off state comes from the tile's
  ``workingStatus`` boolean and is refreshed by the coordinator on the
  60-second polling cadence (see :data:`const.SCAN_INTERVAL`).
* **Fire/motion sensors** -- TYPE_FIRE_SENSOR (=2) tiles, also handled by
  :class:`RelaySensor` but with the MOTION device class so the HA UI
  shows the correct iconography.
* **Contact widgets** -- TYPE_WIDGET (=6) sub-payloads with the
  contact-shape marker (``unit==-1, type==0, txtId!=0``), backed by
  :class:`TileWidgetContactSensor`. EU-i-3+ extension modules expose all
  four of their voltage / potential-free inputs this way.
* **Widget status sensors** -- TYPE_WIDGET (=6) tiles whose
  ``params.statusId`` is ``0`` or ``1`` **and** whose widgets include a
  pump type (``WIDGET_DHW_PUMP`` or ``WIDGET_COLLECTOR_PUMP``), backed by
  :class:`TileWidgetStatusSensor`. The statusId signals ON/OFF state for
  PWM-controlled pumps whose widgets carry temperature data (rather than
  a relay ``workingStatus`` boolean). Tiles with only temperature or
  contact widgets always report ``statusId=1`` and never toggle, so they
  are excluded to avoid flooding HA with useless always-ON sensors.

Contact widgets share their parent tile with numeric widgets that go to
:mod:`sensor`. Both modules use the same :func:`_is_contact_widget`
predicate to decide which platform owns each widget; without that
agreement the same widget could be emitted twice (or not at all).
"""

import logging

from homeassistant.components import binary_sensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PARAMS,
    CONF_TYPE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType, UndefinedType

from . import TechCoordinator, assets
from .const import (
    CONTROLLER,
    DOMAIN,
    TYPE_ADDITIONAL_PUMP,
    TYPE_FIRE_SENSOR,
    TYPE_RELAY,
    TYPE_WIDGET,
    UDID,
    VALUE,
    VISIBILITY,
    WIDGET_COLLECTOR_PUMP,
    WIDGET_DHW_PUMP,
)
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)


def _is_contact_widget(widget: dict) -> bool:
    """Return ``True`` for widgets that should be exposed as binary contacts."""
    return (
        widget.get("unit") == -1
        and widget.get(CONF_TYPE) == 0
        and widget.get("txtId", 0) != 0
    )


def _has_pump_widget(params: dict) -> bool:
    """Return ``True`` if the TYPE_WIDGET tile carries a pump-type widget.

    Pump-type widgets (``type=1`` = WIDGET_DHW_PUMP, ``type=2`` =
    WIDGET_COLLECTOR_PUMP) indicate the tile represents a pump whose
    ``statusId`` carries ON/OFF semantics. Pure temperature or contact
    widgets always report ``statusId=1`` and never toggle.
    """
    for key in ("widget1", "widget2"):
        widget = params.get(key)
        if widget and widget.get(CONF_TYPE) in (WIDGET_DHW_PUMP, WIDGET_COLLECTOR_PUMP):
            return True
    return False


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech binary sensors for a newly created config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller metadata.
        async_add_entities: Callback used to register entities with Home Assistant.

    """
    _LOGGER.debug("Setting up entry for sensors…")
    controller = config_entry.data[CONTROLLER]
    coordinator = hass.data[DOMAIN][config_entry.entry_id]

    entities = []
    # for controller in controllers:
    controller_udid = controller[UDID]
    tiles = await coordinator.api.get_module_tiles(controller_udid)
    # _LOGGER.debug("Setting up entry for binary sensors...tiles: %s", tiles)
    for t in tiles:
        tile = tiles[t]
        if tile[VISIBILITY] is False:
            continue
        if tile[CONF_TYPE] == TYPE_RELAY:
            entities.append(RelaySensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_FIRE_SENSOR:
            entities.append(
                RelaySensor(
                    tile,
                    coordinator,
                    config_entry,
                    binary_sensor.BinarySensorDeviceClass.MOTION,
                )
            )
        if tile[CONF_TYPE] == TYPE_ADDITIONAL_PUMP:
            entities.append(RelaySensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_WIDGET:
            for widget_key in ("widget1", "widget2"):
                widget = tile.get(CONF_PARAMS, {}).get(widget_key)
                if widget and _is_contact_widget(widget):
                    entities.append(
                        TileWidgetContactSensor(
                            tile, coordinator, config_entry, widget_key
                        )
                    )
            # TYPE_WIDGET tiles with statusId 0 or 1 carry ON/OFF state for
            # PWM-controlled pumps (e.g. solar collector). Only emit the
            # binary sensor when the tile has pump-type widgets (type=1 or
            # type=2) — pure temperature/contact widgets always report
            # statusId=1 and never toggle.
            status_id = tile.get(CONF_PARAMS, {}).get("statusId")
            if status_id in (0, 1) and _has_pump_widget(tile.get(CONF_PARAMS, {})):
                entities.append(
                    TileWidgetStatusSensor(tile, coordinator, config_entry)
                )

    async_add_entities(entities, True)


class TileBinarySensor(TileEntity, binary_sensor.BinarySensorEntity):
    """Base class for Tech tiles that expose binary sensor semantics."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_state(self, device):
        """Return the raw binary state extracted from ``device`` data."""

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_binary_sensor"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def state(self) -> str | int | float | StateType | None:
        """Get the state of the binary sensor."""
        return STATE_ON if self._state else STATE_OFF


class RelaySensor(TileBinarySensor):
    """Representation of a RelaySensor."""

    def __init__(
        self, device, coordinator: TechCoordinator, config_entry, device_class=None
    ) -> None:
        """Initialize the relay-backed binary sensor tile.

        Args:
            device: Tile payload returned from the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry providing controller metadata.
            device_class: Optional Home Assistant device class for the sensor.

        """
        TileBinarySensor.__init__(self, device, coordinator, config_entry)
        self._attr_device_class = device_class
        self._coordinator = coordinator
        icon_id = device[CONF_PARAMS].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)
        else:
            self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    def get_state(self, device):
        """Return the on/off working status for the provided ``device`` payload."""
        return device[CONF_PARAMS]["workingStatus"]


class TileWidgetContactSensor(TileBinarySensor):
    """A widget-shaped contact (e.g. EU-i-3+ voltage / potential-free input).

    Detected by ``unit == -1`` and ``type == 0`` on a TYPE_WIDGET tile widget.
    Exposed as an opening device-class binary sensor; ``value == 1`` means open.
    """

    _attr_device_class = binary_sensor.BinarySensorDeviceClass.OPENING

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        widget_key: str,
    ) -> None:
        """Initialise the contact widget binary sensor.

        Args:
            device: Tile payload returned from the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry providing controller metadata.
            widget_key: ``"widget1"`` or ``"widget2"`` - which widget within the
                tile this entity represents.

        """
        self._widget_key = widget_key
        TileBinarySensor.__init__(self, device, coordinator, config_entry)
        widget = device[CONF_PARAMS][widget_key]
        # Contact widgets carry their label inside the widget payload, not the
        # tile params, so override the name TileEntity computed from tile-level
        # txtId. ``_attr_has_entity_name = True`` lets HA prepend the device.
        self._name = coordinator.translations.get_text(widget["txtId"])
        icon_id = device[CONF_PARAMS].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_widget_contact_{self._widget_key}"

    def get_state(self, device):
        """Return the contact state from the widget value."""
        return device[CONF_PARAMS][self._widget_key][VALUE] == 1


class TileWidgetStatusSensor(TileBinarySensor):
    """A TYPE_WIDGET tile whose ``statusId`` signals ON/OFF pump state.

    PWM-controlled pumps (solar collector, etc.) use ``statusId``
    (1=ON, 0=OFF) rather than a ``workingStatus`` boolean or a relay
    tile. The tile's own widgets carry temperature readings handled by
    :mod:`sensor`; this entity adds the companion ON/OFF indicator.

    Only statusId values 0 and 1 are consumed — larger values are
    translation keys for :class:`~sensor.TileTextSensor` and are ignored
    here.
    """

    _attr_device_class = binary_sensor.BinarySensorDeviceClass.RUNNING

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
    ) -> None:
        """Initialise the status-id-backed binary sensor.

        Args:
            device: Tile payload returned by the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry providing controller metadata.

        """
        TileBinarySensor.__init__(self, device, coordinator, config_entry)
        icon_id = device[CONF_PARAMS].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_status"

    def get_state(self, device):
        """Return the ON/OFF state from the tile's statusId.

        Args:
            device: Tile payload returned by the Tech API.

        Returns:
            ``True`` when statusId == 1 (ON), ``False`` when statusId == 0
            (OFF). Any other value is returned as ``None`` (unknown).

        """
        status_id = device[CONF_PARAMS].get("statusId")
        if status_id == 1:
            return True
        if status_id == 0:
            return False
        return None
