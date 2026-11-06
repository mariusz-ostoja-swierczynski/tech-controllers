"""Tech DataUpdateCoordinator."""

import asyncio
import logging

from aiohttp import ClientSession

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

# The repair issue is raised only for a code the controller would not accept.
# A menu nobody gave a code for is refused exactly as it was before codes
# existed, and on a consumer account that is normal for several trees -- the
# manufacturer menu above all -- so reporting those would be a permanent,
# unactionable notice on almost every installation.
MENU_CODE_REJECTED_ISSUE = "menu_code_rejected"


class TechCoordinator(DataUpdateCoordinator):
    """Coordinate periodic refreshes from the Tech HTTP API."""

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

    async def _async_update_data(self) -> dict:
        """Fetch the latest module data for the configured controller.

        Returns:
            Fresh module payload containing ``zones`` and ``tiles`` data.

        Raises:
            ConfigEntryAuthFailed: If the API indicates that the token expired.
            UpdateFailed: If any other API error occurs during refresh.

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
            raise ConfigEntryAuthFailed from err
        except TechError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        if not self.translations_loaded:
            await self.async_load_translations()

        self._async_sync_menu_code_issues(data.get("menu_code_rejections") or set())
        return data
