"""Exercise each weekly menu sensor through Home Assistant's normal entry."""

from typing import Any

from common import EMPTY_MENU, entry_for
import pytest
from test_menu_schedules import _day, _snapshot

from custom_components.tech.tech import Tech, TechError
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def test_weekly_schedules_follow_the_full_menu(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discover later, keep distinct identities, and disregard stale menu values."""
    snapshot = _snapshot()
    connected = False

    async def get(_self: Tech, path: str) -> dict[str, Any]:
        if "/menu/" in path:
            tree = path.rstrip("/").rsplit("/", 1)[-1]
            if not connected and tree == "MI":
                raise TechError(503, "unavailable")
            if connected and tree in snapshot:
                return {"data": snapshot[tree]}
            return EMPTY_MENU
        return {"tiles": [], "zones": {"elements": []}}

    monkeypatch.setattr(Tech, "get", get)
    entry = entry_for("Synthetic")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)

    def entities() -> dict[str, str]:
        return {
            row.unique_id.split("_menu_", 1)[1]: row.entity_id
            for row in er.async_entries_for_config_entry(registry, entry.entry_id)
            if row.unique_id.endswith("_weekly")
        }

    assert not entities()
    connected = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    rows = entities()
    dhw = rows["MU_30028_weekly"]
    circulation = rows["MI_30666_weekly"]
    assert hass.states.get(dhw).state == "ready"
    assert hass.states.get(circulation).attributes["schedule_selected"] is True
    assert (
        hass.states.get(dhw).attributes["days"]["monday"]["intervals"][0]["target"]
        == 43
    )

    # The ordinary menu cache keeps one item for each id. Both original
    # records must still reach the schedule decoder and invalidate this day.
    snapshot["MU"]["elements"].append(_day(snapshot))
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(dhw).state == "invalid"
    assert not hass.states.get(dhw).attributes["days"]["monday"]["valid"]

    connected = False
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(dhw).state == "missing"
    assert hass.states.get(dhw).attributes["days"]["monday"]["intervals"] == []
    assert hass.states.get(circulation).state == "unavailable"

    snapshot["MU"]["elements"].pop()
    connected = True
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert entities() == rows
    assert hass.states.get(dhw).state == "ready"
    assert hass.states.get(circulation).state == "ready"
