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

from . import assets
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
        vol.Required(CONF_USERNAME): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
    }
)


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

    async def _async_finish_controller(
        self, user_input: dict[str, str]
    ) -> ConfigFlowResult:
        """Create config entries for the selected controller identifiers.

        Args:
            user_input: Form payload returning controller ids and options.

        Returns:
            Config flow result signalling completion, continuation, or abort.

        """

        include_name: bool = INCLUDE_HUB_IN_NAME in user_input

        if self._controllers is not None and user_input is not None:
            if (
                CONTROLLERS not in user_input
                or not user_input[CONTROLLERS]
                or len(user_input[CONTROLLERS]) == 0
            ):
                return self.async_abort(reason="no_modules")

            controllers = user_input[CONTROLLERS]

            # check if we have any of the selected controllers already configured
            # and abort if so
            for controller_id in controllers:
                controller = next(
                    obj
                    for obj in self._controllers
                    if obj[CONTROLLER].get(ATTR_ID) == int(controller_id)
                )
                await self.async_set_unique_id(controller[CONTROLLER][UDID])
                self._abort_if_unique_id_configured()

            # process first set of controllers and add config entries for them
            if len(controllers) > 1:
                for controller_id in controllers[1 : len(controllers)]:
                    controller = next(
                        obj
                        for obj in self._controllers
                        if obj[CONTROLLER].get(ATTR_ID) == int(controller_id)
                    )
                    await self.async_set_unique_id(controller[CONTROLLER][UDID])

                    controller[INCLUDE_HUB_IN_NAME] = include_name
                    _LOGGER.debug(
                        "Adding config entry for: %s",
                        assets.redact(controller, ["token"]),
                    )

                    await self.hass.config_entries.async_add(
                        self._create_config_entry(controller=controller)
                    )

            # process last controller and async create entry finishing the step
            controller_udid = next(
                obj
                for obj in self._controllers
                if obj[CONTROLLER].get(ATTR_ID) == int(controllers[0])
            )[CONTROLLER][UDID]

            await self.async_set_unique_id(controller_udid)

            controller = next(
                obj
                for obj in self._controllers
                if obj[CONTROLLER].get(ATTR_ID) == int(controllers[0])
            )
            controller[INCLUDE_HUB_IN_NAME] = include_name

            return self.async_create_entry(
                title=next(
                    obj
                    for obj in self._controllers
                    if obj[CONTROLLER].get(ATTR_ID) == int(controllers[0])
                )[CONTROLLER][CONF_NAME],
                data=controller,
            )
        return self.async_abort(reason="no_modules")

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

        return await self._async_finish_controller(user_input)

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
            unique_id=None,
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
