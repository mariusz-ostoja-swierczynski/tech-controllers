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
* **Contact widgets** -- TYPE_WIDGET (=6) tiles made of contact widgets
  only (``unit==-1, type==0, txtId!=0``), backed by
  :class:`TileWidgetContactSensor`. EU-i-3+ and i2+ extension modules
  expose their voltage / potential-free inputs this way. A *lone*
  ``unit == -1`` widget next to a visible reading is the API's "value
  invisible" rather than a contact (issue #221).
* **Widget flags** -- TYPE_WIDGET widgets of API value type 28
  ("Enabled / Disabled"), backed by :class:`TileWidgetFlagSensor`. The
  label may live on the sibling widget, which is how heat pumps name
  their settings (issue #221).
* **Widget status sensors** -- TYPE_WIDGET (=6) tiles whose
  ``params.statusId`` is ``0`` or ``1`` **and** which carry a pump widget that
  reads a pump quantity (a temperature or a percentage), backed by
  :class:`TileWidgetStatusSensor`. The statusId signals ON/OFF state for
  PWM-controlled pumps whose widgets carry temperature data (rather than
  a relay ``workingStatus`` boolean). Tiles with only temperature or
  contact widgets always report ``statusId=1`` and never toggle, so they
  are excluded to avoid flooding HA with useless always-ON sensors.

Contact and flag widgets share their parent tile with numeric widgets that go
to :mod:`sensor`. Both modules use the same :func:`_is_contact_widget` and
:func:`_is_flag_widget` predicates to decide which platform owns each widget;
without that agreement the same widget could be emitted twice (or not at all).
"""

import logging
from typing import Any

from homeassistant.components import binary_sensor
from homeassistant.components.sensor.const import SensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_PARAMS,
    CONF_TYPE,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType, UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    widget_unit,
)
from .entity import TileEntity, controller_device_info
from .schedules import schedule_problem

_LOGGER = logging.getLogger(__name__)


def _sibling_widget(tile_params: dict, widget_key: str) -> dict | None:
    """Return the tile's other widget payload, when it carries one.

    A TYPE_WIDGET tile has exactly two slots, so the sibling is simply the one
    ``widget_key`` does not name.

    Args:
        tile_params: The tile's ``params`` dict.
        widget_key: ``widget1`` or ``widget2`` -- the slot being classified.

    Returns:
        The other slot's payload, or ``None`` when that slot is empty.

    """
    other_key = "widget2" if widget_key == "widget1" else "widget1"
    return tile_params.get(other_key) or None


def _is_contact_marker(widget: dict | None) -> bool:
    """Return True for the per-widget half of the dry-contact marker.

    The marker triple this tests is documented on the mirrored predicate in
    :func:`sensor._is_contact_marker`.
    """
    return bool(widget) and (
        widget.get("unit") == -1
        and widget.get(CONF_TYPE) == 0
        and widget.get("txtId", 0) != 0
    )


def _is_contact_widget(widget: dict, sibling: dict | None) -> bool:
    """Return ``True`` for widgets that should be exposed as binary contacts.

    The rule this tests is documented on the mirrored predicate in
    :func:`sensor._is_contact_widget`: contacts come as a tile built entirely of
    contact widgets, so a lone ``unit == -1`` widget next to a visible reading
    is an invisible value rather than a contact. Both modules have to agree on
    which widgets they own, or a widget is claimed twice or not at all.
    """
    return _is_contact_marker(widget) and (sibling is None or _is_contact_marker(sibling))


def _widget_txt_id(widget: dict, sibling: dict | None = None) -> int:
    """Return the label a widget is named by, borrowing its sibling's.

    The marker triple this borrows on is documented on the mirrored helper in
    :func:`sensor._widget_txt_id`.
    """
    return widget.get("txtId") or (sibling or {}).get("txtId", 0)


def _is_flag_widget(widget: dict, sibling: dict | None) -> bool:
    """Return ``True`` for enable/disable widgets (API value type 28).

    The API documents value type 28 as "Enabled / Disabled - [1/0]", which is a
    state rather than a measurement, so these widgets belong here instead of the
    sensor platform. The widget ``type`` is deliberately not checked: real
    payloads carry these as ``type == 1``, unlike the ``type == 0`` contact
    marker. A widget without a label of its own is named after its sibling --
    heat pumps label their settings that way (issue #221) -- and one with no
    label anywhere is skipped, as everywhere else.
    """
    return widget.get("unit") == 28 and _widget_txt_id(widget, sibling) != 0


def _has_pump_widget(params: dict) -> bool:
    """Return ``True`` if the tile carries a pump widget that reads a pump value.

    Pump-type widgets (``type=1`` = WIDGET_DHW_PUMP, ``type=2`` =
    WIDGET_COLLECTOR_PUMP) indicate the tile represents a pump whose
    ``statusId`` carries ON/OFF semantics. Heat pumps use those subtypes for
    *every* reading, so the widget's value type has to agree as well: only a
    temperature or a percentage is a pump quantity, and without that check a
    pressure, energy, flow or runtime tile raises a phantom ON/OFF sensor
    (issue #221 -- 51 of the Kołton's tiles qualified before this).
    """
    for key in ("widget1", "widget2"):
        widget = params.get(key)
        if not widget or widget.get(CONF_TYPE) not in (
            WIDGET_DHW_PUMP,
            WIDGET_COLLECTOR_PUMP,
        ):
            continue
        metadata = widget_unit(widget.get("unit"))
        if (
            metadata.device_class == SensorDeviceClass.TEMPERATURE
            or metadata.unit == PERCENTAGE
        ):
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
            params = tile.get(CONF_PARAMS, {})
            for widget_key in ("widget1", "widget2"):
                widget = params.get(widget_key)
                if not widget:
                    continue
                sibling = _sibling_widget(params, widget_key)
                if _is_flag_widget(widget, sibling):
                    entities.append(
                        TileWidgetFlagSensor(
                            tile, coordinator, config_entry, widget_key
                        )
                    )
                if _is_contact_widget(widget, sibling):
                    entities.append(
                        TileWidgetContactSensor(
                            tile, coordinator, config_entry, widget_key
                        )
                    )
            # TYPE_WIDGET tiles with statusId 0 or 1 carry ON/OFF state for
            # PWM-controlled pumps (e.g. solar collector). Only emit the binary
            # sensor when the tile carries a pump widget that reads a pump
            # quantity -- a temperature or a percentage -- so that a pressure,
            # energy or runtime tile does not raise a phantom ON/OFF entity
            # (issue #221). Pure temperature or contact widgets always report
            # statusId=1 and never toggle.
            status_id = tile.get(CONF_PARAMS, {}).get("statusId")
            if status_id in (0, 1) and _has_pump_widget(tile.get(CONF_PARAMS, {})):
                entities.append(
                    TileWidgetStatusSensor(tile, coordinator, config_entry)
                )

    schedule_data = (coordinator.data or {}).get("schedules")
    if isinstance(schedule_data, dict) and schedule_data.get("supported"):
        entities.append(ScheduleProblemSensor(coordinator, config_entry))

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
    Exposed as an opening device-class binary sensor; ON/OFF state comes from
    the tile-level ``params.statusId`` (1=ON, 0=OFF), which is how the emodul
    UI renders contact state — the individual widget ``value`` field is always
    0 for contact widgets in the API response.
    """

    _UNIQUE_ID_SUFFIX = "tile_widget_contact"
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
        # txtId. A widget without a label of its own borrows the sibling's -
        # which is how a value type 28 flag is labelled, since its label sits
        # on the widget next to it. ``_attr_has_entity_name = True`` lets HA
        # prepend the device.
        self._name = coordinator.translations.get_text(
            _widget_txt_id(widget, _sibling_widget(device[CONF_PARAMS], widget_key))
        )
        icon_id = device[CONF_PARAMS].get("iconId")
        if icon_id:
            self._attr_icon = assets.get_icon(icon_id)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_{self._UNIQUE_ID_SUFFIX}_{self._widget_key}"

    def get_state(self, device):
        """Return the contact state from the tile's statusId.

        The emodul UI derives contact ON/OFF from ``params.statusId``
        (1=ON, 0=OFF), not from the individual widget ``value`` which
        is always 0 for contact widgets in the API response.
        """
        return device[CONF_PARAMS].get("statusId") == 1


class TileWidgetFlagSensor(TileWidgetContactSensor):
    """A widget-shaped enable/disable flag (API value type 28).

    Detected by ``unit == 28``. The API names the state "Enabled / Disabled"
    without naming a device class, so this one carries none; ``value == 1``
    means enabled.
    """

    _UNIQUE_ID_SUFFIX = "tile_widget_flag"
    _attr_device_class = None

    def get_state(self, device):
        """Return the flag state from its own widget value.

        Unlike a contact, whose state lives in the tile's ``statusId``, a value
        type 28 widget reports its state in its own ``value``: the API documents
        it as "Enabled / Disabled - [1/0]" and real payloads carry non-zero
        values, so inheriting :meth:`TileWidgetContactSensor.get_state` would
        read the wrong field.
        """
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
        # Override the name from TileEntity's "type 6" fallback to the
        # pump widget's own label (e.g. "Pompa solarna"). Iterate widgets
        # in order so widget1's txtId wins when both carry labels.
        params = device.get(CONF_PARAMS, {})
        for key in ("widget1", "widget2"):
            widget = params.get(key, {})
            if widget.get(CONF_TYPE) in (WIDGET_DHW_PUMP, WIDGET_COLLECTOR_PUMP):
                txt_id = widget.get("txtId", 0)
                if txt_id > 0:
                    self._name = coordinator.translations.get_text(txt_id)
                    break

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


class ScheduleProblemSensor(CoordinatorEntity, binary_sensor.BinarySensorEntity):
    """Controller-level read-only indicator for unusable selected schedules."""

    _attr_device_class = binary_sensor.BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "schedule_problem_entity"
    _attr_entity_registry_enabled_default = True

    def __init__(self, coordinator: TechCoordinator, config_entry: ConfigEntry) -> None:
        """Bind to the existing coordinator without an additional API read."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]

    @property
    def unique_id(self) -> str:
        """Keep one stable entity identity per physical controller."""
        return f"{self._udid}_schedule_problem"

    @property
    def device_info(self) -> DeviceInfo:
        """Attach to the shared controller device."""
        return controller_device_info(self._config_entry)

    def _schedule_data(self) -> Any:
        """Return the current schedule snapshot."""
        return (self.coordinator.data or {}).get("schedules")

    @property
    def available(self) -> bool:
        """Become unavailable when the schedule snapshot disappears."""
        return super().available and isinstance(self._schedule_data(), dict)

    @property
    def is_on(self) -> bool | None:
        """Report a problem only for a selected schedule that is actually broken."""
        data = self._schedule_data()
        if not self.coordinator.last_update_success or not isinstance(data, dict):
            return None
        return schedule_problem(data, True)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Write the coordinator's schedule problem state."""
        self.async_write_ha_state()
