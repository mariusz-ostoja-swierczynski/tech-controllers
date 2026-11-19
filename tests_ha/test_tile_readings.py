"""A reading a controller reports has to reach the entity that publishes it.

Home Assistant serves a sensor's state from ``native_value``, and every entity
here caches the reading it read from the payload. Version 3 moved the published
value to ``_attr_native_value`` and left one class writing its cache only, so a
valve's opening percentage froze at the value of the setup payload and only a
reload moved it again (issue #249). These tests take the path a poll takes: the
payload changes underneath the entities, the coordinator hands it down, and the
states Home Assistant serves must follow.
"""

from __future__ import annotations

import copy
import json
import pathlib
from typing import Any

from common import EMPTY_MENU, entry_for
import pytest
from pytest_homeassistant.common import MockConfigEntry

from custom_components.tech.sensor import TileSensor
from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

_FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"

# Controllers whose payload carries the valve tile (type 23) the report was
# written about, plus a heat pump and a solar controller for the rest.
_CARRIERS = ("pellet", "demo_i3", "demo_pellet")


def _payload(fixture: str) -> dict[str, Any]:
    """Return a controller payload the test can change between polls."""
    return json.loads((_FIXTURES / fixture / "module.json").read_text())


async def _set_up(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any]
) -> MockConfigEntry:
    """Set an entry up, serving whatever ``payload`` holds when it next polls."""

    async def _get(_self: Tech, path: str) -> dict[str, Any]:
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


def _changed(node: Any) -> Any:
    """Return ``node`` with every numeric reading changed, booleans untouched.

    Booleans are left alone on purpose: they are the payload's "this input is
    working" flags, and a reading behind a switched-off input is ``None`` by
    design rather than stale.
    """
    if isinstance(node, dict):
        return {key: _changed(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_changed(value) for value in node]
    if isinstance(node, int) and not isinstance(node, bool):
        return node + 7
    return node


def _entity_in(hass: HomeAssistant, entry: MockConfigEntry, suffix: str) -> str:
    """Return the entity id whose unique id ends with ``suffix``."""
    registry = er.async_get(hass)
    row = next(
        row
        for row in er.async_entries_for_config_entry(registry, entry.entry_id)
        if row.unique_id.endswith(suffix)
    )
    return row.entity_id


async def test_a_valves_opening_follows_the_payload(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A valve the controller closes again reports the new opening after a poll.

    The reported controller's ``sensor.defro_calori_built_in_valve_1`` stayed at
    the percentage it was set up with -- ten while the eModul app showed a
    hundred -- and moved only when the integration was reloaded.
    """
    payload = _payload("pellet")
    entry = await _set_up(hass, monkeypatch, payload)

    valve = _entity_in(hass, entry, "_1012_tile_valve")
    before = hass.states.get(valve)
    assert before is not None
    assert before.state == "100"

    tile = next(tile for tile in payload["tiles"] if tile["id"] == 1012)
    tile["params"]["openingPercentage"] = 10

    await _poll(hass, entry)

    after = hass.states.get(valve)
    assert after is not None
    assert after.state == "10"


@pytest.mark.parametrize("fixture", _CARRIERS)
async def test_every_tile_sensor_publishes_the_reading_it_reads(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, fixture: str
) -> None:
    """After a poll every tile sensor serves what its ``get_state`` reads.

    The comparison is against the entity's own reading of the refreshed tile, so
    a class that reads the payload but publishes it somewhere Home Assistant
    never looks fails here, whatever field it is that it forgot.
    """
    payload = _payload(fixture)
    entry = await _set_up(hass, monkeypatch, payload)
    coordinator = entry.runtime_data

    for tile in payload["tiles"]:
        tile["params"] = _changed(copy.deepcopy(tile["params"]))

    await _poll(hass, entry)

    checked = 0
    for source_key, entities in coordinator.reported.items():
        if not source_key.startswith("tile_"):
            continue
        tile = coordinator.data["tiles"][int(source_key.split("_", 1)[1])]
        for entity in entities:
            if not isinstance(entity, TileSensor):
                continue
            expected = entity.get_state(tile)
            state = hass.states.get(entity.entity_id)
            if expected is None or state is None:
                # A reading behind a switched-off input is unavailable, and a
                # disabled-by-default entity was never written a state.
                continue
            checked += 1
            assert state.state == str(expected), (
                entity.entity_id,
                state.state,
                expected,
            )

    # The parametrised controllers all carry tile sensors, so an empty sweep
    # would be a test that asserts nothing.
    assert checked
