"""Tests for keeping a removed entity's user-visible identity.

The module is small but its branches matter: a stale record has to age out, a
store that was never opened must not be written, and restoring has to reclaim
the user's entity id only when nothing else took it in the meantime. These tests
drive those branches directly, with a fake store for the storage side and the
real entity registry for the restore side.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

from custom_components.tech import identity
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_registry import (
    RegistryEntryDisabler,
    RegistryEntryHider,
)


class _Store:
    """Stand-in for the identity ``Store``, recording delayed writes."""

    def __init__(self, loaded: dict | None = None) -> None:
        """Hold the payload ``async_load`` should return."""
        self.loaded = loaded
        self.delayed: list[tuple] = []

    async def async_load(self) -> dict | None:
        """Return the payload this store was built with."""
        return self.loaded

    def async_delay_save(self, data_func, delay: int) -> None:
        """Record the deferred write instead of scheduling a real one."""
        self.delayed.append((data_func, delay))


def _coordinator(store: _Store | None = None) -> SimpleNamespace:
    """Return a coordinator carrying an identity store and no records."""
    return SimpleNamespace(identity_store=store, identities={})


def _row(**overrides) -> SimpleNamespace:
    """Return a registry row carrying the fields the identity module saves."""
    fields = {
        "unique_id": "uid",
        "entity_id": "sensor.old",
        "name": "Mine",
        "icon": "mdi:custom",
        "area_id": "kitchen",
        "labels": {"b", "a"},
        "aliases": ["z", "a"],
        "options": {"sensor": {"unit": "custom"}},
        "disabled_by": RegistryEntryDisabler.USER,
        "hidden_by": RegistryEntryHider.USER,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def test_saved_keeps_the_user_fields_and_sorts_the_sets() -> None:
    """Only the fields a user can set are kept, with stable ordering."""
    record = identity._saved(_row(aliases=["z", 1, "a"]))

    assert record["entity_id"] == "sensor.old"
    assert record["name"] == "Mine"
    assert record["icon"] == "mdi:custom"
    assert record["area_id"] == "kitchen"
    assert record["labels"] == ["a", "b"]
    # A non-string alias is Home Assistant's own, not the user's; the user's
    # aliases keep the order Home Assistant holds them in.
    assert record["aliases"] == ["z", "a"]
    assert record["options"] == {"sensor": {"unit": "custom"}}
    assert record["disabled_by"] == "user"
    assert record["hidden_by"] == "user"
    assert record["removed_at"] <= time.time()


def test_saved_records_absent_enum_fields_as_none() -> None:
    """A row that is neither disabled nor hidden keeps that as ``None``."""
    record = identity._saved(_row(disabled_by=None, hidden_by=None))

    assert record["disabled_by"] is None
    assert record["hidden_by"] is None


async def test_load_drops_expired_records_and_keeps_fresh_ones(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A record older than the TTL never comes back; a fresh one is held."""
    fresh = {"removed_at": time.time(), "entity_id": "sensor.fresh"}
    expired = {"removed_at": time.time() - identity.RECORD_TTL - 1}
    store = _Store({"fresh": fresh, "expired": expired})
    monkeypatch.setattr(identity, "_storage", lambda hass, entry_id: store)
    coordinator = _coordinator()

    await identity.async_load(hass, coordinator, "entry")

    assert coordinator.identity_store is store
    assert coordinator.identities == {"fresh": fresh}


async def test_load_accepts_a_store_that_has_never_been_written(
    hass: HomeAssistant, monkeypatch
) -> None:
    """A missing store file reads as an empty record set."""
    store = _Store(None)
    monkeypatch.setattr(identity, "_storage", lambda hass, entry_id: store)
    coordinator = _coordinator()

    await identity.async_load(hass, coordinator, "entry")

    assert coordinator.identity_store is store
    assert coordinator.identities == {}


def test_save_without_a_store_does_nothing() -> None:
    """An entry that never loaded its store has nowhere to write."""
    identity._save(_coordinator())


def test_remember_saves_the_row_and_schedules_a_write() -> None:
    """Remembering a row updates the held records and asks for a write."""
    store = _Store()
    coordinator = _coordinator(store)

    identity.remember(coordinator, _row())

    assert coordinator.identities["uid"]["entity_id"] == "sensor.old"
    assert len(store.delayed) == 1
    data_func, delay = store.delayed[0]
    assert delay == identity.SAVE_DELAY
    assert data_func() == coordinator.identities
    assert data_func() is not coordinator.identities


