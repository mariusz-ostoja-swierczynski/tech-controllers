"""Support for Tech HVAC system."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
import logging
import re
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
    UnitOfTime,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.icon import icon_for_signal_level
from homeassistant.helpers.typing import UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util, slugify

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
    OPENTHERM_ACTIVE_DHW,
    OPENTHERM_ACTIVE_HEATING,
    OPENTHERM_ALARM_CODE,
    OPENTHERM_COMMUNICATION,
    OPENTHERM_CURRENT_TEMP,
    OPENTHERM_CURRENT_TEMP_DHW,
    OPENTHERM_HEATING_CURVE,
    OPENTHERM_MODULATION,
    OPENTHERM_SET_TEMP,
    OPENTHERM_SET_TEMP_DHW,
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
    TYPE_PERIPHERAL_SW_VERSION,
    TYPE_SW_VERSION,
    TYPE_SYSTEM_CONTAINER,
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

_API_SHORT_TZ_SUFFIX = re.compile(r"([+-]\d{2})$")


def _parse_api_timestamp(value: Any) -> datetime | None:
    """Parse timestamps returned by the Tech API."""
    if not isinstance(value, str) or not value:
        return None

    normalized = value.strip()
    if _API_SHORT_TZ_SUFFIX.search(normalized) is not None:
        normalized = f"{normalized}:00"

    parsed = dt_util.parse_datetime(normalized)
    if parsed is None or parsed.tzinfo is None:
        return None

    return dt_util.as_utc(parsed)


def _seconds_since_timestamp(value: datetime | None) -> int | None:
    """Return elapsed whole seconds since ``value``."""
    if value is None:
        return None

    elapsed = dt_util.utcnow() - dt_util.as_utc(value)
    return max(int(elapsed.total_seconds()), 0)


def _get_controller_device_name(config_entry: ConfigEntry) -> str:
    """Return the display name for the shared controller device."""
    return f"{config_entry.title} Controller"


def _get_controller_device_info(config_entry: ConfigEntry) -> DeviceInfo:
    """Return shared ``DeviceInfo`` for controller-level entities."""
    controller = config_entry.data[CONTROLLER]
    return {
        ATTR_IDENTIFIERS: {(DOMAIN, f"{controller[UDID]}_controller")},
        CONF_NAME: _get_controller_device_name(config_entry),
        CONF_MODEL: controller.get(VER),
        ATTR_MANUFACTURER: MANUFACTURER,
    }


def _get_controller_last_update_entity_id(config_entry: ConfigEntry) -> str:
    """Return the preferred entity_id for the controller last-update sensor."""
    return f"sensor.{slugify(_get_controller_device_name(config_entry))}_last_update"


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

    diagnostic_entities: list[CoordinatorEntity] = [
        TechTilesLastUpdateSensor(coordinator, config_entry)
    ]

    async_add_entities([*tile_entities, *zone_entities, *diagnostic_entities], True)


def _iter_mapping(mapping: dict[Any, Any] | Iterable[Any]) -> Iterable[Any]:
    """Yield mapping values regardless of whether ``mapping`` is a dict or list."""
    if not mapping:
        return ()
    if isinstance(mapping, dict):
        return mapping.values()
    return mapping


def _has_value(value: Any) -> bool:
    """Return whether a payload field contains a meaningful value."""
    return value not in (None, "null")


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


_SYSTEM_CONTAINER_ROLE_BY_TYPE = {
    0: "master",
    1: "slave_1",
    2: "slave_2",
    3: "slave_3",
    4: "slave_4",
    5: "slave_5",
}

_SYSTEM_CONTAINER_CONFIGURATION_SLOT_BY_INDEX = {
    0: "master",
    1: "module_1",
    2: "module_2",
    3: "module_3",
    4: "module_4",
    5: "module_5",
}

_SYSTEM_CONTAINER_CONFIGURATION_UI_LABEL_BY_INDEX = {
    0: "M",
    1: "1",
    2: "2",
    3: "3",
    4: "4",
    5: "5",
}

_SYSTEM_CONTAINER_SIGNAL_STATE_BY_VALUE = {
    -3: "communication_loss",
    -2: "wired",
    -1: "waiting",
}

_SYSTEM_CONTAINER_CONNECTION_LABEL_TXT_ID = 8309
_SYSTEM_CONTAINER_OPERATING_MODE_LABEL_TXT_ID = 814
_SYSTEM_CONTAINER_PUMP_LABEL_TXT_ID = 3089
_SYSTEM_CONTAINER_FREE_CONTACT_LABEL_TXT_ID = 1736
_SYSTEM_CONTAINER_HEATING_LABEL_TXT_ID = 1816
_SYSTEM_CONTAINER_COOLING_LABEL_TXT_ID = 1815
_SYSTEM_CONTAINER_ACTIVE_LABEL_TXT_ID = 5829
_SYSTEM_CONTAINER_INACTIVE_LABEL_TXT_ID = 5830
_SYSTEM_CONTAINER_WAITING_LABEL_TXT_ID = 2310


def _get_system_container_payload(
    coordinator: TechCoordinator, container_id: int
) -> dict[str, Any] | None:
    system = coordinator.data.get("system", {})
    containers = system.get("containers", []) if isinstance(system, dict) else []
    for container in containers:
        if isinstance(container, dict) and container.get("containerId") == container_id:
            return container
    return None


def _get_system_container_data_payload(
    coordinator: TechCoordinator, container_id: int
) -> dict[str, Any] | None:
    system = coordinator.data.get("system", {})
    containers_data = (
        system.get("containersData", []) if isinstance(system, dict) else []
    )
    for container_data in containers_data:
        if (
            isinstance(container_data, dict)
            and container_data.get("parentId") == container_id
        ):
            return container_data
    return None


def _get_system_container_name(
    container: dict[str, Any] | None, config_entry: ConfigEntry
) -> str:
    if isinstance(container, dict):
        text_id = container.get("textId")
        if isinstance(text_id, int) and text_id != 0:
            return assets.get_text(text_id)
        container_name = container.get("containerName")
        if isinstance(container_name, str) and container_name:
            return container_name
    return config_entry.title


def _normalize_container_flags(flags: Any) -> dict[str, bool]:
    if not isinstance(flags, dict):
        return {}
    return {str(key): bool(value) for key, value in flags.items()}


def _map_container_flags_to_configuration(flags: dict[str, bool]) -> dict[str, bool]:
    mapped_flags: dict[str, bool] = {}
    for key, enabled in flags.items():
        try:
            mapped_key = _SYSTEM_CONTAINER_CONFIGURATION_SLOT_BY_INDEX.get(
                int(key), key
            )
        except (TypeError, ValueError):
            mapped_key = key
        mapped_flags[mapped_key] = enabled
    return mapped_flags


def _map_container_flags_to_ui_labels(flags: dict[str, bool]) -> dict[str, bool]:
    mapped_flags: dict[str, bool] = {}
    for key, enabled in flags.items():
        try:
            mapped_key = _SYSTEM_CONTAINER_CONFIGURATION_UI_LABEL_BY_INDEX.get(
                int(key), key
            )
        except (TypeError, ValueError):
            mapped_key = key
        mapped_flags[mapped_key] = enabled
    return mapped_flags


def _active_container_flags(flags: dict[str, bool]) -> list[str]:
    active_flags: list[str] = []
    for key, enabled in flags.items():
        if not enabled:
            continue
        try:
            active_flags.append(
                _SYSTEM_CONTAINER_CONFIGURATION_SLOT_BY_INDEX.get(int(key), key)
            )
        except (TypeError, ValueError):
            active_flags.append(key)
    return active_flags


def _format_system_container_signal(signal: Any) -> Any:
    if not isinstance(signal, int):
        return None
    if signal == -1:
        return assets.get_text(_SYSTEM_CONTAINER_WAITING_LABEL_TXT_ID)
    return _SYSTEM_CONTAINER_SIGNAL_STATE_BY_VALUE.get(signal, signal)


def _get_system_container_entity_name(
    container: dict[str, Any] | None, config_entry: ConfigEntry, label_txt_id: int
) -> str:
    container_name = _get_system_container_name(container, config_entry)
    if config_entry.data[INCLUDE_HUB_IN_NAME]:
        container_name = f"{config_entry.title} {container_name}"
    return f"{container_name} {assets.get_text(label_txt_id)}"


def _build_system_container_common_attrs(
    container_id: int | None,
    container: dict[str, Any] | None,
    container_data: dict[str, Any] | None,
) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    if isinstance(container_id, int):
        attrs["container_id"] = container_id
    if isinstance(container, dict):
        for source_key, target_key in (
            ("containerName", "container_name"),
            ("parentId", "container_parent_id"),
            ("processorId", "processor_id"),
            ("version", "version"),
            ("textId", "text_id"),
            ("iconId", "icon_id"),
            ("wikiId", "wiki_id"),
        ):
            value = container.get(source_key)
            if value is not None:
                attrs[target_key] = value
    if isinstance(container_data, dict):
        parameter_id = container_data.get("parameterId")
        if parameter_id is not None:
            attrs["parameter_id"] = parameter_id
        container_type = container_data.get("type")
        if isinstance(container_type, int):
            attrs["connection_role"] = _SYSTEM_CONTAINER_ROLE_BY_TYPE.get(
                container_type, container_type
            )
    return attrs


def _format_system_container_bool_state(value: Any) -> str | None:
    if value is None:
        return None
    return assets.get_text(
        _SYSTEM_CONTAINER_ACTIVE_LABEL_TXT_ID
        if bool(value)
        else _SYSTEM_CONTAINER_INACTIVE_LABEL_TXT_ID
    )


def _format_system_container_operating_mode(value: Any) -> str | None:
    if value is None:
        return None
    return assets.get_text(
        _SYSTEM_CONTAINER_HEATING_LABEL_TXT_ID
        if bool(value)
        else _SYSTEM_CONTAINER_COOLING_LABEL_TXT_ID
    )


OPEN_THERM_SENSOR_DESCRIPTIONS: tuple[dict[str, Any], ...] = (
    {
        **OPENTHERM_CURRENT_TEMP,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "divisor": 10,
    },
    {
        **OPENTHERM_SET_TEMP,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "divisor": 10,
    },
    {
        **OPENTHERM_CURRENT_TEMP_DHW,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "divisor": 10,
    },
    {
        **OPENTHERM_SET_TEMP_DHW,
        "native_unit_of_measurement": UnitOfTemperature.CELSIUS,
        "device_class": SensorDeviceClass.TEMPERATURE,
        "state_class": SensorStateClass.MEASUREMENT,
        "divisor": 10,
    },
    {
        **OPENTHERM_MODULATION,
        "native_unit_of_measurement": PERCENTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
        "icon": "mdi:percent",
    },
    {
        **OPENTHERM_ALARM_CODE,
        "icon": "mdi:alert-circle-outline",
    },
)


OPEN_THERM_FLAG_SENSOR_DESCRIPTIONS: tuple[dict[str, Any], ...] = (
    {
        **OPENTHERM_COMMUNICATION,
        "icon": "mdi:lan-connect",
        "source": "flags",
        "state_map": "on_off",
    },
    {
        **OPENTHERM_HEATING_CURVE,
        "icon": "mdi:chart-line",
        "source": "flags",
        "state_map": "on_off",
    },
    {
        **OPENTHERM_ACTIVE_HEATING,
        "icon": "mdi:radiator",
        "source": "flags",
        "state_map": "on_off",
    },
    {
        **OPENTHERM_ACTIVE_DHW,
        "icon": "mdi:water-boiler",
        "source": "flags",
        "state_map": "on_off",
    },
)


def _build_open_therm_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    """Create OpenTherm entities for a tile payload."""
    params = tile.get(CONF_PARAMS, {})
    flags = params.get("flags", {}) if isinstance(params.get("flags"), dict) else {}
    entities: list[CoordinatorEntity] = []
    for description in OPEN_THERM_SENSOR_DESCRIPTIONS:
        if params.get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermSensor(tile, coordinator, config_entry, description)
            )

    for description in OPEN_THERM_FLAG_SENSOR_DESCRIPTIONS:
        if flags.get(description["state_key"]) is not None:
            entities.append(
                TileOpenThermSensor(tile, coordinator, config_entry, description)
            )
    return entities


def _build_system_container_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    container_id = tile.get(CONF_PARAMS, {}).get("containerId")
    if not isinstance(container_id, int):
        return []
    container = _get_system_container_payload(coordinator, container_id)
    container_data = _get_system_container_data_payload(coordinator, container_id)
    if not isinstance(container, dict) or not container.get("visibility"):
        return []
    if not isinstance(container_data, dict):
        return []
    entities: list[CoordinatorEntity] = [
        _SystemContainerSignalSensor(tile, coordinator, config_entry)
    ]
    if container_data.get("pumpsState") is not None:
        entities.append(_SystemContainerPumpSensor(tile, coordinator, config_entry))
    if container_data.get("freeContactState") is not None:
        entities.append(
            _SystemContainerFreeContactSensor(tile, coordinator, config_entry)
        )
    if container_data.get("hcState") is not None:
        entities.append(
            _SystemContainerOperatingModeSensor(tile, coordinator, config_entry)
        )
    return entities


def _build_sw_version_tile(
    tile: dict[str, Any],
    coordinator: TechCoordinator,
    config_entry: ConfigEntry,
) -> list[CoordinatorEntity]:
    if not isinstance(tile.get(CONF_PARAMS, {}).get("version"), str):
        return []
    return [TileSoftwareVersionSensor(tile, coordinator, config_entry)]


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
    TYPE_SW_VERSION: _build_sw_version_tile,
    TYPE_PERIPHERAL_SW_VERSION: _build_sw_version_tile,
    TYPE_OPEN_THERM: _build_open_therm_tile,
    TYPE_SYSTEM_CONTAINER: _build_system_container_tile,
}


class TechTilesLastUpdateSensor(CoordinatorEntity, SensorEntity):
    """Diagnostic sensor exposing the latest module tile refresh timestamp."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_has_entity_name = True
    _attr_translation_key = "tiles_last_update_entity"
    _attr_icon = "mdi:clock-check-outline"
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: TechCoordinator, config_entry: ConfigEntry) -> None:
        """Initialize the tiles-last-update diagnostic sensor."""
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._last_update_at = _parse_api_timestamp(coordinator.data.get("tiles_last_update"))
        self._attr_native_value = _seconds_since_timestamp(self._last_update_at)
        self._unsub_elapsed_refresh = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._udid}_tiles_last_update"

    async def async_added_to_hass(self) -> None:
        """Migrate old autogenerated entity IDs to a controller-based name."""
        await super().async_added_to_hass()
        self._unsub_elapsed_refresh = async_track_time_interval(
            self.hass,
            self._async_refresh_elapsed_state,
            timedelta(seconds=15),
        )
        if self.registry_entry is None:
            return

        old_default_entity_id = f"sensor.tech_{self._udid}_tiles_last_update"
        if self.registry_entry.entity_id != old_default_entity_id:
            return

        entity_registry = er.async_get(self.hass)
        preferred_entity_id = _get_controller_last_update_entity_id(self._config_entry)
        if preferred_entity_id == self.registry_entry.entity_id:
            return

        try:
            entity_registry.async_update_entity(
                self.registry_entry.entity_id,
                new_entity_id=preferred_entity_id,
            )
        except ValueError:
            _LOGGER.debug(
                "Unable to migrate tiles-last-update entity_id to %s",
                preferred_entity_id,
            )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic metadata tied to the same refresh cycle."""
        attributes: dict[str, Any] = {}
        if self._last_update_at is not None:
            attributes["last_update_at"] = self._last_update_at.isoformat()
            attributes["seconds_since_update"] = _seconds_since_timestamp(
                self._last_update_at
            )
        transaction_time = self.coordinator.data.get("transaction_time")
        if transaction_time is not None:
            attributes["transaction_time"] = transaction_time
        return attributes

    async def async_will_remove_from_hass(self) -> None:
        """Cancel scheduled elapsed-time refreshes."""
        if self._unsub_elapsed_refresh is not None:
            self._unsub_elapsed_refresh()
            self._unsub_elapsed_refresh = None
        await super().async_will_remove_from_hass()

    @callback
    def _async_refresh_elapsed_state(self, _now: datetime) -> None:
        """Refresh elapsed-time state between coordinator updates."""
        native_value = _seconds_since_timestamp(self._last_update_at)
        if native_value == self._attr_native_value:
            return
        self._attr_native_value = native_value
        self.async_write_ha_state()

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the shared controller."""
        return _get_controller_device_info(self._config_entry)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Refresh the entity from coordinator data."""
        self._last_update_at = _parse_api_timestamp(
            self.coordinator.data.get("tiles_last_update")
        )
        self._attr_native_value = _seconds_since_timestamp(self._last_update_at)
        self.async_write_ha_state()


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
        device = self._coordinator.data["zones"].get(self._id)
        if device is None:
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
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
        device = self._coordinator.data["zones"].get(self._id)
        if device is None:
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
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
        self.update_properties(device)
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
        device = self._coordinator.data["zones"].get(self._id)
        if device is None:
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
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
        device = self._coordinator.data["zones"].get(self._id)
        if device is None:
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
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
    _attr_icon = "mdi:valve"

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


class TileSoftwareVersionSensor(TileSensor, SensorEntity):
    """Representation of a software version tile sensor."""

    def __init__(self, device, coordinator, config_entry) -> None:
        """Initialize the sensor."""
        self._attrs: dict[str, Any] = {}
        TileSensor.__init__(self, device, coordinator, config_entry)
        icon_id = device[CONF_PARAMS].get("iconId")
        if isinstance(icon_id, int):
            self._attr_icon = assets.get_icon(icon_id)
        self.update_properties(device)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_sw_version"

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the name of the sensor."""
        return self._name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional metadata for the version tile."""
        return dict(self._attrs)

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return Home Assistant ``DeviceInfo`` for the shared controller."""
        return _get_controller_device_info(self._config_entry)

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        return device.get(CONF_PARAMS, {}).get("version")

    def update_properties(self, device):
        """Update the properties of the device based on the provided device information."""
        self._state = self.get_state(device)
        params = device.get(CONF_PARAMS, {})
        attrs: dict[str, Any] = {}
        for source_key, target_key in (
            ("controllerName", "controller_name"),
            ("mainControllerId", "main_controller_id"),
            ("companyId", "company_id"),
        ):
            value = params.get(source_key)
            if value is not None:
                attrs[target_key] = value
        self._attrs = attrs


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


