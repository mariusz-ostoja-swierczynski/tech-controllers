"""Wiring tests for the menu platforms: zone device names and ``device_info``.

:mod:`test_assets` covers the *logic* of :func:`assets.build_zone_names` and
:func:`assets.resolve_zone_device_name`. What it cannot see is whether the four
menu platforms actually use that logic, and a regression there would be easy to
miss: on a hubs controller the zone device is already created and named by
``climate.TechThermostat`` a few milliseconds before the first menu entity
registers, so a broken menu ``device_info`` leaves no trace in a Home Assistant
log or registry. These tests close that gap by building each platform entity and
reading its real ``device_info`` property.

Home Assistant is stubbed, in the style of :mod:`test_widget_logic`, so no HA
install is needed. The entities are constructed through their real ``__init__``,
which also proves that ``__init__`` derives ``_zone_name`` from the ``zone_names``
mapping produced by ``assets.build_zone_names`` in ``async_setup_entry``.
"""

from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import sys
import types
from typing import Any

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"

_UDID = "d" * 32
_HUB = "L-8 DEMO"

# ---------------------------------------------------------------------------
# Home Assistant stubs. Only what the platform modules, const.py and
# coordinator.py touch on import: annotations are evaluated at runtime (the
# modules do not use ``from __future__ import annotations``), so every imported
# name has to exist, but nothing is ever called.
# ---------------------------------------------------------------------------
_FAKE_MODULES = (
    "homeassistant",
    "homeassistant.components",
    "homeassistant.components.automation",
    "homeassistant.components.binary_sensor",
    "homeassistant.components.button",
    "homeassistant.components.number",
    "homeassistant.components.script",
    "homeassistant.components.select",
    "homeassistant.components.sensor",
    "homeassistant.components.sensor.const",
    "homeassistant.components.switch",
    "homeassistant.config_entries",
    "homeassistant.const",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.device_registry",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.entity_registry",
    "homeassistant.helpers.icon",
    "homeassistant.helpers.issue_registry",
    "homeassistant.helpers.typing",
    "homeassistant.helpers.update_coordinator",
)


class _Entity:
    """Minimal stand-in for ``homeassistant.helpers.entity.Entity``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Record the optional ``hass`` the real base class accepts."""
        self.hass = kwargs.get("hass")

    async def async_added_to_hass(self) -> None:
        """Pretend the entity was added."""

    def async_write_ha_state(self) -> None:
        """Pretend to publish the entity state; nothing is recorded."""


class CoordinatorEntity(_Entity):
    """Stand-in for ``CoordinatorEntity``; only stores the coordinator."""

    def __init__(self, coordinator: Any = None, *args: Any, **kwargs: Any) -> None:
        """Store the coordinator the way the real base class does."""
        super().__init__(*args, **kwargs)
        self.coordinator = coordinator


class SensorEntity(_Entity):
    """Stand-in for ``homeassistant.components.sensor.SensorEntity``.

    Kept a sibling of :class:`BinarySensorEntity` rather than the same class, so
    a platform that mixes both bases keeps a resolvable MRO as it does in core.
    """


class BinarySensorEntity(_Entity):
    """Stand-in for ``homeassistant.components.binary_sensor.BinarySensorEntity``."""


class DataUpdateCoordinator(_Entity):
    """Stand-in for ``DataUpdateCoordinator``."""


class _UpdateFailed(Exception):
    """Stand-in for ``UpdateFailed``."""


class _ConfigEntryAuthFailed(Exception):
    """Stand-in for ``ConfigEntryAuthFailed``."""


class _ConfigEntry:
    """Stand-in for ``homeassistant.config_entries.ConfigEntry``."""


class _DeviceInfo(dict):
    """Stand-in for the ``DeviceInfo`` typed dict."""


class _AddEntitiesCallback:
    """Stand-in for the ``AddEntitiesCallback`` annotation."""


class _Platform:
    """Stand-in for ``homeassistant.const.Platform``; only the names matter."""

    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CLIMATE = "climate"
    NUMBER = "number"
    SELECT = "select"
    SENSOR = "sensor"
    SWITCH = "switch"


class _EntityCategory:
    """Stand-in for ``homeassistant.const.EntityCategory``."""

    CONFIG = "config"
    DIAGNOSTIC = "diagnostic"


class _NumberMode:
    """Stand-in for ``homeassistant.components.number.NumberMode``."""

    BOX = "box"
    SLIDER = "slider"


# The subclasses each platform module declares for its own entity type. The
# switch stub is written out because a test has to be able to read ``is_on`` the
# way Home Assistant publishes it, not just the ``_attr_is_on`` behind it.
class SwitchEntity(_Entity):
    """Stand-in for ``homeassistant.components.switch.SwitchEntity``."""

    @property
    def is_on(self) -> bool | None:
        """Return the state Home Assistant would publish."""
        return getattr(self, "_attr_is_on", None)


globals()["switch"] = SwitchEntity
for _name in ("button", "select", "number"):
    globals()[_name] = type(f"{_name.title()}Entity", (_Entity,), {})


class _AutoNamespace:
    """Stand-in for an HA enum; any attribute reads back as its own name."""

    def __getattr__(self, name: str) -> str:
        """Return the attribute name lowercased."""
        return name.lower()


class _RegistryEntry:
    """Stand-in for a registry entry, carrying only what the code reads."""

    def __init__(self, disabled: bool) -> None:
        """Record the disabled flag."""
        self.disabled = disabled


class _Registry:
    """Stand-in for the entity registry, recording removals."""

    def __init__(self, entity_id: str | None, disabled: bool = False) -> None:
        """Record the entity the lookups should resolve to."""
        self.entity_id = entity_id
        self.entry = _RegistryEntry(disabled)
        self.removed: list[str] = []

    def async_get_entity_id(self, *args: Any) -> str | None:
        """Return the recorded entity id, if any."""
        return self.entity_id

    def async_get(self, entity_id: str) -> _RegistryEntry | None:
        """Return the recorded entry when the id matches."""
        return self.entry if entity_id == self.entity_id else None

    def async_remove(self, entity_id: str) -> None:
        """Record the removal instead of touching a real registry."""
        self.removed.append(entity_id)
        self.entity_id = None


def _async_get_registry(hass: Any) -> _Registry:
    """Return an empty registry; tests install their own."""
    return _Registry(entity_id=None)


def _async_create_issue(hass: Any, domain: str, issue_id: str, **kwargs: Any) -> None:
    """Accept a repair issue without registering one; tests install their own."""


def _async_delete_issue(hass: Any, domain: str, issue_id: str) -> None:
    """Accept the removal of a repair issue; tests install their own."""


def _automations_with_entity(hass: Any, entity_id: str) -> list[str]:
    """Report no automations referencing an entity."""
    return []


def _scripts_with_entity(hass: Any, entity_id: str) -> list[str]:
    """Report no scripts referencing an entity."""
    return []


def _fake_module(name: str) -> types.ModuleType:
    """Build the stub for one ``homeassistant`` module."""
    module = types.ModuleType(name)

    if name == "homeassistant.const":
        module.ATTR_ID = "id"
        module.ATTR_IDENTIFIERS = "identifiers"
        module.ATTR_MANUFACTURER = "manufacturer"
        module.CONF_DESCRIPTION = "description"
        module.CONF_ID = "id"
        module.CONF_MODEL = "model"
        module.CONF_NAME = "name"
        module.CONF_PARAMS = "params"
        module.CONF_PASSWORD = "password"
        module.CONF_TOKEN = "token"
        module.CONF_TYPE = "type"
        module.CONF_USERNAME = "username"
        module.CONF_ZONE = "zone"
        module.PERCENTAGE = "%"
        module.STATE_OFF = "off"
        module.STATE_ON = "on"
        module.EntityCategory = _EntityCategory
        module.Platform = _Platform
        module.UnitOfElectricPotential = _AutoNamespace()
        module.UnitOfEnergy = _AutoNamespace()
        module.UnitOfPower = _AutoNamespace()
        module.UnitOfPressure = _AutoNamespace()
        module.UnitOfTemperature = _AutoNamespace()
        module.UnitOfTime = _AutoNamespace()
        module.UnitOfVolume = _AutoNamespace()
        module.UnitOfVolumeFlowRate = _AutoNamespace()
    elif name == "homeassistant.components.switch":
        module.SwitchEntity = globals()["switch"]
    elif name == "homeassistant.components.button":
        module.ButtonEntity = globals()["button"]
    elif name == "homeassistant.components.select":
        module.SelectEntity = globals()["select"]
    elif name == "homeassistant.components.number":
        module.NumberEntity = globals()["number"]
        module.NumberMode = _NumberMode
    elif name == "homeassistant.config_entries":
        module.ConfigEntry = _ConfigEntry
        module.ConfigEntryState = type("ConfigEntryState", (), {"LOADED": "loaded"})
        module.ConfigFlowResult = dict
        module.SOURCE_USER = "user"
    elif name == "homeassistant.core":
        module.HomeAssistant = _Entity
        module.callback = lambda func: func
    elif name == "homeassistant.exceptions":
        module.ConfigEntryAuthFailed = _ConfigEntryAuthFailed
        module.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    elif name == "homeassistant.helpers.device_registry":
        module.DeviceInfo = _DeviceInfo
    elif name == "homeassistant.helpers.entity_platform":
        module.AddEntitiesCallback = _AddEntitiesCallback
    elif name == "homeassistant.helpers.update_coordinator":
        module.CoordinatorEntity = CoordinatorEntity
        module.DataUpdateCoordinator = DataUpdateCoordinator
        module.UpdateFailed = _UpdateFailed
    elif name == "homeassistant.components.automation":
        module.automations_with_entity = _automations_with_entity
    elif name == "homeassistant.components.binary_sensor":
        module.BinarySensorEntity = BinarySensorEntity
        module.BinarySensorDeviceClass = _AutoNamespace()
    elif name == "homeassistant.components.script":
        module.scripts_with_entity = _scripts_with_entity
    elif name == "homeassistant.components.sensor":
        module.SensorEntity = SensorEntity
    elif name == "homeassistant.components.sensor.const":
        module.SensorDeviceClass = _AutoNamespace()
        module.SensorStateClass = _AutoNamespace()
    elif name == "homeassistant.helpers.entity":
        module.Entity = _Entity
    elif name == "homeassistant.helpers.entity_registry":
        module.EntityRegistry = _Registry
        module.async_get = _async_get_registry
    elif name == "homeassistant.helpers.icon":
        module.icon_for_signal_level = lambda level: "mdi:signal"
    elif name == "homeassistant.helpers.typing":
        module.StateType = object
        module.UndefinedType = type("UndefinedType", (), {})
    elif name == "homeassistant.helpers.issue_registry":
        module.IssueSeverity = _AutoNamespace()
        module.async_create_issue = _async_create_issue
        module.async_delete_issue = _async_delete_issue
    elif name == "homeassistant.helpers.typing":
        module.UndefinedType = type("UndefinedType", (), {})
    return module


