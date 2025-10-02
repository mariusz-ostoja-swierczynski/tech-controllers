"""The Tech Controllers integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.typing import ConfigType

from . import assets
from .const import DOMAIN, PLATFORMS, USER_ID
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
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
        assets.redact(dict(entry.data), ["token"]),
        entry.entry_id,
        entry.domain,
    )
    language_code = hass.config.language
    user_id = entry.data[USER_ID]
    token = entry.data[CONF_TOKEN]
    # Store an API object for your platforms to access
    hass.data.setdefault(DOMAIN, {})
    websession = async_get_clientsession(hass)

    coordinator = TechCoordinator(hass, websession, user_id, token)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await assets.load_subtitles(language_code, coordinator.api)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Configuration entry to unload.

    Returns:
        ``True`` if all platforms were unloaded successfully.

    """
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
