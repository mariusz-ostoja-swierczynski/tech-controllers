"""Tests for the entities a controller starts and stops reporting.

A platform builds its entities when it sets up, but a controller's
configuration changes while Home Assistant runs: a zone or a tile appears, and
one the user removed in the eModul app disappears from the payload. These drive
both halves through the recorded payloads -- a payload the test edits between
polls -- rather than through the platform setups alone.
"""

from __future__ import annotations

import copy
import json
import pathlib

from common import DOMAIN, EMPTY_MENU, UDID, entity_counts, entry_for
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech import (
    REMOVAL_MISSES,
    async_remove_config_entry_device,
    const,
)
from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"


def _payload(fixture: str) -> dict:
    """Return a module payload the test can change between polls."""
    return json.loads((_FIXTURES / fixture / "module.json").read_text())


async def _set_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, payload: dict
) -> MockConfigEntry:
    """Set an entry up, serving whatever ``payload`` holds when it next polls."""

    async def _get(_self: Tech, path: str) -> dict:
        if "/menu/" in path:
            return EMPTY_MENU
        return payload

    monkeypatch.setattr(Tech, "get", _get)

    entry = entry_for("mutable")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _poll(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Let the coordinator poll once, the way its interval does."""
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


def _entity_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """Return the entity ids this entry currently owns."""
    registry = er.async_get(hass)
    return {
        registered.entity_id
        for registered in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


def _device_ids(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """Return the ids of the devices this entry currently owns."""
    registry = dr.async_get(hass)
    return {
        device.id
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
    }


async def test_a_zone_the_controller_starts_reporting_gains_its_entities(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone added in the eModul app appears as a device with its entities.

    The payload is served from a dict the test edits, so the second poll is a
    controller that reports one zone more than the first.
    """
    payload = _payload("l12")
    entry = await _set_up(hass, monkeypatch, payload)
    before = entity_counts(hass)

    extra = copy.deepcopy(payload["zones"]["elements"][0])
    extra["zone"]["id"] = 99
    extra["zone"]["index"] = 99
    extra["description"]["name"] = "New zone"
    payload["zones"]["elements"].append(extra)

    await _poll(hass, entry)

    counts = entity_counts(hass)
    assert counts["climate"] == before["climate"] + 1
    assert counts["sensor"] > before["sensor"]

    identifiers = {
        identifier
        for device in dr.async_entries_for_config_entry(
            dr.async_get(hass), entry.entry_id
        )
        for identifier in device.identifiers
    }
    assert (DOMAIN, f"{UDID}_99") in identifiers


async def test_a_tile_the_controller_starts_reporting_gains_its_entities(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tile the controller starts sending is picked up the same way."""
    payload = _payload("l12")
    entry = await _set_up(hass, monkeypatch, payload)
    before = entity_counts(hass)

    # A temperature tile the builders know, reported visible and working.
    payload["tiles"].append(
        {
            "id": 4242,
            "menuId": 0,
            "parentId": 0,
            "orderId": 4242,
            "type": const.TYPE_TEMPERATURE,
            "visibility": True,
            "workingStatus": True,
            "params": {const.VALUE: 210},
        }
    )

    await _poll(hass, entry)

    assert entity_counts(hass)["sensor"] == before["sensor"] + 1


async def test_a_zone_gone_for_an_hour_takes_its_entities_and_device_with_it(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removal waits out the absence: one poll without a zone removes nothing.

    A controller being reconfigured reports nothing for a while, so an entry has
    to stay missing for :data:`REMOVAL_MISSES` polls in a row -- an hour at the
    polling interval -- before its entities are removed, and the device that
    held them goes with the last of them.
    """
    payload = _payload("l12")
    entry = await _set_up(hass, monkeypatch, payload)

    before_entities = _entity_ids(hass, entry)
    before_devices = _device_ids(hass, entry)

    payload["zones"]["elements"].pop(0)

    for _ in range(REMOVAL_MISSES - 1):
        await _poll(hass, entry)
    assert _entity_ids(hass, entry) == before_entities
    assert _device_ids(hass, entry) == before_devices

    await _poll(hass, entry)

    assert _entity_ids(hass, entry) < before_entities
    assert _device_ids(hass, entry) < before_devices


async def test_the_controller_device_cannot_be_removed_by_hand(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone device may be deleted by hand; the controller's own may not.

    The controller's device is the entry itself, so deleting it would be undone
    by the next setup; removing the entry is what the user means.
    """
    entry = await _set_up(hass, monkeypatch, _payload("l12"))
    registry = dr.async_get(hass)
    devices = {
        tuple(sorted(device.identifiers)): device
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
    }

    controller = devices[((DOMAIN, UDID),)]
    zone = next(
        device
        for identifiers, device in devices.items()
        if identifiers != ((DOMAIN, UDID),)
    )

    assert not await async_remove_config_entry_device(hass, entry, controller)
    assert await async_remove_config_entry_device(hass, entry, zone)
