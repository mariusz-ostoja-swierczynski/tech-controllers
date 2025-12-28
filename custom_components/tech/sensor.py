"""Support for Tech HVAC system."""

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
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
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
    HUMIDITY_SENSOR_TXT_IDS,
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
    OPENTHERM_SET_TEMP,
    OPENTHERM_SET_TEMP_DHW,
    RECUPERATION_EXHAUST_FLOW,
    RECUPERATION_SUPPLY_FLOW,
    RECUPERATION_SUPPLY_FLOW_ALT,
    RECUPERATION_TEMP_SENSORS,
    SENSOR_DAMAGED,
    SENSOR_TYPE,
    SERVICE_ERROR,
    SIGNAL_STRENGTH,
    TEMP_TOO_HIGH,
    TEMP_TOO_LOW,
    TYPE_FAN,
    TYPE_FUEL_SUPPLY,
    TYPE_MIXING_VALVE,
    TYPE_OPEN_THERM,
    TYPE_RECUPERATION,
    TYPE_TEMPERATURE,
    TYPE_TEMPERATURE_CH,
    TYPE_TEXT,
    TYPE_VALVE,
    UDID,
    UNDERFLOOR,
    VALUE,
    VALVE_SENSOR_CURRENT_TEMPERATURE,
    VALVE_SENSOR_RETURN_TEMPERATURE,
    VALVE_SENSOR_SET_TEMPERATURE,
    VER,
    VISIBILITY,
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
    for description in (
        OPENTHERM_CURRENT_TEMP,
        OPENTHERM_SET_TEMP,
        OPENTHERM_CURRENT_TEMP_DHW,
        OPENTHERM_SET_TEMP_DHW,
    ):
        if tile[CONF_PARAMS].get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermSensor(tile, coordinator, config_entry, description)
            )
    return entities
    entities = []
    for t in tiles:
        tile = tiles[t]
        if tile[VISIBILITY] is False or tile.get(WORKING_STATUS, True) is False:
            continue
        if tile[CONF_TYPE] == TYPE_TEMPERATURE:
            _LOGGER.debug("Creating temperature sensor: id=%s, txtId=%s, value=%s",
                         tile[CONF_ID], tile[CONF_PARAMS].get("txtId"), tile[CONF_PARAMS].get("value"))

            # Check if this is a recuperation temperature sensor by txtId
            tile_txt_id = tile[CONF_PARAMS].get("txtId", 0)
            is_recuperation_temp = False
            for temp_sensor in RECUPERATION_TEMP_SENSORS:
                if temp_sensor["txt_id"] == tile_txt_id:
                    is_recuperation_temp = True
                    _LOGGER.debug("Creating recuperation temperature sensor from TYPE_TEMPERATURE tile: %s (txtId: %s)", temp_sensor["name"], temp_sensor["txt_id"])
                    entities.append(
                        SimpleRecuperationTemperatureSensor(
                            tile, coordinator, config_entry, temp_sensor
                        )
                    )
                    break

            if not is_recuperation_temp:
                # Regular temperature sensor processing
                signal_strength = tile[CONF_PARAMS].get(SIGNAL_STRENGTH)
                battery_level = tile[CONF_PARAMS].get(BATTERY_LEVEL)
                create_devices = False
                if signal_strength not in (None, "null"):
                    create_devices = True
                    entities.append(
                        TileTemperatureSignalSensor(
                            tile, coordinator, config_entry, create_devices
                        )
                    )
                if battery_level not in (None, "null"):
                    create_devices = True
                    entities.append(
                        TileTemperatureBatterySensor(
                            tile, coordinator, config_entry, create_devices
                        )
                    )
                entities.append(
                    TileTemperatureSensor(tile, coordinator, config_entry, create_devices)
                )
        if tile[CONF_TYPE] == TYPE_TEMPERATURE_CH:
            # Check if this tile contains recuperation flow data
            widget1_txt_id = tile[CONF_PARAMS].get("widget1", {}).get("txtId", 0)
            widget2_txt_id = tile[CONF_PARAMS].get("widget2", {}).get("txtId", 0)

            # Check for recuperation flow sensors
            is_recuperation_flow = False
            for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                    is_recuperation_flow = True
                    # Create flow sensor if widget has data
                    widget_key = flow_sensor["widget"]
                    if tile[CONF_PARAMS].get(widget_key, {}).get("txtId") == flow_sensor["txt_id"]:
                        entities.append(
                            TileRecuperationFlowSensor(
                                tile, coordinator, config_entry, flow_sensor
                            )
                        )

            # Check for recuperation temperature sensors
            is_recuperation_temp = False
            for widget_key in ["widget1", "widget2"]:
                widget_data = tile[CONF_PARAMS].get(widget_key, {})
                widget_txt_id = widget_data.get("txtId", 0)
                widget_unit = widget_data.get("unit", -1)
                widget_type = widget_data.get("type", 0)

                # Check if this is a recuperation temperature sensor
                for temp_sensor in RECUPERATION_TEMP_SENSORS:
                    if temp_sensor["txt_id"] == widget_txt_id:
                        is_recuperation_temp = True
                        # Always create sensor if txtId matches, even if current value is None/0
                        entities.append(
                            TileRecuperationTemperatureSensor(
                                tile, coordinator, config_entry, widget_key, temp_sensor
                            )
                        )
                        _LOGGER.debug("Created temperature sensor: %s (txtId: %s)", temp_sensor["name"], temp_sensor["txt_id"])
                        break

            # Check for humidity sensors in widgets
            is_humidity_sensor = False
            for widget_key in ["widget1", "widget2"]:
                widget_data = tile[CONF_PARAMS].get(widget_key, {})
                widget_txt_id = widget_data.get("txtId", 0)
                widget_unit = widget_data.get("unit", -1)
                widget_type = widget_data.get("type", 0)

                # Check if this is a humidity sensor (unit: 8, type: 2)
                if widget_txt_id in HUMIDITY_SENSOR_TXT_IDS or (widget_unit == 8 and widget_type == 2):
                    is_humidity_sensor = True
                    if widget_data.get("value", 0) > 0 or widget_txt_id > 0:  # Has data
                        entities.append(
                            TileHumiditySensorWidget(
                                tile, coordinator, config_entry, widget_key, widget_txt_id
                            )
                        )

            # If not recuperation flow data, humidity sensor, or temperature sensor, create regular widget sensor
            if not is_recuperation_flow and not is_humidity_sensor and not is_recuperation_temp and widget1_txt_id > 0:
                entities.append(TileWidgetSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_FAN:
            # Check if this fan is handled by the fan platform (recuperation)
            # Use common root words that work across all supported languages
            description = tile[CONF_PARAMS].get(CONF_DESCRIPTION, "").lower()
            recuperation_keywords = [
                "recup", "rekup",  # Covers most languages
                "ventil", "wentyl", "větr", "vėdin", "szellőz",  # Ventilation variants
                "lüft",  # German: Lüftung
                "вентиля", "рекупер",  # Russian
            ]
            if not any(keyword in description for keyword in recuperation_keywords):
                entities.append(TileFanSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_RECUPERATION:
            # TYPE_RECUPERATION fans are handled by fan platform, create sensor for monitoring only
            entities.append(TileRecuperationSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_VALVE:
            entities.append(TileValveSensor(tile, coordinator, config_entry))
            for valve_sensor in [
                VALVE_SENSOR_RETURN_TEMPERATURE,
                VALVE_SENSOR_SET_TEMPERATURE,
                VALVE_SENSOR_CURRENT_TEMPERATURE,
            ]:
                if tile[CONF_PARAMS].get(valve_sensor["state_key"]) is not None:
                    entities.append(
                        TileValveTemperatureSensor(
                            tile, coordinator, config_entry, valve_sensor
                        )
                    )
        if tile[CONF_TYPE] == TYPE_MIXING_VALVE:
            entities.append(TileMixingValveSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_FUEL_SUPPLY:
            entities.append(TileFuelSupplySensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_TEXT:
            entities.append(TileTextSensor(tile, coordinator, config_entry))
        if tile[CONF_TYPE] == TYPE_OPEN_THERM:
            for openThermEntity in [
                OPENTHERM_CURRENT_TEMP,
                OPENTHERM_SET_TEMP,
                OPENTHERM_CURRENT_TEMP_DHW,
                OPENTHERM_SET_TEMP_DHW,
            ]:
                if tile[CONF_PARAMS].get(openThermEntity["state_key"]) is not None:
                    entities.append(
                        TileOpenThermSensor(
                            tile, coordinator, config_entry, openThermEntity
                        )
                    )

    # Check if we have recuperation system (detected by flow sensors) for filter usage sensor
    has_recuperation_flow = False
    for t in tiles:
        tile = tiles[t]
        if tile.get("type") == TYPE_TEMPERATURE_CH:
            widget1_txt_id = tile.get("params", {}).get("widget1", {}).get("txtId", 0)
            widget2_txt_id = tile.get("params", {}).get("widget2", {}).get("txtId", 0)
            for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                if flow_sensor["txt_id"] in [widget1_txt_id, widget2_txt_id]:
                    has_recuperation_flow = True
                    break
        if has_recuperation_flow:
            break

    # Create filter usage sensor, efficiency sensor, and outdoor temperature if we have recuperation
    if has_recuperation_flow:
        _LOGGER.debug("Creating filter usage, efficiency, and outdoor temperature sensors")
        entities.append(FilterUsageSensor(coordinator, config_entry))
        entities.append(RecuperationEfficiencySensor(coordinator, config_entry))
        entities.append(OutdoorTemperatureSensor(coordinator, config_entry))

    async_add_entities(entities, True)

    # async_add_entities(
    #     [
    #         ZoneTemperatureSensor(zones[zone], coordinator, controller_udid, model)
    #         for zone in zones
    #     ],
    #     True,
    # )

    battery_devices = map_to_battery_sensors(zones, coordinator, config_entry)
    temperature_sensors = map_to_temperature_sensors(zones, coordinator, config_entry)
    zone_state_sensors = map_to_zone_state_sensors(zones, coordinator, config_entry)
    humidity_sensors = map_to_humidity_sensors(zones, coordinator, config_entry)
    actuator_sensors = map_to_actuator_sensors(zones, coordinator, config_entry)
    window_sensors = map_to_window_sensors(zones, coordinator, config_entry)
    signal_strength_sensors = map_to_signal_strength_sensors(
        zones, coordinator, config_entry
    )
    # tile_sensors = map_to_tile_sensors(tiles, api, config_entry)

    async_add_entities(
        itertools.chain(
            battery_devices,
            temperature_sensors,
            zone_state_sensors,
            humidity_sensors,  # , tile_sensors
            actuator_sensors,
            window_sensors,
            signal_strength_sensors,
        ),
        True,
    )


def map_to_battery_sensors(zones, coordinator, config_entry):
    """Map the battery-operating devices in the zones to TechBatterySensor objects.

    Args:
    zones: list of devices
    coordinator: the api object
    config_entry: the config entry object
    model: device model

    Returns:
    - list of TechBatterySensor objects

    """
    devices = filter(
        lambda deviceIndex: is_battery_operating_device(zones[deviceIndex]), zones
    )
    return (
        ZoneBatterySensor(zones[deviceIndex], coordinator, config_entry)
        for deviceIndex in devices
    )


def is_battery_operating_device(device) -> bool:
    """Check if the device is operating on battery.


_TILE_ENTITY_BUILDERS: dict[int, TileBuilder] = {
    TYPE_TEMPERATURE: _build_temperature_tile,
    TYPE_TEMPERATURE_CH: lambda tile, coordinator, config_entry: [
        TileWidgetSensor(tile, coordinator, config_entry)
    ],
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
        return None


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
        return None


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
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(device[CONF_PARAMS]["headerId"])

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


class TileWidgetSensor(TileSensor, SensorEntity):
    """Representation of a Tile Widget Sensor."""

    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(device[CONF_PARAMS]["widget1"]["txtId"])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_widget"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS]["widget1"][VALUE] / 10


class TileValveSensor(TileSensor, SensorEntity):
    """Representation of a Tile Valve Sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.native_unit_of_measurement = PERCENTAGE
        self.state_class = SensorStateClass.MEASUREMENT
        self._valve_number = device[CONF_PARAMS]["valveNumber"]
        self._attr_icon = assets.get_icon_by_type(device[CONF_TYPE])
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])

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
        name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])
        self._name = f"{name} {device[CONF_PARAMS]['valveNumber']} {sensor_name}"

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
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])

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


