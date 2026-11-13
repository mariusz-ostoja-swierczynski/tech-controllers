"""Set the integration up against the controller payloads kept as fixtures.

The config flow tests set an entry up against an empty envelope, so the platform
``async_setup_entry`` bodies never walk a real payload and the tile, zone and
menu code paths stay cold. These tests serve the recorded controllers through
the API stub instead, which is what makes those paths run.

The fixtures keep the shape the API answers with, so they are served unchanged:
``tiles`` as a list, ``zones`` as the ``zones.elements`` envelope whose entries
wrap the zone in a ``zone`` key, and, for the ST-491, the four menus. Only the
L-12 records visible zones -- the other controllers are heat pumps or were
recorded with their zones stripped -- so its numbers are the ones that cover the
climate platform, while the ST-491's menus cover the menu platforms.
"""

from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any
from unittest.mock import AsyncMock

from common import EMPTY_MENU, UDID, entity_counts, entry_for, set_up
import pytest
from pytest_homeassistant.common import async_fire_time_changed

from custom_components.tech.const import DOMAIN, SCAN_INTERVAL
from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.util import dt as dt_util

# What each recorded controller produces, per entity domain. Pinned so that a
# change in what a payload builds shows up as a failing count rather than as a
# quiet drop in coverage.
_EXPECTED = {
    "st491": {
        "binary_sensor": 4,
        "button": 13,
        "number": 78,
        "select": 19,
        "sensor": 17,
        "switch": 28,
    },
    "kolton_st5305": {
        "binary_sensor": 33,
        "button": 8,
        "number": 130,
        "select": 14,
        "sensor": 61,
        "switch": 28,
    },
    # The L-12 reports schedules, so each of its five zones also gets the
    # schedule reading, the local template and the schedule select, the
    # controller gets the five global slots and the compact diagnostic, and the
    # problem indicator is a binary sensor.
    "l12": {"binary_sensor": 1, "climate": 5, "select": 5, "sensor": 35},
    "st521": {"binary_sensor": 65, "sensor": 84},
    "st2801": {"binary_sensor": 3, "sensor": 8},
    "pellet": {"binary_sensor": 4, "sensor": 12},
    # The live demo account's current controllers. They were downloaded from
    # the eModul API and are kept unchanged, so the tests cover the real
    # installation, zones-controller and solar payload shapes.
    "demo_i3": {"binary_sensor": 9, "sensor": 25},
    "demo_l12": {"binary_sensor": 1, "climate": 8, "select": 8, "sensor": 46},
    "demo_l8": {"binary_sensor": 1, "climate": 8, "select": 8, "sensor": 66},
    "demo_pellet": {"binary_sensor": 4, "sensor": 12},
    "demo_solar": {"binary_sensor": 1, "sensor": 5},
    # Issue-provided dumps, sanitized: the controller name, mainControllerId
    # and any menu passwords are removed or redacted before they are committed.
    # The counts pin what each real-world payload builds.
    "st581_user": {
        "binary_sensor": 8,
        "button": 18,
        "number": 112,
        "select": 27,
        "sensor": 12,
        "switch": 38,
    },
    "st534g_user": {"binary_sensor": 3, "sensor": 4},
    "i3_plus_user": {"binary_sensor": 13, "sensor": 28},
    "st9721_user": {"binary_sensor": 9, "sensor": 15},
    "i1_cwu_user": {"binary_sensor": 2, "sensor": 10},
    "i3_plus_solar_user": {"binary_sensor": 12, "sensor": 16},
}