def _install_stubs() -> None:
    """Install the stubs and wire the parent/child attributes."""
    modules = {name: _fake_module(name) for name in _FAKE_MODULES}
    modules["homeassistant"].__path__ = []
    modules["homeassistant.components"].__path__ = []
    modules["homeassistant.helpers"].__path__ = []
    for parent, children in (
        (
            "homeassistant",
            ("components", "config_entries", "const", "core", "exceptions", "helpers"),
        ),
        (
            "homeassistant.components",
            (
                "automation",
                "binary_sensor",
                "button",
                "number",
                "script",
                "select",
                "sensor",
                "switch",
            ),
        ),
        (
            "homeassistant.helpers",
            (
                "device_registry",
                "entity",
                "entity_platform",
                "entity_registry",
                "icon",
                "issue_registry",
                "typing",
                "update_coordinator",
            ),
        ),
    ):
        for child in children:
            setattr(modules[parent], child, modules[f"{parent}.{child}"])
    modules["homeassistant.components.sensor"].const = modules[
        "homeassistant.components.sensor.const"
    ]
    sys.modules.update(modules)


def _load_tech_module(name: str) -> types.ModuleType:
    """Load ``custom_components.tech.<name>`` without executing ``__init__.py``."""
    full_name = f"custom_components.tech.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    for package, path in (
        ("custom_components", _REPO_ROOT / "custom_components"),
        ("custom_components.tech", _TECH_DIR),
    ):
        if package not in sys.modules:
            module = types.ModuleType(package)
            module.__path__ = [str(path)]
            sys.modules[package] = module
    spec = importlib.util.spec_from_file_location(full_name, _TECH_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_install_stubs()
const = _load_tech_module("const")
assets = _load_tech_module("assets")
_tech_module = _load_tech_module("tech")
_coordinator = _load_tech_module("coordinator")
sensor = _load_tech_module("sensor")

# binary_sensor.py imports TechCoordinator and assets from the package rather
# than from their own modules, which only resolves once the package exposes them.
_tech_package = sys.modules["custom_components.tech"]
_tech_package.TechCoordinator = sys.modules[
    "custom_components.tech.coordinator"
].TechCoordinator
_tech_package.assets = assets
binary_sensor = _load_tech_module("binary_sensor")

PLATFORMS = (
    ("switch", "MenuSwitchEntity"),
    ("number", "MenuNumberEntity"),
    ("select", "MenuSelectEntity"),
    ("button", "MenuButtonEntity"),
)
_PLATFORM_IDS = [name for name, _ in PLATFORMS]

_modules = {name: _load_tech_module(name) for name, _ in PLATFORMS}


class _Translations:
    """Stand-in for the coordinator's translation catalog."""

    def get_text(self, txt_id: int) -> str:
        """Return a stable label for any text id."""
        return f"label-{txt_id}"

    def get_text_by_type(self, text_type: int) -> str:
        """Return a stable label for any tile type.

        TYPE_WIDGET tiles carry no ``txtId`` of their own, so
        :class:`~custom_components.tech.entity.TileEntity` resolves their name
        through the tile type instead.
        """
        return f"type-{text_type}"


class _Api:
    """Async API stub; the menu payload is irrelevant to these tests.

    Menu writes are recorded rather than sent, so a test can assert the payload
    a platform sends to the controller.
    """

    def __init__(self, menus: dict[str, dict[str, Any]] | None = None) -> None:
        """Start with no writes recorded and the given menu tree to serve."""
        self.calls: list[tuple[str, int, dict]] = []
        self._menus = menus or {}

    async def get_module_menus(self, udid: str) -> dict:
        """Return the menu tree this stub was built with (empty by default)."""
        return self._menus

    async def get_module_zones(self, udid: str) -> dict:
        """Return an empty zone payload."""
        return {}

    async def set_menu_value(
        self, udid: str, menu_type: str, ido: int, data: dict
    ) -> dict:
        """Record a menu write instead of sending it."""
        self.calls.append((menu_type, ido, data))
        return {}


class _Coordinator:
    """Stand-in for ``TechCoordinator``."""

    def __init__(self, menus: dict[str, dict[str, Any]] | None = None) -> None:
        """Wire up the API, translation catalog and cache."""
        self.api = _Api(menus)
        self.translations = _Translations()
        self.udid = _UDID
        self.data: dict = {}

    async def async_request_refresh(self) -> None:
        """Pretend to ask for a poll after a write; nothing is fetched."""


class _Entry:
    """Stand-in for the config entry, with just the fields the code reads."""

    def __init__(self, title: str = _HUB, include_hub_in_name: bool = False) -> None:
        """Build an entry carrying the controller udid and the naming flag."""
        self.title = title
        self.entry_id = "entry-id"
        self.data = {
            const.CONTROLLER: {const.UDID: _UDID},
            const.INCLUDE_HUB_IN_NAME: include_hub_in_name,
        }


def _item() -> dict[str, Any]:
    """Return a menu item payload carrying every field the entities touch."""
    return {
        "id": 3550,
        "menuType": "MU",
        "type": 1,
        "access": True,
        "txtId": 459,
        "params": {
            "value": 1,
            "format": 1,
            "min": 0,
            "max": 100,
            "jump": 1,
            "type": 0,
            "options": [
                {"value": 0, "id": 0, "txtId": 1, "label": "Off"},
                {"value": 1, "id": 1, "txtId": 2, "label": "On"},
            ],
        },
    }


def _build(
    module_name: str,
    class_name: str,
    *,
    zone_id: int | None,
    zone_names: dict[int, str] | None,
    entry: _Entry | None = None,
    key: str = "MU_3550",
):
    """Construct a menu entity the way its platform's ``async_setup_entry`` does."""
    entity_class = getattr(_modules[module_name], class_name)
    return entity_class(
        _item(),
        key,
        _Coordinator(),
        entry or _Entry(),
        {},
        depth=0,
        zone_id=zone_id,
        zone_names=zone_names,
    )


@pytest.mark.parametrize(("module_name", "class_name"), PLATFORMS, ids=_PLATFORM_IDS)
def test_zone_entity_uses_the_zone_device_name(
    module_name: str, class_name: str
) -> None:
    """A zone-attached entity names the zone device from the resolved mapping."""
    entity = _build(
        module_name, class_name, zone_id=101, zone_names={101: "L-8 DEMO Strefa 1"}
    )

    assert entity._zone_name == "L-8 DEMO Strefa 1"

    info = entity.device_info
    assert info["identifiers"] == {(const.DOMAIN, f"{_UDID}_101")}
    assert info["name"] == "L-8 DEMO Strefa 1"
    assert info["manufacturer"] == const.MANUFACTURER


@pytest.mark.parametrize(("module_name", "class_name"), PLATFORMS, ids=_PLATFORM_IDS)
def test_unzoned_entity_stays_on_the_controller_device(
    module_name: str, class_name: str
) -> None:
    """An entity without a zone keeps the controller device and its hub name."""
    entity = _build(module_name, class_name, zone_id=None, zone_names={})

    assert entity._zone_name is None

    info = entity.device_info
    assert info["identifiers"] == {(const.DOMAIN, _UDID)}
    assert info["name"] == _HUB
    assert info["manufacturer"] == const.MANUFACTURER


@pytest.mark.parametrize(("module_name", "class_name"), PLATFORMS, ids=_PLATFORM_IDS)
def test_zone_entity_falls_back_to_the_hub_title(
    module_name: str, class_name: str
) -> None:
    """A zone without a usable name keeps the zone device but names it after the hub.

    This is the branch that matters when a zone payload carries no description:
    the device is still the zone device, so the fallback must not silently move
    the entity back onto the controller device.
    """
    entity = _build(module_name, class_name, zone_id=101, zone_names={})

    assert entity._zone_name == _HUB

    info = entity.device_info
    assert info["identifiers"] == {(const.DOMAIN, f"{_UDID}_101")}
    assert info["name"] == _HUB


@pytest.mark.parametrize(("module_name", "class_name"), PLATFORMS, ids=_PLATFORM_IDS)
def test_zone_names_built_with_the_hub_prefix_reach_the_device(
    module_name: str, class_name: str
) -> None:
    """The prefixed mapping built for ``include_hub_in_name`` is what gets used."""
    zone_names = assets.build_zone_names(
        {101: {"zone": {"id": 101, "index": 0}, "description": {"name": "Strefa 1"}}},
        _HUB,
        include_hub_in_name=True,
    )
    entity = _build(module_name, class_name, zone_id=101, zone_names=zone_names)

    assert entity.device_info["name"] == "L-8 DEMO Strefa 1"


@pytest.mark.parametrize(("module_name", "class_name"), PLATFORMS, ids=_PLATFORM_IDS)
def test_zone_names_built_without_the_prefix_reach_the_device(
    module_name: str, class_name: str
) -> None:
    """With the flag off the device takes the bare zone name, as before."""
    zone_names = assets.build_zone_names(
        {101: {"zone": {"id": 101, "index": 0}, "description": {"name": "Strefa 1"}}},
        _HUB,
        include_hub_in_name=False,
    )
    entity = _build(module_name, class_name, zone_id=101, zone_names=zone_names)

    assert entity.device_info["name"] == "Strefa 1"


def _flag_tile(*, txt_id: int = 4640, unit: int = 28) -> dict[str, Any]:
    """Return a TYPE_WIDGET tile carrying one flag-shaped widget."""
    return {
        "id": 4660,
        "type": const.TYPE_WIDGET,
        "visibility": True,
        "params": {
            "id": 4660,
            "txtId": 100,
            "iconId": 0,
            "value": 1,
            "widget1": {"txtId": txt_id, "value": 1, "unit": unit, "type": 1},
        },
    }


def _record_issues(
    *,
    automations: list[str] | None = None,
    scripts: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Point the deprecation helpers at recording fakes and return the log."""
    issues: list[dict[str, Any]] = []

    def _create(hass: Any, domain: str, issue_id: str, **kwargs: Any) -> None:
        """Record a repair issue instead of registering one."""
        issues.append({"domain": domain, "issue_id": issue_id, **kwargs})

    # The sensor module imports these two by name, so they are replaced there
    # rather than on the homeassistant module.
    sensor.automations_with_entity = lambda hass, entity_id: list(automations or [])
    sensor.scripts_with_entity = lambda hass, entity_id: list(scripts or [])
    sys.modules["homeassistant.helpers.issue_registry"].async_create_issue = _create
    return issues


def _install_registry(registry: _Registry) -> _Registry:
    """Make ``er.async_get`` hand out the given registry."""
    module = sys.modules["homeassistant.helpers.entity_registry"]
    module.async_get = lambda hass: registry
    return registry


def _deprecate(registry: _Registry) -> bool:
    """Run the deprecation decision the way the sensor platform does."""
    return sensor._async_deprecate_flag_sensor(object(), registry, "some-unique-id")


def _widget_tile(
    *,
    status_id: int,
    widget: dict[str, Any],
    tile_id: int = 4660,
) -> dict[str, Any]:
    """Return a TYPE_WIDGET tile carrying one widget and a chosen ``statusId``."""
    return {
        "id": tile_id,
        "type": const.TYPE_WIDGET,
        "visibility": True,
        "params": {
            "id": tile_id,
            "txtId": 100,
            "iconId": 0,
            "statusId": status_id,
            "value": 0,
            "widget1": widget,
        },
    }


def test_widget_metadata_follows_the_api_value_type() -> None:
    """Unit and device class come from the value type, not from a temperature.

    Issue #221: kW, COP and kelvin readings were published as degrees Celsius with
    the temperature device class. Units are compared through the table because
    the harness stubs Home Assistant's unit constants as name-like strings; the
    device classes are compared by name, which works either way because they are
    StrEnum members in Home Assistant.
    """
    cases = {
        0: (3600, None, None),
        6: (55, const.WIDGET_UNITS[6].unit, "temperature"),
        7: (498, const.WIDGET_UNITS[7].unit, "temperature"),
        10: (3, const.WIDGET_UNITS[10].unit, "power"),
        26: (56, const.WIDGET_UNITS[26].unit, "power"),
        29: (950, const.WIDGET_UNITS[29].unit, "power"),
        32: (35, const.WIDGET_UNITS[32].unit, None),
        38: (35, None, None),
    }

    for code, (raw, unit, device_class) in cases.items():
        tile = {
            "id": 9000 + code,
            "type": const.TYPE_WIDGET,
            "visibility": True,
            "params": {
                "id": 9000 + code,
                "txtId": 100,
                "iconId": 0,
                "statusId": 1,
                "value": 0,
                "widget1": {"txtId": 1562, "unit": code, "type": 0, "value": raw},
            },
        }
        entities = sensor._build_widget_tile(tile, _Coordinator(), _Entry())

        assert len(entities) == 1, code
        entity = entities[0]
        assert entity._attr_native_unit_of_measurement == unit, code
        assert entity._attr_device_class == device_class, code
        assert entity.get_state(tile) == raw / const.widget_unit(code).divisor, code


_KOLTON_DUMP = _REPO_ROOT / "tests" / "fixtures" / "kolton_st5305" / "module.json"


def _kolton_module() -> dict[str, Any]:
    """Load the Kołton ST-5305 dump the reporter attached to issue #221."""
    return json.loads(_KOLTON_DUMP.read_text())


def _kolton_sensor_rows() -> list[tuple[Any, ...]]:
    """Return one row per sensor entity the payload's TYPE_WIDGET tiles yield.

    Columns: tile id, widget slot, API value type, entity class, unit of
    measurement, device class, state. Device classes are read as their name so
    the table reads the same against Home Assistant's StrEnums and the stubs,
    and the expected table compares units through :data:`const.WIDGET_UNITS`
    because which module loaded that table first decides whether a unit is the
    real constant or the harness's stand-in.

    """
    rows: list[tuple[Any, ...]] = []
    for tile in _kolton_module()["tiles"]:
        if tile["type"] != const.TYPE_WIDGET:
            continue
        for entity in sensor._build_widget_tile(tile, _Coordinator(), _Entry()):
            device_class = getattr(entity, "_attr_device_class", None)
            rows.append(
                (
                    tile["id"],
                    entity._widget_key,
                    tile["params"][entity._widget_key]["unit"],
                    type(entity).__name__,
                    entity._attr_native_unit_of_measurement,
                    getattr(device_class, "value", device_class),
                    entity.get_state(tile),
                )
            )
    return rows


def _widget_unit(code: int) -> str | None:
    """Return the unit of measurement the value-type table gives a code."""
    return const.widget_unit(code).unit


def test_kolton_st5305_widget_entities() -> None:
    """The whole widget entity table for the issue #221 payload.

    Every reading on this heat pump used to be published as degrees Celsius with
    the temperature device class, whatever its value type said. The payload is
    kept as the permanent fixture for that: it carries no temperature widget at
    all (the histogram is -1, 0, 3, 8, 13, 23, 26, 28, 32, 38, 39), so any °C
    reading in the table below is a regression, and so is an opening sensor for
    one of the 18 invisible widgets.
    """
    percent, hours, bar = _widget_unit(8), _widget_unit(3), _widget_unit(23)
    kilowatt, kelvin, flow = _widget_unit(26), _widget_unit(32), _widget_unit(39)
    expected = [
        # 8 -- percentages (pump duty cycle)
        (1006, "widget2", 8, "TileWidgetPumpSensor", percent, None, 0),
        (1014, "widget2", 8, "TileWidgetPumpSensor", percent, None, 0),
        (1552, "widget2", 8, "TileWidgetPumpSensor", percent, None, 0),
        (2270, "widget2", 8, "TileWidgetPumpSensor", percent, None, 5),
        # 0 -- ordinary numbers, no unit
        (1553, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 78),
        (2191, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2197, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2198, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2209, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 1000),
        (2217, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2218, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2219, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2220, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        (2223, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 4274),
        (2232, "widget2", 0, "TileWidgetTemperatureSensor", None, None, 0),
        # 39 -- "Value l / m" in the API prose, labelled l/godz. by the app
        (
            1096,
            "widget2",
            39,
            "TileWidgetTemperatureSensor",
            flow,
            "volume_flow_rate",
            0,
        ),
        # 13 -- hours and minutes
        (1664, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "00:00"),
        (1666, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "17:21"),
        (1668, "widget2", 13, "TileWidgetTemperatureSensor", None, None, None),
        (2193, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "00:00"),
        (2194, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "00:00"),
        (2195, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "00:00"),
        (2196, "widget2", 13, "TileWidgetTemperatureSensor", None, None, "00:00"),
        # 23 -- pressure in tenths of a bar
        (1548, "widget2", 23, "TileWidgetTemperatureSensor", bar, "pressure", 6.1),
        (1550, "widget2", 23, "TileWidgetTemperatureSensor", bar, "pressure", 6.0),
        # 26 -- power in tenths of a kW (the snapshot was taken with the pump idle)
        (1562, "widget2", 26, "TileWidgetTemperatureSensor", kilowatt, "power", 0.0),
        (1575, "widget2", 26, "TileWidgetTemperatureSensor", kilowatt, "power", 0.0),
        # 32 -- kelvin, and these are superheat *differences*, so no class
        (1549, "widget2", 32, "TileWidgetTemperatureSensor", kelvin, None, 3),
        (2269, "widget2", 32, "TileWidgetTemperatureSensor", kelvin, None, 10),
        # 38 -- COP, dimensionless
        (1590, "widget2", 38, "TileWidgetTemperatureSensor", None, None, 0.0),
        # 3 -- hours
        (2213, "widget2", 3, "TileWidgetTemperatureSensor", hours, "duration", 0),
        (2214, "widget2", 3, "TileWidgetTemperatureSensor", hours, "duration", 0),
        (2215, "widget2", 3, "TileWidgetTemperatureSensor", hours, "duration", 0),
        (2216, "widget2", 3, "TileWidgetTemperatureSensor", hours, "duration", 0),
    ]

    rows = _kolton_sensor_rows()
    assert sorted(rows) == sorted(expected)
    assert len(rows) == 34
    # Nothing may claim to be a temperature: the payload has no unit 6 or 7.
    assert {row[5] for row in rows} == {
        None,
        "duration",
        "power",
        "pressure",
        "volume_flow_rate",
    }
    assert {_widget_unit(6), _widget_unit(7)}.isdisjoint({row[4] for row in rows})
    # Every widget is published through its own slot, and only widget2 carries
    # a reading: all 52 widget1 payloads are placeholders, flags, or invisible.
    assert {row[1] for row in rows} == {"widget2"}


def test_kolton_st5305_registers_the_counters_disabled() -> None:
    """The eleven elapsed-time counters are registered disabled by default.

    The reporter asked for the eight numbered compressor counters to stay out of
    the entity list (issue #221). The payload marks them only by their value type
    -- 3 hours for the run-time block, 13 hours:minutes for the downtime block --
    which three other duration readings share, so the value types are switched
    off as a family and a user enables the one they read.
    """
    disabled = [
        (tile["id"], tile["params"][entity._widget_key]["unit"])
        for tile in _kolton_module()["tiles"]
        if tile["type"] == const.TYPE_WIDGET
        for entity in sensor._build_widget_tile(tile, _Coordinator(), _Entry())
        # Home Assistant defaults an entity to enabled when the attribute is
        # never set, and the pump sensors do not set it.
        if getattr(entity, "_attr_entity_registry_enabled_default", True) is False
    ]

    assert sorted(disabled) == sorted(
        [
            (1664, 13),
            (1666, 13),
            (1668, 13),
            (2193, 13),
            (2194, 13),
            (2195, 13),
            (2196, 13),
            (2213, 3),
            (2214, 3),
            (2215, 3),
            (2216, 3),
        ]
    )


def test_kolton_st5305_exposes_flags_but_no_contacts() -> None:
    """The 18 invisible widgets are flags, not phantom opening sensors.

    Their partner widget is the value type 28 "Enabled / Disabled" state, and
    the label sits on the invisible widget: value type -1 means "value
    invisible" in the API, so the tile is not a contact either (issue #221).
    """
    flags: list[tuple[Any, ...]] = []
    contacts: list[tuple[Any, ...]] = []
    for tile in _kolton_module()["tiles"]:
        if tile["type"] != const.TYPE_WIDGET:
            continue
        params = tile["params"]
        for widget_key in ("widget1", "widget2"):
            widget = params.get(widget_key)
            if not widget:
                continue
            sibling = binary_sensor._sibling_widget(params, widget_key)
            if binary_sensor._is_flag_widget(widget, sibling):
                entity = binary_sensor.TileWidgetFlagSensor(
                    tile, _Coordinator(), _Entry(), widget_key
                )
                flags.append((tile["id"], entity.name, entity.get_state(tile)))
            if binary_sensor._is_contact_widget(widget, sibling):
                contacts.append((tile["id"], widget_key))

    assert contacts == []
    assert len(flags) == 18
    assert flags[0] == (1075, "label-246", False)
    assert (12038, "label-296", True) in flags
    assert (12052, "label-6677", False) in flags


def test_kolton_st5305_publishes_the_reported_values() -> None:
    """The three readings the reporter named, in the unit he expects.

    unit=26 (heat pump power) and unit=38 (COP) are zero in this idle snapshot,
    which is why the divisor matters more than the sample: 35 must be 3.5 kW and
    35 must be COP 3.5, and neither may be a temperature.
    """
    for code, raw, state in (
        (26, 56, 5.6),
        (38, 35, 3.5),
        (32, 35, 35),
        (29, 950, 950),
    ):
        tile = _widget_tile(
            status_id=1,
            widget={"txtId": 1562, "unit": code, "type": 0, "value": raw},
        )
        entity = sensor._build_widget_tile(tile, _Coordinator(), _Entry())[0]

        assert entity._attr_native_unit_of_measurement == _widget_unit(code), code
        assert entity.get_state(tile) == state, code
        assert entity._attr_device_class != "temperature", code

    # unit=19 is "kWh with a decimal point", which no widget in this payload
    # carries; the API's own wording and the eModul formatter agree on tenths.
    tile = _widget_tile(
        status_id=1,
        widget={"txtId": 1562, "unit": 19, "type": 0, "value": 1234},
    )
    energy = sensor._build_widget_tile(tile, _Coordinator(), _Entry())[0]
    assert energy.get_state(tile) == 123.4
    assert energy._attr_native_unit_of_measurement == _widget_unit(19)


class TestBorrowedLabelWidgets:
    """A widget may carry its label on the sibling (issue #221).

    Heat pump tiles put the label on one widget and the state on the other, so
    both platforms have to look at the pair when deciding which widget they own
    and what to call it.
    """

    def test_unlabelled_flag_next_to_a_labelled_widget_is_exposed(self) -> None:
        """A unit-28 widget without its own label takes the sibling's."""
        tile = _widget_tile(
            status_id=0,
            widget={"txtId": 0, "unit": 28, "type": 1, "value": 1},
        )
        tile["params"]["widget2"] = {"txtId": 4492, "unit": -1, "type": 0, "value": 0}

        # The sensor platform owns neither widget: the flag belongs to
        # binary_sensor, and the lone unit=-1 widget is an invisible value
        # rather than a contact.
        assert sensor._build_widget_tile(tile, _Coordinator(), _Entry()) == []

        entity = binary_sensor.TileWidgetFlagSensor(
            tile, _Coordinator(), _Entry(), "widget1"
        )
        assert entity.name == "label-4492"
        assert entity.unique_id.endswith("_tile_widget_flag_widget1")
        assert entity.get_state(tile) is True

    def test_unlabelled_flag_without_any_label_stays_hidden(self) -> None:
        """With no label on either slot there is nothing to name the flag."""
        tile = _widget_tile(
            status_id=0,
            widget={"txtId": 0, "unit": 28, "type": 1, "value": 1},
        )
        tile["params"]["widget2"] = {"txtId": 0, "unit": -1, "type": 0, "value": 0}

        assert sensor._build_widget_tile(tile, _Coordinator(), _Entry()) == []
        assert (
            binary_sensor._is_flag_widget(
                tile["params"]["widget1"], tile["params"]["widget2"]
            )
            is False
        )


class TestWidgetNameSuffix:
    """The DHW "Set/Current Temperature" suffix belongs to temperature readings."""

    def test_a_flow_reading_keeps_its_plain_label(self) -> None:
        """A pump-subtype widget that is not a temperature gets no suffix.

        Issue #221: the Kołton's unit=39 flow reading was published as
        "Przepływ Current Temperature", because heat pumps mark every reading
        with the pump subtype, not just their temperature pair.
        """
        tile = _widget_tile(
            status_id=1,
            widget={"txtId": 632, "unit": 39, "type": 1, "value": 0},
        )
        # The Kołton reports this reading in the second slot, the way widget2 of
        # its tile 1096 does, so " Current Temperature" is the suffix at stake.
        tile["params"]["widget2"] = tile["params"].pop("widget1")

        entities = sensor._build_widget_tile(tile, _Coordinator(), _Entry())

        assert [entity.name for entity in entities] == ["label-632"]

    def test_a_pump_temperature_pair_keeps_the_suffix(self) -> None:
        """Both slots of a real DHW pump temperature pair stay distinguishable."""
        tile = _widget_tile(
            status_id=1,
            widget={"txtId": 2442, "unit": 7, "type": 1, "value": 560},
        )
        tile["params"]["widget2"] = {"txtId": 2442, "unit": 7, "type": 1, "value": 455}

        entities = sensor._build_widget_tile(tile, _Coordinator(), _Entry())

        assert [entity.name for entity in entities] == [
            "label-2442 Set Temperature",
            "label-2442 Current Temperature",
        ]


class TestContactAndFlagStateSources:
    """Contacts read the tile's ``statusId``; unit-28 flags read their own value.

    Both entities are built from the same kind of tile, and each case is arranged
    so the two candidate fields disagree. A test where they agreed would pass
    against either implementation and prove nothing.
    """

    def test_contact_takes_its_state_from_status_id(self) -> None:
        """A contact is on when statusId is 1, even though its value is 0."""
        tile = _widget_tile(
            status_id=1,
            widget={"txtId": 5320, "unit": -1, "type": 0, "value": 0},
        )
        entity = binary_sensor.TileWidgetContactSensor(
            tile, _Coordinator(), _Entry(), "widget1"
        )

        assert entity.get_state(tile) is True

    def test_flag_takes_its_state_from_its_own_value(self) -> None:
        """A flag is on when its own value is 1, even though statusId is 0."""
        tile = _widget_tile(
            status_id=0,
            widget={"txtId": 4640, "unit": 28, "type": 1, "value": 1},
        )
        entity = binary_sensor.TileWidgetFlagSensor(
            tile, _Coordinator(), _Entry(), "widget1"
        )

        assert entity.get_state(tile) is True

    def test_flag_does_not_inherit_the_status_id_lookup(self) -> None:
        """A flag with an off value stays off even when statusId is on.

        This is the case that catches the inherited contact implementation: if
        the flag read ``statusId`` it would report on here.
        """
        tile = _widget_tile(
            status_id=1,
            widget={"txtId": 4640, "unit": 28, "type": 1, "value": 0},
        )
        entity = binary_sensor.TileWidgetFlagSensor(
            tile, _Coordinator(), _Entry(), "widget1"
        )

        assert entity.get_state(tile) is False


class TestDeprecatedFlagSensor:
    """The numeric sensor that value type 28 widgets used to be exposed as."""

    def test_absent_legacy_entity_is_not_rebuilt(self) -> None:
        """A fresh install gets no deprecated sensor and no repair issue."""
        registry = _Registry(entity_id=None)
        issues = _record_issues()

        assert _deprecate(registry) is False
        assert registry.removed == []
        assert issues == []

    def test_enabled_entity_is_rebuilt_and_warns(self) -> None:
        """While the entity is enabled it keeps working, and the user is told."""
        registry = _Registry(entity_id="sensor.flag", disabled=False)
        issues = _record_issues()

        assert _deprecate(registry) is True
        assert registry.removed == []
        assert [issue["translation_key"] for issue in issues] == [
            "deprecated_flag_sensor"
        ]
        assert issues[0]["severity"] == "warning"
        assert issues[0]["breaks_in_ha_version"] == "2027.5.0"
        assert issues[0]["translation_placeholders"] == {"entity_id": "sensor.flag"}

    def test_references_block_removal_and_are_named(self) -> None:
        """A disabled entity that is still referenced is kept, and named."""
        registry = _Registry(entity_id="sensor.flag", disabled=True)
        issues = _record_issues(
            automations=["automation.boiler"], scripts=["script.evening"]
        )

        assert _deprecate(registry) is True
        assert registry.removed == []
        assert issues[0]["translation_key"] == "deprecated_flag_sensor_used"
        items = issues[0]["translation_placeholders"]["items"]
        assert "automation.boiler" in items
        assert "script.evening" in items

    def test_disabled_unreferenced_entity_is_removed(self) -> None:
        """Disabling the entity with no references left is the acknowledgement."""
        registry = _Registry(entity_id="sensor.flag", disabled=True)
        issues = _record_issues()

        assert _deprecate(registry) is False
        assert registry.removed == ["sensor.flag"]
        assert issues == []


class TestDeprecatedFlagSensorSelection:
    """Which widgets do and do not produce a deprecated sensor."""

    def test_labelled_flag_with_a_registry_row_is_rebuilt(self) -> None:
        """An existing labelled flag entity is the only one recreated."""
        _record_issues()
        _install_registry(_Registry(entity_id="sensor.flag"))

        entities = sensor._build_deprecated_flag_sensors(
            object(), {4660: _flag_tile()}, _Coordinator(), _Entry()
        )

        assert [type(entity).__name__ for entity in entities] == [
            "TileWidgetTemperatureSensor"
        ]

    def test_nothing_is_built_without_a_registry_row(self) -> None:
        """No registry row means no entity, so new installs never see one."""
        _record_issues()
        _install_registry(_Registry(entity_id=None))

        entities = sensor._build_deprecated_flag_sensors(
            object(), {4660: _flag_tile()}, _Coordinator(), _Entry()
        )

        assert entities == []

    def test_unlabelled_and_other_widgets_are_skipped(self) -> None:
        """An unlabelled flag, or a widget that is not a flag, is skipped."""
        _record_issues()
        _install_registry(_Registry(entity_id="sensor.flag"))

        unlabelled = sensor._build_deprecated_flag_sensors(
            object(), {4660: _flag_tile(txt_id=0)}, _Coordinator(), _Entry()
        )
        temperature = sensor._build_deprecated_flag_sensors(
            object(), {4660: _flag_tile(unit=7)}, _Coordinator(), _Entry()
        )

        assert unlabelled == []
        assert temperature == []


# ---------------------------------------------------------------------------
# Menu item type 15 -- checkbox controls (issue #222)
# ---------------------------------------------------------------------------


def _kolton_menus() -> dict[str, dict[str, Any]]:
    """Return the reporter's user menu, keyed the way the API client keys it."""
    return _menus_of("MU")


def _kolton_switches() -> list[Any]:
    """Return every switch the reporter's user menu produces."""
    menus = _kolton_menus()
    coordinator = _Coordinator()
    ctx = assets.build_menu_context(menus, {}, coordinator.translations)
    return _modules["switch"]._build_menu_switches(
        menus, ctx, coordinator, _Entry(), {}
    )


def _kolton_checkbox_switches() -> dict[str, Any]:
    """Return the checkbox option switches of the reporter's menu by unique id."""
    checkbox = _modules["switch"].MenuCheckboxEntity
    return {
        entity.unique_id: entity
        for entity in _kolton_switches()
        if isinstance(entity, checkbox)
    }


def test_kolton_user_menu_switch_inventory() -> None:
    """The whole switch inventory of the reporter's user menu.

    Eight accessible on/off items (two are inaccessible and stay out) plus the
    two options of the Operating modes checkbox item, in menu order. His board
    has both operating modes available, and the ``value: 1`` bitmask means the
    first option is the one currently enabled.
    """
    assert [(entity.unique_id, entity.is_on) for entity in _kolton_switches()] == [
        (f"{_UDID}_menu_MU_2311", True),
        (f"{_UDID}_menu_MU_30029_option_128", True),
        (f"{_UDID}_menu_MU_30029_option_3645", False),
        (f"{_UDID}_menu_MU_1049", True),
        (f"{_UDID}_menu_MU_1076", False),
        (f"{_UDID}_menu_MU_2165", True),
        (f"{_UDID}_menu_MU_1095", False),
        (f"{_UDID}_menu_MU_2164", False),
        (f"{_UDID}_menu_MU_1645", False),
        (f"{_UDID}_menu_MU_2323", False),
    ]


def test_checkbox_option_switches_are_named_after_their_option() -> None:
    """Each option switch takes the option label, not the group's label.

    The item's own label belongs to the group, which several switches share, so
    the option's subtitle id is what names and identifies the entity.
    """
    switches = _kolton_checkbox_switches()

    assert [(entity.name, entity.unique_id) for entity in switches.values()] == [
        ("label-128", f"{_UDID}_menu_MU_30029_option_128"),
        ("label-3645", f"{_UDID}_menu_MU_30029_option_3645"),
    ]


def test_inaccessible_checkbox_item_produces_no_switch() -> None:
    """An inaccessible checkbox item stays out, even sharing the group label.

    The reporter's menu carries label 820 twice: the accessible two-option item
    and an inaccessible three-option one. Registering both would duplicate the
    group, so only the accessible item creates switches.
    """
    menus = _kolton_menus()
    item = menus["MU_30030"]

    assert item["access"] is False
    assert item["params"]["options"] == [128, 3645, 1815]
    assert not [key for key in _kolton_checkbox_switches() if "30030" in key]


async def test_turning_one_option_keeps_the_other_options() -> None:
    """A write sends every option with the state it should end up in.

    That is the payload the eModul app uses for a checkbox item, and it is what
    keeps the other boxes as the user set them: the group starts as ``value: 1``,
    so switching the second option on leaves the first on, and switching the
    first off afterwards leaves the second on.
    """
    switches = _kolton_checkbox_switches()
    first = switches[f"{_UDID}_menu_MU_30029_option_128"]
    second = switches[f"{_UDID}_menu_MU_30029_option_3645"]
    api = first.coordinator.api

    await second.async_turn_on()

    assert api.calls == [
        (
            "MU",
            30029,
            {"many_of_many": [{"id": 0, "value": 1}, {"id": 1, "value": 1}]},
        )
    ]
    assert (first.is_on, second.is_on) == (True, True)

    await first.async_turn_off()

    assert api.calls[-1] == (
        "MU",
        30029,
        {"many_of_many": [{"id": 0, "value": 0}, {"id": 1, "value": 1}]},
    )
    assert (first.is_on, second.is_on) == (False, True)


async def test_user_menu_dialogue_is_the_factory_reset_not_a_lockout() -> None:
    """The user menu's only dialogue is factory settings, not a clear-lockout.

    Issue #222 asked for the clear-lockout control, and this item was read as
    it: menu type 20, so :mod:`button` maps it, and the one dialogue in his
    user menu. The eModul subtitle catalog says otherwise -- text 839 is
    "Ustawienia fabryczne" and the question it confirms, 838 ("Czy przywrócić
    ustawienia fabryczne?"), is a factory reset. A button named after 839 is
    therefore that reset; the clear-lockout control the reporter still misses
    is not in this tree at all, see
    :func:`test_service_menu_dialogue_becomes_a_button`.
    """
    menus = _kolton_menus()
    dialogues = [
        item
        for item in menus.values()
        if item.get("type") == const.MENU_ITEM_TYPE_DIALOGUE
    ]

    assert [item["id"] for item in dialogues] == [10000]

    item = dialogues[0]
    assert (item["txtId"], item["params"]["txtId"], item["params"]["type"]) == (
        839,
        838,
        1,
    )

    coordinator = _Coordinator()
    entity = _modules["button"].MenuButtonEntity(
        item, "MU_10000", coordinator, _Entry(), {}, depth=0
    )

    assert (entity.name, entity.unique_id) == ("label-839", f"{_UDID}_menu_MU_10000")
    # A factory reset is one press away from wiping the controller, so it is
    # registered disabled even though it sits at the top level.
    assert not entity.entity_registry_enabled_default

    await entity.async_press()

    # A Yes/No dialogue: confirming it sends 1, the app's "Tak".
    assert coordinator.api.calls == [("MU", 10000, {"type": 1, "value": 1})]


# ---------------------------------------------------------------------------
# Menu trees -- the clear-lockout control lives in the service tree (#222)
# ---------------------------------------------------------------------------

# The item the reporter traced in #222: "Zdjęcie blokady", the clear-lockout
# dialogue of his heat pump's service tree, whose sub-type 2 is what makes a
# press send {"type": 2, "value": 3}. The item id is his, and the tree it lives
# in is now his own dump rather than a stand-in.
_SERVICE_LOCKOUT_ID = 1537


def _service_menu() -> dict[str, dict[str, Any]]:
    """Return the reporter's service tree, keyed the way the API client keys it.

    This is his own ``/menu/MS/`` dump, committed as a fixture with the service
    password replaced by a placeholder: the tree under "Menu serwis" that holds
    "Blokada presostatu", whose clear-lockout dialogue is item 1537 with
    sub-type 2 -- the control #222 is about. The dump also pins the nesting depth
    that the enabled-by-default rule is measured against, which the synthetic
    tree this replaces could only approximate.
    """
    return _menus_of("MS")


def _menus_of(menu_type: str) -> dict[str, dict[str, Any]]:
    """Return one tree of the reporter's controller, keyed as the client keys it."""
    payload = json.loads(
        (_REPO_ROOT / "tests/fixtures/kolton_st5305/menus.json").read_text()
    )
    return {
        f"{item['menuType']}_{item['id']}": item
        for item in payload[menu_type]["data"]["elements"]
        if isinstance(item, dict) and item.get("id") is not None
    }


class _MenuTrees:
    """Stub for ``Tech.get`` serving one element per menu tree.

    A tree can be refused in the three ways the API refuses one, and the
    difference matters to the caller:

    - ``refused``: a ``TechError``, which is not a gate at all.
    - ``messaged``: an answer with a message instead of elements -- HTTP 200,
      body ``{"message": "missing items in <TYPE> menu"}``, no ``data``. This is
      what a gated tree answers, and what a real controller's manufacturer tree
      answers at all times.
    - ``gated``: a ``(tree, code)`` pair. The tree answers with its root alone,
      whose ``params.password`` marks it as needing a code, and the rest arrives
      only for the request that carries ``0:<code>``. A code that does not match is
      answered with the API's documented ``422 Invalid parameter pin`` -- or, with
      ``empty_pin``, with a 2xx whose element list is empty, the other shape a
      refused code has been seen in.

    ``bodies`` serves recorded refusal payloads verbatim, so the gated path can
    be tested against what the API really sent rather than a stand-in.
    """

    def __init__(
        self,
        refused: str | None = None,
        messaged: str | None = None,
        gated: tuple[str, str] | None = None,
        bodies: dict[str, dict[str, Any]] | None = None,
        empty_pin: bool = False,
    ) -> None:
        """Record how each tree answers, and start with no requests."""
        self.paths: list[str] = []
        self._refused = refused
        self._messaged = messaged
        self._gated = gated
        self._bodies = bodies or {}
        self._empty_pin = empty_pin

    @staticmethod
    def _refusal(menu_type: str) -> dict[str, Any]:
        """Return the message a tree the account may not read answers with."""
        return {"message": f"missing items in {menu_type} menu"}

    def _served(self, menu_type: str) -> dict[str, Any]:
        """Return one element for a tree the stub is willing to serve."""
        element = {"menuType": menu_type, "id": len(self.paths), "type": 0}
        return {"data": {"elements": [element]}}

    def _gated_answer(self, menu_type: str, segment: str) -> dict[str, Any]:
        """Answer a tree held behind a code the way the live API does.

        Its root alone without a code, and the root carries ``params.password``;
        the rest only once the segment names that root and the code it wants; and
        an empty element list for a segment that does not match. All three shapes
        were observed live, and the last one is what the eModul app reads as a
        wrong code.
        """
        root = {
            "menuType": menu_type,
            "id": 0,
            "parentId": 0,
            "type": 0,
            "access": True,
            "txtId": 391,
            "params": {"description": "Element gruping menu", "password": "password"},
        }
        if segment == f"0:{self._gated[1]}":
            child = {
                "menuType": menu_type,
                "id": 7,
                "parentId": 0,
                "type": 20,
                "access": True,
                "params": {"type": 2, "value": -1},
            }
            return {"data": {"elements": [root, child]}}
        if segment:
            if self._empty_pin:
                # The other shape a refused code was seen in: a 2xx whose element
                # list is simply empty, which is what the eModul app checks for.
                return {"data": {"elements": []}}
            raise _tech_module.TechError(422, '{"error":"Invalid parameter pin"}')
        return {"data": {"elements": [root]}}

    async def __call__(self, path: str) -> dict[str, Any]:
        """Record the request and answer it, or raise where the tree is refused."""
        self.paths.append(path)
        # A menu request has two shapes: the tree alone (".../MS/"), and the tree
        # with the code's path segment (".../MS/0:1989").
        menu_type, _, segment = path.rsplit("/menu/", 1)[-1].partition("/")
        if menu_type == self._refused:
            raise _tech_module.TechError(403, "menu not available")
        if menu_type in self._bodies:
            return self._bodies[menu_type]
        if self._gated is not None and menu_type == self._gated[0]:
            return self._gated_answer(menu_type, segment)
        if menu_type == self._messaged:
            return self._refusal(menu_type)
        return self._served(menu_type)


def _menu_client(
    menu_codes: dict[str, str] | None = None, **transport: Any
) -> tuple[Any, _MenuTrees]:
    """Return a ``Tech`` client whose only stub is the menu tree transport."""
    tech = _tech_module.Tech.__new__(_tech_module.Tech)
    tech.user_id = 7
    # The real constructor sets this; ``__new__`` skips it.
    tech.menu_codes = dict(menu_codes or {})
    transport_stub = _MenuTrees(**transport)
    tech.get = transport_stub
    return tech, transport_stub


def _refused_bodies() -> dict[str, dict[str, Any]]:
    """Return the refusal bodies the API sent the demo account, as recorded.

    The demo account is refused the three trees a consumer account cannot read,
    so this fixture holds both sides of the gate: the message a refusal is made
    of, and the trees a served controller answers with, which are in
    ``tests/fixtures/kolton_st5305/menus.json``.
    """
    return json.loads(
        (_REPO_ROOT / "tests/fixtures/demo_refused_menus.json").read_text()
    )


async def test_every_menu_tree_is_fetched() -> None:
    """The controller is asked for all four of its menu trees.

    The service tree is where a heat pump keeps the clear-lockout control, so
    not asking for it left the reporter of #222 with the lockout on a sensor and
    no way to clear it. Items are keyed by tree, so the same item id in two trees
    cannot collide.
    """
    tech, transport = _menu_client()

    items = await tech._fetch_menu_data("abcd")

    assert transport.paths == [
        f"users/7/modules/abcd/menu/{menu_type}/" for menu_type in const.MENU_TYPES
    ]
    assert sorted(items) == ["MI_2", "MP_4", "MS_3", "MU_1"]


async def test_a_refused_menu_tree_leaves_the_others_alone() -> None:
    """One unreadable tree does not cost the controller the remaining three.

    The API answers a tree the account may not read with ``TechError`` -- the
    manufacturer tree of a consumer account is locked on the controllers we have
    dumps of. That used to be harmless because only two trees were requested;
    now it has to be contained per tree.
    """
    tech, transport = _menu_client(refused="MP")

    items = await tech._fetch_menu_data("abcd")

    assert transport.paths == [
        f"users/7/modules/abcd/menu/{menu_type}/" for menu_type in const.MENU_TYPES
    ]
    assert sorted(items) == ["MI_2", "MS_3", "MU_1"]


async def test_a_menu_tree_answered_with_a_message_loses_nothing() -> None:
    """A tree that answers with a message instead of elements is not an error.

    A real controller's manufacturer tree answers ``{"message": "missing items
    in MP menu"}`` -- no ``data``, no elements -- and that is not a ``TechError``,
    so only the shape of the answer tells it apart from a served tree. It must
    cost that tree alone, leaving the other three and the rest of the poll
    intact; it is also why the item count logged for a controller can be far
    below what its dumps hold.
    """
    tech, transport = _menu_client(messaged="MP")

    items = await tech._fetch_menu_data("abcd")

    assert transport.paths == [
        f"users/7/modules/abcd/menu/{menu_type}/" for menu_type in const.MENU_TYPES
    ]
    assert sorted(items) == ["MI_2", "MS_3", "MU_1"]


async def test_service_menu_dialogue_becomes_a_working_button() -> None:
    """The clear-lockout dialogue of the service tree reaches Home Assistant.

    The button is named after its group and label ("Blokada presostatu -
    Zdjęcie blokady" with the real catalog), registered enabled because the
    group is top level, and pressing it sends the payload the reporter traced in
    the app for this very item: ``{"value": 3, "type": 2}`` on ido 1537.
    """
    entry = _Entry()
    coordinator = _Coordinator(_service_menu())
    added: list[Any] = []
    hass = types.SimpleNamespace(data={const.DOMAIN: {entry.entry_id: coordinator}})

    await _modules["button"].async_setup_entry(
        hass, entry, lambda entities, update: added.extend(entities)
    )

    lockout = f"{_UDID}_menu_MS_{_SERVICE_LOCKOUT_ID}"
    # The service tree carries four dialogues and the clear-lockout is one of
    # them: all four register from that tree, and this one is the control #222
    # asks for.
    assert len(added) == 4
    by_id = {entity.unique_id: entity for entity in added}
    assert lockout in by_id

    button = by_id[lockout]
    assert button.name == "label-4764 - label-8395"
    assert button.entity_registry_enabled_default
    assert button._attr_available  # access: true while there is a lockout

    # The tree also carries two factory-reset dialogues (one top-level, one
    # under "Zabezpieczenia"). They register, but disabled.
    assert not by_id[f"{_UDID}_menu_MS_2457"].entity_registry_enabled_default
    assert not by_id[f"{_UDID}_menu_MS_10002"].entity_registry_enabled_default

    await button.async_press()

    assert coordinator.api.calls == [
        ("MS", _SERVICE_LOCKOUT_ID, {"type": 2, "value": 3})
    ]


def test_fan_lockout_button_says_what_it_clears() -> None:
    """The fan lockout button no longer shares its name with the binary sensor.

    Its label is "Blokada wentylatora" -- the same text as the flag sensor --
    while the pressure-switch dialogue is already labelled with the action. The
    dialogue's ``params.txtId`` is the shared "Brak blokady" status, which is
    what marks it as a lockout control; the action label from the same catalogue
    is appended so a press reads as "Blokada wentylatora - Zdjęcie blokady".
    """
    item = _service_menu()["MS_2746"]

    entity = _modules["button"].MenuButtonEntity(
        item, "MS_2746", _Coordinator(), _Entry(), {}, depth=0
    )

    assert entity.name == "label-6956 - label-8395"
    assert entity.entity_registry_enabled_default


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"type": 0}, {"type": 0, "value": 2}),
        ({"type": 1}, {"type": 1, "value": 1}),
        ({"type": 2}, {"type": 2, "value": 3}),
        # A sub-type the app draws no control for: keep the value this platform
        # has always sent rather than invent one.
        ({"type": 9}, {"type": 9, "value": 1}),
        # No sub-type at all reads as 0, which the app shows as its OK button.
        ({}, {"type": 0, "value": 2}),
    ],
    ids=["ok", "yes-no", "traced", "unmapped", "absent"],
)
async def test_dialogue_press_value_follows_the_item_sub_type(
    params: dict[str, int], expected: dict[str, int]
) -> None:
    """The confirm value comes from the sub-type, as the app's control sends it.

    The app's dialogue template switches on ``params.type``: 1 is Yes/No, where
    its two buttons send 1 ("Tak") and 0 ("Nie") and a Home Assistant press
    confirms; 0 draws one OK button sending 2; and 2, the clear-lockout
    dialogue, draws one cancel-styled button sending 3. Only the value varies --
    the sub-type itself goes back to the controller untouched.
    """
    item = dict(_service_menu()[f"MS_{_SERVICE_LOCKOUT_ID}"])
    item["parentId"] = 0
    # Built from scratch rather than merged over the lockout item's params, so
    # that the "absent" case really has no sub-type to fall back on.
    item["params"] = {"txtId": 8395, "value": -1, "blockHide": 0, **params}
    coordinator = _Coordinator()
    entity = _modules["button"].MenuButtonEntity(
        item, f"MS_{_SERVICE_LOCKOUT_ID}", coordinator, _Entry(), {}, depth=0
    )

    await entity.async_press()

    assert coordinator.api.calls == [("MS", _SERVICE_LOCKOUT_ID, expected)]


