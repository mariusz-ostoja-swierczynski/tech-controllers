"""Python wrapper for getting interaction with Tech devices."""
import asyncio
import json
import logging
import time
from typing import Any, Final, Optional, cast

import aiohttp

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)


class Tech:
    """Main class to perform Tech API requests."""

    TECH_API_URL: Final[str] = "https://emodul.eu/api/v1/"

    def __init__(
        self,
        session: aiohttp.ClientSession,
        user_id: Optional[str] = None,
        token: Optional[str] = None,
        base_url: str = TECH_API_URL,
        # update_interval: int = 130,
    ) -> None:
        """Initialize the Tech object.

        Args:
        session (aiohttp.ClientSession): The aiohttp client session.
        user_id (str): The user ID.
        token (str): The authentication token.
        base_url (str): The base URL for the API.
        update_interval (int): The interval for updates in seconds.

        """
        _LOGGER: logging.Logger = logging.getLogger(__name__)
        """Initialize the Tech object.

        Args:
            session (aiohttp.ClientSession): The aiohttp client session.
            user_id (Optional[str]): The user ID.
            token (Optional[str]): The authentication token.
            base_url (str): The base URL for the API.

        """
        self.headers: dict[str, str] = {
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
        }
        self.base_url: str = base_url
        self.session: aiohttp.ClientSession = session
        self.authenticated: bool = False
        if user_id and token:
            self.user_id = user_id
            self.token = token
            self.headers.setdefault("Authorization", "Bearer " + token)
            self.authenticated = True
        else:
            self.authenticated = False
        self.last_update: Optional[float] = None
        self.update_lock: asyncio.Lock = asyncio.Lock()
        self.modules: dict[str, dict[str, Any]] = {}

    async def get(self, request_path: str) -> Any:
        """Perform a GET request to the specified request path.

        Args:
            request_path (str): The path to send the GET request to.

        Returns:
            dict[str, Any]: The JSON response data.

        Raises:
            TechError: If the response status is not 200.

        """
        url: str = self.base_url + request_path
        _LOGGER: logging.Logger = logging.getLogger(__name__)
        _LOGGER.debug("Sending GET request: %s", url)
        async with self.session.get(url, headers=self.headers) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            data: dict[str, Any] = await response.json()
            return data

    async def post(self, request_path: str, post_data: str) -> dict[str, Any]:
        """Send a POST request to the specified URL with the given data.

        Args:
            request_path (str): The path for the request.
            post_data (dict[str, Any]): The data to be sent with the request.

        Returns:
            dict[str, Any]: The JSON response from the request.

        Raises:
            TechError: If the response status is not 200.

        """
        url: str = self.base_url + request_path
        _LOGGER: logging.Logger = logging.getLogger(__name__)
        _LOGGER.debug("Sending POST request: %s", url)
        async with self.session.post(
            url, data=post_data, headers=self.headers
        ) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            data: dict[str, Any] = await response.json()
            return data

    async def authenticate(self, username: str, password: str) -> bool:
        """Authenticate the user with the given username and password.

        Args:
            username: str, the username of the user
            password: str, the password of the user

        Returns:
            bool, indicating whether the user was authenticated successfully

        """
        path: str = "authentication"
        post_data: str = (
            '{"username": "' + username + '", "password": "' + password + '"}'
        )
        try:
            result: dict[str, Any] = await self.post(path, post_data)
            self.authenticated = result["authenticated"]
            if self.authenticated:
                self.user_id = str(result["user_id"])
                self.token = result["token"]
                self.headers = {
                    "Accept": "application/json",
                    "Accept-Encoding": "gzip",
                    "Authorization": "Bearer " + self.token,
                }
        except TechError as err:
            raise TechLoginError(401, "Unauthorized") from err
        return result["authenticated"]

    async def list_modules(self) -> list[dict[str, Any]]:
        """Retrieve the list of modules for the authenticated user.

        Returns:
            list[dict[str, Any]]: The list of modules for the authenticated user.

        Raises:
            TechError: If the user is not authenticated.

        """
        if self.authenticated:
            # Construct the path for the user's modules
            path: str = "users/" + self.user_id + "/modules"
            # Make a GET request to retrieve the modules
            result: list[dict[str, Any]] = await self.get(path)
            return result
        else:
            # Raise an error if the user is not authenticated
            raise TechError(401, "Unauthorized")

    # Asynchronous function to retrieve module data
    async def get_module_data(self, module_udid: str) -> dict[str, Any]:
        """Retrieve module data for a given module ID.

        Args:
            module_udid (str): The unique ID of the module to retrieve.

        Returns:
            dict[str, Any]: The data of the retrieved module.

        Raises:
            TechError: If not authenticated, raise 401 Unauthorized error.

        """
        _LOGGER.debug("Getting module data...  %s,  %s", module_udid, self.user_id)
        if self.authenticated:
            path: str = "users/" + self.user_id + "/modules/" + module_udid
            result: dict[str, Any] = await self.get(path)
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def get_translations(self, language: str) -> dict[str, str]:
        """Retrieve language pack for a given language.

        Args:
            language (str): Language code.

        Returns:
            dict[str, str]: The data of the retrieved language pack with translations.

        Raises:
            TechError: If not authenticated, raise 401 Unauthorized error.

        """
        _LOGGER.debug("Getting %s language", language)
        if self.authenticated:
            path: str = "i18n/" + language
            result: dict[str, str] = await self.get(path)
            # API already takes care of wrong and non-existent languages by returning "en"
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def get_module_zones(self: "Tech", module_udid: str) -> dict[str, Any]:
        """Return Tech module zones.

        Return Tech module zones.

        Args:
            self (Tech): The instance of the Tech API.
            module_udid (str): The Tech module udid.

        Returns:
            dictionary of zones indexed by zone ID.

        """
        now = time.time()
        _LOGGER.debug(
            "Getting module zones: now: %s",
            now,
        )

        _LOGGER.debug("Updating module zones cache... %s", module_udid)
        result: dict[str, Any] = await self.get_module_data(module_udid)
        zones: list[dict[str, Any]] = result["zones"]["elements"]
        zones = list(filter(lambda e: e["zone"]["visibility"], zones))

        for zone in zones:
            self.modules[module_udid]["zones"][zone["zone"]["id"]] = zone

        return self.modules[module_udid]["zones"]

    async def get_module_tiles(self: "Tech", module_udid: str) -> dict[str, Any]:
        """Return Tech module tiles.

        Return Tech module tiles.

        Args:
            self (Tech): The instance of the Tech API.
            module_udid (str): The Tech module udid.

        Returns:
            dictionary of tiles indexed by tile ID.

        """
        now = time.time()
        _LOGGER.debug(
            "Getting module tiles: now: %s",
            now,
        )

        _LOGGER.debug("Updating module tiles cache... %s", module_udid)
        result: dict[str, Any] = await self.get_module_data(module_udid)
        tiles: list[dict[str, Any]] = result["tiles"]
        tiles = list(filter(lambda e: e["visibility"], tiles))

        for tile in tiles:
            self.modules[module_udid]["tiles"][tile["id"]] = tile

        return self.modules[module_udid]["tiles"]

    async def module_data(self: "Tech", module_udid: str) -> dict[str, dict[str, Any]]:
        """Update Tech module zones and tiles.

        Update Tech module zones and tiles.
        either from cache or it will
        update all the cached values for Tech module assuming
        no update has occurred for at least the [update_interval].

        Args:
            self (Tech): The instance of the Tech API.
            module_udid (str): The Tech module udid.

        Returns:
            dictionary of zones and tiles indexed by zone ID.

        """
        now = time.time()

        self.modules.setdefault(
            module_udid, {"last_update": None, "zones": {}, "tiles": {}}
        )

        _LOGGER.debug("Updating module zones & tiles cache... %s", module_udid)
        result: dict[str, Any] = await self.get_module_data(module_udid)
        zones: list[dict[str, Any]] = result["zones"]["elements"]
        zones = list(filter(lambda e: e["zone"]["visibility"], zones))

        if len(zones) > 0:
            _LOGGER.debug("Updating zones cache for controller: %s", module_udid)
            zones = list(
                filter(
                    lambda e: e["zone"]["zoneState"] != "zoneUnregistered",
                    zones,
                )
            )
            for zone in zones:
                self.modules[module_udid]["zones"][zone["zone"]["id"]] = zone
        tiles: list[dict[str, Any]] = result["tiles"]
        tiles = list(filter(lambda e: e["visibility"], tiles))

        if len(tiles) > 0:
            _LOGGER.debug("Updating tiles cache for controller: %s", module_udid)
            for tile in tiles:
                self.modules[module_udid]["tiles"][tile["id"]] = tile
        self.modules[module_udid]["last_update"] = now
        return self.modules[module_udid]

    async def get_zone(self, module_udid: str, zone_id: int) -> dict[str, Any]:
        """Return zone from Tech API cache.

        Args:
            module_udid (str): The Tech module udid.
            zone_id (int): The Tech module zone ID.

        Returns:
            dict[str, Any]: dictionary of zone.

        """
        await self.get_module_zones(module_udid)
        return cast(dict[str, Any], self.modules[module_udid]["zones"][zone_id])

    async def get_tile(self, module_udid: str, tile_id: int) -> dict[str, Any]:
        """Return tile from Tech API cache.

        Args:
            module_udid (str): The Tech module udid.
            tile_id (int): The Tech module tile ID.

        Returns:
            dict[str, Any]: dictionary of tile.

        """
        await self.get_module_tiles(module_udid)
        return cast(dict[str, Any], self.modules[module_udid]["tiles"][tile_id])

    async def set_const_temp(
        self, module_udid: str, zone_id: str, target_temp: float
    ) -> dict[str, Any]:
        """Set constant temperature of the zone.

        Args:
            module_udid (str): The Tech module udid.
            zone_id (int): The Tech module zone ID.
            target_temp (float): The target temperature to be set within the zone.

        Returns:
            dict[str, Any]: JSON object with the result.

        """
        _LOGGER.debug("Setting zone constant temperature")
        if self.authenticated:
            path: str = "users/" + self.user_id + "/modules/" + module_udid + "/zones"
            data: dict[str, Any] = {
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
            result: dict[str, Any] = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
            return result
        raise TechError(401, "Unauthorized")

    async def set_zone(
        self, module_udid: str, zone_id: str, on: bool = True
    ) -> dict[str, Any]:
        """Turn the zone on or off.

        Args:
            module_udid (str): The Tech module udid.
            zone_id (int): The Tech module zone ID.
            on (bool, optional): Flag indicating to turn the zone on if True or off if False.

        Returns:
            dict[str, Any]: JSON object with the result.

        """
        _LOGGER.debug("Turing zone on/off: %s", on)
        if self.authenticated:
            path: str = "users/" + self.user_id + "/modules/" + module_udid + "/zones"
            data: dict[str, Any] = {
                "zone": {"id": zone_id, "zoneState": "zoneOn" if on else "zoneOff"}
            }
            _LOGGER.debug(data)
            result: dict[str, Any] = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
            return result
        raise TechError(401, "Unauthorized")


class TechError(Exception):
    """Raised when Tech APi request ended in error.

    Attributes:
        status_code (int): The error code returned by Tech API.
        status (str): More detailed description of the error.

    """

    def __init__(self, status_code: int, status: str) -> None:
        """Initialize the status code and status of the object.

        Args:
            status_code (int): The status code to be assigned.
            status (str): The status to be assigned.

        Returns:
            None

        """
        self.status_code: int = status_code
        self.status: str = status


class TechLoginError(Exception):
    """Raised when Tech API login fails.

    Attributes:
        status_code (int): The error code returned by Tech API.
        status (str): More detailed description of the error.

    """

    def __init__(self, status_code: int, status: str) -> None:
        """Initialize the status code and status of the object.

        Args:
            status_code (int): The status code to be assigned.
            status (str): The status to be assigned.

        Returns:
            None

        """
        self.status_code: int = status_code
        self.status: str = status
