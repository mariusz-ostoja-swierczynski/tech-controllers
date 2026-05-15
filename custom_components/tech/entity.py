"""Shared base entity helpers for Tech tile-derived devices."""

from abc import abstractmethod
import asyncio
from collections.abc import Callable
from datetime import datetime
import logging
from typing import Any

from homeassistant.const import CONF_DESCRIPTION, CONF_ID, CONF_PARAMS, CONF_TYPE
from homeassistant.core import callback
from homeassistant.helpers import entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import assets
from .const import (
    CONTROLLER,
    INCLUDE_HUB_IN_NAME,
    MANUFACTURER,
    OPTIMISTIC_POLL_INTERVAL,
    OPTIMISTIC_POLL_MAX_ATTEMPTS,
    OPTIMISTIC_TIMEOUT,
    UDID,
)
from .coordinator import TechCoordinator
from .tech import TechError

_LOGGER = logging.getLogger(__name__)


class TileEntity(
    CoordinatorEntity,
    entity.Entity,
):
    """Representation of a TileEntity."""

    _attr_has_entity_name = True

    def __init__(self, device, coordinator: TechCoordinator, config_entry) -> None:
        """Initialise common attributes for a Tech tile entity.

        Args:
            device: Tile payload returned by the Tech API.
            coordinator: Shared Tech data coordinator instance.
            config_entry: Config entry that owns the coordinator.

        """
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._udid = config_entry.data[CONTROLLER][UDID]
        self._id = device[CONF_ID]
        self._unique_id = f"{self._udid}_{device[CONF_ID]}"
        self._model = device[CONF_PARAMS].get(CONF_DESCRIPTION)
        self._state = self.get_state(device)
        self.manufacturer = MANUFACTURER
        txt_id = device[CONF_PARAMS].get("txtId")
        if self._config_entry.data[INCLUDE_HUB_IN_NAME]:
            self._name = self._config_entry.title + " "
        else:
            self._name = ""
        if txt_id:
            self._name += assets.get_text(txt_id)
        else:
            self._name += assets.get_text_by_type(device[CONF_TYPE])

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return self._unique_id

    @property
    def state(self):
        """Return the cached state reported by the Tech API."""
        return self._state

    @abstractmethod
    def get_state(self, device):
        """Extract the integration-specific state from ``device`` data."""
        raise NotImplementedError("Must override get_state")

    def update_properties(self, device):
        """Refresh entity attributes using the latest tile payload.

        Args:
            device: Tile dictionary with the most recent values.

        """
        # Update _state property
        self._state = self.get_state(device)

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Handle updated data from the coordinator."""
        self.update_properties(self.coordinator.data["tiles"][self._id])
        self.async_write_ha_state()


class OptimisticMenuMixin:
    """Mixin: optimistic write + ``duringChange`` long-poll confirm.

    Mixed into menu-backed entities (switch/number/select). Coordinates the
    fire-and-poll pattern documented for the eModul API:

    1. POST the new value via ``set_menu_value`` (validates ``status``).
    2. Apply the requested value locally and mark the entity as assumed.
    3. Spawn a background task that long-polls ``update/data`` until the
       controller flips ``duringChange`` from ``"t"`` to ``"f"``, then
       refreshes the entity from the authoritative payload.
    4. While the optimistic window is open, ``_handle_coordinator_update``
       drops stale ``duringChange:"t"`` snapshots so the entity doesn't
       flicker back to the previous value mid-transition.

    Subclasses must:

    * Inherit from ``CoordinatorEntity`` (provides ``self.coordinator``).
    * Define ``_menu_key``, ``_udid``, ``_menu_type``, ``_item_id``.
    * Implement ``_update_from_item(item)``.
    """

    _optimistic_until: datetime | None = None
    _attr_assumed_state: bool = False

    async def _async_set_menu_value(
        self,
        payload: dict[str, Any],
        apply_optimistic: Callable[[], None],
    ) -> None:
        """POST a menu value, then write optimistic state and spawn confirm.

        Args:
            payload: Request body for ``set_menu_value`` (typically
                ``{"value": int}``).
            apply_optimistic: Zero-arg callable that mutates the entity's
                ``_attr_*`` fields to reflect the requested value.

        """
        api = self.coordinator.api  # type: ignore[attr-defined]
        await api.set_menu_value(
            self._udid, self._menu_type, self._item_id, payload
        )
        apply_optimistic()
        self._optimistic_until = dt_util.utcnow() + OPTIMISTIC_TIMEOUT
        self._attr_assumed_state = True
        self.async_write_ha_state()  # type: ignore[attr-defined]
        self.hass.async_create_task(  # type: ignore[attr-defined]
            self._async_confirm_menu_change()
        )

    async def _async_confirm_menu_change(self) -> None:
        """Long-poll until the controller settles the change or budget runs out.

        Drives reconciliation via ``poll_update``. On success applies the
        authoritative payload and clears the assumed-state flag. On timeout
        or transport error falls back to ``async_request_refresh`` so the
        regular coordinator path resolves the final state.
        """
        api = self.coordinator.api  # type: ignore[attr-defined]
        cursor = api.last_update or ""
        for _ in range(OPTIMISTIC_POLL_MAX_ATTEMPTS):
            try:
                data = await api.poll_update(self._udid, cursor)
            except (TechError, asyncio.TimeoutError) as err:
                _LOGGER.debug(
                    "poll_update failed for %s: %s", self._menu_key, err
                )
                break
            cursor = data.get("lastUpdate") or cursor
            item = _find_menu_item(data, self._menu_type, self._item_id)
            if item and item.get("duringChange") == "f":
                self._update_from_item(item)
                self._clear_optimistic_state()
                self.async_write_ha_state()  # type: ignore[attr-defined]
                return
            await asyncio.sleep(OPTIMISTIC_POLL_INTERVAL)
        # Budget exhausted or transport error: clear the assumed flag and let
        # the coordinator's next refresh authoritatively reconcile.
        self._clear_optimistic_state()
        self.async_write_ha_state()  # type: ignore[attr-defined]
        self.hass.async_create_task(  # type: ignore[attr-defined]
            self.coordinator.async_request_refresh()  # type: ignore[attr-defined]
        )

    def _clear_optimistic_state(self) -> None:
        """Reset the optimistic window so coordinator updates flow normally."""
        self._optimistic_until = None
        self._attr_assumed_state = False

    def _is_optimistic_active(self) -> bool:
        """Return ``True`` while the controller is still expected to confirm."""
        return (
            self._optimistic_until is not None
            and dt_util.utcnow() < self._optimistic_until
        )

    @callback
    def _handle_coordinator_update(self, *args: Any) -> None:
        """Shared coordinator-update path for menu entities.

        While the optimistic window is open we drop stale ``duringChange:"t"``
        snapshots so the entity doesn't briefly revert to the previous value.
        Any other payload (settled, or out-of-window) clears the assumed flag
        and is applied authoritatively.
        """
        menus = self.coordinator.data.get("menus", {})  # type: ignore[attr-defined]
        item = menus.get(self._menu_key)
        if item is not None:
            if self._is_optimistic_active() and item.get("duringChange") == "t":
                return
            self._clear_optimistic_state()
            self._update_from_item(item)
        self.async_write_ha_state()  # type: ignore[attr-defined]


def _find_menu_item(
    data: dict[str, Any], menu_type: str, item_id: int
) -> dict[str, Any] | None:
    """Locate a menu item in an ``update/data`` poll response.

    The endpoint returns a ``menu`` array containing the entries that
    changed since the cursor; entries carry the original ``menuType`` and
    ``id`` fields, so we match on the pair.
    """
    for menu_item in data.get("menu", []) or []:
        if (
            isinstance(menu_item, dict)
            and menu_item.get("id") == item_id
            and menu_item.get("menuType") == menu_type
        ):
            return menu_item
    return None
