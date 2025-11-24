"""Python wrapper for interacting with Tech devices via the eModul API."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from aiohttp import ClientSession
else:  # pragma: no cover
    ClientSession = Any

from .const import TECH_SUPPORTED_LANGUAGES

_LOGGER = logging.getLogger(__name__)


class Tech:
    """Main class to perform Tech API requests."""

    TECH_API_URL = "https://emodul.eu/api/v1/"

    def __init__(
        self,
        session: ClientSession,
        user_id=None,
        token=None,
        base_url=TECH_API_URL,
    ) -> None:
        """Initialise the Tech API client.

        Args:
            session: aiohttp client session used for HTTP requests.
            user_id: Optional user identifier returned by authentication.
            token: Optional bearer token returned by authentication.
            base_url: Base URL for the Tech API endpoints.

        """
        _LOGGER.debug("Init Tech")
        self.headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
        self.base_url = base_url
        self.session = session
        if user_id and token:
            self.user_id = user_id
            self.token = token
            self.headers.setdefault("Authorization", f"Bearer {token}")
            self.authenticated = True
        else:
            self.authenticated = False
        self.last_update = None
        self.update_lock = asyncio.Lock()
        self.modules = {}

    async def get(self, request_path: str) -> dict[str, Any]:
        """Perform a GET request against the Tech API.

        Args:
            request_path: Relative path appended to the base URL.

        Returns:
            Parsed JSON response.

        Raises:
            TechError: Raised when the API responds with a non-200 status code.

        """
        url = self.base_url + request_path
        _LOGGER.debug("Sending GET request: %s", url)
        async with self.session.get(url, headers=self.headers) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            return await response.json()

    async def post(self, request_path: str, post_data: str) -> dict[str, Any]:
        """Send a POST request against the Tech API with JSON payload string.

        Args:
            request_path: Relative path appended to the base URL.
            post_data: Raw JSON payload encoded as a string.

        Returns:
            Parsed JSON response.

        Raises:
            TechError: Raised when the API responds with a non-200 status code.

        """
        url = self.base_url + request_path
        _LOGGER.debug("Sending POST request: %s", url)
        async with self.session.post(
            url, data=post_data, headers=self.headers
        ) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            return await response.json()

    async def authenticate(self, username: str, password: str) -> bool:
        """Authenticate the user with the provided credentials.

        Args:
            username: Account username.
            password: Account password.

        Returns:
            ``True`` when authentication succeeded.

        Raises:
            TechLoginError: When the API returns an authentication error.

        """
        path = "authentication"
        post_data = json.dumps({"username": username, "password": password})
        try:
            result = await self.post(path, post_data)
            self.authenticated = result["authenticated"]
            if self.authenticated:
                self.user_id = str(result["user_id"])
                self.token = result["token"]
                self.headers = {
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Authorization": f"Bearer {self.token}",
                }
        except TechError as err:
            raise TechLoginError(401, "Unauthorized") from err
        return result["authenticated"]

    async def list_modules(self) -> dict[str, Any]:
        """Return the list of modules available for the authenticated user.

        Returns:
            Parsed JSON response describing all modules.

        Raises:
            TechError: If the client is not currently authenticated.

        """
        if self.authenticated:
            # Construct the path for the user's modules
            path = f"users/{self.user_id}/modules"
            # Make a GET request to retrieve the modules
            result = await self.get(path)
        else:
            # Raise an error if the user is not authenticated
            raise TechError(401, "Unauthorized")
        return result

    # Asynchronous function to retrieve module data
    async def get_module_data(self, module_udid: str) -> dict[str, Any]:
        """Return a full module payload for ``module_udid``.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Parsed JSON response representing the module.

        Raises:
            TechError: If the client is not currently authenticated.

        """
        _LOGGER.debug("Getting module data...  %s", module_udid)
        if self.authenticated:
            path = f"users/{self.user_id}/modules/{module_udid}"
            result = await self.get(path)
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def get_translations(self, language: str) -> dict[str, Any]:
        """Retrieve the translation pack for ``language``.

        If the requested language is unsupported, ``en`` will be used.

        Args:
            language: Two-letter language code.

        Returns:
            Parsed JSON response containing translation data.

        Raises:
            TechError: If the client is not currently authenticated.

        """

        if language not in TECH_SUPPORTED_LANGUAGES:
            _LOGGER.debug("Language %s not supported. Switching to default", language)
            language = "en"

        _LOGGER.debug("Getting %s language", language)

        if self.authenticated:
            path = f"i18n/{language}"
            result = await self.get(path)
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def get_module_zones(self, module_udid: str) -> dict[int, dict[str, Any]]:
        """Return the cached zones dictionary for ``module_udid``.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Mapping of zone identifier to zone payload.

        """

        module = await self.module_data(module_udid)
        return module["zones"]

    async def get_module_tiles(self, module_udid: str) -> dict[int, dict[str, Any]]:
        """Return the cached tiles dictionary for ``module_udid``.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Mapping of tile identifier to tile payload.

        """

        module = await self.module_data(module_udid)
        return module["tiles"]

    async def module_data(self, module_udid: str) -> dict[str, Any]:
        """Refresh module zones and tiles and return the cached payload.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Dictionary containing ``zones`` and ``tiles`` entries.

        """
        now = time.time()

        cache = self.modules.setdefault(
            module_udid, {"last_update": None, "zones": {}, "tiles": {}}
        )

        _LOGGER.debug("Updating module zones & tiles ... %s", module_udid)
        result = await self.get_module_data(module_udid)

        raw_zones = result.get("zones", {}).get("elements", [])
        visible_zones = [
            zone
            for zone in raw_zones
            if zone
            and zone.get("zone")
            and zone["zone"].get("visibility")
            and zone["zone"].get("zoneState") != "zoneUnregistered"
        ]

        if visible_zones:
            _LOGGER.debug(
                "Updating %s zones for controller: %s", len(visible_zones), module_udid
            )
            cache["zones"].update({zone["zone"]["id"]: zone for zone in visible_zones})

        raw_tiles = result.get("tiles", [])
        visible_tiles = [tile for tile in raw_tiles if tile and tile.get("visibility")]

        if visible_tiles:
            _LOGGER.debug(
                "Updating %s tiles for controller: %s", len(visible_tiles), module_udid
            )
            cache["tiles"].update({tile["id"]: tile for tile in visible_tiles})

        cache["last_update"] = now
        return cache

    async def get_zone(self, module_udid, zone_id):
        """Return a single zone payload.

        Args:
            module_udid: Tech module identifier.
            zone_id: Numeric zone identifier.

        Returns:
            Cached zone dictionary.

        """
        await self.get_module_zones(module_udid)
        return self.modules[module_udid]["zones"][zone_id]

    async def get_tile(self, module_udid, tile_id):
        """Return a single tile payload.

        Args:
            module_udid: Tech module identifier.
            tile_id: Numeric tile identifier.

        Returns:
            Cached tile dictionary.

        """
        await self.get_module_tiles(module_udid)
        return self.modules[module_udid]["tiles"][tile_id]

    async def set_const_temp(self, module_udid, zone_id, target_temp):
        """Set the constant temperature of a zone.

        Args:
            module_udid: Tech module identifier.
            zone_id: Numeric zone identifier.
            target_temp: Temperature in °C to maintain.

        Returns:
            Parsed JSON response from the API.

        """
        _LOGGER.debug("Setting zone constant temperature…")
        if self.authenticated:
            path = f"users/{self.user_id}/modules/{module_udid}/zones"
            data = {
                "mode": {
                    "id": self.modules[module_udid]["zones"][zone_id]["mode"]["id"],
                    "parentId": zone_id,
                    "mode": "constantTemp",
                    "constTempTime": 60,
                    "setTemperature": int(target_temp * 10),
                    "scheduleIndex": 0,
                }
            }
            _LOGGER.debug(data)
            result = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def set_zone(self, module_udid, zone_id, on=True):
        """Toggle a zone on or off.

        Args:
            module_udid: Tech module identifier.
            zone_id: Numeric zone identifier.
            on: ``True`` to turn the zone on, ``False`` to turn it off.

        Returns:
            Parsed JSON response from the API.

        """
        _LOGGER.debug("Turing zone on/off: %s", on)
        if self.authenticated:
            path = f"users/{self.user_id}/modules/{module_udid}/zones"
            data = {"zone": {"id": zone_id, "zoneState": "zoneOn" if on else "zoneOff"}}
            _LOGGER.debug(data)
            result = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
        else:
            raise TechError(401, "Unauthorized")
        return result


class TechError(Exception):
    """Raised when a Tech API request results in an error."""

    def __init__(self, status_code, status) -> None:
        """Initialise an error with the API status code and message.

        Args:
            status_code: HTTP status or API-specific code.
            status: Human-readable reason message from the API.

        """
        self.status_code = status_code
        self.status = status


class TechLoginError(Exception):
    """Raised when a Tech API login attempt fails."""

    def __init__(self, status_code, status) -> None:
        """Initialize the status code and status of the object.

        Args:
            status_code (int): The status code to be assigned.
            status (str): The status to be assigned.

        """
        self.status_code = status_code
        self.status = status
