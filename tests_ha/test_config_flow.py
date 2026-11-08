"""Tests for the Tech config flow, its options flow and its entry migration.

These drive a real Home Assistant instance through
pytest-homeassistant-custom-component, so they cover what the stubbed suites in
``tests/`` cannot: the flow exactly as Home Assistant runs it, the entry it
creates, the settings it stores and the migration of entries written by version
3. The config flow aims at full coverage of ``config_flow.py`` -- the happy
paths, every error branch and both aborts -- plus ``async_migrate_entry``.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant.common import MockConfigEntry

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
    CONF_CONFIGURE_MENU_CODES,
    CONF_MENU_CODES,
    CONTROLLER,
    CONTROLLERS,
    DOMAIN,
    MENU_CODE_TREES,
    MENU_TYPE_INSTALLER,
    MENU_TYPE_MANUFACTURER,
    MENU_TYPE_SERVICE,
    MENU_TYPE_USER,
    UDID,
    USER_ID,
    VER,
    menu_code_field,
)
from custom_components.tech.tech import TechError, TechLoginError
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryError
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
    codes: dict[str, str] | None = None,
    configure_menu_codes: bool | None = None,
) -> dict[str, Any]:
    """Submit the controller form and return the flow result.

    The form creates the entry directly. ``configure_menu_codes`` is left out
    when it is ``None``, which is how the form behaves when the checkbox is left
    as it is: the schema fills in its default. Codes submitted without an
    explicit checkbox are submitted with it ticked, which is what a user giving
    a code does; the checkbox is passed as ``False`` to prove that a hidden
    field stores nothing.
    """
    user_input: dict[str, Any] = {CONTROLLERS: str(controller_id)}
    if configure_menu_codes is not None:
        user_input[CONF_CONFIGURE_MENU_CODES] = configure_menu_codes
    elif codes:
        user_input[CONF_CONFIGURE_MENU_CODES] = True
    user_input.update(codes or {})
    return await hass.config_entries.flow.async_configure(flow_id, user_input)


async def _create_entry(hass: HomeAssistant, controller_id: Any = 1) -> dict[str, Any]:
    """Run the whole flow for one controller, with no menu codes."""
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)
    return await _select(hass, flow_id, controller_id)


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
        CONF_CONFIGURE_MENU_CODES,
        menu_code_field(MENU_TYPE_USER),
        menu_code_field(MENU_TYPE_INSTALLER),
        menu_code_field(MENU_TYPE_SERVICE),
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
    assert entry.options == {}

    # The second controller is a second run of the same flow.
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)
    result = await _select(hass, flow_id, 2)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert {entry.unique_id for entry in hass.config_entries.async_entries(DOMAIN)} == {
        "a" * 32,
        "b" * 32,
    }


async def test_the_controller_form_offers_menu_codes_behind_a_checkbox(
    hass: HomeAssistant,
) -> None:
    """The code fields are offered only while their checkbox is ticked.

    Each code field is a masked text field, because a code is a credential like
    the token. The manufacturer tree is left out: it is refused on every
    consumer account, so a field for it would be one nobody can fill in.
    """
    flow_id = (await _start_flow(hass))["flow_id"]

    result = await _submit_credentials(hass, flow_id)

    schema = result["data_schema"]
    assert _field_names(schema) == [
        CONTROLLERS,
        CONF_CONFIGURE_MENU_CODES,
        menu_code_field(MENU_TYPE_USER),
        menu_code_field(MENU_TYPE_INSTALLER),
        menu_code_field(MENU_TYPE_SERVICE),
    ]
    assert MENU_TYPE_MANUFACTURER not in MENU_CODE_TREES

    for menu_type in MENU_CODE_TREES:
        marker = next(
            key for key in schema.schema if key.schema == menu_code_field(menu_type)
        )
        assert marker.visible == {
            "field": CONF_CONFIGURE_MENU_CODES,
            "value": True,
        }

    selector = schema.schema[
        next(
            key
            for key in schema.schema
            if key.schema == menu_code_field(MENU_TYPE_SERVICE)
        )
    ]
    assert selector.config["type"] == TextSelectorType.PASSWORD


async def test_a_menu_code_is_stored_with_the_credentials(
    hass: HomeAssistant,
) -> None:
    """A code the user gives is kept in the entry's data, beside the token.

    The fetch that needs it runs right after setup, and a code is a credential
    of the same kind as the token, so it is stored where the token is.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    result = await _select(
        hass,
        flow_id,
        1,
        codes={menu_code_field(MENU_TYPE_SERVICE): "2468"},
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert entry.data[CONF_MENU_CODES] == {MENU_TYPE_SERVICE: "2468"}


async def test_an_empty_menu_code_stores_nothing(hass: HomeAssistant) -> None:
    """An untouched form is an entry without codes, not one with empty ones.

    That keeps an entry configured here indistinguishable from one configured
    before codes existed, so nothing empty is ever sent to the controller.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    result = await _select(
        hass,
        flow_id,
        1,
        codes={
            menu_code_field(MENU_TYPE_USER): "",
            menu_code_field(MENU_TYPE_INSTALLER): "  ",
            menu_code_field(MENU_TYPE_SERVICE): "",
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert CONF_MENU_CODES not in entry.data


async def test_an_unticked_menu_code_checkbox_stores_nothing(
    hass: HomeAssistant,
) -> None:
    """A hidden code field is left out of the submitted input.

    The visibility condition that reveals the code fields also keeps them out of
    the payload while the checkbox is unticked, so a client that sends a code
    anyway gets the same entry as a user who never saw the field.
    """
    flow_id = (await _start_flow(hass))["flow_id"]
    await _submit_credentials(hass, flow_id)

    result = await _select(
        hass,
        flow_id,
        1,
        codes={menu_code_field(MENU_TYPE_SERVICE): "2468"},
        configure_menu_codes=False,
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (entry,) = hass.config_entries.async_entries(DOMAIN)
    assert CONF_MENU_CODES not in entry.data


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


async def test_migration_drops_the_legacy_naming_flag(
    hass: HomeAssistant,
) -> None:
    """A version 3 entry loses the naming flag and moves to the current version.

    The hub-name preference is gone. An entry from before the removal may carry
    the old key in its data or its options; the migration drops it and moves the
    entry to the version this integration writes now.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=3,
        unique_id="a" * 32,
        data={
            USER_ID: "42",
            CONF_TOKEN: "token",
            "include_hub_in_name": True,
            CONTROLLER: _MODULES[0],
        },
        options={"include_hub_in_name": True},
    )
    entry.add_to_hass(hass)

    await async_migrate_entry(hass, entry)

    assert entry.version == ConfigFlow.VERSION
    assert entry.options == {}
    assert "include_hub_in_name" not in entry.data
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

    await async_migrate_entry(hass, entry)

    assert entry.version == ConfigFlow.VERSION
    assert entry.options == {}
    assert entry.data.keys() == {USER_ID, CONF_TOKEN, CONTROLLER}