@pytest.mark.parametrize("fixture", sorted(_EXPECTED))
async def test_the_recorded_payload_builds_its_entities(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    """A recorded controller set up for real produces exactly its entities."""
    await set_up(hass, fixture, monkeypatch)

    assert entity_counts(hass) == _EXPECTED[fixture]


async def test_a_platform_never_claims_the_same_unique_id_twice(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pass that finds an entity again does not register it a second time.

    Pellet DEMO's relay tiles exposed a race in the per-poll registration: an
    entity reaches the coordinator's bookkeeping only once Home Assistant has
    called it back, which can be after the pass that added it, and a pass that
    forgot it in the meantime added it again. Home Assistant ignores the second
    claim and says so with an error in the log, which the live instance showed
    for tile 1002 of that controller.
    """
    await set_up(hass, "pellet", monkeypatch)

    assert "does not generate unique IDs" not in caplog.text
    assert entity_counts(hass) == {"binary_sensor": 4, "sensor": 12}


async def test_renaming_an_entity_keeps_it_in_place(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An entity_id change is a rename, not a departure.

    Home Assistant removes and re-adds an entity whose class has not opted in to
    the in-place rename. That departure told the platform the entity left, and
    the next poll registered a second object for the same unique id, which Home
    Assistant refused with a duplicate-unique-id error. Assigning a device to an
    area renames its entities, which is how a fresh install hit it.
    """
    entry = await set_up(hass, "pellet", monkeypatch)
    registry = er.async_get(hass)
    row = next(row for row in registry.entities.values() if row.platform == DOMAIN)
    new_entity_id = row.entity_id.replace(".", ".renamed_", 1)

    registry.async_update_entity(row.entity_id, new_entity_id=new_entity_id)
    await hass.async_block_till_done()

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    renamed = registry.async_get(new_entity_id)
    assert renamed is not None
    assert renamed.unique_id == row.unique_id
    assert "does not generate unique IDs" not in caplog.text


async def test_a_controller_that_reports_nothing_builds_nothing(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A payload without tiles, zones or menus produces no entities and no error."""

    async def _get(_self: Tech, path: str) -> dict[str, Any]:
        return EMPTY_MENU

    monkeypatch.setattr(Tech, "get", _get)

    entry = entry_for("empty")
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entity_counts(hass) == {}


@pytest.mark.parametrize("fixture", sorted(_EXPECTED))
async def test_a_poll_hands_the_payload_to_every_entity_again(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    """A later poll updates every entity that the setup registered.

    The setups add their entities with an update, so this is the path a 60-second
    poll takes afterwards: the coordinator hands the payload down and each entity
    re-reads its own tile, zone or menu item.
    """
    entry = await set_up(hass, fixture, monkeypatch)

    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()

    assert entry.runtime_data.last_update_success
    assert entity_counts(hass) == _EXPECTED[fixture]


async def test_the_zone_devices_are_children_of_the_controller(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every zone device is a child of the controller's device.

    A zone is a logical part of the controller, not a separate product reached
    through it, so the registry records a child relationship: the zone points at
    its parent device, has no via link, and carries no hardware identity of its
    own. The parent's manufacturer, model and firmware are what the frontend
    shows for the child.
    """
    caplog.set_level(logging.WARNING, logger="homeassistant.helpers.frame")
    entry = await set_up(hass, "l12", monkeypatch)

    registry = dr.async_get(hass)
    controller = registry.async_get_device_by_identifier((DOMAIN, UDID), entry.entry_id)
    assert controller is not None

    children = dr.async_child_entries_for_config_entry(registry, entry.entry_id)

    assert children
    assert {device.parent_device_id for device in children} == {controller.id}
    # A child device is a lightweight entry: it has no via link and no
    # manufacturer, model or firmware of its own.
    for device in children:
        assert not hasattr(device, "via_device_id")
        assert not hasattr(device, "manufacturer")
        assert not hasattr(device, "model")
        assert not hasattr(device, "sw_version")
    # Every device keeps its name: the controller is named after the entry and a
    # child after the zone it stands for, and neither is emptied by the model
    # being cleared.
    assert controller.name == entry.title
    assert all(device.name for device in children)
    assert "deprecated `via_device`" not in caplog.text


async def test_an_existing_zone_device_becomes_a_child_in_place(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone device from a previous setup is converted to a child, keeping its id.

    The zone's identifiers have not changed, so Home Assistant finds the device
    the integration created before the migration and adopts it as a child
    instead of replacing it: device-based automations keep working.
    """
    registry = dr.async_get(hass)
    existing_id: str | None = None

    def _precreate(entry: Any) -> None:
        nonlocal existing_id
        existing = registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            identifiers={(DOMAIN, f"{UDID}_9061")},
            name="Old zone device",
        )
        existing_id = existing.id

    entry = await set_up(hass, "l12", monkeypatch, before_setup=_precreate)

    # The pre-created device is a live main device for this setup, so Home
    # Assistant refuses the conversion. The next setup, after an unload, is what
    # a user gets when they upgrade: the device from the previous setup can then
    # be adopted as a child without changing its id.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    controller = registry.async_get_device_by_identifier((DOMAIN, UDID), entry.entry_id)
    zones = [
        device
        for device in dr.async_child_entries_for_config_entry(
            registry, entry.entry_id
        )
        if (DOMAIN, f"{UDID}_9061") in device.identifiers
    ]
    assert controller is not None
    assert zones
    zone = zones[0]
    assert zone.id == existing_id
    assert zone.parent_device_id == controller.id


async def test_unloading_the_entry_stops_the_polling(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unloading leaves nothing polling the controller behind it.

    Home Assistant reloads an entry whenever its options change, and every
    reload builds a fresh coordinator. A coordinator that kept its 60-second
    timer through the unload would leave one more poller behind on each change.
    """
    entry = await set_up(hass, "st491", monkeypatch)
    get = AsyncMock(return_value=EMPTY_MENU)
    monkeypatch.setattr(Tech, "get", get)

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    get.reset_mock()
    async_fire_time_changed(
        hass, dt_util.utcnow() + SCAN_INTERVAL + timedelta(seconds=1)
    )
    await hass.async_block_till_done()

    get.assert_not_awaited()
