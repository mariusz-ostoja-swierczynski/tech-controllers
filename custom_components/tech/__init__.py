"""The Tech Controllers integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.redact import async_redact_data
from homeassistant.helpers.typing import ConfigType

from . import assets
from .const import DOMAIN, INCLUDE_HUB_IN_NAME, PLATFORMS, USER_ID
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The runtime data of a Tech config entry is the coordinator that polls the
# controller. Platforms reach it through ``config_entry.runtime_data`` instead
# of a shared ``hass.data`` mapping: it is typed, and there is nothing left to
# unwind when the entry unloads.
type TechConfigEntry = ConfigEntry[TechCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:  # pylint: disable=unused-argument
    """Set up the Tech Controllers integration via YAML configuration.

    This entry point exists for completeness; the integration relies on
    config entries, so the function simply returns ``True`` to signal
    successful initialization.

    Args:
        hass: Home Assistant instance.
        config: Top-level configuration data (unused).

    Returns:
        ``True`` to indicate setup should continue.

    """
    return True


async def async_setup_entry(hass: HomeAssistant, entry: TechConfigEntry) -> bool:
    """Initialize Tech Controllers from a config entry.

    The method creates a :class:`TechCoordinator`, refreshes the initial
    dataset, loads translated subtitles, and forwards the setup to the
    supported platforms.

    Args:
        hass: Home Assistant instance.
        entry: Active configuration entry for the integration.

    Returns:
        ``True`` if the entry was set up successfully.

    """
    _LOGGER.debug("Setting up component's entry")
    _LOGGER.debug("Entry id: %s", str(entry.entry_id))
    _LOGGER.debug(
        "Entry -> title: %s, data: %s, id: %s, domain: %s",
        entry.title,
        async_redact_data(dict(entry.data), ["token"]),
        entry.entry_id,
        entry.domain,
    )
    language_code = hass.config.language
    user_id = entry.data[USER_ID]
    token = entry.data[CONF_TOKEN]
    websession = async_get_clientsession(hass)

    coordinator = TechCoordinator(hass, websession, user_id, token)
    entry.runtime_data = coordinator

    await coordinator.async_config_entry_first_refresh()

    coordinator.translations = await assets.Translations.load(
        language_code, coordinator.api
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: TechConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Configuration entry to unload.

    Returns:
        ``True`` if all platforms were unloaded successfully.

    """
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: TechConfigEntry) -> bool:
    """Migrate an entry written by an older version of this integration.

    Version 3 stored the hub-name setting among the entry's data; version 4
    keeps it in the entry's options, where the settings that are not needed to
    connect belong.

    Args:
        hass: Home Assistant instance.
        entry: Configuration entry to migrate.

    Returns:
        ``True`` when the entry can be set up, ``False`` to refuse it.

    """
    if entry.version > 4:
        # A newer version wrote this entry, and it may carry data this version
        # cannot interpret: refusing it is safer than setting it up halfway.
        return False

    if entry.version < 4:
        data = dict(entry.data)
        options = dict(entry.options)
        include_hub = data.pop(INCLUDE_HUB_IN_NAME, None)
        if include_hub is not None:
            options.setdefault(INCLUDE_HUB_IN_NAME, include_hub)
        hass.config_entries.async_update_entry(
            entry, data=data, options=options, version=4
        )
        _LOGGER.debug("Migrated config entry %s to version 4", entry.entry_id)

    return True
