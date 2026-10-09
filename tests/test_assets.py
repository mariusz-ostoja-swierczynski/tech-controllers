"""Unit tests for the translation and menu helpers in ``assets.py``.

Like :mod:`test_widget_logic`, these tests stub the ``homeassistant``
package just enough to import :mod:`custom_components.tech.const` (which
only needs ``homeassistant.const.Platform``) and then load ``assets.py``
under its real package name so its relative import of ``const`` resolves.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import types

_ha = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
_ha_const = sys.modules.setdefault(
    "homeassistant.const", types.ModuleType("homeassistant.const")
)


class _Platform:
    """Stand-in for homeassistant.const.Platform; only the names matter."""

    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CLIMATE = "climate"
    NUMBER = "number"
    SELECT = "select"
    SENSOR = "sensor"
    SWITCH = "switch"


if not hasattr(_ha_const, "Platform"):
    _ha_const.Platform = _Platform
if not hasattr(_ha_const, "CONF_DESCRIPTION"):
    _ha_const.CONF_DESCRIPTION = "description"
if not hasattr(_ha_const, "CONF_NAME"):
    _ha_const.CONF_NAME = "name"
if not hasattr(_ha_const, "CONF_ZONE"):
    _ha_const.CONF_ZONE = "zone"


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"


def _load_tech_module(name: str):
    """Load ``custom_components.tech.<name>`` without executing __init__.py.

    Fake parent packages are registered in ``sys.modules`` so that the
    relative imports inside the module resolve, while the integration's
    ``__init__.py`` (which needs a full Home Assistant install) is skipped.
    """
    full_name = f"custom_components.tech.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    for pkg, path in (
        ("custom_components", _REPO_ROOT / "custom_components"),
        ("custom_components.tech", _TECH_DIR),
    ):
        if pkg not in sys.modules:
            mod = types.ModuleType(pkg)
            mod.__path__ = [str(path)]
            sys.modules[pkg] = mod
    spec = importlib.util.spec_from_file_location(full_name, _TECH_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[full_name] = mod
    spec.loader.exec_module(mod)
    return mod


const = _load_tech_module("const")
assets = _load_tech_module("assets")


# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------


def test_get_text_resolves_known_id() -> None:
    """A text id present in the catalog resolves to its translation."""
    translations = assets.Translations({"data": {"100": "Pompa"}})
    assert translations.get_text(100) == "Pompa"


def test_get_text_falls_back_for_unknown_and_zero_ids() -> None:
    """Unknown and zero text ids fall back to the txtId placeholder."""
    translations = assets.Translations({"data": {"100": "Pompa"}})
    assert translations.get_text(101) == "txtId 101"
    assert translations.get_text(0) == "txtId 0"


def test_empty_catalog_degrades_to_fallback() -> None:
    """An empty Translations() still answers with the placeholder."""
    translations = assets.Translations()
    assert translations.get_text(100) == "txtId 100"


def test_get_text_by_type_resolves_mapped_type() -> None:
    """A tile type mapped in TXT_ID_BY_TYPE resolves via the catalog."""
    fan_txt_id = const.TXT_ID_BY_TYPE[const.TYPE_FAN]
    translations = assets.Translations({"data": {str(fan_txt_id): "Wentylator"}})
    assert translations.get_text_by_type(const.TYPE_FAN) == "Wentylator"


def test_get_text_by_type_unmapped_type_returns_type_label() -> None:
    """An unmapped tile type yields 'type N', not 'txtId type N'."""
    translations = assets.Translations({"data": {}})
    assert 9999 not in const.TXT_ID_BY_TYPE
    # Regression: the old module-level implementation fed the string
    # fallback back into get_text and produced "txtId type 9999".
    assert translations.get_text_by_type(9999) == "type 9999"


# ---------------------------------------------------------------------------
# Menu helpers
# ---------------------------------------------------------------------------


def _menu_item(item_id, parent_id=0, menu_type="MU", item_type=None, txt_id=0):
    item = {"id": item_id, "parentId": parent_id, "menuType": menu_type}
    if item_type is not None:
        item["type"] = item_type
    if txt_id:
        item["txtId"] = txt_id
    return item


def test_menu_entity_name_prepends_parent_group_label() -> None:
    """Items in a non-root group get the group label prepended."""
    translations = assets.Translations({"data": {"1": "Pompa", "2": "On"}})
    group = _menu_item(
        10, item_type=const.MENU_ITEM_TYPE_GROUP, txt_id=1, menu_type="MU"
    )
    leaf = _menu_item(11, parent_id=10, txt_id=2, menu_type="MU")
    menus = {"MU_10": group, "MU_11": leaf}

    group_names = assets.build_menu_group_names(menus, translations)
    assert group_names[("MU", 10)] == "Pompa"
    assert assets.menu_entity_name(leaf, group_names, translations) == "Pompa - On"
    assert assets.menu_entity_name(group, group_names, translations) == "Pompa"


def test_build_menu_context_bundles_all_lookups() -> None:
    """build_menu_context returns group names, assignments and depths."""
    translations = assets.Translations({"data": {"1": "Grupa"}})
    group = _menu_item(10, item_type=const.MENU_ITEM_TYPE_GROUP, txt_id=1)
    leaf = _menu_item(11, parent_id=10)
    menus = {"MU_10": group, "MU_11": leaf}

    ctx = assets.build_menu_context(menus, {}, translations)
    assert ctx.group_names == {("MU", 10): "Grupa"}
    assert ctx.zone_assignments == {}
    assert ctx.depths == {"MU_10": 0, "MU_11": 1}


def _zone(zone_id: int, name: str | None = None, index: int | None = None) -> dict:
    """Build a minimal zone payload matching the cached API shape."""
    zone: dict = {"zone": {"id": zone_id, "visibility": True, "zoneState": "zoneOn"}}
    if index is not None:
        zone["zone"]["index"] = index
    if name is not None:
        zone["description"] = {"name": name}
    return zone


def test_build_zone_names_extracts_description_name() -> None:
    """Zone device names come from the zone payload description."""
    zones = {
        1: _zone(1, "Strefa 1", index=0),
        2: _zone(2, "Strefa 2", index=1),
    }
    assert assets.build_zone_names(zones, "Wisniowa 13") == {
        1: "Strefa 1",
        2: "Strefa 2",
    }


def test_build_zone_names_prefixes_hub_when_configured() -> None:
    """include_hub_in_name prefixes the zone name with the hub title."""
    zones = {1: _zone(1, "Strefa 1", index=0)}
    assert assets.build_zone_names(zones, "Wisniowa 13", include_hub_in_name=True) == {
        1: "Wisniowa 13 Strefa 1"
    }


def test_build_zone_names_skips_zones_without_name() -> None:
    """Zones without a usable description name are omitted."""
    zones = {
        1: _zone(1, "Strefa 1", index=0),
        2: _zone(2, index=1),
    }
    assert assets.build_zone_names(zones, "Wisniowa 13") == {1: "Strefa 1"}


def test_build_zone_names_no_bare_prefix_for_nameless_zone() -> None:
    """A nameless zone is omitted even with the hub prefix enabled."""
    zones = {1: _zone(1, index=0)}
    assert assets.build_zone_names(zones, "Wisniowa 13", include_hub_in_name=True) == {}


def test_build_zone_names_skips_empty_name() -> None:
    """An empty description name is treated as no name."""
    zones = {1: _zone(1, "", index=0)}
    assert assets.build_zone_names(zones, "Wisniowa 13") == {}


def test_build_zone_names_skips_non_dict_description() -> None:
    """A non-dict description is treated as no name."""
    zones = {1: _zone(1, index=0)}
    zones[1]["description"] = "not a dict"
    assert assets.build_zone_names(zones, "Wisniowa 13") == {}


def test_resolve_zone_device_name_uses_zone_name() -> None:
    """A zone with a mapped name yields that name."""
    zone_names = {1: "Strefa 1"}
    assert assets.resolve_zone_device_name(zone_names, 1, "Wisniowa 13") == "Strefa 1"


def test_resolve_zone_device_name_falls_back_to_title() -> None:
    """A missing or empty zone entry falls back to the config entry title."""
    assert assets.resolve_zone_device_name({}, 1, "Wisniowa 13") == "Wisniowa 13"
    assert assets.resolve_zone_device_name(None, 1, "Wisniowa 13") == "Wisniowa 13"
    assert (
        assets.resolve_zone_device_name({2: "Strefa 2"}, 1, "Wisniowa 13")
        == "Wisniowa 13"
    )
    assert assets.resolve_zone_device_name({1: ""}, 1, "Wisniowa 13") == "Wisniowa 13"


def test_resolve_zone_device_name_none_for_unzoned_entity() -> None:
    """Entities without a zone get no zone device name."""
    assert assets.resolve_zone_device_name(None, None, "Wisniowa 13") is None


def _menus_with_zone_group(children: int = 4) -> dict:
    """Build a minimal menu tree: a top-level group holding ``children`` groups."""
    group_type = const.MENU_ITEM_TYPE_GROUP
    menus = {"MI_1": {"id": 1, "menuType": "MI", "type": group_type, "parentId": 0}}
    for index in range(children):
        menus[f"MI_{10 + index}"] = {
            "id": 10 + index,
            "menuType": "MI",
            "type": group_type,
            "parentId": 1,
        }
    return menus


def _zoneless_envelope() -> dict:
    """Return a zones payload with no elements, as a controller without zones sends."""
    return {
        "transaction_time": None,
        "elements": [],
        "globalSchedules": {"time": None, "duringChange": None, "elements": []},
        "controllerParameters": {},
    }


def test_zone_payloads_keeps_only_usable_entries() -> None:
    """Entries that are not zone payloads are dropped rather than passed on."""
    valid = _zone(1, "Strefa 1", index=0)
    mixed = {1: valid, 2: None, 3: [], 4: {"description": {"name": "x"}}, 5: "nope"}

    assert assets.zone_payloads(mixed) == {1: valid}


def test_zone_payloads_tolerates_none_and_empty() -> None:
    """A missing or empty zones value yields an empty mapping."""
    assert assets.zone_payloads(None) == {}
    assert assets.zone_payloads({}) == {}


def test_build_menu_zone_assignments_ignores_a_zoneless_envelope() -> None:
    """A heat pump's zones envelope neither raises nor assigns anything."""
    assignments = assets.build_menu_zone_assignments(
        _menus_with_zone_group(), _zoneless_envelope()
    )

    assert assignments == {}


def test_build_menu_zone_assignments_skips_zones_without_an_index() -> None:
    """Zones that cannot be matched positionally lead to no assignment at all."""
    zones = {1: _zone(1, "Strefa 1")}  # a zone payload without "index"

    assert assets.build_menu_zone_assignments(_menus_with_zone_group(1), zones) == {}


def test_build_zone_names_ignores_non_zone_entries() -> None:
    """The naming helper filters the same way, naming only real zones."""
    zones = dict(_zoneless_envelope())
    zones[101] = _zone(101, "Strefa 1", index=0)

    assert assets.build_zone_names(zones, "L-8 DEMO") == {101: "Strefa 1"}
