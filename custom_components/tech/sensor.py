"""Sensor platform for the Tech Sterowniki integration.

The platform creates two distinct families of entities:

* **Zone sensors** -- battery, temperature, humidity, signal, alarm,
  actuator and window descriptors derived from the ``zones.elements``
  array of the /modules/{udid} response. Created only for controllers
  that expose climate zones (e.g. L-12 underfloor).
* **Tile sensors** -- numeric/text readings emitted from individual
  tiles in the ``tiles`` array. Tile creation is dispatched through
  :data:`_TILE_ENTITY_BUILDERS`, which maps each tile ``type`` constant
  to a builder function. New tile types are added by registering a
  builder there.

A single tile may emit several entities. Examples:

* a TYPE_TEMPERATURE tile with battery + signal yields a temperature,
  battery and signal entity (and creates its own DeviceInfo);
* a TYPE_VALVE tile yields a valve-percentage entity plus zero, one,
  or several valve-temperature entities (return / set / current);
* a TYPE_WIDGET tile yields one entity per non-empty widget, each
  named from its own ``txtId`` -- this fixes the long-standing bug
  where stock TileWidgetSensor read only widget1 and silently
  dropped CH/DHW temperatures (issues #132 / #144 upstream).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import Any, cast

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.sensor.const import SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_MODEL,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
    CONF_ZONE,
    PERCENTAGE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.icon import icon_for_signal_level
from homeassistant.helpers.typing import UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    ACTUATORS,
    ACTUATORS_OPEN,
    BATTERY_LEVEL,
    CONTROLLER,
    CORRECT_WORK,
    CURRENT_STATE,
    DOMAIN,
    EVENTS,
    FLOOR_PUMP,
    INCLUDE_HUB_IN_NAME,
    LOW_BATTERY,
    LOW_SIGNAL,
    MANUFACTURER,
    MODE,
    NO_COMMUNICATION,
    OPENTHERM_CURRENT_TEMP,
    OPENTHERM_CURRENT_TEMP_DHW,
    OPENTHERM_MODULATION,
    OPENTHERM_SET_TEMP,
    OPENTHERM_SET_TEMP_DHW,
    SENSOR_DAMAGED,
    SENSOR_TYPE,
    SERVICE_ERROR,
    SIGNAL_STRENGTH,
    TEMP_TOO_HIGH,
    TEMP_TOO_LOW,
    TYPE_DISINFECTION,
    TYPE_FAN,
    TYPE_FUEL_SUPPLY,
    TYPE_MIXING_VALVE,
    TYPE_OPEN_THERM,
    TYPE_TEMPERATURE,
    TYPE_TEXT,
    TYPE_VALVE,
    TYPE_WIDGET,
    UDID,
    UNDERFLOOR,
    VALUE,
    VALVE_SENSOR_CURRENT_TEMPERATURE,
    VALVE_SENSOR_RETURN_TEMPERATURE,
    VALVE_SENSOR_SET_TEMPERATURE,
    VER,
    VISIBILITY,
    WIDGET_COLLECTOR_PUMP,
    WIDGET_DHW_PUMP,
    WIDGET_UNIT_DIVISORS,
    WINDOW_SENSORS,
    WINDOW_STATE,
    WORKING_STATUS,
    ZONE_STATE,
)
from .coordinator import TechCoordinator
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech sensor entities for the provided config entry.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller metadata.
        async_add_entities: Callback used to register entities with Home Assistant.

    """
    controller_udid = config_entry.data[CONTROLLER][UDID]
    _LOGGER.debug("Setting up sensor entry, controller udid: %s", controller_udid)

    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    zones = await coordinator.api.get_module_zones(controller_udid)
    tiles = await coordinator.api.get_module_tiles(controller_udid)

    zone_entities = [
        entity
        for zone in _iter_mapping(zones)
        for entity in _build_zone_entities(zone, coordinator, config_entry)
    ]

    tile_entities = [
        entity
        for tile in _iter_mapping(tiles)
        for entity in _build_tile_entities(tile, coordinator, config_entry)
    ]

    async_add_entities([*tile_entities, *zone_entities], True)


def _iter_mapping(mapping: dict[Any, Any] | Iterable[Any]) -> Iterable[Any]:
    """Yield mapping values regardless of whether ``mapping`` is a dict or list."""
    if not mapping:
        return ()
    if isinstance(mapping, dict):
        return mapping.values()
    return mapping