# ---------------------------------------------------------------------------
# The gate: a tree the account may not read until it is given a code (#222)
# ---------------------------------------------------------------------------


def test_the_recorded_refusal_is_a_message_and_not_an_error() -> None:
    """Pin down the shape of a refusal, which is the only signal there is.

    The body is recorded from the demo account, which is refused the three trees
    a consumer account cannot read. There is no ``data``, no elements and no
    ``status``: HTTP 200 with a message is what a gated tree answers, so the
    status code says nothing and the body has to be read.
    """
    bodies = _refused_bodies()

    assert sorted(bodies) == ["MP", "MS", "MU"]
    for menu_type, body in bodies.items():
        assert body == {"message": f"missing items in {menu_type} menu"}
        assert "data" not in body
        assert "status" not in body


async def test_a_recorded_refusal_costs_only_its_own_tree() -> None:
    """The recorded bodies are handled as refusals, and cost no other tree.

    This is the gated path tested against what the API actually sent rather than
    a hand-built payload, and it is why a controller that answers for two trees
    can still lose three of them silently: each refusal costs its own tree and
    nothing else, and leaves no error behind for anyone to notice.
    """
    tech, _ = _menu_client(bodies=_refused_bodies())

    items = await tech._fetch_menu_data("abcd")

    assert sorted(key.split("_")[0] for key in items) == ["MI"]
    # And nothing is reported for them: a menu the account may not read is how
    # those trees have always behaved, so a refusal on its own is not news.
    assert tech.menu_code_rejections == set()