class TileOpenThermSensor(TileSensor, SensorEntity):
    """Representation of config_OpenTherm Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

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
        self.native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self.device_class = SensorDeviceClass.TEMPERATURE
        self.state_class = SensorStateClass.MEASUREMENT
        self.manufacturer = MANUFACTURER
        self.device_name = (
            f"{self._config_entry.title} {assets.get_text_by_type(device[CONF_TYPE])}"
        )
        self.model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text(self._txt_id)

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_opentherm_{self._state_key}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device[CONF_PARAMS][self._state_key] / 10

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


class TileRecuperationSensor(TileSensor, SensorEntity):
    """Representation of a Tile Recuperation Sensor for monitoring."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self.state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = assets.get_icon_by_type(TYPE_RECUPERATION)
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Recuperation Status"

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_recuperation_sensor"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        gear = device[CONF_PARAMS].get("gear", 0)
        if gear == 0:
            return "off"
        elif gear == 1:
            return "low"
        elif gear == 2:
            return "medium"
        elif gear == 3:
            return "high"
        else:
            return f"speed_{gear}"


class TileRecuperationFlowSensor(TileSensor, SensorEntity):
    """Representation of a Tile Recuperation Flow Sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "m³/h"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        flow_sensor_config,
    ) -> None:
        """Initialize the sensor."""
        self._flow_config = flow_sensor_config
        self._widget_key = flow_sensor_config["widget"]
        self._flow_name = flow_sensor_config["name"]

        TileSensor.__init__(self, device, coordinator, config_entry)

        # Set the appropriate device class and icon based on flow type
        if self._flow_name == "exhaust_flow":
            self._attr_icon = "mdi:arrow-up-bold"
            self._flow_display_name = "Exhaust Flow"
        elif self._flow_name == "supply_flow":
            self._attr_icon = "mdi:arrow-down-bold"
            self._flow_display_name = "Supply Flow"
        else:
            self._flow_display_name = "Air Flow"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + f"Recuperation {self._flow_display_name}"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_recuperation_{self._flow_name}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        widget_data = device[CONF_PARAMS].get(self._widget_key, {})
        flow_value = widget_data.get("value", 0)
        # Flow values are in m³/h units, no conversion needed
        return flow_value if flow_value else 0

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._unique_id}_recuperation")
            },  # Unique identifiers for the device
            CONF_NAME: f"{self._config_entry.title} Recuperation",  # Name of the device
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),  # Model of the device
            ATTR_MANUFACTURER: MANUFACTURER,  # Manufacturer of the device
        }


class TileHumiditySensorWidget(TileSensor, SensorEntity):
    """Representation of a Tile Humidity Sensor Widget."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "%"
    _attr_device_class = SensorDeviceClass.HUMIDITY
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-percent"

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        widget_key: str,
        txt_id: int,
    ) -> None:
        """Initialize the humidity sensor."""
        self._widget_key = widget_key
        self._txt_id = txt_id

        TileSensor.__init__(self, device, coordinator, config_entry)

        # Get the proper name from assets using txtId
        sensor_name = assets.get_text(txt_id) if txt_id > 0 else f"Humidity Sensor {txt_id}"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + sensor_name

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the device."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_humidity_{self._txt_id}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        widget_data = device[CONF_PARAMS].get(self._widget_key, {})
        humidity_value = widget_data.get("value", 0)
        # Humidity values are already in percent, no conversion needed
        return humidity_value if humidity_value else 0

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._unique_id}_humidity_sensors")
            },  # Unique identifiers for the device
            CONF_NAME: f"{self._config_entry.title} Humidity Sensors",  # Name of the device
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),  # Model of the device
            ATTR_MANUFACTURER: MANUFACTURER,  # Manufacturer of the device
        }


