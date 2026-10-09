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


# The subclasses each platform module declares for its own entity type.
for _name in ("switch", "button", "select", "number"):
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
        module.UnitOfTemperature = _AutoNamespace()
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
    elif name == "homeassistant.helpers.issue_registry":
        module.IssueSeverity = _AutoNamespace()
        module.async_create_issue = _async_create_issue
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
_load_tech_module("tech")
_load_tech_module("coordinator")
sensor = _load_tech_module("sensor")

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


class _Api:
    """Async API stub; the menu payload is irrelevant to these tests."""

    async def get_module_menus(self, udid: str) -> dict:
        """Return an empty menu tree."""
        return {}

    async def get_module_zones(self, udid: str) -> dict:
        """Return an empty zone payload."""
        return {}


class _Coordinator:
    """Stand-in for ``TechCoordinator``."""

    def __init__(self) -> None:
        """Wire up the API, translation catalog and cache."""
        self.api = _Api()
        self.translations = _Translations()
        self.udid = _UDID
        self.data: dict = {}


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
def test_zone_entity_uses_the_zone_device_name(module_name: str, class_name: str) -> None:
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
        {101: {"description": {"name": "Strefa 1"}}},
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
        {101: {"description": {"name": "Strefa 1"}}},
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
