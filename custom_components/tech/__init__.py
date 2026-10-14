"""The Tech Controllers integration."""

import logging
from typing import Any

from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.redact import async_redact_data
from homeassistant.helpers.typing import ConfigType

from . import assets, identity
from .const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    PLATFORMS,
    UDID,
    USER_ID,
)
from .coordinator import TechConfigEntry, TechCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# The runtime data of a Tech config entry is the coordinator that polls the
# controller. Platforms reach it through ``config_entry.runtime_data`` instead
# of a shared ``hass.data`` mapping: it is typed, and there is nothing left to
# unwind when the entry unloads.


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

    # The controller's own device is created before the platforms run, because
    # the registry names a parent device by its id and an entity of one of the
    # controller's zones or sensors can only point at a device that exists.
    controller = entry.data[CONTROLLER]
    controller_device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, controller[UDID])},
        name=entry.title,
        # The API's descriptor carries the model and the firmware in one string,
        # so both are read from it: the model gives the device its heading in the
        # UI, sw_version its firmware. A model field of its own does not exist,
        # and the entry's title would only repeat the device name.
        model=assets.controller_model(entry),
        sw_version=assets.controller_firmware(entry),
        manufacturer=MANUFACTURER,
    )
    coordinator.controller_device_id = controller_device.id

    coordinator.translations = await assets.Translations.load(
        language_code, coordinator.api
    )

    # What the user made of an entity the removal pass takes away is kept across
    # the removal, so that an entry the controller reports again is the same
    # entity: the same id, name, icon and area.
    await identity.async_load(hass, coordinator, entry.entry_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # A controller stops reporting a tile, a zone or a menu item eventually, and
    # the platforms only ever add entities: the removal side lives here, where
    # the entry and the registries are at hand.
    def _watch_reported() -> None:
        _drop_unreported_entities(hass, coordinator)

    entry.async_on_unload(coordinator.async_add_listener(_watch_reported))

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


# How many polls in a row a controller has to leave a payload entry out before
# its entities are removed: an hour at the 60-second interval. A controller
# being reconfigured reports nothing for a while, and removing an entity loses
# its name, its history and every automation that points at it, so the absence
# has to be long enough to mean something.
REMOVAL_MISSES = 60


def _drop_unreported_entities(
    hass: HomeAssistant, coordinator: TechCoordinator
) -> None:
    """Remove the entities of the payload entries a controller stopped reporting.

    Called on every poll. An entry the controller still reports clears its
    count; one it has left out counts up, and at :data:`REMOVAL_MISSES` its
    entities are removed from the registry, along with the device that held
    them.

    Args:
        hass: Home Assistant instance.
        coordinator: The entry's coordinator, holding the entities by source key.

    """
    reported = assets.reported_keys(coordinator.data or {})

    for key in list(coordinator.reported):
        if key in reported:
            coordinator.reported_misses.pop(key, None)
            continue

        misses = coordinator.reported_misses.get(key, 0) + 1
        coordinator.reported_misses[key] = misses
        if misses < REMOVAL_MISSES:
            continue

        coordinator.reported_misses.pop(key, None)
        for entity in list(coordinator.reported.get(key, ())):
            _forget_entity(hass, coordinator, entity)


def _forget_entity(
    hass: HomeAssistant, coordinator: TechCoordinator, entity: Any
) -> None:
    """Remove one entity, and its device once nothing is left on it.

    Removing has to reach Home Assistant as well as the registry. An entity that
    only leaves the registry keeps serving its last value and is never told it
    left, so the platform that built it still counts it as registered, tries to
    register it again the moment its entry is reported, and Home Assistant
    refuses a unique id it already holds.

    Args:
        hass: Home Assistant instance.
        coordinator: The entry's coordinator, which keeps what the user made of
            the entity, so that a return is the same entity.
        entity: The entity to remove.

    """
    entity_id = entity.entity_id
    if not entity_id:
        return

    registry = er.async_get(hass)
    registered = registry.async_get(entity_id)
    if registered is not None:
        identity.remember(coordinator, registered)
    device_id = registered.device_id if registered else None

    _LOGGER.debug("Removing %s: the controller no longer reports it", entity_id)
    registry.async_remove(entity_id)
    # The entity has to leave Home Assistant as well, and that removal is a
    # coroutine, so it is scheduled: the row is gone by now, and the platform
    # hears about the departure -- which is what stops it registering the entity
    # again -- in time for the next poll.
    hass.async_create_task(entity.async_remove())

    if device_id and not er.async_entries_for_device(registry, device_id):
        dr.async_get(hass).async_remove_device(device_id)


async def async_remove_config_entry_device(
    hass: HomeAssistant, config_entry: TechConfigEntry, device_entry: dr.DeviceEntry
) -> bool:
    """Allow removing a device the controller no longer reports.

    Home Assistant asks this before it deletes a device from the registry by
    hand. The controller's own device is the entry itself -- deleting it would
    be undone by the next setup, and removing the entry is what the user means
    -- so that one is refused; every other device is theirs to delete.

    Args:
        hass: Home Assistant instance.
        config_entry: The entry the device belongs to.
        device_entry: The device the user is deleting.

    Returns:
        ``True`` when the device may be removed.

    """
    controller = config_entry.data[CONTROLLER]
    return (DOMAIN, controller[UDID]) not in device_entry.identifiers