class FilterUsageSensor(CoordinatorEntity, SensorEntity):
    """Representation of filter usage tracking sensor."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = "days"
    _attr_icon = "mdi:air-filter"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(
        self,
        coordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the filter usage sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_filter_usage_days"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Filter Usage Days"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self) -> int | None:
        """Return the current filter usage in days."""
        # Calculate days since last filter reset from stored date
        if hasattr(self._coordinator, '_filter_reset_date') and self._coordinator._filter_reset_date:
            from datetime import datetime
            reset_date = datetime.fromisoformat(self._coordinator._filter_reset_date)
            current_date = datetime.now()
            days_diff = (current_date - reset_date).days
            return days_diff
        else:
            # No reset date stored, assume filter is new (0 days)
            return 0

    @property
    def entity_category(self):
        """Return the entity category for diagnostic entities."""
        return EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_recuperation")
            },  # Unique identifiers for the device
            CONF_NAME: f"{self._config_entry.title} Recuperation",  # Name of the device
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),  # Model of the device
            ATTR_MANUFACTURER: MANUFACTURER,  # Manufacturer of the device
        }


class TileRecuperationTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a recuperation temperature sensor."""

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
        widget_key: str,
        temp_sensor: dict,
    ) -> None:
        """Initialize the recuperation temperature sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._widget_key = widget_key
        self._temp_sensor = temp_sensor
        self._attr_unique_id = f"{self._unique_id}_{widget_key}_{temp_sensor['txt_id']}_temp"
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:thermometer"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + temp_sensor["name"]

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def native_value(self) -> float | None:
        """Return the temperature value."""
        if self._coordinator.data and "tiles" in self._coordinator.data:
            tile_data = self._coordinator.data["tiles"].get(self._id)
            if tile_data:
                widget_data = tile_data.get("params", {}).get(self._widget_key, {})
                temp_value = widget_data.get("value")
                # Temperature values might need conversion from tenths of degrees
                if temp_value is not None:
                    return float(temp_value) / 10.0 if temp_value > 100 else float(temp_value)
        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_recuperation")
            },
            CONF_NAME: f"{self._config_entry.title} Recuperation",
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),
            ATTR_MANUFACTURER: MANUFACTURER,
        }


class SimpleRecuperationTemperatureSensor(TileSensor, SensorEntity):
    """Representation of a simple recuperation temperature sensor following TYPE_TEMPERATURE pattern."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        temp_sensor: dict,
    ) -> None:
        """Initialize the sensor."""
        TileSensor.__init__(self, device, coordinator, config_entry)
        self._coordinator = coordinator
        self._temp_sensor = temp_sensor
        self._attr_unique_id = f"{self._unique_id}_recuperation_temp_{temp_sensor['txt_id']}"
        self._attr_icon = "mdi:thermometer"

        # Use the temperature sensor name from the config
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + temp_sensor["name"]

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._attr_unique_id

    def get_state(self, device) -> Any:
        """Get the state of the device using TYPE_TEMPERATURE pattern."""
        temp_value = device[CONF_PARAMS].get(VALUE)
        if temp_value is not None:
            # Follow the same pattern as other temperature sensors: divide by 10
            return temp_value / 10
        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._config_entry.data[CONTROLLER][UDID]}_recuperation")
            },
            CONF_NAME: f"{self._config_entry.title} Recuperation",
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),
            ATTR_MANUFACTURER: MANUFACTURER,
        }