async def test_a_tree_configured_with_a_code_is_retried_once_and_arrives() -> None:
    """A code the user supplied turns a refused tree into a served one.

    The retry is the same GET with ``0:<code>`` appended, which is the documented
    pairing: the code belongs to the tree root. It happens once, right after the
    refusal that prompted it, and the tree's items then reach the controller's
    cache like any other tree's.
    """
    tech, transport = _menu_client(gated=("MS", "1989"), menu_codes={"MS": "1989"})

    items = await tech._fetch_menu_data("abcd")

    assert list(transport.paths) == [
        "users/7/modules/abcd/menu/MU/",
        "users/7/modules/abcd/menu/MI/",
        "users/7/modules/abcd/menu/MS/",
        "users/7/modules/abcd/menu/MS/0:1989",
        "users/7/modules/abcd/menu/MP/",
    ]
    # The tree opened: its child arrived beside the root that was all it would
    # give away without the code.
    assert "MS_7" in items
    assert tech.menu_code_rejections == set()


async def test_a_code_the_controller_rejects_is_tried_once_and_recorded() -> None:
    """A code the controller will not accept is tried once and reported.

    The refusal is the API's documented ``422 Invalid parameter pin`` -- the same
    answer the write path gives for a bad pin -- so the tree keeps the root it
    handed over and the code is recorded rather than retried.
    """
    tech, transport = _menu_client(gated=("MS", "1989"), menu_codes={"MS": "0000"})

    items = await tech._fetch_menu_data("abcd")

    assert transport.paths.count("users/7/modules/abcd/menu/MS/0:0000") == 1
    # The tree stayed shut: all it gave away is the root, and the child the right
    # code would have brought never arrived.
    assert "MS_7" not in items
    assert "MS_0" in items
    assert tech.menu_code_rejections == {"MS"}


