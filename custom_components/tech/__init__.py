"""The Tech Controllers integration."""

import logging
from typing import Any

from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
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
    CONF_MENU_CODES,
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

# An entry written by a newer version may carry data this version cannot
# interpret: refusing it is safer than setting it up halfway.
MIGRATION_NEWER_VERSION_KEY = "entry_from_newer_version"
MIGRATION_NEWER_VERSION_MESSAGE = (
    "This entry was written by a newer version of Tech Controllers. "
    "Update the integration and restart Home Assistant."
)

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


async def async_setup_entry(hass: HomeAssistant, entry: TechConfigEntry) -> None:
    """Initialize Tech Controllers from a config entry.

    The method creates a :class:`TechCoordinator`, refreshes the initial
    dataset, loads translated subtitles, and forwards the setup to the
    supported platforms.

    Args:
        hass: Home Assistant instance.
        entry: Active configuration entry for the integration.

    Raises:
        ConfigEntryNotReady: If the initial refresh fails. Home Assistant
            retries the setup.

    """
    _LOGGER.debug("Setting up component's entry")
    _LOGGER.debug("Entry id: %s", str(entry.entry_id))
    _LOGGER.debug(
        "Entry -> title: %s, data: %s, id: %s, domain: %s",
        entry.title,
        # The menu codes are credentials like the token, and sit under one key,
        # so redacting that key hides all of them: nothing here may log a code.
        async_redact_data(dict(entry.data), ["token", CONF_MENU_CODES]),
        entry.entry_id,
        entry.domain,
    )
    user_id = entry.data[USER_ID]
    token = entry.data[CONF_TOKEN]
    # An entry without the key, or with an empty mapping, has no codes: that is
    # what every entry configured before codes existed looks like.
    menu_codes = dict(entry.data.get(CONF_MENU_CODES) or {})
    websession = async_get_clientsession(hass)

    coordinator = TechCoordinator(
        hass, websession, user_id, token, menu_codes=menu_codes
    )
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

    # The catalog names things; it is not needed to run, and the coordinator
    # retries it on each refresh if the API will not serve it.
    await coordinator.async_load_translations()

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


async def async_unload_entry(hass: HomeAssistant, entry: TechConfigEntry) -> None:
    """Unload a config entry.

    Args:
        hass: Home Assistant instance.
        entry: Configuration entry to unload.

    Raises:
        ConfigEntryError: If a platform fails to unload, which leaves the entry
            in Home Assistant's failed-unload state.

    """
    await hass.config_entries.async_unload_platforms_or_raise(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: TechConfigEntry) -> None:
    """Migrate an entry written by an older version of this integration.

    Version 3 stored the hub-name setting among the entry's data; version 4
    keeps it in the entry's options, where the settings that are not needed to
    connect belong.

    Args:
        hass: Home Assistant instance.
        entry: Configuration entry to migrate.

    Raises:
        ConfigEntryError: If a newer version wrote the entry, since this version
            may not be able to interpret its data.

    """
    if entry.version > 4:
        # A newer version wrote this entry, and it may carry data this version
        # cannot interpret: refusing it is safer than setting it up halfway.
        raise ConfigEntryError(
            MIGRATION_NEWER_VERSION_MESSAGE,
            translation_domain=DOMAIN,
            translation_key=MIGRATION_NEWER_VERSION_KEY,
        )

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
    # The departure hook is not run for an entity Home Assistant never wrote a
    # state for, which is every disabled-by-default entity, so the platform is
    # told here as well. Both paths discard from the same set, so hearing about
    # a departure twice is harmless, and hearing about it once is what lets a
    # returning payload rebuild the entity.
    for forget in coordinator.forget_callbacks:
        forget(entity.unique_id)

    if device_id and not er.async_entries_for_device(registry, device_id):
        # The device goes with the last entity on it, and everything still on it
        # goes too -- including the disabled-by-default entities, which are not
        # in that count and which Home Assistant never told they left, because
        # it never wrote their state and so never ran their departure hook. They
        # are not in the coordinator's bookkeeping either, for the same reason,
        # so the platforms are told about them here. Without this, a payload
        # that reports the device again would build the enabled entities and
        # silently leave the disabled ones out for good.
        for row in er.async_entries_for_device(
            registry, device_id, include_disabled_entities=True
        ):
            for forget in coordinator.forget_callbacks:
                forget(row.unique_id)
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
