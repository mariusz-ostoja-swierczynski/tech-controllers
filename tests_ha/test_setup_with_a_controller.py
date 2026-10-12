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

from typing import Any

from common import EMPTY_MENU, entity_counts, entry_for, set_up
import pytest

from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant

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
}


@pytest.mark.parametrize("fixture", sorted(_EXPECTED))
async def test_the_recorded_payload_builds_its_entities(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    """A recorded controller set up for real produces exactly its entities."""
    await set_up(hass, fixture, monkeypatch)

    assert entity_counts(hass) == _EXPECTED[fixture]


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
