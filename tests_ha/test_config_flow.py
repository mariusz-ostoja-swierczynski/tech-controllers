"""Tests for the Tech config flow, its options flow and its entry migration.

These drive a real Home Assistant instance through
pytest-homeassistant-custom-component, so they cover what the stubbed suites in
``tests/`` cannot: the flow exactly as Home Assistant runs it, the entry it
creates, the settings it stores and the migration of entries written by version
3. The config flow aims at full coverage of ``config_flow.py`` -- the happy
paths, every error branch and both aborts -- plus ``async_migrate_entry``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech import (
    async_migrate_entry,
    config_flow as config_flow_module,
)
from custom_components.tech.config_flow import (
    CannotConnect,
    ConfigFlow,
    InvalidAuth,
    validate_input,
)
from custom_components.tech.const import (
    CONTROLLER,
    CONTROLLERS,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    USER_ID,
    VER,
)
from custom_components.tech.tech import TechError, TechLoginError
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import TextSelectorType

_CREDENTIALS = {CONF_USERNAME: "test", CONF_PASSWORD: "test"}

_MODULES: list[dict[str, Any]] = [
    {"id": 1, "name": "L-8 DEMO", "udid": "a" * 32, "version": "3.0.14"},
    {"id": 2, "name": "ST-491 DEMO", "udid": "b" * 32, "version": "2.1.9"},
]

_VALIDATED = {USER_ID: "42", CONF_TOKEN: "token", CONTROLLERS: _MODULES}


def _patched_validation(modules: list[dict[str, Any]] | None = None):
    """Patch the credentials step so it never touches the API."""
    return patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(
            return_value={
                **_VALIDATED,
                CONTROLLERS: modules if modules is not None else _MODULES,
            }
        ),
    )


async def _start_flow(hass: HomeAssistant) -> dict[str, Any]:
    """Start a user flow and return its first form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    return result


async def _submit_credentials(
    hass: HomeAssistant, flow_id: str, modules: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Submit valid credentials and return the next step."""
    with _patched_validation(modules):
        return await hass.config_entries.flow.async_configure(flow_id, _CREDENTIALS)


async def _select(
    hass: HomeAssistant,
    flow_id: str,
    controller_id: Any,
    include_hub_in_name: bool | None = None,
) -> dict[str, Any]:
    """Submit a controller selection and return the flow result.

    ``include_hub_in_name`` is left out when it is ``None``, which is how the
    form behaves when the box is left as it is: the schema fills in its default.
    """
    user_input: dict[str, Any] = {CONTROLLERS: str(controller_id)}
    if include_hub_in_name is not None:
        user_input[INCLUDE_HUB_IN_NAME] = include_hub_in_name
    return await hass.config_entries.flow.async_configure(flow_id, user_input)


def _field_names(schema: Any) -> list[str]:
    """Return the field names of a form schema, in declaration order."""
    return [getattr(key, "schema", key) for key in schema.schema]


async def test_user_step_asks_for_username_and_password(
    hass: HomeAssistant,
) -> None:
    """The first form collects the account credentials, with the password masked."""
    result = await _start_flow(hass)

    assert _field_names(result["data_schema"]) == [CONF_USERNAME, CONF_PASSWORD]

    password_selector = result["data_schema"].schema[
        next(key for key in result["data_schema"].schema if key.schema == CONF_PASSWORD)
    ]
    assert password_selector.config["type"] == TextSelectorType.PASSWORD


async def test_credentials_lead_to_the_controller_selection(
    hass: HomeAssistant,
) -> None:
    """Correct credentials show one selectable option per controller."""
    flow_id = (await _start_flow(hass))["flow_id"]

    result = await _submit_credentials(hass, flow_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "select_controllers"
    assert _field_names(result["data_schema"]) == [
        CONTROLLERS,
        INCLUDE_HUB_IN_NAME,
    ]

    selector = result["data_schema"].schema[
        next(key for key in result["data_schema"].schema if key.schema == CONTROLLERS)
    ]
    assert selector.config["options"] == [
        {"value": "1", "label": "L-8 DEMO"},
        {"value": "2", "label": "ST-491 DEMO"},
    ]


async def test_selecting_a_controller_creates_its_entry(hass: HomeAssistant) -> None:
    """One flow run adds exactly the selected controller, and nothing else.

    The entry carries the credentials the flow validated, the controller
    payload, and the controller's udid as both its unique id and its device
    identity. The naming preference is asked alongside the controller and stored
    as the entry's option. Adding the second controller takes a second run of
    the flow.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    result = await _select(hass, flow_id, 1)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "L-8 DEMO"

    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.unique_id == "a" * 32
    assert entry.data[USER_ID] == "42"
    assert entry.data[CONF_TOKEN] == "token"
    assert entry.data[CONTROLLER][CONF_NAME] == "L-8 DEMO"
    assert entry.data[VER] == "3.0.14: L-8 DEMO"
    assert INCLUDE_HUB_IN_NAME not in entry.data
    assert entry.options == {INCLUDE_HUB_IN_NAME: False}

    # The second controller is a second run of the same flow.
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)
    result = await _select(hass, flow_id, 2)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {entry.unique_id for entry in hass.config_entries.async_entries(DOMAIN)} == {
        "a" * 32,
        "b" * 32,
    }


