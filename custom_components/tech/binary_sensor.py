"""Platform for binary sensor integration."""

import logging

from homeassistant.components import binary_sensor
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TYPE,
    STATE_OFF,
    STATE_ON,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType, UndefinedType
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import TechCoordinator, assets
from .const import (
    CONTROLLER,
    DOMAIN,
    FILTER_ALARM_MAX_DAYS,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    RECUPERATION_EXHAUST_FLOW,
    RECUPERATION_SUPPLY_FLOW,
    RECUPERATION_SUPPLY_FLOW_ALT,
    TYPE_ADDITIONAL_PUMP,
    TYPE_FIRE_SENSOR,
    TYPE_RELAY,
    TYPE_TEMPERATURE_CH,
    UDID,
    VER,
    VISIBILITY,
)
from .entity import TileEntity

_LOGGER = logging.getLogger(__name__)


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

    # Check if we have recuperation system for filter replacement sensor
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

    # Add recuperation binary sensors if system detected
    if has_recuperation_flow:
        _LOGGER.debug("Creating recuperation binary sensors")
        entities.extend([
            FilterReplacementSensor(coordinator, config_entry),
            RecuperationSystemStatusSensor(coordinator, config_entry),
        ])

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


class FilterReplacementSensor(CoordinatorEntity, binary_sensor.BinarySensorEntity):
    """Binary sensor to indicate when filter replacement is needed."""

    _attr_has_entity_name = True
    _attr_device_class = binary_sensor.BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:air-filter-outline"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the filter replacement sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_filter_replacement_needed"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Filter Replacement Needed"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return True if filter replacement is needed."""
        # Calculate if filter replacement is needed based on usage days
        if hasattr(self._coordinator, '_filter_reset_date') and self._coordinator._filter_reset_date:
            from datetime import datetime
            reset_date = datetime.fromisoformat(self._coordinator._filter_reset_date)
            current_date = datetime.now()
            days_since_reset = (current_date - reset_date).days
            return days_since_reset >= FILTER_ALARM_MAX_DAYS
        else:
            # No reset date stored, check if we're over the default max days
            # Assume filter is new if no reset date
            return False

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


class RecuperationSystemStatusSensor(CoordinatorEntity, binary_sensor.BinarySensorEntity):
    """Binary sensor to indicate recuperation system operational status."""

    _attr_has_entity_name = True
    _attr_device_class = binary_sensor.BinarySensorDeviceClass.RUNNING
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the system status sensor."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_recuperation_running"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Recuperation Running"

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self._name

    @property
    def is_on(self) -> bool | None:
        """Return True if recuperation system is running."""
        # Check if any flow sensors show activity
        if self._coordinator.data and "tiles" in self._coordinator.data:
            for tile_id, tile_data in self._coordinator.data["tiles"].items():
                if tile_data.get("type") == TYPE_TEMPERATURE_CH:
                    # Check flow sensors for activity
                    widget1_data = tile_data.get("params", {}).get("widget1", {})
                    widget2_data = tile_data.get("params", {}).get("widget2", {})

                    # Check if any flow sensor shows activity (> 0)
                    for widget_data in [widget1_data, widget2_data]:
                        widget_txt_id = widget_data.get("txtId", 0)
                        for flow_sensor in [RECUPERATION_EXHAUST_FLOW, RECUPERATION_SUPPLY_FLOW, RECUPERATION_SUPPLY_FLOW_ALT]:
                            if flow_sensor["txt_id"] == widget_txt_id:
                                flow_value = widget_data.get("value", 0)
                                if flow_value and flow_value > 0:
                                    return True
        return False

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
