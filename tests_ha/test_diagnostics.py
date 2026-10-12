"""Tests for the diagnostics download.

A diagnostics file is meant to be pasted into an issue, so what matters is that
it says something useful about the controller and that it can never carry the
account's secrets.
"""

from __future__ import annotations

import json

from common import USER_ID, set_up
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech.diagnostics import async_get_config_entry_diagnostics
from homeassistant.const import CONF_TOKEN
from homeassistant.core import HomeAssistant

_TOKEN = "secret-account-token"


async def _diagnostics(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Return the diagnostics of an entry, freshly generated."""
    return await async_get_config_entry_diagnostics(hass, entry)


async def test_diagnostics_describe_what_the_controller_reported(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The summary counts the zones, tiles and menu items in the cached payload."""
    entry = await set_up(hass, "l12", monkeypatch)

    diagnostics = await _diagnostics(hass, entry)

    assert diagnostics["entry"]["title"] == "l12"
    assert diagnostics["entry"]["options"] == {"include_hub_in_name": False}
    assert diagnostics["controller"]["last_update_success"] is True
    assert diagnostics["controller"]["zones"] == 5
    assert diagnostics["controller"]["tiles"] == 6
    assert diagnostics["controller"]["menus"] == 0


async def test_diagnostics_never_carry_the_account_secrets(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The token and the account id are redacted wherever they appear.

    The entry's data holds the bearer token, which authenticates as the account,
    so a diagnostics file has to be safe to paste into a public issue.
    """
    entry = await set_up(hass, "l12", monkeypatch, token=_TOKEN)

    diagnostics = await _diagnostics(hass, entry)
    dumped = json.dumps(diagnostics)

    assert _TOKEN not in dumped
    assert diagnostics["entry"]["data"][CONF_TOKEN] == "**REDACTED**"
    assert entry.data[CONF_TOKEN] != diagnostics["entry"]["data"][CONF_TOKEN]
    assert entry.data[USER_ID] != diagnostics["entry"]["data"][USER_ID]
    # What is needed to reason about a report stays visible.
    assert diagnostics["entry"]["data"]["controller"]["udid"]
