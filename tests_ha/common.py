"""Helpers for the Home Assistant suite: recorded controllers and their entities.

The fixtures under ``tests/fixtures`` hold what the eModul API answered for
several reported controllers, so they are served to the integration the way the
API would answer, which is what makes the platform setups walk a real payload
instead of an empty envelope.
"""

from __future__ import annotations

from collections import Counter
import json
import pathlib
from typing import Any
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech.config_flow import ConfigFlow
from custom_components.tech.const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    USER_ID,
    VER,
)
from custom_components.tech.tech import Tech
from homeassistant.const import CONF_TOKEN, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

FIXTURES = pathlib.Path(__file__).resolve().parents[1] / "tests" / "fixtures"
UDID = "a" * 32
EMPTY_MENU: dict[str, Any] = {"status": "success", "data": {"elements": []}}


def controller_payload(name: str) -> dict[str, Any]:
    """Return the controller payload the config flow stores in an entry.

    It carries the personal data the API returns with a controller (owner
    email, phone and postcode) so the diagnostics test can prove a download
    taken from it is safe to paste into a public issue.
    """
    return {
        "id": 1,
        "name": name,
        "udid": UDID,
        "version": "1.0.0",
        "email": "owner@example.com",
        "phoneNumber": "+48123456789",
        "zipCode": "00-001",
    }


def entry_for(name: str, *, token: str = "token") -> MockConfigEntry:
    """Return an entry for one controller, not yet added to Home Assistant.

    The options mirror what the config flow stores, and the token is a parameter
    so a test can tell a secret apart from the word "token" in a dump.
    """
    return MockConfigEntry(
        domain=DOMAIN,
        title=name,
        version=ConfigFlow.VERSION,
        unique_id=UDID,
        data={
            USER_ID: "42",
            CONF_TOKEN: token,
            CONTROLLER: controller_payload(name),
            VER: "1.0.0: " + name,
        },
        options={INCLUDE_HUB_IN_NAME: False},
    )


async def set_up(
    hass: HomeAssistant,
    fixture: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    post: AsyncMock | None = None,
    token: str = "token",
) -> MockConfigEntry:
    """Set an entry up while the API answers with the recorded payloads.

    Args:
        hass: Home Assistant instance.
        fixture: Directory under ``tests/fixtures`` to answer with.
        monkeypatch: Test fixture used to replace the API transport.
        post: Optional stub for the write path, so a test can see what an
            entity's action sent; the shared offline stub answers otherwise.
        token: Bearer token the entry holds, distinctive where a test needs to
            spot a leak of it.

    Returns:
        The config entry, now set up.

    """
    module = json.loads((FIXTURES / fixture / "module.json").read_text())
    menus_file = FIXTURES / fixture / "menus.json"
    menus = json.loads(menus_file.read_text()) if menus_file.exists() else {}

    async def _get(_self: Tech, path: str) -> dict[str, Any]:
        # ``Tech.get`` is patched on the class, so it is bound like a method.
        if "/menu/" in path:
            menu_type = path.rstrip("/").rsplit("/", 1)[-1]
            return menus.get(menu_type, EMPTY_MENU)
        return module

    monkeypatch.setattr(Tech, "get", _get)
    if post is not None:
        monkeypatch.setattr(Tech, "post", post)

    entry = entry_for(fixture, token=token)
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


def entity_counts(hass: HomeAssistant) -> dict[str, int]:
    """Return how many entities of each domain this integration registered."""
    registry = er.async_get(hass)
    return dict(
        Counter(
            entity.entity_id.split(".", 1)[0]
            for entity in registry.entities.values()
            if entity.platform == DOMAIN
        )
    )


def entity_ids(hass: HomeAssistant, domain: str) -> list[str]:
    """Return the registered entity ids of one domain, in a stable order."""
    registry = er.async_get(hass)
    return sorted(
        entity.entity_id
        for entity in registry.entities.values()
        if entity.platform == DOMAIN and entity.entity_id.startswith(f"{domain}.")
    )


def live_entity_ids(hass: HomeAssistant, domain: str) -> list[str]:
    """Return the entity ids of one domain that a user could actually act on.

    Entities the integration registers as disabled-by-default are in the
    registry but carry no state, and Home Assistant skips a service call aimed
    at an unavailable entity, so both are left out: neither is something a
    service call can reach.
    """
    live = []
    for entity_id in entity_ids(hass, domain):
        state = hass.states.get(entity_id)
        if state is not None and state.state != STATE_UNAVAILABLE:
            live.append(entity_id)
    return live