class RecuperationEfficiencySensor(CoordinatorEntity, SensorEntity):
    """Sensor for calculating recuperation heat recovery efficiency."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:percent"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the efficiency sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_recuperation_efficiency"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Recuperation Efficiency"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Calculate heat recovery efficiency based on temperature sensors."""
        if self._coordinator.data and "tiles" in self._coordinator.data:
            tiles_data = self._coordinator.data["tiles"]
            if not tiles_data:
                _LOGGER.debug("No tiles data available for efficiency calculation")
                return None

            _LOGGER.debug("Starting efficiency calculation, searching for temperature sensors...")
            _LOGGER.debug("Found %d tiles to examine", len(tiles_data))

            # Try to find temperature sensors for efficiency calculation
            # Standard efficiency formula: (Supply - Outdoor) / (Exhaust - Outdoor) * 100
            supply_temp = None
            exhaust_temp = None
            outdoor_temp = None

            # First, log all available tiles for debugging
            _LOGGER.debug("Available tiles for efficiency calculation:")
            for tile_id, tile_data in tiles_data.items():
                tile_type = tile_data.get("type", "unknown")
                tile_params = tile_data.get("params", {})
                # Safe logging - only log key parameters to avoid issues
                txtId = tile_params.get("txtId", "none")
                value = tile_params.get("value", "none")
                _LOGGER.debug("Tile %s: type=%s, txtId=%s, value=%s", tile_id, tile_type, txtId, value)

            # Look for temperature sensors in tiles
            for tile_id, tile_data in tiles_data.items():
                # Check TYPE_TEMPERATURE tiles for recuperation sensors
                if tile_data.get("type") == TYPE_TEMPERATURE:
                    tile_txt_id = tile_data.get("params", {}).get("txtId", 0)
                    temp_value = tile_data.get("params", {}).get("value")

                    _LOGGER.debug("Found TYPE_TEMPERATURE tile: txtId=%s, value=%s", tile_txt_id, temp_value)

                    if temp_value is not None:
                        try:
                            # Temperature processing - handle both formats (tenths vs direct)
                            if isinstance(temp_value, (int, float)) and temp_value > 100:
                                temp_celsius = temp_value / 10  # Likely in tenths (e.g., 215 = 21.5°C)
                            else:
                                temp_celsius = float(temp_value)  # Already in correct format

                            _LOGGER.debug("Temperature processed: txtId=%s, raw_value=%s, temp_celsius=%.1f", tile_txt_id, temp_value, temp_celsius)
                        except (ValueError, TypeError) as e:
                            _LOGGER.debug("Could not process temperature value: txtId=%s, value=%s, error=%s", tile_txt_id, temp_value, e)
                            continue

                        # Comprehensive txtId mapping - trying all possible recuperation temperature sensors
                        # Supply Air Temperature (expanded list from various implementations)
                        if tile_txt_id in [119, 126, 127, 5997, 2010, 6001, 6002, 6003]:
                            supply_temp = temp_celsius
                            _LOGGER.debug("Found Supply Air Temperature: %.1f°C (txtId: %s)", temp_celsius, tile_txt_id)
                        # Exhaust Air Temperature (expanded list)
                        elif tile_txt_id in [120, 127, 128, 5998, 5996, 2011, 6004, 6005, 6006]:
                            exhaust_temp = temp_celsius
                            _LOGGER.debug("Found Exhaust Air Temperature: %.1f°C (txtId: %s)", temp_celsius, tile_txt_id)
                        # External/Fresh Air Temperature (expanded list)
                        elif tile_txt_id in [121, 122, 129, 5995, 2012, 6007, 6008, 6009]:
                            outdoor_temp = temp_celsius
                            _LOGGER.debug("Found External Air Temperature: %.1f°C (txtId: %s)", temp_celsius, tile_txt_id)
                        # Log any reasonable temperature for manual identification
                        elif -30 <= temp_celsius <= 70:  # Reasonable temperature range
                            _LOGGER.warning("UNRECOGNIZED TEMPERATURE SENSOR: txtId=%s, temp=%.1f°C - could be supply/exhaust/outdoor air", tile_txt_id, temp_celsius)
                        else:
                            _LOGGER.debug("Found non-temperature sensor: txtId=%s, value=%s", tile_txt_id, temp_value)

                # Check all other tile types too in case temperature is elsewhere
                elif tile_data.get("type") not in [TYPE_TEMPERATURE_CH]:  # Skip TYPE_TEMPERATURE_CH as we handle it separately
                    tile_params = tile_data.get("params", {})
                    if "value" in tile_params and isinstance(tile_params.get("value"), (int, float)):
                        potential_temp = tile_params["value"]
                        txtId = tile_params.get("txtId", 0)
                        if txtId > 0:  # Valid txtId
                            _LOGGER.debug("Found other tile type %s with numeric value: txtId=%s, value=%s", tile_data.get("type"), txtId, potential_temp)

                # Also check TYPE_TEMPERATURE_CH widgets
                elif tile_data.get("type") == TYPE_TEMPERATURE_CH:
                    for widget_key in ["widget1", "widget2"]:
                        widget_data = tile_data.get("params", {}).get(widget_key, {})
                        widget_txt_id = widget_data.get("txtId", 0)
                        temp_value = widget_data.get("value")

                        if widget_txt_id > 0:  # Only log if we have a valid txtId
                            _LOGGER.debug("Found TYPE_TEMPERATURE_CH widget: %s, txtId=%s, value=%s", widget_key, widget_txt_id, temp_value)

                        if temp_value is not None:
                            try:
                                # Same temperature processing for widgets
                                if isinstance(temp_value, (int, float)) and temp_value > 100:
                                    temp_celsius = temp_value / 10
                                else:
                                    temp_celsius = float(temp_value)

                                _LOGGER.debug("Widget temperature processed: txtId=%s, raw_value=%s, temp_celsius=%.1f", widget_txt_id, temp_value, temp_celsius)
                            except (ValueError, TypeError) as e:
                                _LOGGER.debug("Could not process widget temperature value: txtId=%s, value=%s, error=%s", widget_txt_id, temp_value, e)
                                continue

                            # Same comprehensive txtId mapping for widgets
                            if widget_txt_id in [119, 126, 127, 5997, 2010, 6001, 6002, 6003]:  # Supply Air
                                supply_temp = temp_celsius
                                _LOGGER.debug("Found Supply Air Temperature (widget): %.1f°C (txtId: %s)", temp_celsius, widget_txt_id)
                            elif widget_txt_id in [120, 127, 128, 5998, 5996, 2011, 6004, 6005, 6006]:  # Exhaust Air
                                exhaust_temp = temp_celsius
                                _LOGGER.debug("Found Exhaust Air Temperature (widget): %.1f°C (txtId: %s)", temp_celsius, widget_txt_id)
                            elif widget_txt_id in [121, 122, 129, 5995, 2012, 6007, 6008, 6009]:  # External Air
                                outdoor_temp = temp_celsius
                                _LOGGER.debug("Found External Air Temperature (widget): %.1f°C (txtId: %s)", temp_celsius, widget_txt_id)
                            elif -30 <= temp_celsius <= 70:  # Reasonable temperature range
                                _LOGGER.warning("UNRECOGNIZED TEMPERATURE WIDGET: txtId=%s, temp=%.1f°C - could be supply/exhaust/outdoor air", widget_txt_id, temp_celsius)
                            else:
                                _LOGGER.debug("Found non-temperature widget: txtId=%s, value=%s", widget_txt_id, temp_value)

            # Try to get outdoor temperature from existing sensor if not found in tiles
            if outdoor_temp is None:
                try:
                    external_sensor_state = self._coordinator.hass.states.get("sensor.external_air_temperature")
                    if external_sensor_state and external_sensor_state.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]:
                        outdoor_temp = float(external_sensor_state.state)
                        _LOGGER.debug("Using external_air_temperature sensor: %.1f°C", outdoor_temp)
                except (ValueError, AttributeError) as e:
                    _LOGGER.debug("Could not get outdoor temperature from external sensor: %s", e)

            # Final temperature summary and calculation
            _LOGGER.debug("Temperature summary: Supply=%.1f, Exhaust=%.1f, Outdoor=%.1f",
                         supply_temp if supply_temp is not None else float('nan'),
                         exhaust_temp if exhaust_temp is not None else float('nan'),
                         outdoor_temp if outdoor_temp is not None else float('nan'))

            # Calculate efficiency if we have all required temperatures
            if supply_temp is not None and exhaust_temp is not None and outdoor_temp is not None:
                # Avoid division by zero
                temperature_diff = exhaust_temp - outdoor_temp
                _LOGGER.debug("Temperature difference (Exhaust - Outdoor): %.1f°C", temperature_diff)

                if abs(temperature_diff) > 0.1:  # Minimum difference threshold
                    efficiency = ((supply_temp - outdoor_temp) / temperature_diff) * 100
                    _LOGGER.debug("Calculated efficiency: %.1f%% (formula: (%.1f - %.1f) / %.1f * 100)",
                                 efficiency, supply_temp, outdoor_temp, temperature_diff)

                    # Clamp efficiency between 0 and 100%
                    final_efficiency = max(0, min(100, round(efficiency, 1)))
                    _LOGGER.debug("Final clamped efficiency: %.1f%%", final_efficiency)
                    return final_efficiency
                else:
                    _LOGGER.debug("Temperature difference too small: %.1f°C", temperature_diff)
            else:
                missing = []
                if supply_temp is None: missing.append("Supply")
                if exhaust_temp is None: missing.append("Exhaust")
                if outdoor_temp is None: missing.append("Outdoor")
                _LOGGER.debug("Missing temperature sensors for efficiency calculation: %s", ", ".join(missing))

        return None

    @property
    def entity_category(self):
        """Return the entity category for diagnostic entities."""
        return EntityCategory.DIAGNOSTIC

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_recuperation")
            },
            CONF_NAME: f"{self._config_entry.title} Recuperation",
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),
            ATTR_MANUFACTURER: MANUFACTURER,
        }


