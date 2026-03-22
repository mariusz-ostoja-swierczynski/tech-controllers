"""Tech DataUpdateCoordinator."""

import asyncio
import logging

from aiohttp import ClientSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import API_TIMEOUT, CONTROLLER, DOMAIN, SCAN_INTERVAL, UDID
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__package__)


class TechCoordinator(DataUpdateCoordinator):
    """Coordinate periodic refreshes from the Tech HTTP API."""

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
        self._filter_reset_date = None
        self.hass = hass

    async def async_load_filter_reset_date(self) -> None:
        """Load filter reset date from storage."""
        if self.config_entry:
            from homeassistant.helpers import storage

            udid = self.config_entry.data[CONTROLLER][UDID]
            store = storage.Store(
                self.hass,
                version=1,
                key=f"{DOMAIN}_{udid}_filter_data"
            )
            data = await store.async_load()
            if data and "filter_reset_date" in data:
                self._filter_reset_date = data["filter_reset_date"]
                _LOGGER.debug("Loaded filter reset date: %s", self._filter_reset_date)

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
                return await self.api.module_data(
                    self.config_entry.data[CONTROLLER][UDID]
                )
        except TechLoginError as err:
            raise ConfigEntryAuthFailed from err
        except TechError as err:
            raise UpdateFailed(f"Error communicating with API: {err}") from err
