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
import pathlib
import sys
import types
from typing import Any

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"

_UDID = "d" * 32
_HUB = "L-8 DEMO"
# What the API reports for a controller: one string carrying its model and its
# firmware, which every device under it is described from.
_TECH_VERSION = "TECH: L8 (v.2.1.19)"
_TECH_MODEL = "L8"
_TECH_FIRMWARE = "v.2.1.19"

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
    "homeassistant.components.binary_sensor.const",
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
    "homeassistant.helpers.storage",
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
    """Stand-in for ``CoordinatorEntity``; stores the coordinator, reports its state."""

    def __class_getitem__(cls, item: Any) -> type[CoordinatorEntity]:
        """Accept the coordinator type the real base is parameterised with.

        ``entity.py`` derives from ``CoordinatorEntity[TechCoordinator]``, the way
        Home Assistant's generic base is meant to be used; this stub only has to
        keep that subscription working.
        """
        return cls

    def __init__(self, coordinator: Any = None, *args: Any, **kwargs: Any) -> None:
        """Store the coordinator the way the real base class does."""
        super().__init__(*args, **kwargs)
        self.coordinator = coordinator

    @property
    def available(self) -> bool:
        """Report availability the way the real base class does.

        The real ``CoordinatorEntity`` overrides ``Entity.available`` with the
        coordinator's last poll result, which is also why an entity cannot
        express its own availability by assigning ``_attr_available``.
        """
        return self.coordinator.last_update_success


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
        module.ATTR_SW_VERSION = "sw_version"
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
    elif name == "homeassistant.components.binary_sensor.const":
        # The device classes live in the component's own const module, the way
        # the sensor ones do; sensor.py imports them from there.
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
        # identity.py reads these off a row and converts them back on restore.
        module.RegistryEntry = type("RegistryEntry", (), {})
        module.RegistryEntryDisabler = _AutoNamespace()
        module.RegistryEntryHider = _AutoNamespace()
    elif name == "homeassistant.helpers.storage":
        # The identity store is never opened by the stubbed suite: identity.py
        # only names Store in an annotation once it has one.
        class Store:  # noqa: D101 - a stub, and only its name is used here.
            pass

        module.Store = Store
    elif name == "homeassistant.helpers.icon":
        module.icon_for_signal_level = lambda level: "mdi:signal"
    elif name == "homeassistant.helpers.typing":
        module.StateType = object
        module.UndefinedType = type("UndefinedType", (), {})
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
                "storage",
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
_load_tech_module("coordinator")
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


# ---------------------------------------------------------------------------
# What counts as reported, for the removal of entities the controller drops
# ---------------------------------------------------------------------------


def _tile_entry(tile_id: int, *, visibility: bool = True) -> dict[str, Any]:
    """Return a tile entry as the API sends it."""
    return {"id": tile_id, "type": 1, "visibility": visibility, "params": {"value": 1}}


def _zone_entry(
    zone_id: int, *, visibility: bool = True, state: str = "zoneOn"
) -> dict[str, Any]:
    """Return a zone entry as the API sends it."""
    return {"zone": {"id": zone_id, "visibility": visibility, "zoneState": state}}


async def _recorded(
    *, tiles: list[dict[str, Any]], zones: list[dict[str, Any]]
) -> dict[str, Any]:
    """Return what the client records as reported for a payload of those entries.

    The record is what the removal decision reads, so a payload of hidden or
    unregistered entries is how one is set up without a controller.
    """
    tech = _tech_module.Tech(None, "7", "token")

    async def _get_module_data(udid: str) -> dict[str, Any]:
        return {"zones": {"elements": zones}, "tiles": tiles}

    async def _get(path: str) -> dict[str, Any]:
        return {"data": {"elements": []}}

    tech.get_module_data = _get_module_data
    tech.get = _get
    data = await tech.module_data("abcd")
    return data["reported"]


async def test_an_invisible_tile_counts_as_reported() -> None:
    """A tile hidden in the eModul app is not a tile the controller dropped.

    ``visibility`` is the app's presentation choice and the payload still carries
    the entry, so treating it as gone deletes the entity, its name, its history
    and any automation pointing at it an hour later.
    """
    reported = await _recorded(tiles=[_tile_entry(42, visibility=False)], zones=[])

    assert 42 in reported["tiles"]


async def test_an_unregistered_zone_counts_as_reported() -> None:
    """A zone that is unregistered is still the controller's own zone.

    Unregistering is what a zone does while its sensors are silent or it is
    switched off in the controller, and it is reversible, so the zone is not a
    zone the controller has dropped.
    """
    reported = await _recorded(tiles=[], zones=[_zone_entry(101, state="zoneUnregistered")])

    assert 101 in reported["zones"]


