"""The Tech Controllers integration."""

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, CONF_TOKEN
from homeassistant.core import HomeAssistant, ServiceCall, Context
from homeassistant.helpers import config_validation as cv, entity_registry as er, template
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
    # Register custom service for setting temperature with duration
    async def async_set_temperature_with_duration_service(call: ServiceCall) -> None:
        """Service to set temperature with duration for Tech climate entities."""
        entity_ids = cv.ensure_list(call.data[ATTR_ENTITY_ID])
        
        # Get raw values
        temp_value = call.data["temperature"]
        duration_value = call.data["duration_minutes"]
        
        # Get context for template rendering
        context = call.context if hasattr(call, 'context') else Context()
        
        # Process temperature - handle templates, strings, and numbers
        if isinstance(temp_value, str):
            # Check if it's a template (contains {{ or states()
            if "{{" in temp_value or "states(" in temp_value:
                try:
                    temp_template = template.Template(temp_value, hass)
                    temp_value = temp_template.async_render(context=context, parse_result=False)
                    _LOGGER.debug("Rendered temperature template: %s -> %s", call.data["temperature"], temp_value)
                except Exception as err:
                    _LOGGER.warning("Failed to render temperature template %s: %s", temp_value, err)
                    return
        
        # Process duration - handle templates, strings, and numbers
        if isinstance(duration_value, str):
            # Check if it's a template (contains {{ or states()
            if "{{" in duration_value or "states(" in duration_value:
                try:
                    duration_template = template.Template(duration_value, hass)
                    duration_value = duration_template.async_render(context=context, parse_result=False)
                    _LOGGER.debug("Rendered duration template: %s -> %s", call.data["duration_minutes"], duration_value)
                except Exception as err:
                    _LOGGER.warning("Failed to render duration template %s: %s", duration_value, err)
                    return
        
        # Convert to proper types - handle both string and numeric inputs
        try:
            # Try to convert to float (handles both string numbers and actual numbers)
            temperature = float(temp_value)
        except (ValueError, TypeError) as err:
            _LOGGER.error("Invalid temperature value: %s (type: %s, original: %s)", 
                         temp_value, type(temp_value).__name__, call.data.get("temperature"))
            return
            
        try:
            # Allow float input and convert to int
            duration_minutes = int(float(duration_value))
        except (ValueError, TypeError) as err:
            _LOGGER.error("Invalid duration_minutes value: %s (type: %s, original: %s)", 
                         duration_value, type(duration_value).__name__, call.data.get("duration_minutes"))
            return

        _LOGGER.debug(
            "Service called: set_temperature_with_duration for %s, temp=%s, duration=%s",
            entity_ids,
            temperature,
            duration_minutes,
        )

        # Get the climate component
        entity_components = hass.data.get("entity_components")
        if not entity_components:
            _LOGGER.error("Entity components not found")
            return

        climate_component = entity_components.get("climate")
        if not climate_component:
            _LOGGER.error("Climate component not found")
            return

        # Find and call the method on each entity
        for entity_id in entity_ids:
            # Get entity from component
            entity = climate_component.get_entity(entity_id)
            
            if entity and hasattr(entity, "async_set_temperature_with_duration"):
                _LOGGER.debug("Calling async_set_temperature_with_duration on %s", entity_id)
                await entity.async_set_temperature_with_duration(
                    temperature, duration_minutes
                )
            else:
                _LOGGER.warning(
                    "Entity %s does not support set_temperature_with_duration",
                    entity_id,
                )

    # Register the service - use cv.string to accept any input, convert in handler
    hass.services.async_register(
        DOMAIN,
        "set_temperature_with_duration",
        async_set_temperature_with_duration_service,
        schema=cv.make_entity_service_schema(
            {
                vol.Required("temperature"): cv.string,
                vol.Required("duration_minutes"): cv.string,
            }
        ),
    )
    _LOGGER.debug("Registered tech.set_temperature_with_duration service")

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