async def test_an_unlock_answered_with_nothing_is_not_an_unlock() -> None:
    """An empty element list is the other shape a refused code has been seen in.

    The eModul app reads exactly this as a wrong code, so it is treated as the 422
    is: the tree keeps its root and the code is recorded.
    """
    tech, _ = _menu_client(
        gated=("MS", "1989"), menu_codes={"MS": "0000"}, empty_pin=True
    )

    items = await tech._fetch_menu_data("abcd")

    assert "MS_7" not in items
    assert "MS_0" in items
    assert tech.menu_code_rejections == {"MS"}


async def test_a_tree_left_shut_keeps_the_root_it_gave_away() -> None:
    """A gated tree with no code contributes exactly what it handed over.

    Its root is a group, so it becomes no entity at all -- which is the silent
    absence the reporter saw.
    """
    tech, transport = _menu_client(gated=("MS", "1989"))

    items = await tech._fetch_menu_data("abcd")

    assert list(transport.paths) == [
        f"users/7/modules/abcd/menu/{menu_type}/" for menu_type in const.MENU_TYPES
    ]
    assert "MS_0" in items
    assert "MS_7" not in items
    assert tech.menu_code_rejections == set()


async def test_a_tree_the_account_may_not_read_is_never_retried() -> None:
    """A message refusal is not a gate, and must not be sent a code.

    The two blocked shapes differ: a gated tree hands over its root and can be
    opened, while a menu the account may not read answers with a message and has
    no password element to pair a code with. Retrying the second would be asking
    the wrong question, and would read as a rejected code.
    """
    tech, transport = _menu_client(messaged="MS", menu_codes={"MS": "1989"})

    await tech._fetch_menu_data("abcd")

    assert transport.paths.count("users/7/modules/abcd/menu/MS/0:1989") == 0
    assert tech.menu_code_rejections == set()


