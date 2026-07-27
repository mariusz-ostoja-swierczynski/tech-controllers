"""Unit tests for :mod:`custom_components.tech.select_recuperator`.

Tests cover ``MenuFanSpeedSelectEntity`` and its ``async_setup_entry`` gate.
"""

from __future__ import annotations

import copy
import importlib.util
import logging
import pathlib
import sys
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ============================================================================
# Load the real target module: ``custom_components.tech.select_recuperator``
# ============================================================================

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"

# Register parent packages so relative imports inside *.tech.* resolve.
for _pkg_name, _pkg_path in (
    ("custom_components", _REPO_ROOT / "custom_components"),
    ("custom_components.tech", _TECH_DIR),
):
    if _pkg_name not in sys.modules:
        _pkg_mod = types.ModuleType(_pkg_name)
        _pkg_mod.__path__ = [str(_pkg_path)]
        sys.modules[_pkg_name] = _pkg_mod

# Load const.py (select_recuperator.py does ``from .const import …``).
if "custom_components.tech.const" not in sys.modules:
    _const_spec = importlib.util.spec_from_file_location(
        "custom_components.tech.const", _TECH_DIR / "const.py"
    )
    _const_mod = importlib.util.module_from_spec(_const_spec)
    if _const_spec.loader is not None:
        _const_spec.loader.exec_module(_const_mod)
    sys.modules["custom_components.tech.const"] = _const_mod

# Stub coordinator.py (select_recuperator.py imports ``TechCoordinator`` as a
# type hint, and accesses ``coordinator.api`` / ``.data`` / ``.translations``
# at runtime through mocks -- no need for the real class).
if "custom_components.tech.coordinator" not in sys.modules:
    _coord_stub = types.ModuleType("custom_components.tech.coordinator")

    class _TechCoordinatorStub:
        """Stand-in for ``TechCoordinator`` -- all attributes are mocks."""

        api: Any = None
        data: dict[str, Any] = {}
        translations: Any = None
        hass: Any = None
        config_entry: Any = None

    _coord_stub.TechCoordinator = _TechCoordinatorStub
    sys.modules["custom_components.tech.coordinator"] = _coord_stub

# Finally load the module under test.
_select_rec_spec = importlib.util.spec_from_file_location(
    "custom_components.tech.select_recuperator",
    _TECH_DIR / "select_recuperator.py",
)
_select_rec_mod = importlib.util.module_from_spec(_select_rec_spec)
if _select_rec_spec.loader is not None:
    _select_rec_spec.loader.exec_module(_select_rec_mod)
sys.modules["custom_components.tech.select_recuperator"] = _select_rec_mod

# Bring the public symbols into the test namespace.
async_setup_entry = _select_rec_mod.async_setup_entry
MenuFanSpeedSelectEntity = _select_rec_mod.MenuFanSpeedSelectEntity

# Shorter alias for the const-level values used in these tests.
from custom_components.tech.const import CONTROLLER, DOMAIN, UDID  # noqa: E402

# ============================================================================
# Fixture data  (from issue #201 JSON.txt)
# ============================================================================

MU_2070_FIXTURE: dict[str, Any] = {
    "menuType": "MU",
    "type": 11,
    "id": 2070,
    "parentId": 0,
    "access": False,
    "txtId": 459,
    "params": {
        "value": 1,
        "default": 0,
        "options": [
            {"txtId": 422, "value": 0},
            {"txtId": 423, "value": 1},
            {"txtId": 424, "value": 2},
            {"txtId": 1620, "value": 3},
        ],
    },
    "duringChange": "f",
}

# Translated labels -- each txtId maps to a short human-readable string as the
# real API would provide.
_TX: dict[int, str] = {
    459: "Fan speed",  # entity name
    422: "Stop",
    423: "Low",
    424: "Medium",
    1620: "High",
}


class _FakeTranslations:
    """A ``translations`` stand-in with dict-backed ``get_text``.

    Tests can override individual lookups by mutating ``store``.
    """

    def __init__(self) -> None:
        self.store: dict[int, str | None] = dict(_TX)

    def get_text(self, txt_id: int) -> str | None:
        return self.store.get(txt_id)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def coordinator() -> MagicMock:
    """Return a mocked ``TechCoordinator``-like object."""
    coord = MagicMock()
    coord.api = AsyncMock()
    coord.data = {"menus": {"MU_2070": copy.deepcopy(MU_2070_FIXTURE)}}
    coord.translations = _FakeTranslations()
    return coord


@pytest.fixture
def config_entry() -> MagicMock:
    """Return a mocked ``ConfigEntry``-like object."""
    entry = MagicMock()
    entry.data = {CONTROLLER: {UDID: "test_udid_001"}}
    entry.entry_id = "entry_1"
    entry.title = "Test Controller"
    return entry


@pytest.fixture
def hass(coordinator: MagicMock, config_entry: MagicMock) -> MagicMock:
    """Return a mocked ``HomeAssistant``-like object."""
    hass_mock = MagicMock()
    hass_mock.data = {DOMAIN: {config_entry.entry_id: coordinator}}
    return hass_mock


