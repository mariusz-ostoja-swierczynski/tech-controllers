"""
Python wrapper for getting interaction with Tech devices.
"""
import logging
import aiohttp
import json
import time
import asyncio

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

class Tech:
    """Main class to perform Tech API requests"""

    TECH_API_URL = "https://emodul.eu/api/v1/"

    def __init__(self, session: aiohttp.ClientSession, user_id = None, token = None, base_url = TECH_API_URL, update_interval = 60):
        _LOGGER.debug("Init Tech")
        self.headers = {
            'Accept': 'application/json',
            'Accept-Encoding': 'gzip'
        }
        self.base_url = base_url
        self.update_interval = update_interval
        self.session = session
        if user_id and token:
            self.user_id = user_id
            self.token = token
            self.headers.setdefault("Authorization", "Bearer " + token)
            self.authenticated = True
        else:
            self.authenticated = False
        self.last_update = None
        self.update_lock = asyncio.Lock()
        self.zones = {}
        self.tiles = {}

    async def get(self, request_path):
        url = self.base_url + request_path
        _LOGGER.debug("Sending GET request: " + url)
        async with self.session.get(url, headers=self.headers) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            data = await response.json()
            _LOGGER.debug(data)
            return data
    
    async def post(self, request_path, post_data):
        url = self.base_url + request_path
        _LOGGER.debug("Sending POST request: " + url)
        async with self.session.post(url, data=post_data, headers=self.headers) as response:
            if response.status != 200:
                _LOGGER.warning("Invalid response from Tech API: %s", response.status)
                raise TechError(response.status, await response.text())

            data = await response.json()
            _LOGGER.debug(data)
            return data
    
    async def authenticate(self, username, password):
        path = "authentication"
        post_data = '{"username": "' + username + '", "password": "' + password + '"}'
        result = await self.post(path, post_data)
        self.authenticated = result["authenticated"]
        if self.authenticated:
            self.user_id = str(result["user_id"])
            self.token = result["token"]
            self.headers = {
                'Accept': 'application/json',
                'Accept-Encoding': 'gzip',
                'Authorization': 'Bearer ' + self.token
            }
        return result["authenticated"]

    async def list_modules(self):
        if self.authenticated:
            path = "users/" + self.user_id + "/modules"
            result = await self.get(path)
        else:
            raise TechError(401, "Unauthorized")
        return result
    
    async def get_module_data(self, module_udid):
        _LOGGER.debug("Getting module data..." + module_udid + ", " + self.user_id)
        if self.authenticated:
            path = "users/" + self.user_id + "/modules/" + module_udid
            result = await self.get(path)
        else:
            raise TechError(401, "Unauthorized")
        return result
    
    async def update_module_data(self, module_udid):
        """Updates Tech module zones and tiles either from cache or
        it will update all the cached values for Tech module assuming
        no update has occurred for at least the [update_interval].

        Parameters:
        module_udid (string): The Tech module udid.

        Returns:
        True when data has been updated or False otherwise.
        """
        async with self.update_lock:
            now = time.time()
            _LOGGER.debug("Geting module data: now: %s, last_update %s, interval: %s", now, self.last_update, self.update_interval)
            if self.last_update is None or now > self.last_update + self.update_interval:
                _LOGGER.debug("Updating module data cache..." + module_udid)    
                result = await self.get_module_data(module_udid)
                zones = result["zones"]["elements"]
                zones = list(filter(lambda e: e['zone']['zoneState'] != "zoneUnregistered", zones))
                tiles = result["tiles"]
                for zone in zones:
                    self.zones[zone["zone"]["id"]] = zone
                for tile in tiles:
                    self.tiles[tile["id"]] = tile
                self.last_update = now
                return True
            else:
                return False

    async def get_zones(self, module_udid):
        """Returns zones from Tech API.

        Parameters:
        module_udid (string): The Tech module udid.

        Returns:
        Dictionary of zones.
        """
        await self.update_module_data(module_udid)
        return self.zones

    async def get_tiles(self, module_udid):
        """Returns tiles from Tech API.

        Parameters:
        module_udid (string): The Tech module udid.

        Returns:
        Dictionary of tiles.
        """
        await self.update_module_data(module_udid)
        return self.tiles
    
    async def get_zone(self, module_udid, zone_id):
        """Returns zone from Tech API.

        Parameters:
        module_udid (string): The Tech module udid.
        zone_id (int): The Tech module zone ID.

        Returns:
        Dictionary of zone.
        """
        await self.update_module_data(module_udid)
        return self.zones[zone_id]

    async def get_tile(self, module_udid, tile_id):
        """Returns tile from Tech API.

        Parameters:
        module_udid (string): The Tech module udid.
        tile_id (int): The Tech module tile ID.

        Returns:
        Dictionary of tile.
        """
        await self.update_module_data(module_udid)
        return self.tiles[tile_id]

    async def set_const_temp(self, module_udid, zone_id, target_temp):
        """Sets constant temperature of the zone.
        
        Parameters:
        module_udid (string): The Tech module udid.
        zone_id (int): The Tech module zone ID.
        target_temp (float): The target temperature to be set within the zone.

        Returns:
        JSON object with the result.
        """
        _LOGGER.debug("Setting zone constant temperature...")
        if self.authenticated:
            path = "users/" + self.user_id + "/modules/" + module_udid + "/zones"
            data = {
                "mode" : {
                    "id" : self.zones[zone_id]["mode"]["id"],
                    "parentId" : zone_id,
                    "mode" : "constantTemp",
                    "constTempTime" : 60,
                    "setTemperature" : int(target_temp  * 10),
                    "scheduleIndex" : 0
                }
            }
            _LOGGER.debug(data)
            result = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
        else:
            raise TechError(401, "Unauthorized")
        return result

    async def set_zone(self, module_udid, zone_id, on = True):
        """Turns the zone on or off.
        
        Parameters:
        module_udid (string): The Tech module udid.
        zone_id (int): The Tech module zone ID.
        on (bool): Flag indicating to turn the zone on if True or off if False.

        Returns:
        JSON object with the result.
        """
        _LOGGER.debug("Turing zone on/off: %s", on)
        if self.authenticated:
            path = "users/" + self.user_id + "/modules/" + module_udid + "/zones"
            data = {
                "zone" : {
                    "id" : zone_id,
                    "zoneState" : "zoneOn" if on else "zoneOff"
                }
            }
            _LOGGER.debug(data)
            result = await self.post(path, json.dumps(data))
            _LOGGER.debug(result)
        else:
            raise TechError(401, "Unauthorized")
        return result

class TechError(Exception):
    """Raised when Tech APi request ended in error.
    Attributes:
        status_code - error code returned by Tech API
        status - more detailed description
    """
    def __init__(self, status_code, status):
        self.status_code = status_code
        self.status = status