async def test_restore_reclaims_the_entity_id_and_user_fields(
    hass: HomeAssistant,
) -> None:
    """The remembered row gets its id, name, icon and flags back."""
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="uid",
        suggested_object_id="current",
    )
    store = _Store()
    coordinator = _coordinator(store)
    coordinator.identities["uid"] = {
        "entity_id": "sensor.custom",
        "name": "Mine",
        "icon": "mdi:custom",
        "area_id": "kitchen",
        "labels": ["a", "b"],
        "aliases": ["z"],
        "options": {"sensor": {"unit": "custom"}},
        "disabled_by": RegistryEntryDisabler.USER.value,
        "hidden_by": RegistryEntryHider.INTEGRATION.value,
    }
    entity = SimpleNamespace(unique_id="uid", entity_id=row.entity_id)

    await identity.async_restore(hass, coordinator, entity)

    restored = registry.async_get("sensor.custom")
    assert restored is not None
    assert restored.name == "Mine"
    assert restored.icon == "mdi:custom"
    assert restored.area_id == "kitchen"
    assert restored.labels == {"a", "b"}
    assert set(restored.aliases) == {"z"}
    assert restored.options == {"sensor": {"unit": "custom"}}
    assert restored.disabled_by is RegistryEntryDisabler.USER
    assert restored.hidden_by is RegistryEntryHider.INTEGRATION
    assert "uid" not in coordinator.identities
    assert store.delayed, "the record is dropped and the store is written"


async def test_restore_drops_an_unknown_enum_value(
    hass: HomeAssistant,
) -> None:
    """A record from a future version does not break the restore."""
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="uid",
        suggested_object_id="current",
    )
    coordinator = _coordinator(_Store())
    coordinator.identities["uid"] = {
        "name": "Mine",
        "disabled_by": "not-a-disabler",
        "hidden_by": "not-a-hider",
    }
    entity = SimpleNamespace(unique_id="uid", entity_id=row.entity_id)

    await identity.async_restore(hass, coordinator, entity)

    restored = registry.async_get(row.entity_id)
    assert restored is not None
    assert restored.name == "Mine"
    assert restored.disabled_by is None
    assert restored.hidden_by is None


async def test_restore_keeps_the_current_id_when_the_wanted_one_is_taken(
    hass: HomeAssistant,
) -> None:
    """Another entity already holding the old id keeps it."""
    registry = er.async_get(hass)
    row = registry.async_get_or_create(
        domain="sensor",
        platform="test",
        unique_id="uid",
        suggested_object_id="current",
    )
    registry.async_get_or_create(
        domain="sensor",
        platform="other",
        unique_id="other",
        suggested_object_id="custom",
    )
    coordinator = _coordinator(_Store())
    coordinator.identities["uid"] = {
        "entity_id": "sensor.custom",
        "name": "Mine",
    }
    entity = SimpleNamespace(unique_id="uid", entity_id=row.entity_id)

    await identity.async_restore(hass, coordinator, entity)

    restored = registry.async_get(row.entity_id)
    assert restored is not None, "the entity keeps the id it has"
    assert restored.name == "Mine", "the other fields are still restored"


async def test_restore_returns_when_the_registry_row_is_gone(
    hass: HomeAssistant,
) -> None:
    """A row that disappeared before the restore is not recreated."""
    coordinator = _coordinator(_Store())
    coordinator.identities["uid"] = {"name": "Mine"}
    entity = SimpleNamespace(unique_id="uid", entity_id="sensor.missing")

    await identity.async_restore(hass, coordinator, entity)

    assert "uid" not in coordinator.identities
    assert er.async_get(hass).async_get("sensor.missing") is None


async def test_restore_returns_when_there_is_no_record(
    hass: HomeAssistant,
) -> None:
    """An entity with no remembered identity is left as Home Assistant made it."""
    coordinator = _coordinator(_Store())
    entity = SimpleNamespace(unique_id="uid", entity_id="sensor.missing")

    await identity.async_restore(hass, coordinator, entity)

    assert not coordinator.identities
