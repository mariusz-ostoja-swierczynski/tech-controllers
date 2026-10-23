"""Config flow for Tech Sterowniki integration."""

import logging
from types import MappingProxyType
from typing import Any
import uuid

import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.config_entries import SOURCE_USER, ConfigEntry, ConfigFlowResult
from homeassistant.const import (
    ATTR_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.helpers import aiohttp_client, config_validation as cv
from homeassistant.helpers.redact import async_redact_data

from .const import (
    CONF_MENU_CODES,
    CONTROLLER,
    CONTROLLERS,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MENU_CODE_TREES,
    UDID,
    USER_ID,
    VER,
    menu_code_field,
)
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__name__)

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


def menu_codes_schema() -> vol.Schema:
    """Build the optional per-tree menu-code form.

    One field per tree that can be gated, every one optional. Some controllers
    keep their installer and service menus behind a code and the API refuses such
    a tree outright -- HTTP 200 with a message and no items -- without saying
    which code it wants, so the code cannot be discovered from the refusal. It
    can only be supplied, which is what this form is for.

    Returns:
        Voluptuous schema with an optional code field for every menu tree that
        can be gated.

    """
    return vol.Schema(
        {
            vol.Optional(menu_code_field(menu_type), default=""): cv.string
            for menu_type in MENU_CODE_TREES
        }
    )


def _menu_codes_from(user_input: dict[str, Any]) -> dict[str, str]:
    """Return the codes a payload carries, dropping the empty ones.

    An empty field means "no code", not "an empty code", so it is not stored at
    all: an entry is then indistinguishable from one configured before codes
    existed, and no empty code is ever sent to the controller.

    Args:
        user_input: Validated payload holding the code fields, or any payload --
            such as the controller selection alone -- that holds none of them.

    Returns:
        Mapping of menu type to code, holding only the trees that were given
        one.

    """
    return {
        menu_type: code
        for menu_type in MENU_CODE_TREES
        if (code := str(user_input.get(menu_code_field(menu_type), "")).strip())
    }


def controllers_schema(controllers) -> vol.Schema:
    """Build a selection form for the provided controller list.

    Args:
        controllers: Sequence returned by the Tech API describing modules.

    Returns:
        Voluptuous schema that lets the user pick controllers to configure.

    """

    return vol.Schema(
        {
            vol.Optional(CONTROLLERS): cv.multi_select(
                {
                    str(controller[CONTROLLER][ATTR_ID]): controller[CONTROLLER][
                        CONF_NAME
                    ]
                    for controller in controllers
                }
            ),
            vol.Required(
                INCLUDE_HUB_IN_NAME,
                default=False,
            ): bool,
        }
    )


async def validate_input(hass: core.HomeAssistant, data):
    """Validate provided credentials against the Tech API.

    Args:
        hass: Home Assistant instance.
        data: Mapping containing ``CONF_USERNAME`` and ``CONF_PASSWORD``.

    Returns:
        A dictionary with API metadata (user id, token, controllers) suitable
        for storing in a config entry.

    Raises:
        InvalidAuth: If the credentials are rejected by the API.

    """

    http_session = aiohttp_client.async_get_clientsession(hass)
    api = Tech(http_session)

    if not await api.authenticate(data[CONF_USERNAME], data[CONF_PASSWORD]):
        raise InvalidAuth

    modules = await api.list_modules()

    # Return info that you want to store in the config entry.
    return {
        USER_ID: api.user_id,
        CONF_TOKEN: api.token,
        CONTROLLERS: modules,
    }