class _SystemContainerSignalSensor(TileSensor, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, device, coordinator, config_entry) -> None:
        self._container_id = device.get(CONF_PARAMS, {}).get("containerId")
        self._signal_raw: int | None = None
        self._attrs: dict[str, Any] = {}
        TileSensor.__init__(self, device, coordinator, config_entry)
        container = _get_system_container_payload(self.coordinator, self._container_id)
        self._name = _get_system_container_entity_name(
            container,
            self._config_entry,
            _SYSTEM_CONTAINER_CONNECTION_LABEL_TXT_ID,
        )
        self.update_properties(device)

    def _payloads(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        container = None
        container_data = None
        if isinstance(self._container_id, int):
            container = _get_system_container_payload(
                self.coordinator, self._container_id
            )
            container_data = _get_system_container_data_payload(
                self.coordinator, self._container_id
            )
        return container, container_data

    @property
    def unique_id(self) -> str:
        return f"{self._unique_id}_tile_system_container_signal"

    @property
    def name(self) -> str | UndefinedType | None:
        return self._name

    @property
    def icon(self) -> str | None:
        if isinstance(self._signal_raw, int) and self._signal_raw >= 0:
            return icon_for_signal_level(self._signal_raw)
        if self._signal_raw == -3:
            return "mdi:lan-disconnect"
        if self._signal_raw == -2:
            return "mdi:lan-connect"
        if self._signal_raw == -1:
            return "mdi:timer-sand"
        return "mdi:signal"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._attrs)

    @property
    def device_info(self) -> DeviceInfo | None:
        return _get_controller_device_info(self._config_entry)

    def get_state(self, device) -> Any:
        del device
        _, container_data = self._payloads()
        signal = (
            container_data.get("signal") if isinstance(container_data, dict) else None
        )
        self._signal_raw = signal if isinstance(signal, int) else None
        if not isinstance(signal, int):
            return None
        return signal if signal >= 0 else 0

    def update_properties(self, device):
        container, container_data = self._payloads()
        self._state = self.get_state(device)

        attrs = _build_system_container_common_attrs(
            self._container_id, container, container_data
        )
        if isinstance(container_data, dict):
            if self._signal_raw is not None:
                attrs["signal_raw"] = self._signal_raw
                attrs["signal_display"] = _format_system_container_signal(self._signal_raw)
                signal_state = _SYSTEM_CONTAINER_SIGNAL_STATE_BY_VALUE.get(
                    self._signal_raw
                )
                if signal_state is not None:
                    attrs["signal_state"] = signal_state
        self._attrs = attrs

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        device = self.coordinator.data["tiles"].get(self._id)
        container, container_data = self._payloads()
        if (
            device is None
            or not isinstance(container, dict)
            or not container.get("visibility")
            or not isinstance(container_data, dict)
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
        self.async_write_ha_state()


class _SystemContainerStatusSensor(TileSensor, SensorEntity):
    def __init__(self, device, coordinator, config_entry, label_txt_id: int) -> None:
        self._container_id = device.get(CONF_PARAMS, {}).get("containerId")
        self._attrs: dict[str, Any] = {}
        self._label_txt_id = label_txt_id
        TileSensor.__init__(self, device, coordinator, config_entry)
        container = _get_system_container_payload(self.coordinator, self._container_id)
        self._name = _get_system_container_entity_name(
            container, self._config_entry, self._label_txt_id
        )
        self.update_properties(device)

    def _payloads(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        container = None
        container_data = None
        if isinstance(self._container_id, int):
            container = _get_system_container_payload(
                self.coordinator, self._container_id
            )
            container_data = _get_system_container_data_payload(
                self.coordinator, self._container_id
            )
        return container, container_data

    @property
    def name(self) -> str | UndefinedType | None:
        return self._name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._attrs)

    @property
    def device_info(self) -> DeviceInfo | None:
        return _get_controller_device_info(self._config_entry)

    def _update_common_attrs(
        self,
        container: dict[str, Any] | None,
        container_data: dict[str, Any] | None,
        *,
        connection_key: str,
        connection_attr_key: str,
        connected_roles_attr_key: str,
        configuration_attr_key: str,
        configuration_ui_attr_key: str,
    ) -> None:
        attrs = _build_system_container_common_attrs(
            self._container_id, container, container_data
        )
        if isinstance(container_data, dict):
            flags = _normalize_container_flags(container_data.get(connection_key))
            if flags:
                attrs[connection_attr_key] = flags
                attrs[connected_roles_attr_key] = _active_container_flags(flags)
                attrs[configuration_attr_key] = _map_container_flags_to_configuration(
                    flags
                )
                attrs[configuration_ui_attr_key] = _map_container_flags_to_ui_labels(
                    flags
                )
        self._attrs = attrs

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        device = self.coordinator.data["tiles"].get(self._id)
        container, container_data = self._payloads()
        if (
            device is None
            or not isinstance(container, dict)
            or not container.get("visibility")
            or not isinstance(container_data, dict)
        ):
            self._attr_available = False
            self.async_write_ha_state()
            return
        self._attr_available = True
        self.update_properties(device)
        self.async_write_ha_state()


class _SystemContainerPumpSensor(_SystemContainerStatusSensor):
    def __init__(self, device, coordinator, config_entry) -> None:
        self._attr_icon = "mdi:pump"
        super().__init__(
            device, coordinator, config_entry, _SYSTEM_CONTAINER_PUMP_LABEL_TXT_ID
        )

    @property
    def unique_id(self) -> str:
        return f"{self._unique_id}_tile_system_container_pump"

    def get_state(self, device) -> Any:
        del device
        _, container_data = self._payloads()
        return _format_system_container_bool_state(
            container_data.get("pumpsState")
            if isinstance(container_data, dict)
            else None
        )

    def update_properties(self, device):
        container, container_data = self._payloads()
        self._state = self.get_state(device)
        self._update_common_attrs(
            container,
            container_data,
            connection_key="pumpsConnection",
            connection_attr_key="pumps_connection",
            connected_roles_attr_key="pumps_connected_roles",
            configuration_attr_key="pumps_configuration",
            configuration_ui_attr_key="pumps_configuration_ui",
        )


class _SystemContainerFreeContactSensor(_SystemContainerStatusSensor):
    def __init__(self, device, coordinator, config_entry) -> None:
        self._attr_icon = "mdi:electric-switch"
        super().__init__(
            device,
            coordinator,
            config_entry,
            _SYSTEM_CONTAINER_FREE_CONTACT_LABEL_TXT_ID,
        )

    @property
    def unique_id(self) -> str:
        return f"{self._unique_id}_tile_system_container_free_contact"

    def get_state(self, device) -> Any:
        del device
        _, container_data = self._payloads()
        return _format_system_container_bool_state(
            container_data.get("freeContactState")
            if isinstance(container_data, dict)
            else None
        )

    def update_properties(self, device):
        container, container_data = self._payloads()
        self._state = self.get_state(device)
        self._update_common_attrs(
            container,
            container_data,
            connection_key="freeContactConnection",
            connection_attr_key="free_contact_connection",
            connected_roles_attr_key="free_contact_connected_roles",
            configuration_attr_key="free_contact_configuration",
            configuration_ui_attr_key="free_contact_configuration_ui",
        )


class _SystemContainerOperatingModeSensor(_SystemContainerStatusSensor):
    def __init__(self, device, coordinator, config_entry) -> None:
        self._attr_icon = "mdi:hvac"
        super().__init__(
            device,
            coordinator,
            config_entry,
            _SYSTEM_CONTAINER_OPERATING_MODE_LABEL_TXT_ID,
        )

    @property
    def unique_id(self) -> str:
        return f"{self._unique_id}_tile_system_container_operating_mode"

    def get_state(self, device) -> Any:
        del device
        _, container_data = self._payloads()
        return _format_system_container_operating_mode(
            container_data.get("hcState") if isinstance(container_data, dict) else None
        )

    def update_properties(self, device):
        container, container_data = self._payloads()
        self._state = self.get_state(device)
        self._update_common_attrs(
            container,
            container_data,
            connection_key="hcConnection",
            connection_attr_key="operation_algorithm_connection",
            connected_roles_attr_key="operation_algorithm_connected_roles",
            configuration_attr_key="operation_algorithm_configuration",
            configuration_ui_attr_key="operation_algorithm_configuration_ui",
        )


class TileOpenThermSensor(TileSensor, SensorEntity):
    """Representation of config_OpenTherm Sensor."""

    _attr_has_entity_name = False
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def name(self) -> str | UndefinedType | None:
        """Return the entity name, keeping the hub prefix for OpenTherm sensors."""
        attr_name = getattr(self, "_attr_name", None)
        if self._txt_id is not None:
            return attr_name

        translation_key = self._description.get("translation_key")
        if translation_key is None or self.platform_data is None:
            return attr_name or self.device_name

        translated_name = self.platform_data.platform_translations.get(
            self._name_translation_key
        )
        if translated_name is None:
            return attr_name or self.device_name

        return (
            f"{self._config_entry.title} {translated_name}"
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else translated_name
        )

    def __init__(
        self,
        device,
        coordinator: TechCoordinator,
        config_entry,
        open_therm_sensor,
    ) -> None:
        """Initialize the sensor."""

        self._description = open_therm_sensor
        self._txt_id = open_therm_sensor.get("txt_id")
        self._state_key = open_therm_sensor["state_key"]

        TileSensor.__init__(self, device, coordinator, config_entry)
        self._attr_native_unit_of_measurement = open_therm_sensor.get(
            "native_unit_of_measurement"
        )
        self._attr_device_class = open_therm_sensor.get("device_class")
        self._attr_state_class = open_therm_sensor.get("state_class")
        self._attr_icon = open_therm_sensor.get("icon")
        self.manufacturer = MANUFACTURER
        self.device_name = (
            f"{self._config_entry.title} {assets.get_text_by_type(device[CONF_TYPE])}"
        )
        self.model = (
            config_entry.data[CONTROLLER][CONF_NAME]
            + ": "
            + config_entry.data[CONTROLLER][VER]
        )
        base_name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + assets.get_text_by_type(device[CONF_TYPE])
        translation_key = open_therm_sensor.get("translation_key")
        if self._txt_id is not None:
            self._attr_name = (
                self._config_entry.title + " "
                if self._config_entry.data[INCLUDE_HUB_IN_NAME]
                else ""
            ) + assets.get_text(self._txt_id)
        elif translation_key is not None:
            self._attr_translation_key = translation_key
        else:
            self._attr_name = base_name

    async def async_added_to_hass(self) -> None:
        """Update stale generic registry names for OpenTherm entities."""
        await super().async_added_to_hass()
        if self.registry_entry is None:
            return

        preferred_name = self.name
        if preferred_name in (None, UndefinedType):
            return

        current_original_name = self.registry_entry.original_name
        if current_original_name not in (
            None,
            self.device_name,
            preferred_name.removeprefix(f"{self._config_entry.title} "),
        ):
            return

        entity_registry = er.async_get(self.hass)
        entity_registry.async_update_entity(
            self.entity_id,
            original_name=preferred_name,
        )

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._unique_id}_tile_opentherm_{self._state_key}"

    def get_state(self, device) -> Any:
        """Get the state of the device."""
        state_source = device.get(CONF_PARAMS, {})
        if self._description.get("source") == "flags":
            state_source = state_source.get("flags", {})

        if not isinstance(state_source, dict):
            return None

        state = state_source.get(self._state_key)
        if state is None:
            return None

        if self._description.get("state_map") == "on_off":
            return STATE_ON if bool(state) else STATE_OFF

        divisor = self._description.get("divisor")
        if divisor is not None:
            return state / divisor

        return state

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
