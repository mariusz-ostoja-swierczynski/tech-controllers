"""Python wrapper for interacting with Tech devices via the eModul API."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any

from aiohttp import ClientTimeout

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from aiohttp import ClientSession
else:  # pragma: no cover
    ClientSession = Any

from .const import (
    API_TIMEOUT,
    MENU_PIN_REJECTION_STATUS,
    MENU_ROOT_ELEMENT_ID,
    MENU_TYPES,
    MODULE_DATA_CACHE_TTL,
    TECH_SUPPORTED_LANGUAGES,
)

_LOGGER = logging.getLogger(__name__)

# A menu code travels in the request path, as ``.../menu/MS/0:<code>``, and the
# path is logged. The code is a credential of the same kind as the token, so it
# is masked out of anything logged here -- the element id stays, it is not
# secret, and the documented multi-element form has one code per pair.
_MENU_PIN_SEGMENT = re.compile(r"(?<=\d:)[^,/]+")


def _redact_menu_pin(path: str) -> str:
    """Mask any menu code carried in a path.

    Args:
        path: Request path, possibly holding an ``<element id>:<code>`` segment.

    Returns:
        The path with every such segment's code replaced by a placeholder.

    """
    return _MENU_PIN_SEGMENT.sub("**REDACTED**", path)


class Tech:
    """Main class to perform Tech API requests."""

    TECH_API_URL = "https://emodul.eu/api/v1/"

    def __init__(
        self,
        session: ClientSession,
        user_id=None,
        token=None,
        base_url=TECH_API_URL,
        menu_codes: dict[str, str] | None = None,
    ) -> None:
        """Initialise the Tech API client.

        Args:
            session: aiohttp client session used for HTTP requests.
            user_id: Optional user identifier returned by authentication.
            token: Optional bearer token returned by authentication.
            base_url: Base URL for the Tech API endpoints.
            menu_codes: Optional mapping of menu type (``MU``, ``MI``, ``MS``,
                ``MP``) to the code the user supplied for that tree. A tree
                whose code is absent is simply not retried; an empty mapping is
                the behaviour of every entry configured before codes existed.

        """
        _LOGGER.debug("Init Tech")
        self.headers = {"Accept": "application/json", "Accept-Encoding": "gzip"}
        self.base_url = base_url
        self.session = session
        # Bound every request so a stalled cloud connection cannot hang the
        # config flow or entry setup, which run outside the coordinator timeout.
        self.timeout = ClientTimeout(total=API_TIMEOUT)
        # The codes are read here rather than passed per call so that one place
        # holds them for both the read path (a refused tree) and the write path
        # (a locked item's ``pin``), whatever platform issued the write.
        self.menu_codes: dict[str, str] = dict(menu_codes or {})
        # The trees whose configured code the controller would not accept during
        # the last fetch. Only these are worth telling the user about: a tree
        # nobody gave a code for is refused like any other unavailable menu, and
        # has been since long before codes existed.
        self.menu_code_rejections: set[str] = set()
        if user_id and token:
            self.user_id = user_id
            self.token = token
            self.headers.setdefault("Authorization", f"Bearer {token}")
            self.authenticated = True
        else:
            self.authenticated = False
        # Serialises concurrent module_data refreshes (the platforms set up in
        # parallel) so they coalesce onto a single fetch instead of stampeding.
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
        _LOGGER.debug("Sending GET request: %s", _redact_menu_pin(url))
        async with self.session.get(
            url, headers=self.headers, timeout=self.timeout
        ) as response:
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
            url, data=post_data, headers=self.headers, timeout=self.timeout
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

    async def module_data(
        self, module_udid: str, force: bool = False
    ) -> dict[str, Any]:
        """Refresh module zones, tiles and menus and return the cached payload.

        Concurrent callers are serialised through :attr:`update_lock`, and a
        payload fetched within :data:`const.MODULE_DATA_CACHE_TTL` seconds is
        reused as-is. This collapses the burst of per-platform setup calls onto
        a single cloud refresh instead of one full (rate-limited) fetch each.
        The coordinator passes ``force=True`` to refresh on its own polling
        cadence regardless of cache age.

        Args:
            module_udid: Tech module identifier.
            force: When ``True``, bypass the freshness check and always refetch.

        Returns:
            Dictionary containing ``zones``, ``tiles`` and ``menus`` entries.

        """
        async with self.update_lock:
            cache = self.modules.setdefault(
                module_udid,
                {
                    "last_update": None,
                    "zones": {},
                    "tiles": {},
                    "menus": {},
                    "menu_code_rejections": set(),
                },
            )

            last_update = cache.get("last_update")
            if (
                not force
                and last_update is not None
                and time.monotonic() - last_update < MODULE_DATA_CACHE_TTL
            ):
                _LOGGER.debug("Reusing cached module data for %s", module_udid)
                return cache

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
                    "Updating %s zones for controller: %s",
                    len(visible_zones),
                    module_udid,
                )
                cache["zones"].update(
                    {zone["zone"]["id"]: zone for zone in visible_zones}
                )

            raw_tiles = result.get("tiles", [])
            visible_tiles = [
                tile for tile in raw_tiles if tile and tile.get("visibility")
            ]

            if visible_tiles:
                _LOGGER.debug(
                    "Updating %s tiles for controller: %s",
                    len(visible_tiles),
                    module_udid,
                )
                cache["tiles"].update({tile["id"]: tile for tile in visible_tiles})

            menu_items = await self._fetch_menu_data(module_udid)
            # Recorded whatever the outcome: a tree whose code starts being
            # accepted has to lose its notice, so the empty case matters as much
            # as the populated one.
            cache["menu_code_rejections"] = set(self.menu_code_rejections)
            if menu_items:
                _LOGGER.debug(
                    "Updating %s menu items for controller: %s",
                    len(menu_items),
                    module_udid,
                )
                cache.setdefault("menus", {}).update(menu_items)

            cache["last_update"] = time.monotonic()
            return cache

    @staticmethod
    def _menu_tree_is_gated(elements: list[Any]) -> bool:
        """Return whether a menu answer is a tree held back behind a code.

        A gated tree is answered with its root alone, and that root carries
        ``params.password``. The value there is a marker rather than the code --
        the demo controllers answer ``"password"``, and the eModul app overwrites
        it with ``"validate"`` before prompting -- so it says "this menu needs a
        code", not which one. It is the signal the app reads to decide to ask,
        mirrored here.

        Args:
            elements: The elements the tree answered with.

        Returns:
            ``True`` when the tree's root is holding the rest of the tree back.

        """
        for element in elements:
            if not isinstance(element, dict):
                continue
            if element.get("id") != MENU_ROOT_ELEMENT_ID:
                continue
            params = element.get("params")
            if isinstance(params, dict) and params.get("password"):
                return True
        return False

    async def _unlock_menu_tree(
        self,
        menu_type: str,
        module_udid: str,
        path: str,
        elements: list[Any],
    ) -> tuple[list[Any], bool]:
        """Retry a gated tree with the code the user supplied for it.

        The request is the documented one, ``.../{tree}/0:<code>``, which is also
        exactly what the eModul app builds. A code the controller does not accept
        is answered with the documented ``422 Invalid parameter pin`` -- the same
        answer the write path gives for one -- and since ``Tech.get`` raises on it,
        it is caught here: nothing else about the tree changes, so it keeps the
        root it handed over and the code is reported.

        Args:
            menu_type: Menu tree being fetched, e.g. ``"MS"``.
            module_udid: Tech module identifier, for the log line.
            path: The tree's request path, which ends in a slash.
            elements: The root-only answer the tree gave without a code.

        Returns:
            The unlocked elements, or the ones given when there is no code to
            try, and whether the code was rejected.

        """
        code = self.menu_codes.get(menu_type)
        if code is None:
            _LOGGER.debug(
                "Menu tree %s of module %s is behind a code and none is "
                "configured for it",
                menu_type,
                module_udid,
            )
            return elements, False
        try:
            result = await self.get(f"{path}{MENU_ROOT_ELEMENT_ID}:{code}")
        except TechError as err:
            # 422 is the API's "the pin is wrong"; anything else is a fault of a
            # different kind and belongs to the caller's own handling.
            if getattr(err, "status_code", None) != MENU_PIN_REJECTION_STATUS:
                raise
            _LOGGER.warning(
                "The %s menu of module %s did not accept the configured code",
                menu_type,
                module_udid,
            )
            return elements, True
        unlocked = result.get("data", {}).get("elements")
        if not unlocked:
            # An answer with no elements is not an unlock either.
            _LOGGER.warning(
                "The %s menu of module %s stayed locked with the configured code",
                menu_type,
                module_udid,
            )
            return elements, True
        _LOGGER.debug(
            "The %s menu of module %s opened with the configured code",
            menu_type,
            module_udid,
        )
        return unlocked, False

    async def _fetch_menu_data(self, module_udid: str) -> dict[str, dict[str, Any]]:
        """Fetch menu items from all configured menu types.

        A tree the account may not read answers with a message instead of
        elements, and there is nothing to retry for it. A tree held behind a code
        answers differently: with its root alone, and the root carries
        ``params.password`` -- the marker the eModul app reads to decide to ask
        for the code. Where the user supplied a code for such a tree the request
        is retried once with the code in the path; a tree with no code is never
        retried, and nothing is retried in a loop. A code the controller rejects
        is recorded on :attr:`menu_code_rejections`.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Mapping of ``{menu_type}_{item_id}`` to menu item payload.

        """
        items: dict[str, dict[str, Any]] = {}
        rejections: set[str] = set()
        for menu_type in MENU_TYPES:
            try:
                path = f"users/{self.user_id}/modules/{module_udid}/menu/{menu_type}/"
                result = await self.get(path)
                elements = result.get("data", {}).get("elements")
                if elements is None:
                    # A tree the account may not read can answer with a message
                    # rather than elements -- "missing items in MP menu" is what
                    # it says for a manufacturer tree -- which is worth seeing in
                    # a debug log beside the trees that do answer. There is no
                    # password element to pair a code with, so nothing is retried
                    # and nothing is reported: this is how those menus have always
                    # behaved.
                    _LOGGER.debug(
                        "Menu tree %s of module %s answered without elements: %s",
                        menu_type,
                        module_udid,
                        result,
                    )
                    continue
                if self._menu_tree_is_gated(elements):
                    elements, rejected = await self._unlock_menu_tree(
                        menu_type, module_udid, path, elements
                    )
                    if rejected:
                        rejections.add(menu_type)
                for element in elements:
                    if not isinstance(element, dict):
                        continue
                    item_id = element.get("id")
                    if item_id is not None:
                        key = f"{menu_type}_{item_id}"
                        items[key] = element
                _LOGGER.debug(
                    "Menu tree %s of module %s carries %s items",
                    menu_type,
                    module_udid,
                    len(elements),
                )
            except TechError:
                _LOGGER.debug(
                    "Menu type %s not available for module %s",
                    menu_type,
                    module_udid,
                )
        self.menu_code_rejections = rejections
        return items

    async def get_module_menus(self, module_udid: str) -> dict[str, dict[str, Any]]:
        """Return the cached menu items dictionary for ``module_udid``.

        Args:
            module_udid: Tech module identifier.

        Returns:
            Mapping of menu item key to menu item payload.

        """
        module = await self.module_data(module_udid)
        return module["menus"]

    async def set_menu_value(
        self,
        module_udid: str,
        menu_type: str,
        ido: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a menu parameter via the Tech API.

        Args:
            module_udid: Tech module identifier.
            menu_type: Menu type (MU, MI, MS, MP).
            ido: Parameter identifier.
            data: Payload to send (varies by menu item type).

        Returns:
            Parsed JSON response from the API.

        """
        code = self.menu_codes.get(menu_type)
        # The write path carries the code as a body field rather than a path
        # segment: "when a menu item is locked you need to attach a pin", as
        # {"pin": 1234, "value": 25}, and a pin the controller rejects is the
        # documented 422 that ``post`` raises as a TechError. Attaching it here
        # covers every platform that writes a menu item, so a control in a
        # gated tree works the same as one in a served tree.
        payload = {**data, "pin": code} if code is not None else data
        # Deliberately logs ``data`` and not ``payload``: the code is a
        # credential and must not reach a log line, so only its presence is
        # recorded.
        _LOGGER.debug(
            "Setting menu value for %s/%s%s: %s",
            menu_type,
            ido,
            " with a menu code" if code is not None else "",
            data,
        )
        if self.authenticated:
            path = (
                f"users/{self.user_id}/modules/{module_udid}/menu/{menu_type}/ido/{ido}"
            )
            result = await self.post(path, json.dumps(payload))
            _LOGGER.debug(result)
        else:
            raise TechError(401, "Unauthorized")
        return result

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