async def test_an_entry_the_controller_leaves_out_is_not_reported() -> None:
    """A payload that truly omits an entry reports nothing for it."""
    reported = await _recorded(tiles=[], zones=[])

    assert reported["tiles"] == set()
    assert reported["zones"] == set()


async def _recorded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return what the client records as reported for a recorded payload."""
    return await _recorded(
        tiles=payload.get("tiles", []),
        zones=payload.get("zones", {}).get("elements", []),
    )


@pytest.mark.parametrize("controller", ["pellet", "st2801", "st491"])
async def test_the_recorded_payloads_count_their_hidden_tiles_as_reported(
    controller: str,
) -> None:
    """A tile the controller hides is still a tile the controller sent.

    These are payloads controllers really answered with, and they mark entries
    invisible: seven on Pellet, one on st2801 and one on st491. Checking the rule
    against them, rather than against a payload written to fit it, is what makes
    it trustworthy.
    """
    payload = json.loads(
        (_REPO_ROOT / "tests" / "fixtures" / controller / "module.json").read_text()
    )
    hidden = {
        tile["id"] for tile in payload.get("tiles", []) if not tile.get("visibility")
    }
    assert hidden, f"{controller} should hide a tile, or it proves nothing"

    reported = await _recorded_payload(payload)

    assert hidden <= reported["tiles"]


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
    """Async API stub; the menu payload is irrelevant to these tests."""

    def __init__(self) -> None:
        """Record the writes an entity makes, so a test can inspect them."""
        self.menu_writes: list[tuple[str, str, int, dict]] = []

    async def get_module_menus(self, udid: str) -> dict:
        """Return an empty menu tree."""
        return {}

    async def get_module_zones(self, udid: str) -> dict:
        """Return an empty zone payload."""
        return {}

    async def set_menu_value(
        self, udid: str, menu_type: str, item_id: int, value: dict
    ) -> dict:
        """Record a menu write; what the API answers is irrelevant here."""
        self.menu_writes.append((udid, menu_type, item_id, value))
        return {"status": "success"}


class _Coordinator:
    """Stand-in for ``TechCoordinator``."""

    def __init__(self) -> None:
        """Wire up the API, translation catalog and cache."""
        self.api = _Api()
        self.translations = _Translations()
        self.udid = _UDID
        self.data: dict = {}
        # What ``CoordinatorEntity.available`` reports; a failed poll flips it.
        self.last_update_success = True
        # The controller's device id, which the entry's setup sets in production.
        self.controller_device_id: str | None = "controller-device"


class _Entry:
    """Stand-in for the config entry, with just the fields the code reads."""

    def __init__(self, title: str = _HUB, include_hub_in_name: bool = False) -> None:
        """Build an entry carrying the controller udid and the naming flag."""
        self.title = title
        self.entry_id = "entry-id"
        self.data = {
            const.CONTROLLER: {const.UDID: _UDID, const.VER: _TECH_VERSION},
            const.INCLUDE_HUB_IN_NAME: include_hub_in_name,
        }
        # The coordinator lives on the entry (``runtime_data``) rather than in a
        # ``hass.data`` mapping; a platform setup reads it from here.
        self.runtime_data: Any = None
        # The settings that are not needed to connect live in the options.
        self.options: dict = {}


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
    # The zone belongs to the controller, which the device tree shows by
    # hanging the zone device under the controller's own device id.
    assert info["via_device_id"] == "controller-device"
    # A zone has no firmware or model of its own: both come from the controller's
    # descriptor.
    assert info["sw_version"] == _TECH_FIRMWARE
    assert info["model"] == _TECH_MODEL


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
    # The controller's own device reports the model and the firmware the API's
    # descriptor carries, so it has both a heading and a version.
    assert info["sw_version"] == _TECH_FIRMWARE
    assert info["model"] == _TECH_MODEL
    # The controller is the top of this integration's device tree.
    assert "via_device_id" not in info


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
    assert info["via_device_id"] == "controller-device"


@pytest.mark.parametrize(
    ("descriptor", "model", "firmware"),
    [
        # The shapes the recorded payloads carry, wall controllers and boilers.
        ("TECH: L8 (v.2.1.19)", "L8", "v.2.1.19"),
        ("TECH: ST-402N PWM  (v.1.1.2)", "ST-402N PWM", "v.1.1.2"),
        ("TECH: ST-970 1.4.0 P01 (v.1.5.0)", "ST-970 1.4.0 P01", "v.1.5.0"),
        # A controller that says nothing, and one whose shape we do not know:
        # neither loses whatever it did report.
        ("", None, ""),
        ("1.0.0", None, "1.0.0"),
    ],
)
def test_the_descriptor_yields_a_model_and_a_firmware(
    descriptor: str, model: str | None, firmware: str
) -> None:
    """The model and the firmware both come from the controller's descriptor.

    The modules list has no model field of its own, so the descriptor is the only
    source there is: everything before the trailing parenthesised version is the
    model, with the vendor prefix dropped because the device reports its
    manufacturer separately.
    """
    entry = _Entry()
    entry.data[const.CONTROLLER][const.VER] = descriptor

    assert assets.controller_model(entry) == model
    assert assets.controller_firmware(entry) == firmware


def test_a_zone_entity_without_a_known_controller_device_has_no_parent() -> None:
    """An entity built before the controller's device id is known has no parent.

    The device id is set while the entry sets up, so an entity built outside a
    running entry -- as these tests do -- must still produce a usable device
    instead of naming a parent that does not exist.
    """
    coordinator = _Coordinator()
    coordinator.controller_device_id = None
    entity = _modules["switch"].MenuSwitchEntity(
        _item(), "MU_3550", coordinator, _Entry(), {}, depth=0, zone_id=101
    )

    info = entity.device_info
    assert info["identifiers"] == {(const.DOMAIN, f"{_UDID}_101")}
    assert "via_device_id" not in info


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


async def test_menu_select_maps_its_options_and_refuses_an_unknown_one() -> None:
    """The option map skips malformed entries, keeps labels apart, and guards.

    The labels are what Home Assistant shows and what a service call hands back,
    so two options translating to the same text need telling apart, an option
    without a label falls back to its value, and an option the entity was never
    told about is refused rather than sent to the API.
    """
    item = _item()
    item["params"]["options"] = [
        {"value": 0, "txtId": 1},
        {"value": 1, "txtId": 1},
        {"value": 2, "txtId": 0},
        "not a mapping",
    ]
    coordinator = _Coordinator()
    entity = _modules["select"].MenuSelectEntity(
        item, "MU_3550", coordinator, _Entry(), {}, depth=0
    )
    # The stub base class carries no state machine, so the write callback the
    # entity makes after a successful option change has nothing to reach.
    entity.async_write_ha_state = lambda *args, **kwargs: None

    assert entity._attr_options == ["label-1", "label-1 (1)", "2"]
    assert entity._attr_current_option == "label-1 (1)"

    await entity.async_select_option("no such option")

    assert entity._attr_current_option == "label-1 (1)"
    assert coordinator.api.menu_writes == []

    await entity.async_select_option("2")

    assert entity._attr_current_option == "2"
    # The value behind the label is what the API is told, not the label.
    assert coordinator.api.menu_writes[-1][3] == {"value": 2}


# ---------------------------------------------------------------------------
# Availability -- entity-unavailable
# ---------------------------------------------------------------------------


def _menu_entity(
    module_name: str,
    class_name: str,
    coordinator: _Coordinator,
    item: dict[str, Any],
):
    """Build one menu entity around the given item and coordinator."""
    return getattr(_modules[module_name], class_name)(
        item, "MU_3550", coordinator, _Entry(), {}, depth=0
    )


def test_menu_entity_is_unavailable_while_the_controller_is() -> None:
    """A failed poll marks menu entities unavailable.

    Every entity of this integration is a ``CoordinatorEntity``, whose
    ``available`` follows the coordinator's ``last_update_success``, so the
    entities stop offering themselves while the controller cannot be reached
    instead of showing their last state.
    """
    coordinator = _Coordinator()
    entity = _menu_entity("switch", "MenuSwitchEntity", coordinator, _item())

    assert entity.available

    coordinator.last_update_success = False

    assert not entity.available

    coordinator.last_update_success = True

    assert entity.available


def test_dialogue_button_is_unavailable_while_the_controller_withdraws_it() -> None:
    """An accessible dialogue is unavailable too when the controller drops it.

    The controller offers a dialogue only while it can be used -- a
    clear-lockout control exists while there is a lockout to clear -- and says so
    through the item's ``access`` flag. Storing that flag in ``_attr_available``
    was dead code, because ``CoordinatorEntity.available`` overrides
    ``Entity.available`` without reading it.
    """
    coordinator = _Coordinator()
    item = _item()
    item["access"] = False
    entity = _menu_entity("button", "MenuButtonEntity", coordinator, item)

    assert not entity.available

    item["access"] = True
    # This is what the coordinator update callback runs to refresh the flags.
    entity._update_from_item(item)

    assert entity.available
