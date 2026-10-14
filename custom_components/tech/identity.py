"""Remember what a user made of an entity the controller stopped reporting.

The removal pass deletes an entity for a payload entry the controller has
genuinely stopped sending, and with it everything the user had attached to that
entity: the entity id an automation points at, the name they gave it, its icon,
the area it was filed under, and the disabled and hidden flags. This module keeps
those fields, per entity unique id, in a store of its own, and puts them back on
the entity that is built when the entry is reported again -- which would
otherwise be a new registry row named after the payload.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import (
    RegistryEntry,
    RegistryEntryDisabler,
    RegistryEntryHider,
)
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .coordinator import TechCoordinator

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.entity_identity"

# The store is written a little after the change rather than during the poll, and
# a record lives long enough for a controller to be reconfigured or a sensor to
# come back, but not forever: entries that are never reported again would
# otherwise accumulate.
SAVE_DELAY = 30
RECORD_TTL = 30 * 24 * 60 * 60


def _storage(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    """Return the identity store of one config entry.

    Args:
        hass: Home Assistant instance.
        entry_id: The config entry the store belongs to.

    Returns:
        The store, which is created on first use.

    """
    return Store(hass, STORAGE_VERSION, f"{STORAGE_KEY}.{entry_id}")


def _saved(row: RegistryEntry) -> dict[str, Any]:
    """Return the fields of a registry row the user can set.

    Args:
        row: The registry row about to be removed.

    Returns:
        A JSON-serialisable mapping of those fields, with the time of removal so
        that a record which is never asked for again can be aged out.

    """
    return {
        "entity_id": row.entity_id,
        "name": row.name,
        "icon": row.icon,
        "area_id": row.area_id,
        "labels": sorted(row.labels),
        # Home Assistant computes some aliases itself; only the ones the user
        # typed are theirs to get back.
        "aliases": sorted(alias for alias in row.aliases if isinstance(alias, str)),
        "options": dict(row.options),
        "disabled_by": row.disabled_by.value if row.disabled_by else None,
        "hidden_by": row.hidden_by.value if row.hidden_by else None,
        "removed_at": time.time(),
    }


async def async_load(
    hass: HomeAssistant, coordinator: TechCoordinator, entry_id: str
) -> None:
    """Load the identity store of an entry into its coordinator.

    Records older than :data:`RECORD_TTL` are dropped here, which is the only
    place they can be aged out: an entity that never comes back is never asked
    for again.

    Args:
        hass: Home Assistant instance.
        coordinator: The entry's coordinator, which holds them while it runs.
        entry_id: The config entry the store belongs to.

    """
    store = _storage(hass, entry_id)
    loaded = await store.async_load() or {}
    deadline = time.time() - RECORD_TTL

    _forget = [
        unique_id
        for unique_id, record in loaded.items()
        if float(record.get("removed_at", 0)) < deadline
    ]
    for unique_id in _forget:
        loaded.pop(unique_id)

    if _forget:
        _LOGGER.debug("Dropping %s identity record(s) nothing asked for", len(_forget))

    coordinator.identity_store = store
    coordinator.identities = loaded
    if loaded:
        _LOGGER.debug("Kept %s entity identit(ies) across removals", len(loaded))


def remember(coordinator: TechCoordinator, row: RegistryEntry) -> None:
    """Keep a row's user-visible fields, so a return is the same entity.

    Args:
        coordinator: The entry's coordinator, holding the records.
        row: The registry row about to be removed.

    """
    coordinator.identities[row.unique_id] = _saved(row)
    _LOGGER.debug("Keeping the identity of %s", row.entity_id)
    _save(coordinator)


def _save(coordinator: TechCoordinator) -> None:
    """Ask the store to write what is held, a little later.

    Args:
        coordinator: The entry's coordinator, holding the records.

    """
    store = coordinator.identity_store
    if store is None:
        return
    store.async_delay_save(lambda: dict(coordinator.identities), SAVE_DELAY)


async def async_restore(
    hass: HomeAssistant, coordinator: TechCoordinator, entity: Any
) -> None:
    """Put a remembered row's fields onto the entity that replaced it.

    Called once an entity is actually registered, which is when its row exists to
    be updated. The record is dropped afterwards: it is the user's settings that
    matter, and they are back where they belong.

    Args:
        hass: Home Assistant instance.
        coordinator: The entry's coordinator, holding the records.
        entity: The entity that has just been added to Home Assistant.

    """
    unique_id = entity.unique_id
    record = coordinator.identities.pop(unique_id, None)
    if record is None:
        return

    registry = er.async_get(hass)
    row = registry.async_get(entity.entity_id)
    if row is None:
        return

    fields: dict[str, Any] = {
        "name": record.get("name"),
        "icon": record.get("icon"),
        "area_id": record.get("area_id"),
        "labels": set(record.get("labels") or ()),
        "aliases": set(record.get("aliases") or ()),
        "options": dict(record.get("options") or {}),
    }
    for field, enum in (
        ("disabled_by", RegistryEntryDisabler),
        ("hidden_by", RegistryEntryHider),
    ):
        value = record.get(field)
        if value is not None:
            try:
                fields[field] = enum(value)
            except ValueError:
                _LOGGER.debug("Dropping an unknown %s of %s", field, value)

    # The entity id is the field automations point at, so it is reclaimed first,
    # and only while nothing else has taken it in the meantime.
    wanted = record.get("entity_id")
    if wanted and wanted != row.entity_id and registry.async_get(wanted) is None:
        row = registry.async_update_entity(row.entity_id, new_entity_id=wanted)

    registry.async_update_entity(row.entity_id, **fields)
    _LOGGER.debug("Restored the identity of %s", row.entity_id)
    _save(coordinator)