@pytest.mark.parametrize(
    ("given", "expected"),
    [(None, False), (False, False), (True, True)],
    ids=["left-alone", "unticked", "ticked"],
)
async def test_the_naming_preference_becomes_the_entry_option(
    hass: HomeAssistant, given: bool | None, expected: bool
) -> None:
    """The checkbox is stored as the entry's option, by its value.

    Asking it during setup keeps a setting from being buried in the options
    dialog, and the answer is still stored where settings belong. Only the value
    counts: the schema fills the key in even when the box was left unticked, so
    reading the key's presence would store True for an untouched form.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    await _select(hass, flow_id, 1, include_hub_in_name=given)

    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.options == {INCLUDE_HUB_IN_NAME: expected}


async def test_invalid_credentials_are_reported(hass: HomeAssistant) -> None:
    """A rejected login keeps the user on the form with the reason shown."""
    flow_id = (await _start_flow(hass))["flow_id"]

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, _CREDENTIALS)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_cannot_connect_is_reported(hass: HomeAssistant) -> None:
    """An unreachable API is reported as a connection problem."""
    flow_id = (await _start_flow(hass))["flow_id"]

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, _CREDENTIALS)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unexpected_errors_are_reported(hass: HomeAssistant) -> None:
    """Anything else is reported as an unknown error rather than crashing."""
    flow_id = (await _start_flow(hass))["flow_id"]

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await hass.config_entries.flow.async_configure(flow_id, _CREDENTIALS)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "unknown"}


async def test_an_account_without_controllers_aborts(hass: HomeAssistant) -> None:
    """An account with no controller has nothing to add, and says so."""
    flow_id = (await _start_flow(hass))["flow_id"]

    result = await _submit_credentials(hass, flow_id, modules=[])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_modules"
    assert not hass.config_entries.async_entries(DOMAIN)


async def test_a_controller_cannot_be_added_twice(hass: HomeAssistant) -> None:
    """The same controller cannot be set up a second time.

    Its udid is the entry's unique id, so Home Assistant refuses the duplicate
    before an entry is created for a device that already has one.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)
    await _select(hass, flow_id, 1)

    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    result = await _select(hass, flow_id, 1)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert len(hass.config_entries.async_entries(DOMAIN)) == 1


async def test_options_flow_stores_the_hub_name_flag(hass: HomeAssistant) -> None:
    """The hub-name setting lives in the entry's options, and a change reloads it.

    The flag is a preference, not something needed to connect, so it is not
    asked for during setup and can be changed afterwards.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)
    await _select(hass, flow_id, 1)
    entry = hass.config_entries.async_entries(DOMAIN)[0]

    result = await hass.config_entries.options.async_init(entry.entry_id)

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "init"
    assert _field_names(result["data_schema"]) == [INCLUDE_HUB_IN_NAME]

    with patch.object(
        hass.config_entries, "async_schedule_reload", Mock()
    ) as reload_entry:
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {INCLUDE_HUB_IN_NAME: True}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {INCLUDE_HUB_IN_NAME: True}
    reload_entry.assert_called_once_with(entry.entry_id)


async def test_migration_moves_the_hub_name_flag_into_options(
    hass: HomeAssistant,
) -> None:
    """A version 3 entry keeps its setting and loses it from the data.

    Before version 4 the flag sat among the entry's data; the migration moves it
    where the other preferences are, so the platforms read it from one place.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=3,
        unique_id="a" * 32,
        data={
            USER_ID: "42",
            CONF_TOKEN: "token",
            INCLUDE_HUB_IN_NAME: True,
            CONTROLLER: _MODULES[0],
        },
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == ConfigFlow.VERSION
    assert entry.options == {INCLUDE_HUB_IN_NAME: True}
    assert INCLUDE_HUB_IN_NAME not in entry.data
    assert entry.data[CONTROLLER] == _MODULES[0]


