"""Tests for OptimisticMenuMixin behavior."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.tech.entity import OptimisticMenuMixin, _find_menu_item
from custom_components.tech.tech import TechError


class _StubEntity(OptimisticMenuMixin):
    """Minimal mixin host used to exercise the optimistic write path."""

    def __init__(self) -> None:
        self._udid = "udid1"
        self._menu_key = "MU_42"
        self._menu_type = "MU"
        self._item_id = 42

        self.api = MagicMock()
        self.api.set_menu_value = AsyncMock(return_value={"status": "success"})
        self.api.poll_update = AsyncMock()
        self.api.last_update = None

        self.coordinator = MagicMock()
        self.coordinator.api = self.api
        self.coordinator.data = {"menus": {}}
        self.coordinator.async_request_refresh = AsyncMock()

        self.hass = MagicMock()
        self.created_tasks: list[Any] = []
        self.hass.async_create_task = self.created_tasks.append

        self.write_calls = 0
        self.value: int | None = None

    def async_write_ha_state(self) -> None:
        self.write_calls += 1

    def _update_from_item(self, item: dict[str, Any]) -> None:
        self.value = item.get("params", {}).get("value")


@pytest.mark.asyncio
async def test_set_menu_value_applies_optimistic_and_spawns_confirm() -> None:
    """POST + optimistic apply + ``_attr_assumed_state`` + spawned task."""
    entity = _StubEntity()

    def apply() -> None:
        entity.value = 7

    await entity._async_set_menu_value({"value": 7}, apply)

    entity.api.set_menu_value.assert_awaited_once_with("udid1", "MU", 42, {"value": 7})
    assert entity.value == 7
    assert entity._attr_assumed_state is True
    assert entity._optimistic_until is not None
    assert entity.write_calls == 1
    assert len(entity.created_tasks) == 1

    # Close the spawned coroutine so we don't leak it.
    entity.created_tasks[0].close()


@pytest.mark.asyncio
async def test_confirm_settles_on_during_change_f() -> None:
    """Settled poll response updates from item and clears assumed flag."""
    entity = _StubEntity()
    entity._attr_assumed_state = True
    entity._optimistic_until = MagicMock()
    entity.api.poll_update.return_value = {
        "lastUpdate": "t1",
        "menu": [
            {
                "id": 42,
                "menuType": "MU",
                "duringChange": "f",
                "params": {"value": 9},
            }
        ],
    }

    await entity._async_confirm_menu_change()

    assert entity.value == 9
    assert entity._attr_assumed_state is False
    assert entity._optimistic_until is None
    assert entity.write_calls == 1
    entity.coordinator.async_request_refresh.assert_not_awaited()


@pytest.mark.asyncio
async def test_confirm_tech_error_retries_then_falls_back() -> None:
    """Transient transport errors are retried; budget exhaustion refreshes."""
    entity = _StubEntity()
    entity._attr_assumed_state = True
    entity._optimistic_until = MagicMock()
    entity.api.poll_update.side_effect = TechError(520, "no modules")

    with patch(
        "custom_components.tech.entity.asyncio.sleep", new=AsyncMock()
    ) as mock_sleep:
        await entity._async_confirm_menu_change()

    # All attempts retried instead of breaking on first error.
    # Sleep count = 1 initial delay + 12 retry sleeps.
    assert entity.api.poll_update.await_count == 12
    assert mock_sleep.await_count == 13
    assert entity._attr_assumed_state is False
    assert entity._optimistic_until is None
    # Fallback path: queue a coordinator refresh task.
    assert len(entity.created_tasks) == 1


@pytest.mark.asyncio
async def test_confirm_budget_exhaustion_triggers_refresh() -> None:
    """When the controller never settles we eventually request a refresh."""
    entity = _StubEntity()
    entity._attr_assumed_state = True
    entity._optimistic_until = MagicMock()
    entity.api.poll_update.return_value = {
        "lastUpdate": "t",
        "menu": [
            {
                "id": 42,
                "menuType": "MU",
                "duringChange": "t",
                "params": {"value": 1},
            }
        ],
    }

    with patch(
        "custom_components.tech.entity.asyncio.sleep", new=AsyncMock()
    ) as mock_sleep:
        await entity._async_confirm_menu_change()

    assert mock_sleep.await_count >= 1
    assert entity._attr_assumed_state is False
    assert entity._optimistic_until is None
    assert len(entity.created_tasks) == 1


@pytest.mark.asyncio
async def test_handle_update_drops_all_coord_ticks_while_window_active() -> None:
    """Coordinator tick during the optimistic window is dropped entirely.

    The coordinator's regular menu fetch does NOT carry ``duringChange``, so
    we cannot rely on that flag to filter stale snapshots. Drop every update
    while the window is open and let the confirm task settle.
    """
    entity = _StubEntity()
    entity.value = 7
    entity._attr_assumed_state = True
    from datetime import timedelta

    from homeassistant.util import dt as dt_util

    entity._optimistic_until = dt_util.utcnow() + timedelta(seconds=60)
    # Coordinator menu cache lacks ``duringChange`` (real-world payload).
    entity.coordinator.data = {
        "menus": {
            "MU_42": {
                "id": 42,
                "menuType": "MU",
                "params": {"value": 0},
            }
        }
    }

    entity._handle_coordinator_update()

    assert entity.value == 7
    assert entity._attr_assumed_state is True
    assert entity.write_calls == 0


@pytest.mark.asyncio
async def test_handle_update_applies_after_window_expires() -> None:
    """Out-of-window coordinator updates apply authoritatively."""
    entity = _StubEntity()
    entity._optimistic_until = None
    entity.coordinator.data = {
        "menus": {
            "MU_42": {
                "id": 42,
                "menuType": "MU",
                "params": {"value": 12},
            }
        }
    }

    entity._handle_coordinator_update()

    assert entity.value == 12
    assert entity.write_calls == 1


@pytest.mark.asyncio
async def test_confirm_cancellation_clears_optimistic_state() -> None:
    """Cancellation (re-toggle / shutdown) must clear ``pending_confirm``."""
    entity = _StubEntity()
    entity._attr_assumed_state = True
    entity._optimistic_until = MagicMock()
    entity.api.poll_update.side_effect = asyncio.CancelledError()

    with patch("custom_components.tech.entity.asyncio.sleep", new=AsyncMock()):
        with pytest.raises(asyncio.CancelledError):
            await entity._async_confirm_menu_change()

    assert entity._attr_assumed_state is False
    assert entity._optimistic_until is None


def test_find_menu_item_matches_type_and_id() -> None:
    """Helper matches ``menuType`` and ``id`` simultaneously."""
    data = {
        "menu": [
            {"id": 1, "menuType": "MU"},
            {"id": 42, "menuType": "MI"},
            {"id": 42, "menuType": "MU", "duringChange": "f"},
        ]
    }
    assert _find_menu_item(data, "MU", 42) == {
        "id": 42,
        "menuType": "MU",
        "duringChange": "f",
    }
    assert _find_menu_item(data, "MS", 42) is None
    assert _find_menu_item({}, "MU", 42) is None
    assert _find_menu_item({"menu": None}, "MU", 42) is None