class OutdoorTemperatureSensor(CoordinatorEntity, SensorEntity):
    """Sensor for outdoor temperature from recuperation system - HomeKit friendly."""

    _attr_has_entity_name = True
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:thermometer"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the outdoor temperature sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_outdoor_temperature"

        # Simple, HomeKit-friendly name
        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Outdoor Temperature"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def native_value(self) -> float | None:
        """Return the outdoor temperature value."""
        if self._coordinator.data and "tiles" in self._coordinator.data:
            # Search for outdoor temperature in both TYPE_TEMPERATURE and TYPE_TEMPERATURE_CH tiles
            for tile_data in self._coordinator.data["tiles"].values():
                # Check TYPE_TEMPERATURE tiles
                if tile_data.get("type") == TYPE_TEMPERATURE:
                    tile_txt_id = tile_data.get("params", {}).get("txtId", 0)
                    temp_value = tile_data.get("params", {}).get("value")

                    if temp_value is not None and tile_txt_id in [121, 5995]:  # External/Fresh Air
                        return temp_value / 10  # Convert from tenths

                # Check TYPE_TEMPERATURE_CH widgets
                elif tile_data.get("type") == TYPE_TEMPERATURE_CH:
                    for widget_key in ["widget1", "widget2"]:
                        widget_data = tile_data.get("params", {}).get(widget_key, {})
                        widget_txt_id = widget_data.get("txtId", 0)
                        temp_value = widget_data.get("value")

                        if temp_value is not None and widget_txt_id in [121, 5995]:  # External/Fresh Air
                            return temp_value / 10  # Convert from tenths

        return None

    @property
    def device_info(self) -> DeviceInfo | None:
        """Returns device information in a dictionary format - separate device for HomeKit."""
        return {
            ATTR_IDENTIFIERS: {
                (DOMAIN, f"{self._udid}_weather_station")
            },
            CONF_NAME: f"{self._config_entry.title} Weather Station",
            CONF_MODEL: (
                self._config_entry.data[CONTROLLER][CONF_NAME]
                + ": "
                + self._config_entry.data[CONTROLLER][VER]
            ),
            ATTR_MANUFACTURER: MANUFACTURER,
        }
