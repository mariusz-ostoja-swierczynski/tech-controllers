"""Tech DataUpdateCoordinator."""

import asyncio
import logging

from aiohttp import ClientError, ClientSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .assets import Translations
from .const import API_TIMEOUT, CONTROLLER, DOMAIN, SCAN_INTERVAL, UDID
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__package__)


class TechCoordinator(DataUpdateCoordinator):
    """Coordinate periodic refreshes from the Tech HTTP API.

    This class does not log the controller going away or coming back: Home
    Assistant's coordinator already does that, once per transition, for as long
    as the failures it sees are ``UpdateFailed``. The entities report themselves
    unavailable in between, because ``CoordinatorEntity.available`` follows
    ``last_update_success``.
    """

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, session: ClientSession, user_id: str, token: str
    ) -> None:
        """Initialise the coordinator responsible for a single Tech account.

        Args:
            hass: Home Assistant instance.
            session: Shared aiohttp client session.
            user_id: Tech platform user identifier.
            token: Bearer token returned by the authentication flow.

        """
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=SCAN_INTERVAL,
        )
        self.api = Tech(session, user_id, token)
        # Replaced with the fetched catalog in ``async_setup_entry`` before
        # any platform is set up; the empty default keeps lookups safe.
        self.translations = Translations()

    async def _async_update_data(self) -> dict:
        """Fetch the latest module data for the configured controller.

        Returns:
            Fresh module payload containing ``zones`` and ``tiles`` data.

        Raises:
            ConfigEntryAuthFailed: If the API indicates that the token expired.
            UpdateFailed: If the controller cannot be reached or the API
                answers with an error.

        """

        _LOGGER.debug(
            "Updating data for: %s", str(self.config_entry.data[CONTROLLER][CONF_NAME])
        )

        try:
            async with asyncio.timeout(API_TIMEOUT):
                # force=True: the coordinator owns the polling cadence and must
                # bypass the freshness cache that coalesces the setup-time burst.
                return await self.api.module_data(
                    self.config_entry.data[CONTROLLER][UDID], force=True
                )
        except TechLoginError as err:
            # A dead token is not the controller being unreachable: the user has
            # to act, and Home Assistant starts the reauthentication flow for
            # this one.
            raise ConfigEntryAuthFailed from err
        except (TechError, ClientError, TimeoutError) as err:
            # ``ClientError`` is a connection problem (name resolution,
            # refused, reset) and ``TimeoutError`` is the API taking longer than
            # API_TIMEOUT. Both mean "not reachable right now", which is why
            # they are raised as UpdateFailed: Home Assistant's coordinator logs
            # that transition once and the recovery once, and any other
            # exception would be logged as an unexpected error on every poll.
            raise UpdateFailed(f"Error communicating with API: {err}") from err