async def test_migration_refuses_an_entry_from_a_newer_version(
    hass: HomeAssistant,
) -> None:
    """A version 5 entry is refused with a reason, not set up halfway.

    The data of an entry written by a newer integration may carry keys this
    version cannot read, so the migration raises: Home Assistant shows the
    translated reason and leaves the entry in the migration-error state.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=5,
        unique_id="a" * 32,
        data={USER_ID: "42", CONF_TOKEN: "token", CONTROLLER: _MODULES[0]},
    )
    entry.add_to_hass(hass)

    with pytest.raises(ConfigEntryError, match="newer version"):
        await async_migrate_entry(hass, entry)

    assert entry.version == 5


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


# ---------------------------------------------------------------------------
# Reauthentication -- reauthentication-flow
# ---------------------------------------------------------------------------


async def _loaded_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Return an entry Home Assistant has set up, so it can be reauthenticated."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="L-8 DEMO",
        version=ConfigFlow.VERSION,
        unique_id="a" * 32,
        data={
            USER_ID: "42",
            CONF_TOKEN: "expired-token",
            CONTROLLER: _MODULES[0],
            VER: "3.0.14: L-8 DEMO",
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def _start_reauth(hass: HomeAssistant, entry: MockConfigEntry) -> dict[str, Any]:
    """Start the reauthentication flow for ``entry`` and return its form."""
    entry.async_start_reauth(hass)
    await hass.async_block_till_done()

    (progress,) = hass.config_entries.flow.async_progress_by_handler(DOMAIN)
    assert progress["step_id"] == "reauth_confirm"
    return progress


async def test_reauthentication_stores_the_new_token(hass: HomeAssistant) -> None:
    """New credentials refresh the entry's token and reload the entry.

    Home Assistant starts this flow when the coordinator reports that the stored
    token is no longer accepted, so the user does not have to remove the
    controller and add it again.
    """
    entry = await _loaded_entry(hass)
    progress = await _start_reauth(hass, entry)

    with _patched_validation():
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"], _CREDENTIALS
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[USER_ID] == "42"
    assert entry.data[CONF_TOKEN] == _VALIDATED[CONF_TOKEN]
    assert entry.data[CONTROLLER] == _MODULES[0]

    await hass.async_block_till_done()


async def test_reauthentication_refuses_a_different_account(
    hass: HomeAssistant,
) -> None:
    """Credentials of another account are refused, and the entry is left alone.

    A controller belongs to the account it was set up with: repointing the entry
    at whatever account those credentials open would leave it describing a
    controller that account may not even hold.
    """
    entry = await _loaded_entry(hass)
    progress = await _start_reauth(hass, entry)

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(
            return_value={
                USER_ID: "99",
                CONF_TOKEN: "other-account-token",
                CONTROLLERS: _MODULES,
            }
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"], _CREDENTIALS
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "wrong_account"
    assert entry.data[USER_ID] == "42"
    assert entry.data[CONF_TOKEN] == "expired-token"


async def test_reauthentication_reports_bad_credentials(hass: HomeAssistant) -> None:
    """Wrong credentials keep the form open, with the reason shown."""
    entry = await _loaded_entry(hass)
    progress = await _start_reauth(hass, entry)

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=InvalidAuth),
    ):
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"], _CREDENTIALS
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "invalid_auth"}


async def test_reauthentication_reports_an_unreachable_api(
    hass: HomeAssistant,
) -> None:
    """An API that cannot be reached is reported as a connection problem."""
    entry = await _loaded_entry(hass)
    progress = await _start_reauth(hass, entry)

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=CannotConnect),
    ):
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"], _CREDENTIALS
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "cannot_connect"}


async def test_reauthentication_reports_unexpected_errors(
    hass: HomeAssistant,
) -> None:
    """Anything else is reported as an unknown error rather than crashing."""
    entry = await _loaded_entry(hass)
    progress = await _start_reauth(hass, entry)

    with patch(
        "custom_components.tech.config_flow.validate_input",
        AsyncMock(side_effect=RuntimeError("boom")),
    ):
        result = await hass.config_entries.flow.async_configure(
            progress["flow_id"], _CREDENTIALS
        )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"
    assert result["errors"] == {"base": "unknown"}


# ---------------------------------------------------------------------------
# Reconfiguration -- reconfiguration-flow
# ---------------------------------------------------------------------------


def _serve_modules(entry: MockConfigEntry, modules: list[dict]) -> None:
    """Make the entry's account hold ``modules``.

    The reconfigure step reads the account through the entry's own client, so a
    test replaces that client rather than the transport: what the step asks of
    it is the module list and nothing else.
    """
    entry.runtime_data.api = SimpleNamespace(
        list_modules=AsyncMock(return_value=modules),
        user_id="42",
        token="token",
    )


async def _start_reconfigure(hass: HomeAssistant, entry: MockConfigEntry) -> dict:
    """Start the reconfigure flow for ``entry`` and return its first form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
    )
    assert result["step_id"] == "reconfigure"
    return result


