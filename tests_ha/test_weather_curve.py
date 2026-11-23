"""Read the reported weather curve and track changes on the existing poll."""

from typing import Any

from common import EMPTY_MENU, entry_for
import pytest

from custom_components.tech.tech import Tech
from custom_components.tech.weather_curve import weather_curve
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


def _item() -> dict[str, Any]:
    return {
        "id": 101,
        "type": 30,
        "menuType": "MU",
        "access": True,
        "params": {
            "min": 25,
            "max": 70,
            "points": [
                {"position": outdoor, "value": target}
                for outdoor, target in [(10, 36), (0, 41), (-10, 46), (-20, 51)]
            ],
        },
    }


@pytest.mark.parametrize(
    "change",
    [
        {"type": 1},
        {"menuType": "MI"},
        {"access": False},
        {"duringChange": "t"},
        {"duringChange": 0},
        {"params": None},
        {"params": {"min": 30, "max": 20, "points": []}},
        {"params": {"min": False, "max": 70, "points": []}},
    ],
)
def test_skip_unproven_curve(change: dict[str, Any]) -> None:
    """Do not treat pending or other menu settings as valid curves."""
    assert weather_curve({**_item(), **change}) is None


@pytest.mark.parametrize(
    "point",
    [
        None,
        {"position": -20, "value": 30},
        {"position": 10, "value": True},
        {"position": 10, "value": 75},
        {"position": "10", "value": 30},
    ],
)
def test_reject_invalid_point(point: Any) -> None:
    """Reject ambiguous outdoor positions and impossible targets."""
    item = _item()
    item["params"]["points"][0] = point
    assert weather_curve(item) is None


async def test_weather_curve_entity(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Publish one user-menu curve, tracking malformed, missing and updated data."""
    items = [_item()]
    installer = {**_item(), "id": 201, "menuType": "MI"}

    async def get(_self: Tech, path: str) -> dict[str, Any]:
        if path.endswith("/menu/MU/"):
            return {"data": {"elements": items}}
        if path.endswith("/menu/MI/"):
            return {"data": {"elements": [installer]}}
        if "/menu/" in path:
            return EMPTY_MENU
        return {"zones": {"elements": []}, "tiles": []}

    monkeypatch.setattr(Tech, "get", get)
    entry = entry_for("Synthetic")
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    (row,) = [
        row
        for row in er.async_entries_for_config_entry(registry, entry.entry_id)
        if row.unique_id.endswith("_weather_curve")
    ]
    state = hass.states.get(row.entity_id)
    assert state.state == "4"
    assert state.attributes["points"][0] == {
        "outdoor_temperature": -20,
        "target_temperature": 51,
    }

    items[0] = {**_item(), "duringChange": True}
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get(row.entity_id).state == "unavailable"

    items[0] = {**_item(), "duringChange": "f"}
    items[0]["params"]["points"][-1]["value"] = 54
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert (
        hass.states.get(row.entity_id).attributes["points"][0]["target_temperature"]
        == 54
    )

    items.clear()
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(row.entity_id)
    assert state is None or state.state == "unavailable"
