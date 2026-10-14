"""Tech DataUpdateCoordinator."""

import asyncio
from collections.abc import Callable
import logging
from typing import Any

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

# The config entry this integration runs on, typed with the coordinator it
# carries in runtime_data. Platinum's strict-typing rule asks for the custom
# entry to be used throughout, not only where runtime_data is read, so every
# signature that takes an entry names this rather than the bare ConfigEntry.
type TechConfigEntry = ConfigEntry[TechCoordinator]

# Translation keys for what the entry shows while it cannot reach the API or the
# token is rejected; the sentences around them are the fallbacks and the detail
# the log carries.
TOKEN_REJECTED = "the eModul token is no longer accepted"
TOKEN_REJECTED_KEY = "token_rejected"
API_UNREACHABLE_KEY = "cannot_connect"


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
        # The registry id of the controller's device, set while the entry sets
        # up. Entities that belong to a zone or a sensor name it as their
        # ``via_device_id``, and the registry needs the id, not the identifier.
        self.controller_device_id: str | None = None
        # The entities of each payload entry, by source key, and how many polls
        # in a row the controller has left that entry out. See
        # ``__init__._drop_unreported_entities``.
        self.reported: dict[str, set[Any]] = {}
        self.reported_misses: dict[str, int] = {}
        # Platforms that register entities from the payload append a callback
        # here, to be told by an entity when it leaves Home Assistant. An entity
        # that has left may be registered again, which is what lets a payload
        # that brings its source entry back rebuild it.
        self.forget_callbacks: list[Callable[[str | None], None]] = []
        # What the user made of the entities the removal pass takes away -- their
        # entity ids, names, icons and areas, per unique id -- and the store they
        # are written to. See ``identity``.
        self.identities: dict[str, dict[str, Any]] = {}
        self.identity_store: Any = None

    async def _async_update_data(self) -> dict[str, Any]:
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
            # A rejected login: the user has to act, and Home Assistant starts
            # the reauthentication flow for this one.
            raise ConfigEntryAuthFailed(
                TOKEN_REJECTED,
                translation_domain=DOMAIN,
                translation_key=TOKEN_REJECTED_KEY,
            ) from err
        except TechError as err:
            if err.status_code == 401:
                # The API answers a request made with a token it no longer
                # accepts with 401 -- the same situation as a rejected login.
                # It has to reach Home Assistant as an authentication failure,
                # or the entry would retry setup forever instead of asking the
                # user for their credentials again.
                raise ConfigEntryAuthFailed(
                    TOKEN_REJECTED,
                    translation_domain=DOMAIN,
                    translation_key=TOKEN_REJECTED_KEY,
                ) from err
            raise UpdateFailed(
                f"Error communicating with API: {err}",
                translation_domain=DOMAIN,
                translation_key=API_UNREACHABLE_KEY,
            ) from err
        except (ClientError, TimeoutError) as err:
            # ``ClientError`` is a connection problem (name resolution,
            # refused, reset) and ``TimeoutError`` is the API taking longer than
            # API_TIMEOUT. Both mean "not reachable right now", which is why
            # they are raised as UpdateFailed: Home Assistant's coordinator logs
            # that transition once and the recovery once, and any other
            # exception would be logged as an unexpected error on every poll.
            # The key is what the entry shows while it retries -- Home Assistant
            # carries it over to the ConfigEntryNotReady it wraps this in -- and
            # the sentence is the fallback plus the detail in the log.
            raise UpdateFailed(
                f"Error communicating with API: {err}",
                translation_domain=DOMAIN,
                translation_key=API_UNREACHABLE_KEY,
            ) from err
