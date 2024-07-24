"""Config flow for Tech Sterowniki integration."""

import logging
import uuid

import voluptuous as vol

from homeassistant import config_entries, core, exceptions
from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.const import (
    ATTR_ID,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import aiohttp_client, config_validation as cv

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
    """Return the data schema for controllers."""

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
    """Validate the user input allows us to connect.

    Data has the keys from DATA_SCHEMA with values provided by the user.
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
        self._init_info: dict[str, str] | None = None
        self._controllers: list[dict] | None = None

    async def _async_finish_controller(self, user_input: dict[str, str]) -> FlowResult:
        """Finish setting up controllers."""

        include_name: bool = user_input[INCLUDE_HUB_IN_NAME]

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
                    _LOGGER.debug("Adding config entry for: %s", controller)

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

    async def async_step_select_controllers(
        self,
        user_input: dict[str, str] | None = None,
    ) -> FlowResult:
        """Handle the selection of controllers."""
        if not user_input:
            self._controllers = self._create_controllers_array(
                validated_input=self._init_info
            )

            return self.async_show_form(
                step_id="select_controllers",
                data_schema=controllers_schema(controllers=self._controllers),
            )

        return await self._async_finish_controller(user_input)

    async def async_step_user(self, user_input: dict[str, str] | None = None):
        """Handle the initial step."""
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
        return ConfigEntry(
            data=controller,
            title=controller[CONTROLLER][CONF_NAME],
            entry_id=uuid.uuid4().hex,
            domain=DOMAIN,
            version=ConfigFlow.VERSION,
            minor_version=ConfigFlow.MINOR_VERSION,
            source=SOURCE_USER,
            options={},
            unique_id=None,
        )

    def _create_controllers_array(self, validated_input: dict) -> list[dict]:
        return [
            self._create_controller_dict(validated_input, controller_dict)
            for controller_dict in validated_input[CONTROLLERS]
        ]

    def _create_controller_dict(
        self, validated_input: dict, controller_dict: dict
    ) -> dict:
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
