"""The Tech Controllers integration."""
import asyncio
import logging
import re
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

    if config_entry.version == 1:
        await migrate_version_1(hass, config_entry)
    elif config_entry.version == 2 and config_entry.minor_version == 1:
        await migrate_version_2_1(hass, config_entry)

    _LOGGER.info("Migration successful")
    return True


async def migrate_version_1(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate from version 1."""
    device_registry = dr.async_get(hass)
    entity_registry = er.async_get(hass)

    udid = config_entry.data[UDID]
    version = 2
    minor_version = 2

    http_session = async_get_clientsession(hass)
    api = Tech(http_session, config_entry.data[USER_ID], config_entry.data[CONF_TOKEN])
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

    # Store existing entity entries:
    old_entity_entries = {
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
            identifiers={(DOMAIN, udid + "_" + str(zone[CONF_ZONE][CONF_ID]))},
            manufacturer=MANUFACTURER,
            name=zone[CONF_DESCRIPTION][CONF_NAME],
            model=controller[CONF_NAME] + ": " + controller[VER],
        )

    remaining_entities_to_remove = {
        entry.unique_id: entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    }

    await update_and_link_entities(
        hass,
        config_entry,
        udid,
        zones,
        old_entity_entries,
        entity_registry,
        remaining_entities_to_remove,
    )

    await remove_remaining_entities(entity_registry, remaining_entities_to_remove)

    return True


async def migrate_version_2_1(hass: HomeAssistant, config_entry: ConfigEntry):
    """Migrate from version 2.1."""
    entity_registry = er.async_get(hass)

    udid = config_entry.data[CONTROLLER][UDID]
    version = 2
    minor_version = 2

    http_session = async_get_clientsession(hass)
    api = Tech(http_session, config_entry.data[USER_ID], config_entry.data[CONF_TOKEN])
    await assets.load_subtitles(hass.config.language, api)

    api.modules.setdefault(udid, {"last_update": None, "zones": {}, "tiles": {}})
    zones = await api.get_module_zones(udid)
    tiles = await api.get_module_tiles(udid)

    # Store existing entity entries:
    old_entity_entries = {
        entry.unique_id: entry
        for entry in er.async_entries_for_config_entry(
            entity_registry, config_entry.entry_id
        )
    }

    # Update config entry
    hass.config_entries.async_update_entry(
        config_entry,
        unique_id=udid,
        version=version,
        minor_version=minor_version,
    )

    # Update device idenfiers
    await update_device_identifiers(hass, config_entry, udid, zones)

    # Update entities with new unique ids
    await update_entities(
        hass,
        config_entry,
        udid,
        zones,
        tiles,
        old_entity_entries,
        entity_registry,
    )

    return True


async def update_entities(
    hass,
    config_entry,
    udid,
    zones,
    tiles,
    old_entity_entries,
    entity_registry,
):
    """Update entities."""

    for unique_id, old_entity_entry in old_entity_entries.items():
        entity_id = old_entity_entry.entity_id
        original_name = old_entity_entry.original_name
        _LOGGER.debug(
            "update_entities, old unique id: %s, entity_id: %s, original_name: %s",
            unique_id,
            entity_id,
            original_name,
        )

        new_unique_id = await get_new_unique_id(
            hass,
            config_entry,
            udid,
            zones,
            tiles,
            old_entity_entry,
            entity_id,
            original_name,
        )

        if new_unique_id:
            entity_registry.async_update_entity(
                old_entity_entry.entity_id, new_unique_id=new_unique_id
            )


async def update_and_link_entities(
    hass,
    config_entry,
    udid,
    zones,
    old_entity_entries,
    entity_registry,
    remaining_entities_to_remove=None,
):
    """Update and link entities to devices."""
    _LOGGER.debug(
        "update_and_link_entities, config_entry: %s, udid: %s, entity_registry: %s",
        config_entry,
        udid,
        entity_registry,
    )

    if remaining_entities_to_remove is None:
        remaining_entities_to_remove: dict[str, er.RegistryEntry] = {
            entry.unique_id: entry
            for entry in er.async_entries_for_config_entry(
                entity_registry, config_entry.entry_id
            )
        }

    for unique_id, old_entity_entry in old_entity_entries.items():
        entity_id = old_entity_entry.entity_id
        original_name = old_entity_entry.original_name
        _LOGGER.debug(
            "update_and_link_entities, old unique id: %s, entity_id: %s, original_name: %s",
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
                if entity_id.startswith("climate."):
                    new_unique_id = udid + "_" + str(zone_id) + "_climate"
                else:
                    zone_id, suffix = get_zone_id_and_suffix(
                        "sensor", entity_id, original_name, zones
                    )
                    new_unique_id = get_unique_id(udid, zone_id=zone_id, suffix=suffix)
            except StopIteration:
                new_unique_id = None
                continue

        if new_unique_id:
            _LOGGER.debug("update_and_link_entities, new unique id: %s", new_unique_id)
            device = await link_entity_to_device(
                hass, old_entity_entry, remaining_entities_to_remove
            )
            entity_registry.async_update_entity(
                old_entity_entry.entity_id,
                area_id=old_entity_entry.area_id,
                device_class=old_entity_entry.device_class,
                disabled_by=old_entity_entry.disabled_by,
                hidden_by=old_entity_entry.hidden_by,
                icon=old_entity_entry.icon,
                name=old_entity_entry.name,
                new_entity_id=old_entity_entry.entity_id,
                new_unique_id=new_unique_id,
                unit_of_measurement=old_entity_entry.unit_of_measurement,
                device_id=device.id if device else None,
            )


async def get_new_unique_id(
    hass,
    config_entry,
    udid,
    zones,
    tiles,
    old_entity_entry,
    entity_id,
    original_name,
):
    """Get the new unique ID for the entity."""
    if entity_id.startswith("binary_sensor"):
        return await get_new_unique_id_for_binary_sensor(udid, tiles, original_name)

    if entity_id.startswith("sensor"):
        if not entity_id.endswith(
            ("battery", "out_temperature", "humidity", "temperature")
        ):
            return await get_new_unique_id_for_tile_sensor(
                udid, tiles, old_entity_entry, original_name
            )

    elif entity_id.startswith("climate."):
        zone_id = next(
            k for k, v in zones.items() if v["description"]["name"] == original_name
        )
        return udid + "_" + str(zone_id) + "_zone_climate"

    zone_id, suffix = get_zone_id_and_suffix("sensor", entity_id, original_name, zones)
    return get_unique_id(udid=udid, zone_id=zone_id, suffix=suffix)


def get_zone_id_and_suffix(start, entity_id, original_name, zones):
    """Get zone id and suffix to create new unique iq."""
    if entity_id.startswith(start):
        for suffix, pattern in [
            ("battery", r" battery$"),
            ("out_temperature", r" out_temperature$"),
            ("humidity", r" humidity$"),
            ("temperature", r" Temperature$"),
        ]:
            match = re.search(pattern, original_name)
            if match:
                zone_id = next(
                    (
                        k
                        for k, v in zones.items()
                        if v["description"]["name"] == original_name[: match.start()]
                    ),
                    None,
                )
                if zone_id is not None:
                    return zone_id, suffix
    return None, None


def get_unique_id(udid, zone_id, suffix):
    """Build new uniuque ID from zone id and suffix."""
    if zone_id is not None and suffix is not None:
        return f"{udid}_{zone_id}_zone_{suffix}"
    return None


async def get_new_unique_id_for_binary_sensor(udid, tiles, original_name):
    """Get the new unique ID for a binary sensor entity."""
    txt_id = assets.get_id_from_text(original_name)
    _LOGGER.debug("get_new_unique_id_for_binary_sensor, txtid: %s", txt_id)

    try:
        key_id = next(
            (k for k, v in tiles.items() if v[CONF_PARAMS].get("txtId") == txt_id),
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
            _LOGGER.debug(
                "get_new_unique_id_for_binary_sensor, tile_type: %s", tile_type
            )
            key_id = next(
                (k for k, v in tiles.items() if v[CONF_TYPE] == tile_type),
                None,
            )
            _LOGGER.debug("get_new_unique_id_for_binary_sensor, key_id: %s", key_id)
        return udid + "_" + str(key_id) + "_tile_binary_sensor"
    except (KeyError, StopIteration):
        return None


async def get_new_unique_id_for_tile_sensor(
    udid, tiles, old_entity_entry, original_name
):
    """Get the new unique ID for a tile sensor entity."""
    # no unique reverse lookup if we had missing title from API 😥
    if "txtId" in original_name:
        if old_entity_entry.original_device_class == "temperature":
            return udid + "_" + str(uuid.uuid4().hex) + "_tile_temperature"
        else:
            return udid + "_" + str(uuid.uuid4().hex) + "_tile_sensor"
    else:
        _LOGGER.debug(
            "get_new_unique_id_for_tile_sensor, original_name: %s", original_name
        )
        txt_id = assets.get_id_from_text(original_name)
        _LOGGER.debug("get_new_unique_id_for_tile_sensor, txtid: %s", txt_id)

        try:
            key_id = next(
                (k for k, v in tiles.items() if v[CONF_PARAMS].get("txtId") == txt_id),
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
                tile_type = assets.get_id_from_type(txt_id)
                _LOGGER.debug(
                    "get_new_unique_id_for_tile_sensor, tile_type: %s", tile_type
                )
                key_id = next(
                    (k for k, v in tiles.items() if v[CONF_TYPE] == tile_type),
                    None,
                )
                _LOGGER.debug("get_new_unique_id_for_tile_sensor, key_id: %s", key_id)

            if tiles[key_id][CONF_TYPE] == TYPE_TEMPERATURE:
                return udid + "_" + str(key_id) + "_tile_temperature"
            if tiles[key_id][CONF_TYPE] == TYPE_TEMPERATURE_CH:
                return udid + "_" + str(key_id) + "_tile_widget"
            if tiles[key_id][CONF_TYPE] == TYPE_FAN:
                return udid + "_" + str(key_id) + "_tile_fan"
            if tiles[key_id][CONF_TYPE] == TYPE_VALVE:
                return udid + "_" + str(key_id) + "_tile_valve"
            if tiles[key_id][CONF_TYPE] == TYPE_MIXING_VALVE:
                return udid + "_" + str(key_id) + "_tile_mixing_valve"
            if tiles[key_id][CONF_TYPE] == TYPE_FUEL_SUPPLY:
                return udid + "_" + str(key_id) + "_tile_fuel_supply"
            if tiles[key_id][CONF_TYPE] == TYPE_TEXT:
                return udid + "_" + str(key_id) + "_tile_text"
        except (KeyError, StopIteration):
            return None


async def link_entity_to_device(hass, old_entity_entry, remaining_entities_to_remove):
    """Link the entity to the corresponding device."""
    device_registry = dr.async_get(hass)
    if old_entity_entry.original_name:
        device = device_registry.async_get_device(
            {(DOMAIN, old_entity_entry.original_name)},
            set(),
        )
        if device and device.name == old_entity_entry.original_name:
            del remaining_entities_to_remove[old_entity_entry.entity_id]
            return device
    return None


async def update_device_identifiers(hass, config_entry, udid, zones):
    """Update device identifiers for the new version."""
    device_registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(device_registry, config_entry.entry_id)

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
                new_identifiers={(DOMAIN, udid + "_" + str(zone_id))},
            )


async def remove_remaining_entities(entity_registry, remaining_entities_to_remove):
    """Remove the remaining entities that are no longer provided by the integration."""
    for entity_to_remove in remaining_entities_to_remove:
        entity_registry.async_remove(
            remaining_entities_to_remove[entity_to_remove].entity_id
        )


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
