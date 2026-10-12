"""Tests for the coordinator's failure and recovery behaviour.

These run against a real Home Assistant, because the behaviour under test is
Home Assistant's: its coordinator logs the transition to unreachable once and
the recovery once, and marks the entities unavailable in between -- but only for
failures raised as ``UpdateFailed``. Anything else takes the unexpected-error
path, which logs a traceback on every poll.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech.const import CONTROLLER, DOMAIN, USER_ID
from custom_components.tech.coordinator import TechCoordinator
from custom_components.tech.tech import TechError
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER_NAME = "custom_components.tech"

_MODULE = {"id": 1, "name": "L-8 DEMO", "udid": "a" * 32, "version": "3.0.14"}
_PAYLOAD = {"zones": {}, "tiles": {}, "menus": {}}


async def _coordinator(hass: HomeAssistant, module_data: AsyncMock) -> TechCoordinator:
    """Return a coordinator whose API client is the given stub."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=4,
        unique_id="a" * 32,
        data={USER_ID: "42", CONTROLLER: _MODULE, CONF_NAME: "L-8 DEMO"},
    )
    entry.add_to_hass(hass)

    coordinator = TechCoordinator(hass, async_get_clientsession(hass), "42", "token")
    # Normally set by Home Assistant while it sets the entry up.
    coordinator.config_entry = entry
    coordinator.api = SimpleNamespace(module_data=module_data)
    return coordinator


async def test_the_unreachable_transition_is_logged_once_and_the_recovery_once(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A controller that stays away is reported once, its return once.

    Polling continues while the controller is unreachable, so logging every
    attempt would flood the log with the same line; Home Assistant logs the
    transition instead, which is what this pins.
    """
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    coordinator = await _coordinator(hass, AsyncMock(return_value=_PAYLOAD))

    await coordinator.async_refresh()
    assert coordinator.last_update_success

    coordinator.api.module_data = AsyncMock(
        side_effect=TechError(503, "Service Unavailable")
    )
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert caplog.text.count("Error fetching tech data") == 1
    assert "recovered" not in caplog.text

    coordinator.api.module_data = AsyncMock(return_value=_PAYLOAD)
    await coordinator.async_refresh()

    assert coordinator.last_update_success
    assert caplog.text.count("Fetching tech data recovered") == 1

    await coordinator.async_shutdown()


async def test_a_timeout_is_an_unreachable_controller_not_an_unexpected_error(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The API taking too long is the controller being away, not a bug.

    A timeout used to escape the coordinator's error handling and be logged as
    an unexpected error with a traceback on every poll; it is now the same
    "cannot reach it right now" failure as an API error.
    """
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    coordinator = await _coordinator(hass, AsyncMock(side_effect=TimeoutError()))

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert caplog.text.count("Error fetching tech data") == 1
    assert "Unexpected error" not in caplog.text

    await coordinator.async_shutdown()