class _FakeResponse:
    """Minimal stand-in for an aiohttp response, for the real ``Tech.get``."""

    status = 200

    async def json(self) -> dict[str, Any]:
        """Return an empty element list."""
        return {"data": {"elements": []}}

    async def text(self) -> str:
        """Return nothing; only read on an error status."""
        return ""

    async def __aenter__(self) -> _FakeResponse:
        """Enter the response context."""
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        """Leave the response context."""
        return False


class _FakeSession:
    """Stand-in for the aiohttp session, recording the URLs requested."""

    def __init__(self) -> None:
        """Start with no requests recorded."""
        self.urls: list[str] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        """Record the request and return a response."""
        self.urls.append(url)
        return _FakeResponse()


async def test_a_menu_code_is_masked_out_of_the_request_log(caplog: Any) -> None:
    """The code travels in the request path, and the path is logged.

    ``.../menu/MS/0:<code>`` would put the credential in the log and in any
    diagnostic download made of it, so the request line masks it. This drives the
    real ``get``, because a stubbed transport never reaches the log line.
    """
    tech = _tech_module.Tech.__new__(_tech_module.Tech)
    tech.base_url = _tech_module.Tech.TECH_API_URL
    tech.headers = {}
    tech.timeout = None
    tech.session = _FakeSession()

    with caplog.at_level(logging.DEBUG):
        await tech.get("users/7/modules/abcd/menu/MS/0:1989")

    assert "1989" not in caplog.text
    assert "/menu/MS/0:**REDACTED**" in caplog.text


