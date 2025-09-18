"""Support for Tech HVAC button controls."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    CONF_MODEL,
    CONF_NAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    RECUPERATION_EXHAUST_FLOW,
    RECUPERATION_SUPPLY_FLOW,
    RECUPERATION_SUPPLY_FLOW_ALT,
    TYPE_TEMPERATURE_CH,
    UDID,
    VER,
)
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entry."""
    _LOGGER.debug(
        "Setting up button entry, controller udid: %s",
        config_entry.data[CONTROLLER][UDID],
    )
    coordinator = hass.data[DOMAIN][config_entry.entry_id]
    controller_udid = config_entry.data[CONTROLLER][UDID]

    tiles = await coordinator.api.get_module_tiles(controller_udid)

    entities = []

    # Check if we have recuperation system (detected by flow sensors)
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

    # Create recuperation buttons if we have recuperation
    if has_recuperation_flow:
        _LOGGER.debug("Creating recuperation buttons: filter reset and party mode")
        entities.append(FilterResetButton(coordinator, config_entry))
        entities.append(PartyModeButton(coordinator, config_entry))
        entities.append(QuickBoostButton(coordinator, config_entry))
    else:
        _LOGGER.debug("No recuperation flow detected, skipping recuperation buttons")

    async_add_entities(entities, True)


class FilterResetButton(CoordinatorEntity, ButtonEntity):
    """Representation of filter reset button."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the filter reset button."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_filter_reset"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Filter Reset"

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return self._name

    async def async_press(self) -> None:
        """Press the button to reset filter timer."""
        _LOGGER.debug("Resetting filter timer")

        # Store the current date as filter reset date
        from datetime import datetime
        current_date = datetime.now().isoformat()

        # Store in coordinator for immediate use by filter usage sensor
        self._coordinator._filter_reset_date = current_date

        # Call API to reset filter data
        await self._coordinator.api.update_filter_data(self._udid)

        # Store the reset date in Home Assistant storage
        from homeassistant.helpers import storage
        store = storage.Store(
            self._coordinator.hass,
            version=1,
            key=f"{DOMAIN}_{self._udid}_filter_data"
        )
        await store.async_save({
            "filter_reset_date": current_date
        })

        # Refresh coordinator data
        await self._coordinator.async_request_refresh()

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


class PartyModeButton(CoordinatorEntity, ButtonEntity):
    """Button to activate party mode with default duration."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:party-popper"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the party mode button."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_party_mode_button"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Party Mode (60min)"

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return self._name

    async def async_press(self) -> None:
        """Press the button to activate party mode for 60 minutes."""
        _LOGGER.debug("Activating party mode for 60 minutes")

        try:
            # Activate party mode for 60 minutes (reasonable default)
            await self._coordinator.api.set_party_mode(self._udid, 60)

            # Refresh coordinator data to reflect the change
            await self._coordinator.async_request_refresh()

            _LOGGER.info("Party mode activated successfully for 60 minutes")

        except Exception as err:
            _LOGGER.error("Failed to activate party mode: %s", err)

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


class QuickBoostButton(CoordinatorEntity, ButtonEntity):
    """Button to activate quick boost mode for 30 minutes."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:rocket-launch"

    def __init__(
        self,
        coordinator: TechCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        """Initialize the quick boost button."""
        super().__init__(coordinator)
        self._coordinator = coordinator
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._attr_unique_id = f"{self._udid}_quick_boost_button"

        self._name = (
            self._config_entry.title + " "
            if self._config_entry.data[INCLUDE_HUB_IN_NAME]
            else ""
        ) + "Quick Boost (30min)"

    @property
    def name(self) -> str:
        """Return the name of the button."""
        return self._name

    async def async_press(self) -> None:
        """Press the button to activate quick boost mode for 30 minutes."""
        _LOGGER.debug("Activating quick boost mode for 30 minutes")

        try:
            # Activate party mode for 30 minutes (short boost)
            await self._coordinator.api.set_party_mode(self._udid, 30)

            # Refresh coordinator data to reflect the change
            await self._coordinator.async_request_refresh()

            _LOGGER.info("Quick boost mode activated successfully for 30 minutes")

        except Exception as err:
            _LOGGER.error("Failed to activate quick boost mode: %s", err)

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