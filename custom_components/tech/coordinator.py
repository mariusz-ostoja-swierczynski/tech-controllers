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
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .assets import Translations
from .const import API_TIMEOUT, CONTROLLER, DOMAIN, MENU_TYPES, SCAN_INTERVAL, UDID
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

# The repair issue is raised only for a code the controller would not accept.
# A menu nobody gave a code for is refused exactly as it was before codes
# existed, and on a consumer account that is normal for several trees -- the
# manufacturer menu above all -- so reporting those would be a permanent,
# unactionable notice on almost every installation.
MENU_CODE_REJECTED_ISSUE = "menu_code_rejected"


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
        self,
        hass: HomeAssistant,
        session: ClientSession,
        user_id: str,
        token: str,
        menu_codes: dict[str, str] | None = None,
    ) -> None:
        """Initialise the coordinator responsible for a single Tech account.

        Args:
            hass: Home Assistant instance.
            session: Shared aiohttp client session.
            user_id: Tech platform user identifier.
            token: Bearer token returned by the authentication flow.
            menu_codes: Optional mapping of menu type to the code the user
                supplied for that tree, passed straight to the API client.

        """
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=SCAN_INTERVAL,
        )
        self.api = Tech(session, user_id, token, menu_codes=menu_codes)
        # Replaced with the fetched catalog in ``async_setup_entry`` before
        # any platform is set up; the empty default keeps lookups safe.
        self.translations = Translations()
        # Tracked separately because an empty catalog is a state in its own
        # right, not a signal that the fetch has not run: see
        # :meth:`async_load_translations`.
        self.translations_loaded = False
        # The registry id of the controller's device, set while the entry sets
        # up. Entities that belong to a zone name it as their child-device
        # parent, and entities for a separate sensor name it as their
        # ``via_device_id``; the registry needs the id, not the identifier.
        self.controller_device_id: str | None = None
        # The entities of each payload entry, by source key, and how many polls
        # in a row the controller has left that entry out. See
        # ``__init__._drop_unreported_entities``.
        self.reported: dict[str, set[Any]] = {}
        self.reported_misses: dict[str, int] = {}
        # The time limit, in minutes, the user picked for each zone's next
        # constant-temperature selection; zero (or no entry) means permanent.
        # The per-zone duration number writes it and the schedule select reads
        # it, so the value survives a poll and is restored on a restart.
        self.zone_constant_durations: dict[int, int] = {}
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

    def _async_sync_menu_code_issues(self, rejected: set[str]) -> None:
        """Report every tree whose configured code was not accepted.

        One issue per controller per tree, scoped by the controller udid, so
        several controllers can report the same tree without colliding. A tree
        that is no longer rejected has its issue deleted rather than left
        behind: a code the user retypes may start working, and an explanation
        that outlives its cause is worse than none.

        Args:
            rejected: Menu types whose configured code the controller refused
                during the last fetch, as recorded by
                :meth:`Tech._fetch_menu_data`.

        """
        udid = self.config_entry.data[CONTROLLER][UDID]
        for menu_type in MENU_TYPES:
            issue_id = f"{MENU_CODE_REJECTED_ISSUE}_{udid}_{menu_type}"
            if menu_type not in rejected:
                # A no-op when the issue was never raised.
                ir.async_delete_issue(self.hass, DOMAIN, issue_id)
                continue
            ir.async_create_issue(
                self.hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=MENU_CODE_REJECTED_ISSUE,
                translation_placeholders={"menu_type": menu_type},
            )

    async def async_load_translations(self) -> None:
        """Fetch the subtitle catalog, tolerating an API that will not serve it.

        The catalog only names things: without it a menu item is called ``txtId
        8395`` rather than "Zdjęcie blokady", and ``Translations`` was written to
        degrade exactly that way. Everything else -- zones, tiles, the menu trees
        and their controls -- is unaffected, so one decorative fetch must not
        cost the user every entity they have. It is retried on each refresh until
        it arrives, which is how the labels come back by themselves once the API
        serves them again.
        """
        try:
            self.translations = await Translations.load(
                self.hass.config.language, self.api
            )
        except TechError as err:
            _LOGGER.warning(
                "Could not fetch the Tech subtitle catalog, entity names fall "
                "back to their text ids: %s",
                err,
            )
            return
        self.translations_loaded = True

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
                data = await self.api.module_data(
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

        if not self.translations_loaded:
            await self.async_load_translations()

        self._async_sync_menu_code_issues(data.get("menu_code_rejections") or set())
        return data