def _options(result: dict) -> list[str]:
    """Return the controller values the returned form offers."""
    for key, value in result["data_schema"].schema.items():
        if str(key) == CONTROLLERS:
            return [option["value"] for option in value.config["options"]]
    raise AssertionError("the form does not offer a controller")


async def test_reconfiguring_points_the_entry_at_another_controller(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The entry keeps its id and moves to the controller that was chosen.

    Home Assistant asks a reconfigure flow to keep the entry's unique id, but
    this integration is unique *per controller*, so the id moves with the
    controller: leaving it behind would block adding the new one later.
    """
    entry = await _loaded_entry(hass)
    entry_id = entry.entry_id
    _serve_modules(entry, _MODULES)
    form = await _start_reconfigure(hass, entry)

    assert _options(form) == ["1", "2"]
    assert _field_names(form["data_schema"]) == [CONTROLLERS]

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONTROLLERS: "2"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.entry_id == entry_id
    assert entry.data[CONTROLLER][UDID] == "b" * 32
    assert entry.data[CONTROLLER][CONF_NAME] == "ST-491 DEMO"
    assert entry.unique_id == "b" * 32
    assert entry.state is config_entries.ConfigEntryState.LOADED


async def test_reconfiguring_refuses_a_controller_another_entry_has(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two entries never stand for the same controller."""
    first = await _loaded_entry(hass)
    second = MockConfigEntry(
        domain=DOMAIN,
        title="Other DEMO",
        version=ConfigFlow.VERSION,
        unique_id="c" * 32,
        data={
            USER_ID: "42",
            CONF_TOKEN: "token",
            CONTROLLER: {
                "id": 7,
                "name": "Other DEMO",
                "udid": "c" * 32,
                "version": "3.0.14",
            },
            VER: "3.0.14: Other DEMO",
        },
    )
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()
    _serve_modules(second, _MODULES)
    form = await _start_reconfigure(hass, second)

    result = await hass.config_entries.flow.async_configure(
        form["flow_id"], {CONTROLLERS: str(_MODULES[0]["id"])}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert second.data[CONTROLLER][UDID] == "c" * 32
    assert second.unique_id == "c" * 32
    assert first.unique_id == _MODULES[0][UDID]


async def test_reconfiguring_an_unreadable_account_offers_the_current_controller(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A listing that fails keeps the form usable and says why.

    The entry's token may have expired, which reauthentication fixes; until
    then the form offers the controller the entry already has, with the reason
    on it rather than an empty dropdown.
    """
    entry = await _loaded_entry(hass)
    entry.runtime_data.api = SimpleNamespace(
        list_modules=AsyncMock(side_effect=TechError(401, "no")),
        user_id="42",
        token="token",
    )

    result = await _start_reconfigure(hass, entry)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}
    assert _options(result) == [str(_MODULES[0]["id"])]