def _build_zone_entities(
    zone: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create coordinator entities for a single zone payload."""

    entities: list[CoordinatorEntity] = []
    zone_state = zone.get(CONF_ZONE, {})

    if zone_state.get(BATTERY_LEVEL) is not None:
        entities.append(ZoneBatterySensor(zone, coordinator, config_entry))

    if zone_state.get("currentTemperature") is not None:
        entities.append(ZoneTemperatureSensor(zone, coordinator, config_entry))

    if zone_state.get(ZONE_STATE) is not None:
        entities.append(ZoneStateSensor(zone, coordinator, config_entry))

    humidity = zone_state.get("humidity")
    if humidity is not None and humidity >= 0:
        entities.append(ZoneHumiditySensor(zone, coordinator, config_entry))

    if zone_state.get(SIGNAL_STRENGTH) is not None:
        entities.append(ZoneSignalStrengthSensor(zone, coordinator, config_entry))

    for idx, _ in enumerate(zone.get(ACTUATORS, [])):
        entities.append(ZoneActuatorSensor(zone, coordinator, config_entry, idx))

    for idx, _ in enumerate(zone.get(WINDOW_SENSORS, [])):
        entities.append(ZoneWindowSensor(zone, coordinator, config_entry, idx))

    if isinstance(zone.get(UNDERFLOOR), dict) and zone.get(UNDERFLOOR):
        entities.append(ZoneUnderfloorSensor(zone, coordinator, config_entry))

    return entities


TileBuilder = Callable[
    [dict[str, Any], TechCoordinator, ConfigEntry], list[CoordinatorEntity]
]


def _build_tile_entities(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create coordinator entities for a single tile payload."""

    if not tile.get(VISIBILITY, False) or not tile.get(WORKING_STATUS, True):
        return []

    builder = _TILE_ENTITY_BUILDERS.get(tile[CONF_TYPE])
    if builder is None:
        return []
    return builder(tile, coordinator, config_entry)


def _build_temperature_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create entities for a temperature tile and its optional sensors."""
    params = tile.get(CONF_PARAMS, {})

    def _has_value(value: Any) -> bool:
        return value not in (None, "null")

    create_device = any(
        _has_value(params.get(key)) for key in (SIGNAL_STRENGTH, BATTERY_LEVEL)
    )

    entities: list[CoordinatorEntity] = [
        TileTemperatureSensor(tile, coordinator, config_entry, create_device)
    ]

    if _has_value(params.get(SIGNAL_STRENGTH)):
        entities.append(
            TileTemperatureSignalSensor(tile, coordinator, config_entry, create_device)
        )
    if _has_value(params.get(BATTERY_LEVEL)):
        entities.append(
            TileTemperatureBatterySensor(tile, coordinator, config_entry, create_device)
        )

    return entities


def _build_valve_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create valve-related entities for a tile payload."""
    entities: list[CoordinatorEntity] = [
        TileValveSensor(tile, coordinator, config_entry)
    ]

    for valve_sensor in (
        VALVE_SENSOR_RETURN_TEMPERATURE,
        VALVE_SENSOR_SET_TEMPERATURE,
        VALVE_SENSOR_CURRENT_TEMPERATURE,
    ):
        if tile[CONF_PARAMS].get(valve_sensor["state_key"]) is not None:
            entities.append(
                TileValveTemperatureSensor(
                    tile, coordinator, config_entry, valve_sensor
                )
            )

    return entities


def _build_open_therm_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create OpenTherm entities for a tile payload."""
    entities: list[CoordinatorEntity] = []
    # Create temperature entities
    for description in (
        OPENTHERM_CURRENT_TEMP,
        OPENTHERM_SET_TEMP,
        OPENTHERM_CURRENT_TEMP_DHW,
        OPENTHERM_SET_TEMP_DHW,
    ):
        if tile[CONF_PARAMS].get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermTemperatureSensor(
                    tile, coordinator, config_entry, description
                )
            )
    # Create percentage entities
    for description in (OPENTHERM_MODULATION,):
        if tile[CONF_PARAMS].get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermPercentageSensor(
                    tile, coordinator, config_entry, description
                )
            )
    # Return the list of discovered entities
    return entities


def _is_contact_widget(widget: dict[str, Any]) -> bool:
    """Return True for widgets that should be modelled as a binary contact sensor.

    Tech encodes a "dry contact" / voltage input on a TYPE_WIDGET tile by
    the marker triple ``unit == -1``, ``type == 0`` and a non-zero ``txtId``.
    EU-i-3+ extension modules expose all four of their inputs this way.

    The contact branch is mirrored by the same predicate in
    :mod:`binary_sensor` -- both modules need to agree on which widgets
    they own, so :func:`_build_widget_tile` *skips* contact widgets here
    and lets the binary_sensor platform create
    :class:`binary_sensor.TileWidgetContactSensor` for them instead.
    """
    return (
        widget.get("unit") == -1
        and widget.get(CONF_TYPE) == 0
        and widget.get("txtId", 0) != 0
    )


def _build_widget_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Build entities from a TYPE_WIDGET (=6) tile.

    Tech's "Universal status with widgets" tile shape::

        {
            "type": 6,
            "params": {
                "iconId": <int>,
                "statusId": <int>,
                "widget1": {"txtId": ..., "value": ..., "unit": ..., "type": ...},
                "widget2": {"txtId": ..., "value": ..., "unit": ..., "type": ...}
            }
        }

    Each widget is an independent reading. The widget's *inner* ``type``
    field selects the semantic class (see :data:`const.WIDGET_DHW_PUMP`,
    :data:`const.WIDGET_COLLECTOR_PUMP`, :data:`const.WIDGET_TEMPERATURE_CH`),
    while the ``unit`` field decides how to scale the integer ``value``
    (see :data:`const.WIDGET_UNIT_DIVISORS`).

    Filtering rules applied in order:

    1. Widgets with ``txtId == 0`` are placeholders -- skip.
    2. Contact-shaped widgets (``unit==-1, type==0, txtId!=0``) belong to
       :mod:`binary_sensor`; skip here so they are not emitted twice.
    3. ``unit == 6`` widgets are decorative state badges (always 0 in the
       wild); skip to avoid useless "always 0" sensors.
    4. WIDGET_COLLECTOR_PUMP -> :class:`TileWidgetPumpSensor` (percentage).
    5. Everything else (DHW set/current temp, CH temp, generic
       ``type==0`` numeric) -> :class:`TileWidgetTemperatureSensor`,
       which applies unit-aware scaling at read time.

    Returns:
        Zero, one, or two coordinator entities -- the upstream registration
        loop in :func:`async_setup_entry` flattens the results.

    """
    entities: list[CoordinatorEntity] = []
    params = tile.get(CONF_PARAMS, {})
    for widget_key in ("widget1", "widget2"):
        widget = params.get(widget_key)
        if not widget or widget.get("txtId", 0) == 0:
            continue
        if _is_contact_widget(widget):
            continue
        if widget.get("unit") == 6:
            continue
        widget_type = widget.get(CONF_TYPE)
        if widget_type == WIDGET_COLLECTOR_PUMP:
            entities.append(
                TileWidgetPumpSensor(tile, coordinator, config_entry, widget_key)
            )
        else:
            # WIDGET_DHW_PUMP, WIDGET_TEMPERATURE_CH and any unknown numeric
            # widget (most commonly ``type == 0``) all flow through the
            # temperature class. Scaling is driven by the widget's own
            # ``unit`` field, not by the widget type, so an unknown numeric
            # type is still rendered correctly so long as ``unit`` is one of
            # the documented values in :data:`const.WIDGET_UNIT_DIVISORS`.
            entities.append(
                TileWidgetTemperatureSensor(
                    tile, coordinator, config_entry, widget_key
                )
            )
    return entities


_TILE_ENTITY_BUILDERS: dict[int, TileBuilder] = {
    TYPE_TEMPERATURE: _build_temperature_tile,
    TYPE_WIDGET: _build_widget_tile,
    TYPE_FAN: lambda tile, coordinator, config_entry: [
        TileFanSensor(tile, coordinator, config_entry)
    ],
    TYPE_VALVE: _build_valve_tile,
    TYPE_MIXING_VALVE: lambda tile, coordinator, config_entry: [
        TileMixingValveSensor(tile, coordinator, config_entry)
    ],
    TYPE_FUEL_SUPPLY: lambda tile, coordinator, config_entry: [
        TileFuelSupplySensor(tile, coordinator, config_entry)
    ],
    TYPE_DISINFECTION: lambda tile, coordinator, config_entry: [
        TileDisinfectionSensor(tile, coordinator, config_entry)
    ],
    TYPE_TEXT: lambda tile, coordinator, config_entry: [
        TileTextSensor(tile, coordinator, config_entry)
    ],
    TYPE_OPEN_THERM: _build_open_therm_tile,
}


class TechBatterySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech battery sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator: TechCoordinator, config_entry) -> None:
        """Initialize the Tech battery sensor."""
        _LOGGER.debug("Init TechBatterySensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][BATTERY_LEVEL]

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_battery"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "battery_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} battery"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech temperature sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech temperature sensor."""
        _LOGGER.debug("Init TechTemperatureSensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the current temperature is available, and update the native value accordingly
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._attr_native_value = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "temperature_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechOutsideTempTile(CoordinatorEntity, SensorEntity):
    """Representation of a Tech outside temperature tile sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech temperature sensor."""
        _LOGGER.debug("Init TechOutsideTemperatureTile... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)
        _LOGGER.debug(
            "Init TechOutsideTemperatureTile...: %s, udid: %s, id: %s",
            self._name,
            self._config_entry.data[CONTROLLER][UDID],
            self._id,
        )

    def update_properties(self, device):
        """Update native values from an outside temperature tile payload.

        Args:
            device: Tile dictionary containing temperature information.

        """
        self._name = "outside_" + str(device[CONF_ID])

        if device[CONF_PARAMS][VALUE] is not None:
            # Update the native value based on the device params
            self._attr_native_value = device[CONF_PARAMS][VALUE] / 10
        else:
            # Set native value to None if device params value is None
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["tiles"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_out_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "ext_temperature_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} temperature"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class TechHumiditySensor(CoordinatorEntity, SensorEntity):
    """Representation of a Tech humidity sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the Tech humidity sensor."""
        _LOGGER.debug("Init TechHumiditySensor... ")
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self.update_properties(device)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the humidity value is not zero and update the native value attribute accordingly
        if device[CONF_ZONE]["humidity"] != 0:
            self._attr_native_value = device[CONF_ZONE]["humidity"]
        else:
            self._attr_native_value = None

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_humidity"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "humidity_entity"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} humidity"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }


class ZoneSensor(CoordinatorEntity, SensorEntity):
    """Representation of a Zone Sensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True

    def __init__(
        self, device: dict, coordinator: TechCoordinator, config_entry: ConfigEntry
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._id = device[CONF_ZONE][CONF_ID]
        self._unique_id = (
            config_entry.data[CONTROLLER][UDID] + "_" + str(device[CONF_ZONE][CONF_ID])
        )
        self._device_name = (
            device[CONF_DESCRIPTION][CONF_NAME]
            if not self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else f"{self._config_entry.title} {device[CONF_DESCRIPTION][CONF_NAME]}"
        )
        self._model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._manufacturer = MANUFACTURER
        self._attr_translation_placeholders = {"entity_name": ""}
        self.update_properties(device)

    def update_properties(self, device):
        """Update cached zone values from the latest coordinator payload.

        Args:
            device: Zone dictionary containing description and telemetry data.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update target_temperature property
        if device[CONF_ZONE]["setTemperature"] is not None:
            self._target_temperature = device[CONF_ZONE]["setTemperature"] / 10
        else:
            self._target_temperature = None

        # Update temperature property
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._temperature = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._temperature = None

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self._coordinator.data["zones"][self._id])
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the associated controller."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self._device_name,  # Name of the device
            CONF_MODEL: self._model,  # Model of the device
            ATTR_MANUFACTURER: self._manufacturer,  # Manufacturer of the device
        }

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id


class ZoneTemperatureSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "temperature_entity"

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the current temperature is available, and update the native value accordingly
        if device[CONF_ZONE]["currentTemperature"] is not None:
            self._attr_native_value = device[CONF_ZONE]["currentTemperature"] / 10
        else:
            self._attr_native_value = None


class ZoneBatterySensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "battery_entity"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_battery"

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][BATTERY_LEVEL]


class ZoneSignalStrengthSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "signal_strength_entity"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    def update_properties(self, device):
        """Update native values from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]
        self._attr_native_value = device[CONF_ZONE][SIGNAL_STRENGTH]


class ZoneHumiditySensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_humidity"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "humidity_entity"

    def update_properties(self, device):
        """Update the properties of the TechHumiditySensor object.

        Args:
        device (dict): The device information.

        Returns:
        None

        """
        # Update the name of the device
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the humidity value is not zero and update the native value attribute accordingly
        if device[CONF_ZONE]["humidity"] != 0:
            self._attr_native_value = device[CONF_ZONE]["humidity"]
        else:
            self._attr_native_value = None


class ZoneActuatorSensor(ZoneSensor):
    """Representation of a Zone Actuator Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = assets.get_icon_by_type(TYPE_VALVE)

    def __init__(self, device, coordinator, config_entry, actuator_index) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _actuator_index already.

        """
        self._actuator_index = actuator_index
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "actuator_entity"
        self._attr_translation_placeholders = {
            "actuator_number": f"{cast(int, self._actuator_index) + 1}"
        }
        self.attrs[BATTERY_LEVEL] = device[ACTUATORS][self._actuator_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[ACTUATORS][self._actuator_index][
            SIGNAL_STRENGTH
        ]

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_actuator_{self._actuator_index + 1!s}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update the native value attribute
        self._attr_native_value = device[CONF_ZONE][ACTUATORS_OPEN]

        # Update battery and signal strength
        self.attrs[BATTERY_LEVEL] = device[ACTUATORS][self._actuator_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[ACTUATORS][self._actuator_index][
            SIGNAL_STRENGTH
        ]


class ZoneWindowSensor(BinarySensorEntity, ZoneSensor):
    """Representation of a Zone Window Sensor."""

    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, device, coordinator, config_entry, window_index) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _window_index already.

        """
        self._window_index = window_index
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "window_sensor_entity"
        self._attr_translation_placeholders = {
            "window_number": f"{cast(int, self._window_index) + 1}"
        }
        self.attrs[BATTERY_LEVEL] = device[WINDOW_SENSORS][self._window_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[WINDOW_SENSORS][self._window_index][
            SIGNAL_STRENGTH
        ]
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_window_{self._window_index + 1!s}"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Update battery and signal strength
        self.attrs[BATTERY_LEVEL] = device[WINDOW_SENSORS][self._window_index][
            BATTERY_LEVEL
        ]
        self.attrs[SIGNAL_STRENGTH] = device[WINDOW_SENSORS][self._window_index][
            SIGNAL_STRENGTH
        ]
        self._attr_is_on = (
            device[WINDOW_SENSORS][self._window_index][WINDOW_STATE] == "open"
        )


class ZoneUnderfloorSensor(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs yet.

        """
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self.attrs[MODE] = device[UNDERFLOOR][MODE]
        self.attrs[CURRENT_STATE] = device[UNDERFLOOR][CURRENT_STATE]
        self.attrs[FLOOR_PUMP] = device[UNDERFLOOR][FLOOR_PUMP]
        self.attrs[SENSOR_TYPE] = device[UNDERFLOOR][SENSOR_TYPE]
        self.attrs[CORRECT_WORK] = device[UNDERFLOOR][EVENTS][CORRECT_WORK]
        self.attrs[NO_COMMUNICATION] = device[UNDERFLOOR][EVENTS][NO_COMMUNICATION]
        self.attrs[SENSOR_DAMAGED] = device[UNDERFLOOR][EVENTS][SENSOR_DAMAGED]  # noqa: F821
        self.attrs[LOW_BATTERY] = device[UNDERFLOOR][EVENTS][LOW_BATTERY]
        self.attrs[LOW_SIGNAL] = device[UNDERFLOOR][EVENTS][LOW_SIGNAL]
        self.attrs[TEMP_TOO_HIGH] = device[UNDERFLOOR][EVENTS][TEMP_TOO_HIGH]
        self.attrs[TEMP_TOO_LOW] = device[UNDERFLOOR][EVENTS][TEMP_TOO_LOW]
        self.attrs[SERVICE_ERROR] = device[UNDERFLOOR][EVENTS][SERVICE_ERROR]
        self.attrs[SIGNAL_STRENGTH] = device[UNDERFLOOR][SIGNAL_STRENGTH]
        self.attrs[BATTERY_LEVEL] = device[UNDERFLOOR][BATTERY_LEVEL]

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_underfloor"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "underfloor_entity"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update the properties of the ZoneUnderfloorSensor object.

        Args:
        device: dict, the device data containing information about the device

        Returns:
        None

        """
        # Set the name of the device
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        # Check if the current temperature is available, and update the native value accordingly
        if device[UNDERFLOOR]["temperature"] is not None:
            self._attr_native_value = device[UNDERFLOOR]["temperature"] / 10
        else:
            self._attr_native_value = None

        # Update attributes
        self.attrs[MODE] = device[UNDERFLOOR][MODE]
        self.attrs[CURRENT_STATE] = device[UNDERFLOOR][CURRENT_STATE]
        self.attrs[FLOOR_PUMP] = device[UNDERFLOOR][FLOOR_PUMP]
        self.attrs[SENSOR_TYPE] = device[UNDERFLOOR][SENSOR_TYPE]
        self.attrs[CORRECT_WORK] = device[UNDERFLOOR][EVENTS][CORRECT_WORK]
        self.attrs[NO_COMMUNICATION] = device[UNDERFLOOR][EVENTS][NO_COMMUNICATION]
        self.attrs[SENSOR_DAMAGED] = device[UNDERFLOOR][EVENTS][SENSOR_DAMAGED]  # noqa: F821
        self.attrs[LOW_BATTERY] = device[UNDERFLOOR][EVENTS][LOW_BATTERY]
        self.attrs[LOW_SIGNAL] = device[UNDERFLOOR][EVENTS][LOW_SIGNAL]
        self.attrs[TEMP_TOO_HIGH] = device[UNDERFLOOR][EVENTS][TEMP_TOO_HIGH]
        self.attrs[TEMP_TOO_LOW] = device[UNDERFLOOR][EVENTS][TEMP_TOO_LOW]
        self.attrs[SERVICE_ERROR] = device[UNDERFLOOR][EVENTS][SERVICE_ERROR]
        self.attrs[SIGNAL_STRENGTH] = device[UNDERFLOOR][SIGNAL_STRENGTH]
        self.attrs[BATTERY_LEVEL] = device[UNDERFLOOR][BATTERY_LEVEL]


class ZoneOutsideTempTile(ZoneSensor):
    """Representation of a Zone Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_out_temperature"

    @property
    def translation_key(self):
        """Return the translation key to translate the entity's name and states."""
        return "ext_temperature_entity"

    def update_properties(self, device):
        """Update native attributes from the provided tile payload.

        Args:
            device: Tile dictionary containing temperature information.

        """
        self._name = "outside_" + str(device[CONF_ID])

        if device[CONF_PARAMS][VALUE] is not None:
            # Update the native value based on the device params
            self._attr_native_value = device[CONF_PARAMS][VALUE] / 10
        else:
            # Set native value to None if device params value is None
            self._attr_native_value = None


class ZoneStateSensor(BinarySensorEntity, ZoneSensor):
    """Representation of a Zone State (alarm) Sensor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor.

        These are needed before the call to super, as ZoneSensor class
        calls update_properties in its init, which actually calls this class
        update_properties, which does not know attrs and _window_index already.

        """
        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"
        self.attrs: dict[str, Any] = {}
        super().__init__(device, coordinator, config_entry)
        self._attr_translation_key = "zone_state_entity"
        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_zone_state"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update native attributes from the provided zone payload.

        Args:
            device: Zone dictionary containing the latest telemetry values.

        """
        self._name = device[CONF_DESCRIPTION][CONF_NAME]

        self.attrs[ZONE_STATE] = device[CONF_ZONE][ZONE_STATE]

        self._attr_is_on = device[CONF_ZONE][ZONE_STATE] != "noAlarm"


class TileSensor(TileEntity, CoordinatorEntity):
    """Representation of a TileSensor."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def get_state(self, device) -> Any:
        """Get the state of the device."""


class TileTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT
        # self.device_name = device[CONF_DESCRIPTION][CONF_NAME]
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "temperature_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][VALUE] / 10

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""

        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        # Fall back to the controller-level device defined in TileEntity so
        # tile-derived entities still get grouped on zone-less controllers.
        return super().device_info


class TileTemperatureBatterySensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Battery Sensor."""

    _attr_has_entity_name = True

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "battery_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_battery"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][BATTERY_LEVEL]

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""

        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        # Fall back to the controller-level device defined in TileEntity so
        # tile-derived entities still get grouped on zone-less controllers.
        return super().device_info


class TileTemperatureSignalSensor(TileSensor, SensorEntity):
    """Representation of a Tile Temperature Signal Sensor."""

    _attr_has_entity_name = True

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:signal"

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        create_device: bool = False,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.manufacturer = MANUFACTURER
        self.model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._attr_translation_key = "signal_strength_entity"
        self._attr_translation_placeholders = (
            {"entity_name": ""} if create_device else {"entity_name": f"{self._name}"}
        )
        self._create_device = create_device

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_temperature_signal_strength"

    @property
    def icon(self) -> str | None:
        """Icon of the entity, based on signal strength."""
        return icon_for_signal_level(self.state)

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][SIGNAL_STRENGTH]

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        if self._create_device:
            return {
                ATTR_IDENTIFIERS: {
                    (DOMAIN, self._unique_id)
                },  # Unique identifiers for the device
                CONF_NAME: self._name,  # Name of the device
                CONF_MODEL: self.model,  # Model of the device
                ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
            }
        return None


class TileFuelSupplySensor(TileSensor, SensorEntity):
    """Representation of a Tile Fuel Supply Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fuel_supply"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["percentage"]


class TileFanSensor(TileSensor, SensorEntity):
    """Representation of a Tile Fan Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_fan"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["gear"]


class TileTextSensor(TileSensor, SensorEntity):
    """Representation of a Tile Text Sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = assets.get_text(device[CONF_PARAMS]["headerId"])

        self._attr_icon = assets.get_icon(device[CONF_PARAMS]["iconId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_text"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return assets.get_text(device[CONF_PARAMS]["statusId"])


class _TileWidgetSensorBase(TileSensor, SensorEntity):
    """Common scaffolding for TYPE_WIDGET-derived sensor entities.

    Widget-backed sensors share three pieces of behaviour:

    * **Indexing** -- a single TYPE_WIDGET tile yields up to two
      sub-entities; ``self._widget_key`` selects ``widget1`` or
      ``widget2`` so each one's :meth:`get_state` reads the right slot.
    * **Naming** -- the entity name is derived from the widget's own
      ``txtId``. If a widget carries no label of its own (txtId 0), the
      sibling widget's label is borrowed so the resulting name still
      reflects the tile's purpose. DHW pump widgets get a "Set Temperature"
      / "Current Temperature" suffix to disambiguate the two slots, since
      both share the same ``txtId``.
    * **Unique ID namespacing** -- ``_UNIQUE_ID_SUFFIX`` plus
      ``self._widget_key`` make the unique_id distinct per widget slot,
      preventing the collisions that the old single-class implementation
      hit when both widgets were exposed.
    """

    _UNIQUE_ID_SUFFIX = "tile_widget"
    _NAME_SUFFIX_FOR_DHW: dict[str, str] = {
        "widget1": " Set Temperature",
        "widget2": " Current Temperature",
    }

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        widget_key: str,
    ) -> None:
        """Initialise a widget-backed sensor.

        Args:
            device: Tile payload returned by the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry providing controller metadata.
            widget_key: Either ``"widget1"`` or ``"widget2"`` -- selects which
                payload entry within the tile this entity represents.

        """
        self._widget_key = widget_key
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = self._build_name(device)

    def _build_name(self, device) -> str:
        params = device[CONF_PARAMS]
        widget = params[self._widget_key]
        txt_id = widget.get("txtId", 0)
        # If this widget has no label (txtId 0), borrow it from its sibling so
        # the entity name still reflects the tile's purpose.
        if txt_id == 0:
            other = "widget2" if self._widget_key == "widget1" else "widget1"
            txt_id = params.get(other, {}).get("txtId", 0)
        suffix = ""
        if widget.get(CONF_TYPE) == WIDGET_DHW_PUMP:
            suffix = self._NAME_SUFFIX_FOR_DHW.get(self._widget_key, "")
        return f"{assets.get_text(txt_id)}{suffix}"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_{self._UNIQUE_ID_SUFFIX}_{self._widget_key}"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name


class TileWidgetTemperatureSensor(_TileWidgetSensorBase):
    """A TYPE_WIDGET widget reporting a (scaled) temperature value."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _UNIQUE_ID_SUFFIX = "tile_widget_temperature"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        widget = device[CONF_PARAMS][self._widget_key]
        divisor = WIDGET_UNIT_DIVISORS.get(widget.get("unit"), 1)
        return widget[VALUE] / divisor if divisor != 1 else widget[VALUE]


class TileWidgetPumpSensor(_TileWidgetSensorBase):
    """A TYPE_WIDGET widget reporting a pump duty-cycle percentage."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:arrow-right-drop-circle-outline"
    _UNIQUE_ID_SUFFIX = "tile_widget_pump"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][self._widget_key][VALUE]


class TileDisinfectionSensor(TileSensor, SensorEntity):
    """Disinfection-cycle progress for boilers exposing a TYPE_DISINFECTION tile.

    The tile's ``txtId`` points at a *status* string ("Disabled" / "Active"),
    not the entity name, so we use the JSON ``description`` ("Disinfection") as
    a stable language-independent label instead.
    """

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:shield-sun"

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialise the disinfection sensor.

        ``TileEntity.__init__`` already resolves the name from the type-level
        txtId fallback (``TXT_ID_BY_TYPE[TYPE_DISINFECTION] = 246``, "Dezynfekcja")
        because TYPE_DISINFECTION is registered in ``TXT_ID_IS_STATUS_FOR_TYPES``.
        """
        TileSensor.__init__(self, device, coordinator, config_entry)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_disinfection"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS].get("percentage", 0)


class TileValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = assets.get_text_by_type(device[CONF_TYPE])

        self.attrs: dict[str, Any] = {}

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_valve"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} {self._valve_number}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        self._state = self.get_state(device)
        self.attrs["setTempCorrection"] = device[CONF_PARAMS]["setTempCorrection"]
        self.attrs["valvePump"] = (
            STATE_ON if device[CONF_PARAMS]["valvePump"] == 1 else STATE_OFF
        )
        self.attrs["boilerProtection"] = (
            STATE_ON if device[CONF_PARAMS]["boilerProtection"] == 1 else STATE_OFF
        )
        self.attrs["returnProtection"] = (
            STATE_ON if device[CONF_PARAMS]["returnProtection"] == 1 else STATE_OFF
        )


class TileValveTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Temperature Sensor."""

    def __init__(self, device, coordinator, config_entry, valve_sensor):
        """Initialize the sensor."""
        self._state_key = valve_sensor["state_key"]
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        sensor_name = assets.get_text(valve_sensor["txt_id"])
        valve_label = assets.get_text_by_type(device[CONF_TYPE])
        self._name = f"{valve_label} {device[CONF_PARAMS]['valveNumber']} {sensor_name}"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_valve_{self._state_key}"

    def get_state(self, device):
        """Get the state of the device."""
        state = device[CONF_PARAMS][self._state_key]
        if self._state_key in ("returnTemp", "currentTemp"):
            state /= 10
        return state


class TileMixingValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Mixing Valve Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = assets.get_text_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_mixing_valve"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return f"{self._name} {self._valve_number}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["openingPercentage"]


class TileGenericOpenThermSensor(TileSensor, SensorEntity):
    """Representation of a generic OpenTherm Sensor."""

    _attr_has_entity_name = True

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        open_therm_sensor,
    ) -> None:
        """Initialize the sensor."""

        # It is needed to store following variables before TileSensor.__init__
        self._txt_id = open_therm_sensor["txt_id"]
        self._state_key = open_therm_sensor["state_key"]

        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = self._attr_native_unit_of_measurement
        self.device_class = self._attr_device_class
        self.state_class = self._attr_state_class
        self.manufacturer = MANUFACTURER

        self.device_name = (
            f"{self._config_entry.title} {assets.get_text_by_type(device[CONF_TYPE])}"
        )
        self.model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._name = assets.get_text(self._txt_id)

        self.attrs = {}

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_opentherm_{self._state_key}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, self._unique_id)
            },  # Unique identifiers for the device
            CONF_NAME: self.device_name,  # Name of the device
            CONF_MODEL: self.model,  # Model of the device
            ATTR_MANUFACTURER: self.manufacturer,  # Manufacturer of the device
        }


class TileOpenThermTemperatureSensor(TileGenericOpenThermSensor):
    """Representation of OpenTherm Temperature Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][self._state_key] / 10


class TileOpenThermPercentageSensor(TileGenericOpenThermSensor):
    """Representation of OpenTherm Percentage Sensor."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_device_class = SensorDeviceClass.POWER_FACTOR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][self._state_key]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attributes = {}
        attributes.update(self.attrs)
        return attributes

    def update_properties(self, device):
        """Update the properties of the device based on the provided device information.

        Args:
        device: dict, the device information containing description, zone, setTemperature, and currentTemperature

        Returns:
        None

        """
        self._state = self.get_state(device)

        def set_attr(key: str, flag: bool = False):
            try:
                if flag:
                    self.attrs[key] = (
                        "on" if device[CONF_PARAMS]["flags"][key] else "off"
                    )
                else:
                    self.attrs[key] = int(device[CONF_PARAMS][key])
            except KeyError:
                pass

        set_attr("alarmCode", flag=False)
        set_attr("activeDHW", flag=True)
        set_attr("activeHeating", flag=True)
        set_attr("communication", flag=True)
        set_attr("heatingCurve", flag=True)
