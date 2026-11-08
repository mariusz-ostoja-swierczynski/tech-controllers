"""Config flow for Tech Sterowniki integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import probatio

from homeassistant import config_entries, core, data_entry_flow, exceptions
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult
from homeassistant.const import (
    ATTR_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.helpers import aiohttp_client
from homeassistant.helpers.redact import async_redact_data
from homeassistant.helpers.selector import (
    BooleanSelector,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_CONFIGURE_MENU_CODES,
    CONF_MENU_CODES,
    CONTROLLER,
    CONTROLLERS,
    DOMAIN,
    MENU_CODE_TREES,
    UDID,
    USER_ID,
    VER,
    menu_code_field,
)
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(autocomplete="username")
        ),
        probatio.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
    }
)


def _menu_codes_from(user_input: dict[str, Any]) -> dict[str, str]:
    """Return the codes a payload carries, dropping the empty ones.

    An empty field means "no code", not "an empty code", so it is not stored at
    all: an entry is then indistinguishable from one configured before codes
    existed, and no empty code is ever sent to the controller. A payload from a
    form whose menu-code checkbox was left unticked holds none of the fields at
    all, because Home Assistant leaves a hidden field out of the submitted
    input.

    Args:
        user_input: Validated payload holding the code fields, or any payload --
            such as a controller selection with the checkbox unticked -- that
            holds none of them.

    Returns:
        Mapping of menu type to code, holding only the trees that were given
        one.

    """
    return {
        menu_type: code
        for menu_type in MENU_CODE_TREES
        if (code := str(user_input.get(menu_code_field(menu_type), "")).strip())
    }


def controllers_schema(
    controllers: list[dict[str, Any]],
    *,
    with_menu_codes: bool = True,
) -> probatio.Schema:
    """Build the selection form for the provided controller list.

    One controller per flow run: the user repeats the flow for the next one, so
    every entry stands for exactly one controller. A controller can also keep
    its menus behind a code, so the form offers the per-tree codes as well,
    behind a checkbox that reveals them: a user who keeps none never sees the
    fields. Home Assistant leaves a hidden field out of the submitted input, so
    an unticked form carries no codes at all. Reconfiguring an entry asks for
    the controller alone: its codes are setup-time only.

    Args:
        controllers: Sequence returned by the Tech API describing modules.
        with_menu_codes: Whether the form also offers the per-tree menu codes.

    Returns:
        Voluptuous schema with a dropdown of the account's controllers and the
        menu codes behind their checkbox.

    """
    fields: dict[Any, Any] = {
        probatio.Required(CONTROLLERS): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(
                        value=str(controller[CONTROLLER][ATTR_ID]),
                        label=controller[CONTROLLER][CONF_NAME],
                    )
                    for controller in controllers
                ],
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
    }

    if with_menu_codes:
        # The checkbox reveals the code fields; Home Assistant drops a hidden
        # field from ``user_input``, so leaving it unticked stores nothing.
        fields[data_entry_flow.Optional(CONF_CONFIGURE_MENU_CODES, default=False)] = (
            BooleanSelector()
        )
        for menu_type in MENU_CODE_TREES:
            fields[
                data_entry_flow.Optional(
                    menu_code_field(menu_type),
                    default="",
                    visible={"field": CONF_CONFIGURE_MENU_CODES, "value": True},
                )
            ] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))

    return probatio.Schema(fields)


async def validate_input(
    hass: core.HomeAssistant, data: dict[str, Any]
) -> dict[str, Any]:
    """Validate provided credentials against the Tech API.

    Args:
        hass: Home Assistant instance.
        data: Mapping containing ``CONF_USERNAME`` and ``CONF_PASSWORD``.

    Returns:
        A dictionary with API metadata (user id, token, controllers) suitable
        for storing in a config entry.

    Raises:
        InvalidAuth: If the credentials are rejected by the API.
        CannotConnect: If the API cannot be reached.

    """
    http_session = aiohttp_client.async_get_clientsession(hass)
    api = Tech(http_session)

    try:
        if not await api.authenticate(data[CONF_USERNAME], data[CONF_PASSWORD]):
            raise InvalidAuth
        modules = await api.list_modules()
    except TechLoginError as err:
        raise InvalidAuth from err
    except TechError as err:
        raise CannotConnect from err

    # Return info that you want to store in the config entry.
    return {
        USER_ID: api.user_id,
        CONF_TOKEN: api.token,
        CONTROLLERS: modules,
    }


@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tech Sterowniki.

    One controller per flow run: the user repeats the flow to add the next one,
    which keeps every entry tied to exactly one controller and its own unique
    id, and lets each of them be removed on its own.
    """

    VERSION = 4
    MINOR_VERSION = 0

    def __init__(self) -> None:
        """Initialize the config flow.

        The credentials are validated in the first step and their result is kept
        for the second one, which picks a controller from it.
        """
        self._init_info: dict[str, Any] | None = None
        self._controllers: list[dict[str, Any]] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credential entry step.

        Args:
            user_input: Optional mapping with username and password.

        Returns:
            Either the controller selection step or the rendered login form.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                self._init_info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return await self.async_step_select_controllers()

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    async def async_step_select_controllers(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Display the controller selection form or create the chosen entry.

        The form also asks for the per-tree menu codes, behind a checkbox that
        reveals them; Home Assistant leaves a hidden field out of the submitted
        input, so a user who keeps no menu behind a code never sees the fields
        and the entry carries no codes.

        Args:
            user_input: Optional mapping naming the controller to add and any
                menu codes given.

        Returns:
            The selection form, or the result of creating the entry for the
            selected controller.

        """
        if self._init_info is None:
            # Reached without credentials, which can only happen for a stale
            # flow: start over rather than showing an empty selection.
            return await self.async_step_user()

        if not self._controllers:
            self._controllers = self._create_controllers_array(self._init_info)

        if user_input is None:
            if not self._controllers:
                # The account holds no controller to add.
                return self.async_abort(reason="no_modules")
            return self.async_show_form(
                step_id="select_controllers",
                data_schema=controllers_schema(self._controllers),
            )

        controllers_by_id = {
            str(controller[CONTROLLER][ATTR_ID]): controller
            for controller in self._controllers
        }
        controller = controllers_by_id.get(str(user_input.get(CONTROLLERS)))
        if controller is None:
            # A controller that is not on the account any more: the form went
            # stale between the two steps, so there is nothing to add.
            return self.async_abort(reason="no_modules")

        await self.async_set_unique_id(controller[CONTROLLER][UDID])
        self._abort_if_unique_id_configured()

        data = dict(controller)
        menu_codes = _menu_codes_from(user_input)
        if menu_codes:
            # Stored next to the token and the user id: a code is a credential of
            # the same kind, and the fetch that needs it runs right after setup.
            data[CONF_MENU_CODES] = menu_codes

        _LOGGER.debug(
            "Adding config entry for: %s",
            async_redact_data(data, ["token", CONF_MENU_CODES]),
        )

        return self.async_create_entry(
            title=controller[CONTROLLER][CONF_NAME],
            data=data,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point this entry at another of the account's controllers.

        Home Assistant offers this from the entry's menu, which is where a user
        looks after replacing a controller in the eModul app. Only the
        controller is asked for: the credentials belong to the account and
        reauthentication handles them. The entry keeps its id, so its history
        and everything that refers to it survive; the unique id moves with the
        controller, since being unique per controller is what stops the same one
        being added twice.

        Args:
            user_input: Optional mapping naming the controller to switch to.

        Returns:
            The selection form, the reconfigured entry, or an abort when the
            account has no controller to choose from.

        """
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}

        if not self._controllers:
            listed = await self._async_account_controllers(entry)
            if listed is None:
                # The account could not be read at all -- an expired token, most
                # likely. Offer the controller the entry already has, with the
                # reason on the form: reauthenticating, or reconfiguring again
                # once the API answers, is what fixes it.
                errors["base"] = "cannot_connect"
                self._controllers = [dict(entry.data)]
            elif not listed:
                return self.async_abort(reason="no_modules")
            else:
                self._controllers = listed

        if user_input is not None:
            controllers_by_id = {
                str(controller[CONTROLLER][ATTR_ID]): controller
                for controller in self._controllers
            }
            controller = controllers_by_id.get(str(user_input.get(CONTROLLERS)))
            if controller is None:
                return self.async_abort(reason="no_modules")

            taken = [
                configured
                for configured in self._async_current_entries()
                if configured.entry_id != entry.entry_id
                and configured.unique_id == controller[CONTROLLER][UDID]
            ]
            if taken:
                return self.async_abort(reason="already_configured")

            _LOGGER.debug(
                "Reconfiguring entry %s for controller: %s",
                entry.entry_id,
                async_redact_data(controller, ["token"]),
            )

            return self.async_update_reload_and_abort(
                entry,
                unique_id=controller[CONTROLLER][UDID],
                data_updates={
                    CONTROLLER: controller[CONTROLLER],
                    VER: controller[VER],
                },
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=controllers_schema(
                self._controllers, with_menu_codes=False
            ),
            errors=errors,
        )

    async def _async_account_controllers(
        self, entry: ConfigEntry
    ) -> list[dict[str, Any]] | None:
        """Return the account's controllers, read with the entry's own token.

        The reconfigure step has no credentials to validate: the account is the
        one the entry was set up with, and that entry's client is the one that
        lists its controllers.

        Args:
            entry: The entry being reconfigured.

        Returns:
            The controllers the account holds, or ``None`` when the API could
            not be asked.

        """
        api = entry.runtime_data.api
        try:
            modules = await api.list_modules()
        except TechError, TechLoginError:
            _LOGGER.debug(
                "Could not list the account's controllers for %s",
                entry.entry_id,
                exc_info=True,
            )
            return None

        return self._create_controllers_array(
            {USER_ID: api.user_id, CONF_TOKEN: api.token, CONTROLLERS: modules}
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Handle a reauthentication request from Home Assistant.

        Home Assistant starts this flow when the coordinator reports that the
        stored token is no longer accepted, so that the user can enter the
        account's credentials again instead of removing the entry and adding the
        controller all over.

        Args:
            entry_data: Data of the config entry being reauthenticated.

        Returns:
            The credentials form.

        """
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the account credentials and store the fresh token.

        Args:
            user_input: Optional mapping with username and password.

        Returns:
            The credentials form, or the result of updating and reloading the
            entry.

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                entry = self._get_reauth_entry()
                if info[USER_ID] != entry.data.get(USER_ID):
                    # A controller belongs to the account it was set up with:
                    # pointing the entry at another account would leave it
                    # describing a controller that account may not even hold.
                    return self.async_abort(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        USER_ID: info[USER_ID],
                        CONF_TOKEN: info[CONF_TOKEN],
                    },
                )

        return self.async_show_form(
            step_id="reauth_confirm", data_schema=DATA_SCHEMA, errors=errors
        )

    def _create_controllers_array(
        self, validated_input: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """Convert API response into config-entry-ready controller payloads."""
        return [
            self._create_controller_dict(validated_input, controller_dict)
            for controller_dict in validated_input[CONTROLLERS]
        ]

    def _create_controller_dict(
        self, validated_input: dict[str, Any], controller_dict: dict[str, Any]
    ) -> dict[str, Any]:
        """Compose controller metadata shared across config entries."""
        return {
            USER_ID: validated_input[USER_ID],
            CONF_TOKEN: validated_input[CONF_TOKEN],
            CONTROLLER: controller_dict,
            VER: f"{controller_dict[VER]}: {controller_dict[CONF_NAME]}",
        }


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
