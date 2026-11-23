"""The controller's DHW pump signal survives a neutral correction on restart."""

from typing import Any

from common import EMPTY_MENU, entry_for
import pytest

from custom_components.tech.tech import Tech
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


@pytest.mark.parametrize("initial", [0, 1])
async def test_dhw_pump_status_neutral(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, initial: int
) -> None:
    """Read the status independently of a changing correction widget."""
    params = {
        "iconId": 17,
        "statusId": initial,
        "widget1": {"type": 0, "txtId": 0, "unit": -1, "value": 0},
        "widget2": {"type": 9, "txtId": 573, "unit": 7, "value": 492},
    }
    tile = {"id": 42, "type": 6, "visibility": True, "menuId": 3203, "params": params}
    other_tile = {**tile, "id": 43, "menuId": 987, "params": dict(params)}

    async def get(_self: Tech, path: str) -> dict[str, Any]:
        if "/menu/" in path:
            return EMPTY_MENU
        return {"tiles": [tile, other_tile], "zones": {"elements": []}}

    monkeypatch.setattr(Tech, "get", get)
    entry = entry_for("Synthetic")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    (row,) = [
        row
        for row in er.async_entries_for_config_entry(registry, entry.entry_id)
        if row.unique_id.endswith("_tile_status")
    ]
    assert row.unique_id.endswith("_42_tile_status")
    assert hass.states.get(row.entity_id).state == ("on" if initial else "off")

    params["widget1"] = {"type": 1, "txtId": 575, "unit": 7, "value": -50}
    params["statusId"] = 1 - initial
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(row.entity_id).state == ("off" if initial else "on")

    params["statusId"] = 2
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(row.entity_id).state == "unknown"

    params.pop("statusId")
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(row.entity_id).state == "unknown"