def test_only_a_menu_code_is_masked_in_a_path() -> None:
    """A path with no code keeps its shape, and every code in one is masked."""
    assert (
        _tech_module._redact_menu_pin("users/7/modules/abcd") == "users/7/modules/abcd"
    )
    assert (
        _tech_module._redact_menu_pin("users/7/modules/abcd/menu/MS/0:1989")
        == "users/7/modules/abcd/menu/MS/0:**REDACTED**"
    )
    # The documented multi-element form carries one code per element.
    assert (
        _tech_module._redact_menu_pin("users/7/modules/abcd/menu/MS/0:1234,33:4321")
        == "users/7/modules/abcd/menu/MS/0:**REDACTED**,33:**REDACTED**"
    )


def _writing_client(menu_codes: dict[str, str]) -> tuple[Any, list[tuple[str, str]]]:
    """Return a ``Tech`` client recording what it would POST."""
    tech = _tech_module.Tech.__new__(_tech_module.Tech)
    tech.user_id = 7
    tech.authenticated = True
    tech.menu_codes = dict(menu_codes)
    sent: list[tuple[str, str]] = []

    async def _post(path: str, payload: str) -> dict[str, Any]:
        sent.append((path, payload))
        return {"status": "success"}

    tech.post = _post
    return tech, sent