async def test_migration_of_an_entry_without_the_flag(hass: HomeAssistant) -> None:
    """A version 3 entry that never carried the flag only moves version."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=3,
        unique_id="a" * 32,
        data={USER_ID: "42", CONF_TOKEN: "token", CONTROLLER: _MODULES[0]},
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry)

    assert entry.version == ConfigFlow.VERSION
    assert entry.options == {}
    assert entry.data.keys() == {USER_ID, CONF_TOKEN, CONTROLLER}


# ---------------------------------------------------------------------------
# The credentials validation itself, and the branches the flow enters around it
# ---------------------------------------------------------------------------


class _FakeTech:
    """Stand-in for the API client, for the tests of ``validate_input``.

    The flow tests above replace ``validate_input`` because they are about the
    flow; these replace the client instead, so the real validation runs and its
    error mapping is exercised.
    """

    user_id = "42"
    token = "token"

    def __init__(self, session: Any, *args: Any, **kwargs: Any) -> None:
        """Accept the arguments the client takes, and keep none of them."""
        self.session = session

    async def authenticate(self, username: str, password: str) -> bool:
        """Accept every login."""
        return True

    async def list_modules(self) -> list[dict[str, Any]]:
        """Return the account's controllers."""
        return _MODULES


class _UnauthenticatedTech(_FakeTech):
    """An API that answers the login with "not authenticated"."""

    async def authenticate(self, username: str, password: str) -> bool:
        """Report the credentials as rejected."""
        return False


class _RejectedTech(_FakeTech):
    """An API that answers the login itself with an error."""

    async def authenticate(self, username: str, password: str) -> bool:
        """Raise what the client raises for a rejected login."""
        raise TechLoginError(401, "Unauthorized")


class _FailingTech(_FakeTech):
    """An API that fails after the login succeeded."""

    async def list_modules(self) -> list[dict[str, Any]]:
        """Raise what the client raises for a failed call."""
        raise TechError(500, "Server error")


async def test_validate_input_returns_the_account_metadata(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A successful login yields the account id, the token and the controllers."""
    monkeypatch.setattr(config_flow_module, "Tech", _FakeTech)

    assert await validate_input(hass, _CREDENTIALS) == {
        USER_ID: "42",
        CONF_TOKEN: "token",
        CONTROLLERS: _MODULES,
    }


async def test_validate_input_rejects_a_false_authentication(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An API that answers "not authenticated" means the credentials are wrong."""
    monkeypatch.setattr(config_flow_module, "Tech", _UnauthenticatedTech)

    with pytest.raises(InvalidAuth):
        await validate_input(hass, _CREDENTIALS)


async def test_validate_input_reports_a_login_error_as_invalid_auth(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API's own login rejection is the same thing to the user."""
    monkeypatch.setattr(config_flow_module, "Tech", _RejectedTech)

    with pytest.raises(InvalidAuth):
        await validate_input(hass, _CREDENTIALS)


async def test_validate_input_reports_an_api_error_as_cannot_connect(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing call after the login is a connection problem, not a bad password."""
    monkeypatch.setattr(config_flow_module, "Tech", _FailingTech)

    with pytest.raises(CannotConnect):
        await validate_input(hass, _CREDENTIALS)


async def test_selecting_without_credentials_starts_over(
    hass: HomeAssistant,
) -> None:
    """A stale flow that holds no credentials falls back to the login form.

    Home Assistant only dispatches to the current step, so this cannot happen
    through the flow manager; the guard is here for a flow that lost its state,
    and it is covered by calling the step directly.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": config_entries.SOURCE_USER}

    result = await flow.async_step_select_controllers()

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_selecting_a_controller_the_account_lost_aborts(
    hass: HomeAssistant,
) -> None:
    """A selection that is not one of the account's controllers adds nothing.

    The select in the form only offers the account's controllers, so Home
    Assistant rejects anything else before the step sees it; the guard is here
    for a selection that went stale, and it is covered by calling the step
    directly.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": config_entries.SOURCE_USER}
    flow._init_info = _VALIDATED
    flow._controllers = flow._create_controllers_array(_VALIDATED)

    result = await flow.async_step_select_controllers({CONTROLLERS: "99"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_modules"
    assert not hass.config_entries.async_entries(DOMAIN)
