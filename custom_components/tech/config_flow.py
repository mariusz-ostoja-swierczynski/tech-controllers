"""Config flow for Tech Sterowniki integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.const import (
    ATTR_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.core import callback
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
    CONTROLLER,
    CONTROLLERS,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    UDID,
    USER_ID,
    VER,
)
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): TextSelector(
            TextSelectorConfig(autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD,
                autocomplete="current-password",
            )
        ),
    }
)


def controllers_schema(
    controllers: list[dict[str, Any]], *, with_naming: bool = True
) -> vol.Schema:
    """Build the selection form for the provided controller list.

    One controller per flow run: the user repeats the flow for the next one, so
    every entry stands for exactly one controller. The naming preference is
    asked when a controller is being added, because it is about the controller
    being added, and a setting is easiest to answer while the user is looking at
    it; it is stored in the entry's options rather than its data. Reconfiguring
    an entry asks for the controller alone: its naming preference belongs to
    that entry, and the options flow is where it is changed.

    Args:
        controllers: Sequence returned by the Tech API describing modules.
        with_naming: Whether the form also asks for the naming preference.

    Returns:
        Voluptuous schema with a dropdown of the account's controllers, and the
        naming preference when it was asked for.

    """
    fields: dict[Any, Any] = {
        vol.Required(CONTROLLERS): SelectSelector(
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

    if with_naming:
        fields[vol.Required(INCLUDE_HUB_IN_NAME, default=False)] = BooleanSelector()

    return vol.Schema(fields)


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
    # Pick one of the available connection classes in homeassistant/config_entries.py
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the config flow.

        The credentials are validated in the first step and their result is kept
        for the second one, which picks a controller from it.
        """
        self._init_info: dict[str, Any] | None = None
        self._controllers: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> TechOptionsFlow:
        """Return the options flow that edits this entry's settings."""
        return TechOptionsFlow()

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

        Args:
            user_input: Optional mapping naming the controller to add and the
                naming preference to start it with.

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

        _LOGGER.debug(
            "Adding config entry for: %s",
            async_redact_data(controller, ["token"]),
        )

        return self.async_create_entry(
            title=controller[CONTROLLER][CONF_NAME],
            data=controller,
            # A naming preference, not connection data: it is asked here while
            # the user is looking at the controller it applies to, stored where
            # the settings belong, and editable afterwards in the options flow.
            options={
                INCLUDE_HUB_IN_NAME: user_input.get(INCLUDE_HUB_IN_NAME, False),
            },
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Point this entry at another of the account's controllers.

        Home Assistant offers this from the entry's menu, which is where a user
        looks after replacing a controller in the eModul app. Only the
        controller is asked for: the credentials belong to the account and
        reauthentication handles them, while the naming preference is a setting
        of this entry, which the options flow changes. The entry keeps its id,
        so its history and everything that refers to it survive; the unique id
        moves with the controller, since being unique per controller is what
        stops the same one being added twice.

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
            data_schema=controllers_schema(self._controllers, with_naming=False),
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


class TechOptionsFlow(OptionsFlowWithReload):
    """Handle the settings that are not needed to connect to the account.

    The only setting so far is whether entity names carry the hub name. The
    base class reloads the entry afterwards, so the renamed entities follow
    without a restart.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show the settings form, or store what was submitted.

        Args:
            user_input: Optional mapping with the settings to store.

        Returns:
            The settings form, or the result of storing the settings.

        """
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        INCLUDE_HUB_IN_NAME,
                        default=self.config_entry.options.get(
                            INCLUDE_HUB_IN_NAME, False
                        ),
                    ): BooleanSelector()
                }
            ),
        )


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
