"""The Tech Controllers integration."""
import asyncio
import logging
import uuid

from aiohttp import ClientSession

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DESCRIPTION,
    CONF_ID,
    CONF_NAME,
    CONF_PARAMS,
    CONF_TOKEN,
    CONF_TYPE,
    CONF_ZONE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    config_validation as cv,
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import assets
from .const import (
    API_TIMEOUT,
    CONTROLLER,
    DOMAIN,
    MANUFACTURER,
    PLATFORMS,
    SCAN_INTERVAL,
    TYPE_FAN,
    TYPE_FUEL_SUPPLY,
    TYPE_MIXING_VALVE,
    TYPE_TEMPERATURE,
    TYPE_TEMPERATURE_CH,
    TYPE_TEXT,
    TYPE_VALVE,
    UDID,
    USER_ID,
    VER,
)
from .tech import Tech, TechError, TechLoginError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict):  # pylint: disable=unused-argument
    """Set up the Tech Controllers component."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up Tech Controllers from a config entry."""
    _LOGGER.debug("Setting up component's entry.")
    _LOGGER.debug("Entry id: %s", str(entry.entry_id))
    _LOGGER.debug(
        "Entry -> title: %s, data: %s, id: %s, domain: %s",
        entry.title,
        str(entry.data),
        entry.entry_id,
        entry.domain,
    )
    language_code = hass.config.language
    user_id = entry.data[USER_ID]
    token = entry.data[CONF_TOKEN]
    # Store an API object for your platforms to access
    hass.data.setdefault(DOMAIN, {})
    websession = async_get_clientsession(hass)

    coordinator = TechCoordinator(hass, websession, user_id, token)
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_config_entry_first_refresh()

    await assets.load_subtitles(language_code, Tech(websession, user_id, token))

    hass.async_create_task(
        hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    )

    return True


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.info("Migrating from version %s", config_entry.version)

    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    if config_entry.version == 1:
        udid = config_entry.data[UDID]
        version = 2
        minor_version = 2

        http_session = async_get_clientsession(hass)
        api = Tech(
            http_session, config_entry.data[USER_ID], config_entry.data[CONF_TOKEN]
        )
        controllers = await api.list_modules()
        controller = next(obj for obj in controllers if obj.get(UDID) == udid)
        api.modules.setdefault(udid, {"last_update": None, "zones": {}, "tiles": {}})
        zones = await api.get_module_zones(udid)
        _LOGGER.debug("▶ zones: %s", zones)

        data = {
            USER_ID: api.user_id,
            CONF_TOKEN: api.token,
            CONTROLLER: controller,
            VER: controller[VER] + ": " + controller[CONF_NAME],
        }

        # Store the existing entity entries:
        old_entity_entries: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

        # Update config entry
        hass.config_entries.async_update_entry(
            config_entry,
            data=data,
            title=controller[CONF_NAME],
            unique_id=udid,
            version=version,
            minor_version=minor_version,
        )

        # Create new devices as version 1 did not have any:
        for z in zones:
            zone = zones[z]
            device_registry.async_get_or_create(
                config_entry_id=config_entry.entry_id,
                identifiers={
                    (
                        DOMAIN,
                        udid + "_" + str(zone[CONF_ZONE][CONF_ID]),
                    )
                },
                manufacturer=MANUFACTURER,
                name=zone[CONF_DESCRIPTION][CONF_NAME],
                model=controller[CONF_NAME] + ": " + controller[VER],
                # sw_version= #TODO
                # hw_version= #TODO
            )

        remaining_entities_to_remove: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

        # Update all entities and link them to appropriate devices
        # plus update unique_id, everything else as it was
        for unique_id, old_entity_entry in old_entity_entries.items():
            entity_id = old_entity_entry.entity_id
            original_name = old_entity_entry.original_name
            _LOGGER.debug(
                "👴 old unique id: %s, entity_id: %s, original_name: %s",
                unique_id,
                entity_id,
                original_name,
            )

            if old_entity_entry.original_name != "":
                try:
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"] == original_name
                    )
                except StopIteration:
                    zone_id = None

                if entity_id.startswith("climate."):
                    new_unique_id = udid + "_" + str(zone_id) + "_climate"

                elif entity_id.startswith("sensor"):
                    if entity_id.endswith("battery"):
                        new_unique_id = udid + "_" + str(zone_id) + "_battery"
                    elif entity_id.endswith("out_temperature"):
                        new_unique_id = udid + "_" + str(zone_id) + "_out_temperature"
                    elif entity_id.endswith("humidity"):
                        new_unique_id = udid + "_" + str(zone_id) + "_humidity"
                    elif entity_id.endswith("temperature"):
                        new_unique_id = udid + "_" + str(zone_id) + "_temperature"

                device = device_registry.async_get_device(
                    {(DOMAIN, old_entity_entry.original_name)},
                    set(),
                )
                if device and device.name == old_entity_entry.original_name:
                    # since thsi entity stays, remove it from collection to remove
                    del remaining_entities_to_remove[unique_id]
                    entity_registry.async_update_entity(
                        old_entity_entry.entity_id,
                        area_id=old_entity_entry.area_id,
                        device_class=old_entity_entry.device_class,
                        device_id=device.id,
                        disabled_by=old_entity_entry.disabled_by,
                        hidden_by=old_entity_entry.hidden_by,
                        icon=old_entity_entry.icon,
                        name=old_entity_entry.name,
                        new_entity_id=old_entity_entry.entity_id,
                        new_unique_id=new_unique_id,
                        unit_of_measurement=old_entity_entry.unit_of_measurement,
                    )

        # Remove the remaining entities that are no longer provided by the integration
        # Items that are not visible in emodul.

        for entity_to_remove in remaining_entities_to_remove:
            entity_registry.async_remove(
                remaining_entities_to_remove[entity_to_remove].entity_id
            )

        _LOGGER.info(
            "Migration to version %s successful",
            str(version) + "." + str(minor_version),
        )

    if config_entry.version == 2 and config_entry.minor_version == 1:
        udid = config_entry.data[CONTROLLER][UDID]
        version = 2
        minor_version = 2

        http_session = async_get_clientsession(hass)
        api = Tech(
            http_session, config_entry.data[USER_ID], config_entry.data[CONF_TOKEN]
        )
        # load translations
        await assets.load_subtitles(hass.config.language, api)

        controllers = await api.list_modules()
        controller = next(obj for obj in controllers if obj.get(UDID) == udid)
        api.modules.setdefault(udid, {"last_update": None, "zones": {}, "tiles": {}})
        zones = await api.get_module_zones(udid)
        _LOGGER.debug("▶ zones: %s", zones)
        tiles = await api.get_module_tiles(udid)
        _LOGGER.debug("🦶 tiles: %s", tiles)

        # Store the existing entity entries:
        old_entity_entries: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

        # Update config entry to new version
        hass.config_entries.async_update_entry(
            config_entry,
            unique_id=udid,
            version=version,
            minor_version=minor_version,
        )

        if zones:
            devices = dr.async_entries_for_config_entry(
                device_registry, config_entry.entry_id
            )

            # Update devices identifiers:
            for device in devices:
                try:
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"] == list(device.identifiers)[0][1]
                    )
                except StopIteration:
                    zone_id = None

                if zone_id:
                    device_registry.async_update_device(
                        device_id=device.id,
                        new_identifiers={
                            (
                                DOMAIN,
                                udid + "_" + str(zone_id),
                            )
                        },
                    )

        # Update all entities to new unique_ids
        for unique_id, old_entity_entry in old_entity_entries.items():
            entity_id = old_entity_entry.entity_id
            original_name = old_entity_entry.original_name
            _LOGGER.debug(
                "👴 old unique id: %s, entity_id: %s, original_name: %s",
                unique_id,
                entity_id,
                original_name,
            )

            # if binary_sensor that means we look in tiles
            if entity_id.startswith("binary_sensor"):
                # original_name = get_substring_until_last_digit(
                #     old_entity_entry.original_name
                # )
                # original_name = old_entity_entry.original_name

                txt_id = assets.get_id_from_text(original_name)
                _LOGGER.debug("👳‍♂️ txtid: %s", txt_id)

                try:
                    key_id = next(
                        (
                            k
                            for k, v in tiles.items()
                            if v[CONF_PARAMS].get("txtId") == txt_id
                        ),
                        None,
                    )
                    if key_id is None:
                        key_id = next(
                            (
                                k
                                for k, v in tiles.items()
                                if v[CONF_PARAMS].get("headerId") == txt_id
                            ),
                            None,
                        )
                    if key_id is None:
                        # looks like we have a sensor with name defined by type

                        tile_type = assets.get_id_from_type(txt_id)
                        _LOGGER.debug("👳‍♂️ tile_type: %s", tile_type)
                        key_id = next(
                            (k for k, v in tiles.items() if v[CONF_TYPE] == tile_type),
                            None,
                        )
                        _LOGGER.debug("👳‍♂️ key_id: %s", key_id)
                        # if txt_id:
                        #     self._name = assets.get_text(txt_id)
                        # else:
                        #     self._name = assets.get_text_by_type(device[CONF_TYPE])
                    new_unique_id = udid + "_" + str(key_id) + "_tile_binary_sensor"
                except (KeyError, StopIteration):
                    continue

            # this is a tile sensor
            elif entity_id.startswith("sensor") and not entity_id.endswith(
                ("battery", "out_temperature", "humidity", "temperature")
            ):
                # no unique reverse lookup if we had missing title from API 😥
                # original_name = get_substring_until_last_digit(
                #     old_entity_entry.original_name
                # )
                # original_name = old_entity_entry.original_name
                if "txtId" in original_name:
                    if old_entity_entry.original_device_class == "temperature":
                        new_unique_id = (
                            udid + "_" + str(uuid.uuid4().hex) + "_tile_temperature"
                        )
                    else:
                        new_unique_id = (
                            udid + "_" + str(uuid.uuid4().hex) + "_tile_sensor"
                        )
                # otherwise we get the name to get the zone/tile ID
                else:
                    _LOGGER.debug("👳‍♂️ original_name: %s", original_name)
                    txt_id = assets.get_id_from_text(original_name)
                    _LOGGER.debug("👳‍♂️ txtid: %s", txt_id)
                    # _LOGGER.debug("👳‍♂️ tiles.item(): %s", tiles.items())

                    try:
                        key_id = next(
                            (
                                k
                                for k, v in tiles.items()
                                if v[CONF_PARAMS].get("txtId") == txt_id
                            ),
                            None,
                        )
                        if key_id is None:
                            key_id = next(
                                (
                                    k
                                    for k, v in tiles.items()
                                    if v[CONF_PARAMS].get("headerId") == txt_id
                                ),
                                None,
                            )
                        if key_id is None:
                            # looks like we have a sensor with name defined by type

                            tile_type = assets.get_id_from_type(txt_id)
                            _LOGGER.debug("👳‍♂️ tile_type: %s", tile_type)
                            key_id = next(
                                (
                                    k
                                    for k, v in tiles.items()
                                    if v[CONF_TYPE] == tile_type
                                ),
                                None,
                            )
                            _LOGGER.debug("👳‍♂️ key_id: %s", key_id)
                            # if txt_id:
                            #     self._name = assets.get_text(txt_id)
                            # else:
                            #     self._name = assets.get_text_by_type(device[CONF_TYPE])

                        if tiles[key_id][CONF_TYPE] == TYPE_TEMPERATURE:
                            new_unique_id = (
                                udid + "_" + str(key_id) + "_tile_temperature"
                            )
                        if tiles[key_id][CONF_TYPE] == TYPE_TEMPERATURE_CH:
                            new_unique_id = udid + "_" + str(key_id) + "_tile_widget"
                        if tiles[key_id][CONF_TYPE] == TYPE_FAN:
                            new_unique_id = udid + "_" + str(key_id) + "_tile_fan"
                        if tiles[key_id][CONF_TYPE] == TYPE_VALVE:
                            new_unique_id = udid + "_" + str(key_id) + "_tile_valve"
                        if tiles[key_id][CONF_TYPE] == TYPE_MIXING_VALVE:
                            new_unique_id = (
                                udid + "_" + str(key_id) + "_tile_mixing_valve"
                            )
                        if tiles[key_id][CONF_TYPE] == TYPE_FUEL_SUPPLY:
                            new_unique_id = (
                                udid + "_" + str(key_id) + "_tile_fuel_supply"
                            )
                        if tiles[key_id][CONF_TYPE] == TYPE_TEXT:
                            new_unique_id = udid + "_" + str(key_id) + "_tile_text"
                    except (KeyError, StopIteration):
                        continue

            # so now we are left with regular zone sensors
            elif entity_id.startswith("climate."):
                zone_id = next(
                    k
                    for k, v in zones.items()
                    if v["description"]["name"] == original_name
                )
                new_unique_id = udid + "_" + str(zone_id) + "_zone_climate"

            elif entity_id.startswith("sensor"):
                if entity_id.endswith("battery"):
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"]
                        == original_name[: original_name.find(" battery")]
                    )
                    new_unique_id = udid + "_" + str(zone_id) + "_zone_battery"
                elif entity_id.endswith("out_temperature"):
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"]
                        == original_name[: original_name.find(" out_temperature")]
                    )
                    new_unique_id = udid + "_" + str(zone_id) + "_zone_out_temperature"
                elif entity_id.endswith("humidity"):
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"]
                        == original_name[: original_name.find(" humidity")]
                    )
                    new_unique_id = udid + "_" + str(zone_id) + "_zone_humidity"
                elif entity_id.endswith("temperature"):
                    zone_id = next(
                        k
                        for k, v in zones.items()
                        if v["description"]["name"]
                        == original_name[: original_name.find(" Temperature")]
                    )
                    new_unique_id = udid + "_" + str(zone_id) + "_zone_temperature"
                # this is not a zone sensor
                else:
                    continue

            # finally update the unique id
            _LOGGER.debug(
                "🕵️‍♀️ Finaly updating: %s with: %s",
                old_entity_entry.unique_id,
                new_unique_id,
            )

            entity_registry.async_update_entity(
                old_entity_entry.entity_id, new_unique_id=new_unique_id
            )

        _LOGGER.info(
            "Migration to version %s successful",
            str(version) + "." + str(minor_version),
        )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    unload_ok = all(
        await asyncio.gather(
            *[
                hass.config_entries.async_forward_entry_unload(entry, component)
                for component in PLATFORMS
            ]
        )
    )
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class TechCoordinator(DataUpdateCoordinator):
    """TECH API data update coordinator."""

    config_entry: ConfigEntry

    def __init__(
        self, hass: HomeAssistant, session: ClientSession, user_id: str, token: str
    ) -> None:
        """Initialize my coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            # Name of the data. For logging purposes.
            name=DOMAIN,
            # Polling interval. Will only be polled if there are subscribers.
            update_interval=SCAN_INTERVAL,
        )
        self.api = Tech(session, user_id, token)

    async def _async_update_data(self):
        """Fetch data from TECH API endpoint(s)."""

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


def get_substring_until_last_digit(string: str) -> str:
    """Extract a substring from a given string up to the last digit.

    Args:
        string (str): The string to extract the substring from.

    Returns:
        str: The extracted substring.

    """
    # Reverse the string
    reversed_string = string[::-1]

    # Find the index of the first digit from the end (last digit in the original string)
    first_digit_from_end_index = next(
        (i for i, char in enumerate(reversed_string) if char.isdigit()), None
    )

    if first_digit_from_end_index is None:
        # No digit found, return the original string
        return string
    else:
        # Calculate the index of the last digit in the original string
        last_digit_index = len(string) - first_digit_from_end_index - 1

        # Check if the last digit is at the end
        if last_digit_index == len(string) - 1:
            # Extract the substring up to the last digit and remove trailing whitespace
            substring = string[:last_digit_index].rstrip()
            return substring
        else:
            # Digit is not at the end, return the original string
            return string
