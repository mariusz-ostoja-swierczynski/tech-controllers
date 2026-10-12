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

from custom_components.tech.config_flow import ConfigFlow
from custom_components.tech.const import CONTROLLER, DOMAIN, USER_ID, VER
from custom_components.tech.coordinator import (
    TOKEN_REJECTED,
    TOKEN_REJECTED_KEY,
    TechCoordinator,
)
from custom_components.tech.tech import Tech, TechError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_NAME, CONF_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
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


_EXPIRED = '{"error": {"authenticated": false}}'


async def test_an_expired_token_is_an_authentication_failure(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """A 401 means the token is dead, not that the controller is away.

    Home Assistant asks for credentials again on an authentication failure, so
    the entry goes to "authentication expired" with the reauthentication flow
    waiting; as an unreachable controller it would instead retry setup forever,
    which is what the reporter saw in the UI.
    """
    caplog.set_level(logging.INFO, logger=_LOGGER_NAME)
    coordinator = await _coordinator(
        hass, AsyncMock(side_effect=TechError(401, _EXPIRED))
    )

    await coordinator.async_refresh()

    assert not coordinator.last_update_success
    assert isinstance(coordinator.last_exception, ConfigEntryAuthFailed)
    assert str(coordinator.last_exception) == TOKEN_REJECTED
    # The key is what makes Home Assistant show the message in the user's
    # language; the sentence above is only the fallback.
    assert coordinator.last_exception.translation_key == TOKEN_REJECTED_KEY
    assert coordinator.last_exception.translation_domain == DOMAIN
    assert "Authentication failed while fetching tech data" in caplog.text
    assert "Error fetching tech data" not in caplog.text

    await coordinator.async_shutdown()


async def test_an_expired_token_starts_the_reauthentication_flow(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setup that meets a 401 leaves the entry asking for credentials.

    This is the reporter's case end to end: with a token the API no longer
    accepts, the entry ends up in the "authentication expired" state with the
    reauthentication flow in progress, instead of "failed, retrying".
    """
    monkeypatch.setattr(Tech, "get", AsyncMock(side_effect=TechError(401, _EXPIRED)))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=ConfigFlow.VERSION,
        unique_id="a" * 32,
        data={
            USER_ID: "42",
            CONF_TOKEN: "expired-token",
            CONTROLLER: _MODULE,
            VER: "3.0.14: L-8 DEMO",
        },
    )
    entry.add_to_hass(hass)

    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.SETUP_ERROR
    # What the frontend reads to render the entry's error: the translation key
    # resolves to this integration's ``exceptions.token_rejected`` message in
    # the user's language, with the sentence below as the fallback.
    assert entry.error_reason_translation_key == TOKEN_REJECTED_KEY
    assert entry.error_reason_translation_domain == DOMAIN
    assert entry.reason == TOKEN_REJECTED

    (progress,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert progress["step_id"] == "reauth_confirm"
