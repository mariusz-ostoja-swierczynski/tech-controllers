"""Drive the entities of a recorded controller the way a user or automation does.

The setup tests register the entities a payload produces; these call Home
Assistant services on them and check what reached the API, which is the write
half of every platform -- number, select, switch, button and climate -- that a
setup alone cannot reach.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from common import live_entity_ids, set_up
import pytest

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant


def _posted(post: AsyncMock) -> list[str]:
    """Return the bodies the write path was called with, as text."""
    return [str(call.args[1]) for call in post.await_args_list]


def _settable(state: object) -> float:
    """Return a value inside the entity's own range, so the call is valid."""
    attributes = state.attributes
    minimum = attributes.get("min")
    maximum = attributes.get("max")
    step = attributes.get("step")
    minimum = 0 if minimum is None else minimum
    maximum = 100 if maximum is None else maximum
    step = step or 1
    if maximum <= minimum:
        return minimum
    return minimum + ((maximum - minimum) // (2 * step)) * step


async def test_numbers_send_the_value_they_were_set_to(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every number entity writes a value, scaled when its widget asks for it."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "st491", monkeypatch, post=post)

    targets = live_entity_ids(hass, "number")
    assert len(targets) > 1

    written: list[tuple[str, float]] = []
    for entity_id in targets:
        value = _settable(hass.states.get(entity_id))
        written.append((entity_id, value))
        await hass.services.async_call(
            "number",
            "set_value",
            {"entity_id": entity_id, "value": value},
            blocking=True,
        )

    bodies = _posted(post)
    assert len(bodies) == len(targets)

    # A value type 13 widget carries tenths and so is scaled by ten; every other
    # number is written as it is. Both encodings appear among these entities,
    # which is what shows the branch on the value format is taken both ways.
    scaled = 0
    for (entity_id, value), body in zip(written, bodies):
        if f'"value": {int(value * 10)}' in body:
            scaled += 1
        else:
            assert f'"value": {int(value)}' in body, entity_id
    assert scaled


async def test_selects_write_the_option_they_were_given(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Choosing an option sends the value behind its label to the API."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "st491", monkeypatch, post=post)

    targets = [
        entity_id
        for entity_id in live_entity_ids(hass, "select")
        if hass.states.get(entity_id).attributes.get("options")
    ]
    assert targets

    for entity_id in targets:
        option = hass.states.get(entity_id).attributes["options"][0]
        await hass.services.async_call(
            "select",
            "select_option",
            {"entity_id": entity_id, "option": option},
            blocking=True,
        )

    bodies = _posted(post)
    assert len(bodies) == len(targets)
    assert all("value" in body for body in bodies)


async def test_switches_turn_on_and_off(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both directions of a menu switch reach the API with their own value."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "st491", monkeypatch, post=post)

    targets = live_entity_ids(hass, "switch")
    assert targets

    for entity_id in targets:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": entity_id}, blocking=True
        )
        await hass.services.async_call(
            "switch", "turn_off", {"entity_id": entity_id}, blocking=True
        )

    bodies = _posted(post)
    assert len(bodies) == 2 * len(targets)
    assert any('"value": 1' in body for body in bodies)
    assert any('"value": 0' in body for body in bodies)


async def test_buttons_press_their_dialogue(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A dialogue button posts its own type and confirm value, then refreshes."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "st491", monkeypatch, post=post)

    targets = live_entity_ids(hass, "button")
    assert targets

    for entity_id in targets:
        await hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )

    bodies = _posted(post)
    assert len(bodies) == len(targets)
    assert all('"type"' in body for body in bodies)


async def test_thermostats_set_their_temperature_and_mode(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone's thermostat writes a target temperature and both zone modes."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "l12", monkeypatch, post=post)

    targets = live_entity_ids(hass, "climate")
    assert targets

    entity_id = targets[0]
    await hass.services.async_call(
        "climate",
        "set_temperature",
        {"entity_id": entity_id, ATTR_TEMPERATURE: 22.5},
        blocking=True,
    )
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": "off"},
        blocking=True,
    )
    await hass.services.async_call(
        "climate",
        "set_hvac_mode",
        {"entity_id": entity_id, "hvac_mode": "heat"},
        blocking=True,
    )

    bodies = _posted(post)
    assert len(bodies) == 3
    assert any("225" in body for body in bodies)
