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
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.tech.const import CONTROLLER, DOMAIN, SCAN_INTERVAL, VER
from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
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
        "switch": 22,
    },
    "kolton_st5305": {"binary_sensor": 33, "sensor": 61},
    "l12": {"climate": 5, "sensor": 19},
    "st521": {"binary_sensor": 65, "sensor": 84},
    "st2801": {"binary_sensor": 3, "sensor": 8},
    "pellet": {"binary_sensor": 4, "sensor": 12},
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


async def test_the_zone_devices_hang_under_the_controller(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every device of the entry names the controller's device as its parent.

    Home Assistant resolves a parent by device id, which is why the controller's
    device is created while the entry sets up; the deprecated tuple form would
    say so in the log instead.
    """
    caplog.set_level(logging.WARNING, logger="homeassistant.helpers.frame")
    entry = await set_up(hass, "l12", monkeypatch)

    registry = dr.async_get(hass)
    controller = registry.async_get_device_by_identifier((DOMAIN, UDID), entry.entry_id)
    assert controller is not None

    children = [
        device
        for device in dr.async_entries_for_config_entry(registry, entry.entry_id)
        if device.id != controller.id
    ]

    assert children
    assert {device.via_device_id for device in children} == {controller.id}
    # Every device reports the firmware of the controller it belongs to, and no
    # model: the API describes a controller with one string that carries its
    # version, and a model would only repeat the device's name.
    firmware = entry.data[CONTROLLER][VER]
    assert firmware
    assert controller.sw_version == firmware
    assert {device.sw_version for device in children} == {firmware}
    assert controller.model is None
    assert {device.model for device in children} == {None}
    # Every device keeps its name: the controller is named after the entry and a
    # child after the zone it stands for, and neither is emptied by the model
    # being cleared.
    assert controller.name == entry.title
    assert all(device.name for device in children)
    assert "deprecated `via_device`" not in caplog.text


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
