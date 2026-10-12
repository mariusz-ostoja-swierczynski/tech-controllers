"""Platform for button entities backed by Tech menu dialogue parameters."""

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.const import (
    ATTR_IDENTIFIERS,
    ATTR_MANUFACTURER,
    ATTR_SW_VERSION,
    CONF_NAME,
    EntityCategory,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import assets
from .const import (
    CONTROLLER,
    DOMAIN,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    MENU_DEPTH_DEFAULT_ENABLED_LIMIT,
    MENU_DEPTH_REGISTRATION_LIMIT,
    MENU_ITEM_TYPE_DIALOGUE,
    UDID,
)
from .coordinator import TechConfigEntry, TechCoordinator
from .entity import ReportedEntity

_LOGGER = logging.getLogger(__name__)

# A dialogue writes to the same cloud account as everything else this
# controller exposes, so its presses are serialised. Home Assistant reads
# PARALLEL_UPDATES from the platform module.
PARALLEL_UPDATES = 1


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: TechConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Tech button entities from menu dialogue parameters.

    Args:
        hass: Home Assistant instance.
        config_entry: Integration entry containing controller data.
        async_add_entities: Callback to register entities with Home Assistant.

    """
    controller = config_entry.data[CONTROLLER]
    coordinator: TechCoordinator = config_entry.runtime_data
    controller_udid = controller[UDID]

    menus = await coordinator.api.get_module_menus(controller_udid)
    zones = await coordinator.api.get_module_zones(controller_udid)
    ctx = assets.build_menu_context(menus, zones, coordinator.translations)
    zone_names = assets.build_zone_names(
        zones,
        config_entry.title,
        config_entry.options.get(INCLUDE_HUB_IN_NAME, False),
    )

    entities: list[MenuButtonEntity] = []
    for key, item in menus.items():
        if item.get("type") != MENU_ITEM_TYPE_DIALOGUE:
            continue
        # Skip items deeper than the registration limit -- L-12 has 600+
        # DIALOGUE items, mostly per-zone "reset to factory" buttons.
        if ctx.depths[key] > MENU_DEPTH_REGISTRATION_LIMIT:
            continue
        entities.append(
            MenuButtonEntity(
                item,
                key,
                coordinator,
                config_entry,
                ctx.group_names,
                depth=ctx.depths[key],
                zone_id=ctx.zone_assignments.get(key),
                zone_names=zone_names,
            )
        )

    async_add_entities(entities, True)


class MenuButtonEntity(
    ReportedEntity, CoordinatorEntity[TechCoordinator], ButtonEntity
):
    """A dialogue menu parameter exposed as a Home Assistant button entity."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        item: dict[str, Any],
        menu_key: str,
        coordinator: TechCoordinator,
        config_entry: TechConfigEntry,
        group_names: dict[tuple[str, int], str],
        depth: int = 0,
        zone_id: int | None = None,
        zone_names: dict[int, str] | None = None,
    ) -> None:
        """Initialise a menu button entity.

        Args:
            item: Menu item payload returned by the Tech API.
            menu_key: Unique key identifying this menu item (e.g. ``MU_250``).
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.
            group_names: Mapping of ``(menu_type, group_id)`` to group label.
            depth: Nesting depth of this item in the Tech menu tree
                (0 = top-level). Drives ``entity_registry_enabled_default``.
            zone_id: Optional zone ID to associate this entity with a zone device.
            zone_names: Mapping of zone ID to zone device name, used to name
                the zone device when ``zone_id`` is set.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._coordinator = coordinator
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._menu_key = menu_key
        self._item_id = item["id"]
        self._menu_type = item["menuType"]
        self._unique_id = f"{self._udid}_menu_{menu_key}"
        self.manufacturer = MANUFACTURER
        self._zone_id = zone_id
        # Explicit zone device name -- without it the device registry falls back
        # to the config entry title and changes composed entity names; see
        # https://developers.home-assistant.io/blog/2026/08/24/device-registry-follow-up-changes
        # (core PR #179397).
        self._zone_name = assets.resolve_zone_device_name(
            zone_names, zone_id, config_entry.title
        )

        # ``_attr_has_entity_name = True`` lets HA prepend the device name; the
        # entity name itself is the menu label only.
        self._name = assets.menu_entity_name(
            item, group_names, coordinator.translations
        )

        self._disabled = depth > MENU_DEPTH_DEFAULT_ENABLED_LIMIT

        self._update_from_item(item)

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def name(self) -> str:
        """Return the display name of this entity."""
        return self._name

    @property
    def entity_registry_enabled_default(self) -> bool:
        """Return whether the entity should be enabled by default."""
        return not self._disabled

    @property
    def available(self) -> bool:
        """Return whether the entity is available.

        ``CoordinatorEntity`` reports whether the last poll reached the
        controller; a dialogue the controller has withdrawn is unavailable on
        top of that, so that Home Assistant never offers an action the
        controller would refuse.
        """
        return super().available and self._item_accessible

    @property
    def source_key(self) -> str:
        """Return the menu item this entity was built from."""
        return f"menu_{self._menu_key}"

    @property
    def device_info(self) -> DeviceInfo | None:
        """Return device info for the zone or controller this entity belongs to."""
        if self._zone_id is not None:
            return {
                ATTR_IDENTIFIERS: {(DOMAIN, f"{self._udid}_{self._zone_id}")},
                CONF_NAME: self._zone_name,
                "model": assets.controller_model(self._config_entry),
                ATTR_SW_VERSION: assets.controller_firmware(self._config_entry),
                ATTR_MANUFACTURER: self.manufacturer,
                **assets.via_controller(self.coordinator),
            }
        return {
            ATTR_IDENTIFIERS: {(DOMAIN, self._udid)},
            CONF_NAME: self._config_entry.title,
            "model": assets.controller_model(self._config_entry),
            ATTR_SW_VERSION: assets.controller_firmware(self._config_entry),
            ATTR_MANUFACTURER: self.manufacturer,
        }

    def _update_from_item(self, item: dict[str, Any]) -> None:
        """Refresh entity properties from the menu item payload.

        Args:
            item: Menu item dictionary with the most recent values.

        """
        # The controller offers or withdraws a dialogue -- a lockout control is
        # only there while there is a lockout to clear -- so the flag is kept
        # beside the coordinator's own state and combined in ``available``.
        self._item_accessible = item.get("access", False)
        # Dialogue type determines the API payload format
        params = item.get("params", {})
        self._dialogue_type = params.get("type", 0)

    async def async_press(self) -> None:
        """Handle the button press by triggering the dialogue action."""
        await self.coordinator.api.set_menu_value(
            self._udid,
            self._menu_type,
            self._item_id,
            {"type": self._dialogue_type, "value": 1},
        )
        await self.coordinator.async_request_refresh()

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        menus = self._coordinator.data.get("menus", {})
        item = menus.get(self._menu_key)
        if item:
            self._update_from_item(item)
        self.async_write_ha_state()