@config_entries.HANDLERS.register(DOMAIN)
class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tech Sterowniki."""

    VERSION = 3
    MINOR_VERSION = 0
    # Pick one of the available connection classes in homeassistant/config_entries.py
    CONNECTION_CLASS = config_entries.CONN_CLASS_CLOUD_POLL

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._init_info: dict[str, Any] | None = None
        self._controllers: list[dict] | None = None
        # The controller selection, held between its own step and the menu-code
        # step that follows it: the entry is created only once both are in.
        self._pending_input: dict[str, str] | None = None

    async def _async_finish_controller(
        self, user_input: dict[str, str]
    ) -> ConfigFlowResult:
        """Create config entries for the selected controller identifiers.

        Args:
            user_input: Form payload returning controller ids and options.

        Returns:
            Config flow result signalling completion, continuation, or abort.

        """

        # ``controllers_schema`` declares INCLUDE_HUB_IN_NAME with
        # ``default=False`` and Home Assistant hands this method the
        # schema-validated payload, so voluptuous fills the key in even when the
        # checkbox was left unticked. The key's presence therefore says nothing
        # about the user's choice -- only its value does.
        include_name: bool = bool(user_input.get(INCLUDE_HUB_IN_NAME, False))

        # The codes ride along in the same payload: the step that asks for them
        # merges its own fields into the selection this method is given.
        menu_codes = _menu_codes_from(user_input)

        if self._controllers is None or not user_input.get(CONTROLLERS):
            return self.async_abort(reason="no_modules")

        # Index the discovered controllers by their (integer) id once, then
        # resolve every selected id through it instead of rescanning the list.
        controllers_by_id = {
            obj[CONTROLLER].get(ATTR_ID): obj for obj in self._controllers
        }
        selected = [controllers_by_id[int(cid)] for cid in user_input[CONTROLLERS]]

        # Abort if any selected controller is already configured.
        for controller in selected:
            await self.async_set_unique_id(controller[CONTROLLER][UDID])
            self._abort_if_unique_id_configured()

        # Add a config entry for every selected controller. The flow itself
        # does not create an entry, so it finishes with an informational abort.
        for controller in selected:
            controller[INCLUDE_HUB_IN_NAME] = include_name
            if menu_codes:
                # Stored next to the token and the user id because the fetch
                # that needs them happens right after setup, per controller, and
                # because a code is a credential of the same kind.
                controller[CONF_MENU_CODES] = dict(menu_codes)
            _LOGGER.debug(
                "Adding config entry for: %s",
                async_redact_data(controller, ["token", CONF_MENU_CODES]),
            )
            await self.hass.config_entries.async_add(
                self._create_config_entry(controller=controller)
            )

        return self.async_abort(reason="controllers_configured")

    async def async_step_select_controllers(
        self,
        user_input: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Display the controller selection form or persist the choice.

        Args:
            user_input: User-provided selection of controller identifiers.

        Returns:
            Next config flow step or the final entry creation result.

        """
        if not user_input:
            if self._init_info is not None:
                self._controllers = self._create_controllers_array(
                    validated_input=self._init_info
                )

            return self.async_show_form(
                step_id="select_controllers",
                data_schema=controllers_schema(controllers=self._controllers),
            )

        # Hold the selection for the step that follows: the codes are asked for
        # on their own form, and the entries are created once both are in.
        self._pending_input = dict(user_input)
        return await self.async_step_menu_codes()

    async def async_step_menu_codes(
        self,
        user_input: dict[str, str] | None = None,
    ) -> ConfigFlowResult:
        """Ask for the per-menu codes and then create the config entries.

        A controller can keep its installer and service menus behind a code, and
        the API refuses such a tree outright rather than saying which code it
        wants, so a code can only be supplied by the user. Every field is
        optional and empty means "no code", so a user with none can submit the
        form untouched and get exactly the behaviour of an entry that predates
        this step.

        Args:
            user_input: The code entered for each menu tree, if the form was
                submitted.

        Returns:
            The code form, or the final entry creation result.

        """
        if user_input is None:
            return self.async_show_form(
                step_id="menu_codes",
                data_schema=menu_codes_schema(),
            )

        return await self._async_finish_controller(
            {**(self._pending_input or {}), **user_input}
        )

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial credential entry step.

        Args:
            user_input: Optional mapping with username and password.

        Returns:
            Either the next flow step or the rendered login form.

        """
        errors = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)

                # Store info to use in next step
                self._init_info = info

                return await self.async_step_select_controllers()
            except TechLoginError:
                errors["base"] = "invalid_auth"
            except TechError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )

    def _create_config_entry(self, controller: dict) -> ConfigEntry:
        """Instantiate an in-memory config entry for ``controller``.

        Args:
            controller: Controller payload returned by the Tech API.

        Returns:
            Unsaved :class:`ConfigEntry` instance mirroring ``controller``.

        """
        return ConfigEntry(
            data=controller,
            title=controller[CONTROLLER][CONF_NAME],
            entry_id=uuid.uuid4().hex,
            discovery_keys=MappingProxyType({}),
            domain=DOMAIN,
            version=ConfigFlow.VERSION,
            minor_version=ConfigFlow.MINOR_VERSION,
            source=SOURCE_USER,
            options={},
            unique_id=controller[CONTROLLER][UDID],
            subentries_data=[],
        )

    def _create_controllers_array(self, validated_input: dict[str, Any]) -> list[dict]:
        """Convert API response into config-entry-ready controller payloads."""
        return [
            self._create_controller_dict(validated_input, controller_dict)
            for controller_dict in validated_input[CONTROLLERS]
        ]

    def _create_controller_dict(
        self, validated_input: dict[str, str], controller_dict: dict[str, str]
    ) -> dict[str, Any]:
        """Compose controller metadata shared across config entries."""
        return {
            USER_ID: validated_input[USER_ID],
            CONF_TOKEN: validated_input[CONF_TOKEN],
            CONTROLLER: controller_dict,
            VER: controller_dict[VER] + ": " + controller_dict[CONF_NAME],
        }


class CannotConnect(exceptions.HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(exceptions.HomeAssistantError):
    """Error to indicate there is invalid auth."""