async def test_a_menu_write_carries_the_code_in_the_body() -> None:
    """A write into a gated tree attaches the code as a body field.

    The spec is explicit that an item behind a lock needs the code attached --
    "when a menu item is locked you need to attach a pin", as ``{"pin": 1234,
    "value": 25}`` -- and lists a ``422 Invalid parameter pin`` for one it
    rejects. Without this the reporter's clear-lockout button would reach a tree
    it can read and still be refused the write.
    """
    tech, sent = _writing_client({"MS": "1989"})

    await tech.set_menu_value(
        "abcd", "MS", _SERVICE_LOCKOUT_ID, {"type": 2, "value": 3}
    )

    (path, payload) = sent[0]
    assert path == f"users/7/modules/abcd/menu/MS/ido/{_SERVICE_LOCKOUT_ID}"
    assert json.loads(payload) == {"type": 2, "value": 3, "pin": "1989"}


async def test_a_menu_write_without_a_code_sends_no_pin() -> None:
    """An entry with no codes writes exactly what it always wrote.

    The key is absent rather than empty, so a controller that never needed a code
    cannot be sent a stray field by this feature.
    """
    tech, sent = _writing_client({})

    await tech.set_menu_value("abcd", "MU", 3550, {"value": 1})

    assert json.loads(sent[0][1]) == {"value": 1}


async def test_the_menu_code_never_reaches_the_log(caplog: Any) -> None:
    """The code is sent, never logged.

    It is a credential of the same kind as the token, and the write path logs its
    payload at debug level, which is exactly where a code would leak into a
    diagnostic download.
    """
    tech, _ = _writing_client({"MS": "1989"})

    with caplog.at_level(logging.DEBUG):
        await tech.set_menu_value("abcd", "MS", _SERVICE_LOCKOUT_ID, {"type": 2})

    assert "1989" not in caplog.text


def _install_issue_recorder() -> tuple[list[dict[str, Any]], list[str]]:
    """Point the issue registry at recording fakes and return what it saw.

    Patched on the module object ``coordinator.py`` actually bound rather than
    through ``sys.modules``: the stub harness and a real Home Assistant install
    both live in this interpreter, and which of the two that import resolved to
    depends on the order the test modules were collected in.
    """
    created: list[dict[str, Any]] = []
    deleted: list[str] = []

    def _create(hass: Any, domain: str, issue_id: str, **kwargs: Any) -> None:
        created.append({"domain": domain, "issue_id": issue_id, **kwargs})

    def _delete(hass: Any, domain: str, issue_id: str) -> None:
        deleted.append(issue_id)

    _coordinator.ir.async_create_issue = _create
    _coordinator.ir.async_delete_issue = _delete
    return created, deleted


def _menu_coordinator() -> Any:
    """Return a coordinator carrying only what the issue sync reads.

    Built with ``__new__`` the way this module builds its ``Tech`` clients. The
    test modules here share the interpreter's import cache, so which
    ``DataUpdateCoordinator`` the real class ends up deriving from depends on
    collection order; the method under test needs neither the base class nor its
    constructor, only ``hass`` and the entry it scopes the issue ids by.
    """
    coordinator = _coordinator.TechCoordinator.__new__(_coordinator.TechCoordinator)
    coordinator.hass = object()
    coordinator.config_entry = types.SimpleNamespace(
        # "name" is ``CONF_NAME``: the controller the coordinator logs for.
        data={const.CONTROLLER: {const.UDID: _UDID, "name": _HUB}}
    )
    return coordinator


def test_a_rejected_code_is_the_only_refusal_worth_reporting() -> None:
    """A code the controller refused is reported; nothing else is.

    A refused menu is not news in itself: on a consumer account the manufacturer
    menu is refused on every controller and the user menu on some, so reporting
    each refusal would leave a permanent, unactionable notice on almost every
    installation. A code the user supplied and the controller would not accept is
    different -- it is specific, and they can act on it.
    """
    created, deleted = _install_issue_recorder()
    coordinator = _menu_coordinator()

    coordinator._async_sync_menu_code_issues({"MS"})

    assert [issue["issue_id"] for issue in created] == [
        f"menu_code_rejected_{_UDID}_MS"
    ]
    assert created[0]["translation_key"] == "menu_code_rejected"
    assert created[0]["translation_placeholders"] == {"menu_type": "MS"}
    assert created[0]["is_fixable"] is False
    # Every other tree's notice is swept in the same pass.
    assert f"menu_code_rejected_{_UDID}_MU" in deleted
    assert len(deleted) == len(const.MENU_TYPES) - 1


def test_nothing_is_reported_and_stale_notices_are_cleared() -> None:
    """With no rejected code there is nothing to raise, and the old one goes.

    The same pass clears the notices of trees that are no longer rejected, so a
    code that starts being accepted -- retyped, or after the controller is reset
    -- does not leave the user looking for a problem that is gone.
    """
    created, deleted = _install_issue_recorder()
    coordinator = _menu_coordinator()

    coordinator._async_sync_menu_code_issues(set())

    assert created == []
    assert f"menu_code_rejected_{_UDID}_MS" in deleted
    assert len(deleted) == len(const.MENU_TYPES)


# ---------------------------------------------------------------------------
# The subtitle catalog cannot take the entry down with it
# ---------------------------------------------------------------------------


def _catalog_coordinator(
    *, catalog: Any = None, error: Exception | None = None
) -> tuple[Any, list[str]]:
    """Return a coordinator whose catalog and module fetches are stubbed.

    ``_async_update_data`` reads the entry's controller name and calls
    ``module_data``, so those are the only two stubs it needs to run for real.
    """
    coordinator = _menu_coordinator()
    coordinator.hass = types.SimpleNamespace(
        config=types.SimpleNamespace(language="pl")
    )
    coordinator.translations = _coordinator.Translations()
    coordinator.translations_loaded = False
    calls: list[str] = []

    async def _get_translations(language: str) -> Any:
        calls.append(language)
        if error is not None:
            raise error
        return catalog

    async def _module_data(udid: str, force: bool = False) -> dict:
        return {"menu_code_rejections": set()}

    coordinator.api = types.SimpleNamespace(
        get_translations=_get_translations, module_data=_module_data
    )
    return coordinator, calls


async def test_a_failing_subtitle_catalog_costs_names_not_entities() -> None:
    """An i18n outage must not cost the user everything.

    On 2026-10-13 the API's ``i18n`` endpoint answered 400 for every language,
    and the catalog is loaded inside ``async_setup_entry``: letting that escape
    failed the whole entry, and with it every zone, tile and menu control the
    user had. The catalog only names things, and ``Translations`` was written to
    degrade to the raw text ids, so the failure is logged and nothing else.
    """
    coordinator, calls = _catalog_coordinator(
        error=_tech_module.TechError(400, "Bad Request")
    )

    await coordinator.async_load_translations()

    assert calls == ["pl"]
    assert coordinator.translations_loaded is False
    assert coordinator.translations.get_text(8395) == "txtId 8395"


async def test_the_catalog_is_adopted_when_the_api_serves_it() -> None:
    """A served catalog is used, and its labels resolve as before."""
    coordinator, _ = _catalog_coordinator(catalog={"data": {"8395": "Zdjęcie blokady"}})

    await coordinator.async_load_translations()

    assert coordinator.translations_loaded is True
    assert coordinator.translations.get_text(8395) == "Zdjęcie blokady"


async def test_a_failed_catalog_is_retried_on_the_next_refresh() -> None:
    """The fetch is retried until it lands, so a repaired API needs no restart."""
    _install_issue_recorder()
    coordinator, calls = _catalog_coordinator(
        error=_tech_module.TechError(400, "Bad Request")
    )

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert calls == ["pl", "pl"]


async def test_a_loaded_catalog_is_never_fetched_again() -> None:
    """Once the catalog is in, later refreshes stop asking for it.

    The retry rides on the polling cadence, so it has to stop the moment it
    succeeds: otherwise every poll pays for a request it does not need.
    """
    _install_issue_recorder()
    coordinator, calls = _catalog_coordinator(catalog={"data": {"8395": "x"}})

    await coordinator._async_update_data()
    await coordinator._async_update_data()

    assert calls == ["pl"]
