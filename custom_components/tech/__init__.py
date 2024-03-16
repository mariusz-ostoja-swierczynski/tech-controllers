"""The Tech Controllers integration."""
import asyncio
import logging
from typing import Any, Final

from aiohttp import ClientSession
from typing_extensions import TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_DESCRIPTION, CONF_NAME, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceEntry, DeviceRegistry
from homeassistant.helpers.entity_registry import EntityRegistry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import assets
from .const import (
    API_TIMEOUT,
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    SCAN_INTERVAL,
    UDID,
    USER_ID,
    VER,
)
from .tech import Tech, TechError, TechLoginError

_LOGGER: Final = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

_DataT = TypeVar("_DataT", default=dict[str, Any])


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # pylint: disable=unused-argument
    """Set up the Tech Controllers component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tech Controllers from a config entry."""
    _LOGGER.debug("Setting up component's entry")
    _LOGGER.debug("Entry id: %s", str(entry.entry_id))
    _LOGGER.debug(
        "Entry -> title: %s, data: %s, id: %s, domain: %s",
        entry.title,
        str(entry.data),
        entry.entry_id,
        entry.domain,
    )
    language_code: str = hass.config.language
    user_id: str = entry.data[USER_ID]
    token: str = entry.data[CONF_TOKEN]
    hass.data.setdefault(DOMAIN, {})
    websession: ClientSession = async_get_clientsession(hass)

    coordinator: DataUpdateCoordinator[dict[str, dict[str, Any]]] = TechCoordinator(
        hass, websession, user_id, token
    )
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await assets.load_subtitles(Tech(websession, user_id, token), language_code)

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.info("Migrating from version %s", config_entry.version)
    device_registry: DeviceRegistry = dr.async_get(hass)
    entity_registry: EntityRegistry = er.async_get(hass)
    udid: str = config_entry.data[UDID]

    if config_entry.version == 1:
        version: int = 2

        http_session: ClientSession = async_get_clientsession(hass)
        api: Tech = Tech(
            http_session, config_entry.data[USER_ID], config_entry.data[CONF_TOKEN]
        )
        controllers: list[dict[str, Any]] = await api.list_modules()
        controller: dict[str, Any] = next(
            obj for obj in controllers if obj.get(UDID) == udid
        )
        api.modules.setdefault(udid, {"last_update": None, "zones": {}, "tiles": {}})
        zones: dict[str, Any] = await api.get_module_zones(udid)

        data: dict[str, Any] = {
            USER_ID: api.user_id,
            CONF_TOKEN: api.token,
            CONTROLLER: controller,
            VER: controller[VER] + ": " + controller[CONF_NAME],
        }

        # Store the existing entity entries:
        old_entity_entries: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

        # Update config entry
        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            title=controller[CONF_NAME],
            unique_id=udid,
            version=version,
        )

        # Create new devices as version 1 did not have any:
        for z in zones:
            zone: dict[str, Any] = zones[z]
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={(DOMAIN, zone[CONF_DESCRIPTION][CONF_NAME])},
                manufacturer=MANUFACTURER,
                name=zone[CONF_DESCRIPTION][CONF_NAME],
                model=controller[CONF_NAME] + ": " + controller[VER],
                # sw_version= #TODO
                # hw_version= #TODO
            )

        remaining_entities_to_remove: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

        # Update all entities and link them to appropriate devices
        # plus update unique_id, everything else as it was
        for unique_id, old_entity_entry in old_entity_entries.items():
            if old_entity_entry.original_name is not None:
                device: DeviceEntry | None = device_registry.async_get_device(
                    {(DOMAIN, old_entity_entry.original_name)},
                    set(),
                )
                if device and device.name == old_entity_entry.original_name:
                    # since thsi entity stays, remove it from collection to remove
                    del remaining_entities_to_remove[unique_id]
                    entity_registry.async_update_entity(
                        entity_id=old_entity_entry.entity_id,
                        area_id=old_entity_entry.area_id,
                        device_class=old_entity_entry.device_class,
                        device_id=device.id,
                        disabled_by=old_entity_entry.disabled_by,
                        hidden_by=old_entity_entry.hidden_by,
                        icon=old_entity_entry.icon,
                        name=old_entity_entry.name,
                        new_entity_id=old_entity_entry.entity_id,
                        new_unique_id=udid + "_" + str(unique_id),
                        unit_of_measurement=old_entity_entry.unit_of_measurement,
                    )

        # Remove the remaining entities that are no longer provided by the integration
        # Items that are not visible in emodul.

        for entity_to_remove in remaining_entities_to_remove:
            entity_registry.async_remove(
                entity_id=remaining_entities_to_remove[entity_to_remove].entity_id
            )

        _LOGGER.info("Migration to version %s successful", version)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Returns:
        True if successful, False if cannot unload.

    """
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class TechCoordinator(DataUpdateCoordinator[dict[str, dict[str, Any]]]):
    """TECH API data update coordinator."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        session: ClientSession,
        user_id: str,
        token: str,
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=SCAN_INTERVAL,
        )
        self.api = Tech(session, user_id, token)

    async def _async_update_data(
        self,
    ):
        """Fetch data from TECH API endpoint(s)."""

        _LOGGER.debug(
            "Updating data for: %s", str(self.config_entry.data[CONTROLLER][CONF_NAME])
        )

        try:
            async with asyncio.timeout(API_TIMEOUT):
                return await self.api.module_data(
                    self.config_entry.data[CONTROLLER][UDID]
                )
        except TechLoginError as err:
            raise ConfigEntryAuthFailed from err
        except TechError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