@pytest.fixture
def async_add_entities() -> MagicMock:
    """Return a mocked ``AddEntitiesCallback``."""
    return MagicMock()


@pytest.fixture
def entity(coordinator: MagicMock, config_entry: MagicMock) -> MenuFanSpeedSelectEntity:
    """Return a fully-initialised ``MenuFanSpeedSelectEntity``."""
    item = copy.deepcopy(MU_2070_FIXTURE)
    ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
    ent.hass = MagicMock()
    ent.entity_id = "select.test_fan_speed"
    ent.async_write_ha_state = MagicMock()
    return ent


# ============================================================================
# Tests
# ============================================================================


class TestAsyncSetupEntry:
    """Tests for the ``async_setup_entry`` platform gate."""

    async def test_creates_entity_when_menu_item_present(
        self,
        hass: MagicMock,
        config_entry: MagicMock,
        async_add_entities: MagicMock,
        coordinator: MagicMock,
    ) -> None:
        """``async_setup_entry`` creates one entity when ``MU_2070`` exists."""
        coordinator.api.get_module_menus.return_value = {"MU_2070": MU_2070_FIXTURE}

        await async_setup_entry(hass, config_entry, async_add_entities)

        async_add_entities.assert_called_once()
        (entities_list, _update_before_add), _ = async_add_entities.call_args
        assert len(entities_list) == 1
        assert isinstance(entities_list[0], MenuFanSpeedSelectEntity)

    async def test_logs_warning_when_menu_item_missing(
        self,
        hass: MagicMock,
        config_entry: MagicMock,
        async_add_entities: MagicMock,
        coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When ``MU_2070`` is absent a warning is logged and no entities are created."""
        coordinator.api.get_module_menus.return_value = {}

        with caplog.at_level(logging.WARNING, logger="custom_components.tech.select_recuperator"):
            await async_setup_entry(hass, config_entry, async_add_entities)

        assert "MU_2070" in caplog.text
        assert "not found" in caplog.text
        async_add_entities.assert_not_called()

    # ------------------------------------------------------------------
    # Parameter validation guards
    # ------------------------------------------------------------------

    async def test_api_call_receives_correct_udid(
        self,
        hass: MagicMock,
        config_entry: MagicMock,
        async_add_entities: MagicMock,
        coordinator: MagicMock,
    ) -> None:
        """The UDID passed to ``get_module_menus`` must match the config entry."""
        coordinator.api.get_module_menus.return_value = {"MU_2070": MU_2070_FIXTURE}

        await async_setup_entry(hass, config_entry, async_add_entities)

        coordinator.api.get_module_menus.assert_awaited_once_with("test_udid_001")


class TestMenuFanSpeedSelectEntity:
    """Tests for the ``MenuFanSpeedSelectEntity`` class."""

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def test_init_sets_unique_id(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """``unique_id`` mirrors the UDID and menu key."""
        assert entity.unique_id == "test_udid_001_menu_MU_2070"

    def test_init_sets_name(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """``name`` is the txtId 459 translation."""
        assert entity.name == "Fan speed"

    def test_init_sets_options(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """``options`` reflects the translated fixture option labels."""
        assert entity._attr_options == ["Stop", "Low", "Medium", "High"]

    def test_init_sets_current_option(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """``current_option`` matches the fixture's current ``value`` (=1 → "Low")."""
        assert entity.current_option == "Low"

    def test_init_sets_entity_attributes(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """Class-level entity attributes are set as expected."""
        assert entity._attr_has_entity_name is True
        assert entity._attr_entity_category == "config"
        assert entity._attr_icon == "mdi:fan"

    # ------------------------------------------------------------------
    # ``async_select_option``
    # ------------------------------------------------------------------

    async def test_async_select_option_calls_set_menu_value(
        self, entity: MenuFanSpeedSelectEntity, coordinator: MagicMock
    ) -> None:
        """Selecting a valid option calls ``set_menu_value`` with the right params."""
        coordinator.api.set_menu_value = AsyncMock()

        await entity.async_select_option("High")

        coordinator.api.set_menu_value.assert_awaited_once_with(
            "test_udid_001", "MU", 2070, {"value": 3}
        )

    async def test_async_select_option_optimistic_update(
        self, entity: MenuFanSpeedSelectEntity, coordinator: MagicMock
    ) -> None:
        """After a successful select the entity optimistically reflects the choice."""
        coordinator.api.set_menu_value = AsyncMock()

        await entity.async_select_option("Medium")

        assert entity.current_option == "Medium"

    async def test_async_select_option_unknown_logs_warning(
        self,
        entity: MenuFanSpeedSelectEntity,
        coordinator: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Selecting an unknown option logs a warning and does not crash."""
        coordinator.api.set_menu_value = AsyncMock()
        previous = entity.current_option

        with caplog.at_level(logging.WARNING, logger="custom_components.tech.select_recuperator"):
            await entity.async_select_option("Bogus")

        assert "Unknown option Bogus" in caplog.text
        coordinator.api.set_menu_value.assert_not_called()
        # Current option must remain unchanged.
        assert entity.current_option == previous

    # ------------------------------------------------------------------
    # ``_handle_coordinator_update``
    # ------------------------------------------------------------------

    def test_handle_coordinator_update_reflects_new_value(
        self, entity: MenuFanSpeedSelectEntity, coordinator: MagicMock
    ) -> None:
        """When coordinator data changes, the entity picks up the new value."""
        coordinator.data["menus"]["MU_2070"]["params"]["value"] = 2

        entity._handle_coordinator_update()

        assert entity.current_option == "Medium"

    def test_handle_coordinator_update_missing_menu_does_not_crash(
        self, entity: MenuFanSpeedSelectEntity, coordinator: MagicMock
    ) -> None:
        """When the menu item vanishes the update handler silently no-ops."""
        coordinator.data["menus"] = {}

        # Should not raise.
        entity._handle_coordinator_update()

        # Current option remains whatever was set during init.
        assert entity.current_option == "Low"

    # ------------------------------------------------------------------
    # ``device_info``
    # ------------------------------------------------------------------

    def test_device_info_contains_identifiers_name_manufacturer(
        self, entity: MenuFanSpeedSelectEntity
    ) -> None:
        """``device_info`` returns the expected dict."""
        info = entity.device_info
        assert info is not None
        assert info["identifiers"] == {("tech", entity._udid)}
        assert info["name"] == "Test Controller"
        assert info["manufacturer"] == "TechControllers"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_txt_id_zero_fallback_uses_str_value(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """When an option's ``txtId`` is 0 the label falls back to ``str(value)``."""
        item: dict[str, Any] = {
            "menuType": "MU",
            "type": 11,
            "id": 2070,
            "parentId": 0,
            "access": False,
            "txtId": 459,
            "params": {
                "value": 5,
                "default": 0,
                "options": [
                    {"txtId": 0, "value": 5},
                ],
            },
            "duringChange": "f",
        }
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
        assert ent._attr_options == ["5"]

    def test_entity_name_falls_back_to_fan_speed(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """When txtId 459 has no translation the name degrades to 'Fan speed'."""
        # Drop the translation for txtId 459 so get_text returns None.
        coordinator.translations.store.pop(459, None)

        item = copy.deepcopy(MU_2070_FIXTURE)
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)

        assert ent.name == "Fan speed"

    def test_entity_name_uses_translation_when_available(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """When txtId 459 has a translation, that translation is used as the name."""
        coordinator.translations.store[459] = "Prędkość wentylatora"

        item = MU_2070_FIXTURE.copy()
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)

        assert ent.name == "Prędkość wentylatora"

    def test_empty_options_does_not_crash(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """An empty options list is handled gracefully."""
        item: dict[str, Any] = {
            "menuType": "MU",
            "type": 11,
            "id": 2070,
            "parentId": 0,
            "access": False,
            "txtId": 459,
            "params": {
                "value": 0,
                "default": 0,
                "options": [],
            },
            "duringChange": "f",
        }
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
        assert ent._attr_options == []
        assert ent.current_option is None

    def test_value_not_in_options_falls_to_first_option(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """When ``params.value`` does not map to any option, the first option is used."""
        item: dict[str, Any] = {
            "menuType": "MU",
            "type": 11,
            "id": 2070,
            "parentId": 0,
            "access": False,
            "txtId": 459,
            "params": {
                "value": 999,
                "default": 0,
                "options": [
                    {"txtId": 0, "value": 10},
                    {"txtId": 0, "value": 20},
                ],
            },
            "duringChange": "f",
        }
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
        assert ent._attr_options == ["10", "20"]
        assert ent.current_option == "10"

    def test_duplicate_label_gets_value_suffix(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """When two options resolve to the same label the second gets a ``(value)`` suffix."""
        # Make both txtId 100 and 101 resolve to the same label.
        coordinator.translations.store.update({100: "Same", 101: "Same"})
        item: dict[str, Any] = {
            "menuType": "MU",
            "type": 11,
            "id": 2070,
            "parentId": 0,
            "access": False,
            "txtId": 459,
            "params": {
                "value": 0,
                "default": 0,
                "options": [
                    {"txtId": 100, "value": 1},
                    {"txtId": 101, "value": 2},
                ],
            },
            "duringChange": "f",
        }
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
        assert ent._attr_options == ["Same", "Same (2)"]

    def test_non_dict_option_is_skipped(
        self, coordinator: MagicMock, config_entry: MagicMock
    ) -> None:
        """If an options entry is not a dict it is silently skipped."""
        item: dict[str, Any] = {
            "menuType": "MU",
            "type": 11,
            "id": 2070,
            "parentId": 0,
            "access": False,
            "txtId": 459,
            "params": {
                "value": 0,
                "default": 0,
                "options": [
                    {"txtId": 0, "value": 1},
                    "not_a_dict",
                ],
            },
            "duringChange": "f",
        }
        ent = MenuFanSpeedSelectEntity(item, "MU_2070", coordinator, config_entry)
        assert ent._attr_options == ["1"]
