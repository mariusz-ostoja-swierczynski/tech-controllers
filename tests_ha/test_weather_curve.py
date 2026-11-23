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
    ],
)
def test_skip_unproven_curve(change: dict[str, Any]) -> None:
    """Do not treat pending or other menu settings as valid curves."""
    assert weather_curve({**_item(), **change}) is None


@pytest.mark.parametrize(
    ("bound", "value"),
    [("min", value) for value in (False, 0.0, "0", None)]
    + [("max", value) for value in (True, 1.0, "1", None)]
    + [("min", 2)],
)
def test_reject_malformed_bounds(bound: str, value: Any) -> None:
    """Reject bad bounds while the four targets are otherwise valid."""
    item = _item()
    item["params"].update(min=0, max=1)
    for point in item["params"]["points"]:
        point["value"] = 1
    item["params"][bound] = value
    assert weather_curve(item) is None


@pytest.mark.parametrize(
    ("target", "valid"), [(24, False), (25, True), (70, True), (71, False)]
)
def test_targets_at_bounds(target: int, valid: bool) -> None:
    """The controller's bounds are inclusive."""
    item = _item()
    item["params"]["points"][0]["value"] = target
    assert (weather_curve(item) is not None) is valid


def test_accept_equal_bounds() -> None:
    """A controller can constrain all four targets to a single value."""
    item = _item()
    item["params"].update(min=40, max=40)
    for point in item["params"]["points"]:
        point["value"] = 40
    assert weather_curve(item) is not None


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
    assert state.attributes["points"] == [
        {"outdoor_temperature": -20, "target_temperature": 51},
        {"outdoor_temperature": -10, "target_temperature": 46},
        {"outdoor_temperature": 0, "target_temperature": 41},
        {"outdoor_temperature": 10, "target_temperature": 36},
    ]
    assert state.attributes["minimum_target_temperature"] == 25
    assert state.attributes["maximum_target_temperature"] == 70

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
