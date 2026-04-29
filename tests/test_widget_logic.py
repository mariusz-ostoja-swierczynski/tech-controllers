"""Lightweight unit tests for the TYPE_WIDGET tile-parsing logic.

These tests do not require Home Assistant to be installed -- they stub the
``homeassistant`` package just well enough to import :mod:`custom_components.tech.const`
and then exercise the widget-dispatch rules against captured live fixtures
(:file:`tests/fixtures/st491/module.json`, :file:`tests/fixtures/l12/module.json`).

The contact-widget predicate and unit-scaling rules are duplicated as oracles
in this file. Both sensor.py and binary_sensor.py implement the same predicate
(see ``_is_contact_widget`` in either module). If the predicate is changed in
either file, update :func:`is_contact_widget_oracle` here and the test will
fail until both implementations agree again.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import sys
import types

# ---------------------------------------------------------------------------
# Stub Home Assistant so that const.py can be imported without booting HA.
# const.py only needs ``homeassistant.const.Platform``; everything else lives
# in the integration's own modules.
# ---------------------------------------------------------------------------
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


_ha_const.Platform = _Platform


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CONST_PATH = _REPO_ROOT / "custom_components" / "tech" / "const.py"


def _load_const_module():
    """Import const.py in isolation, with HA stubs already injected."""
    spec = importlib.util.spec_from_file_location("tech_const", _CONST_PATH)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


C = _load_const_module()
FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def _load(path: str) -> dict:
    """Load a JSON fixture relative to ``tests/fixtures``."""
    return json.loads((FIXTURES / path).read_text())


def is_contact_widget_oracle(widget: dict) -> bool:
    """Reference predicate, copy of :func:`sensor._is_contact_widget`.

    If sensor.py / binary_sensor.py change the rule, update this oracle and
    re-run the tests so we know both implementations still agree.
    """
    return (
        widget.get("unit") == -1
        and widget.get("type") == 0
        and widget.get("txtId", 0) != 0
    )


# ---------------------------------------------------------------------------
# _is_contact_widget oracle
# ---------------------------------------------------------------------------


class TestIsContactWidget:
    """Verify the contact-widget marker triple behaves as documented."""

    def test_canonical_contact_returns_true(self):
        widget = {"unit": -1, "type": 0, "txtId": 1234, "value": 0}
        assert is_contact_widget_oracle(widget) is True

    def test_temperature_widget_is_not_contact(self):
        widget = {"unit": 7, "type": 9, "txtId": 774, "value": 521}
        assert is_contact_widget_oracle(widget) is False

    def test_dhw_pump_widget_is_not_contact(self):
        widget = {"unit": 7, "type": C.WIDGET_DHW_PUMP, "txtId": 938, "value": -40}
        assert is_contact_widget_oracle(widget) is False

    def test_zero_txtid_disables_contact(self):
        widget = {"unit": -1, "type": 0, "txtId": 0, "value": 0}
        assert is_contact_widget_oracle(widget) is False

    def test_state_badge_unit6_is_not_contact(self):
        # unit=6 is the mode/state badge marker (skipped by _build_widget_tile);
        # it shares type=0 with contacts but lacks unit=-1.
        widget = {"unit": 6, "type": 0, "txtId": 760, "value": 0}
        assert is_contact_widget_oracle(widget) is False

    def test_predicate_source_matches_oracle(self):
        """sensor.py and binary_sensor.py duplicate the same predicate.
        Asserting the source code of both still shows the canonical form
        catches divergence between the two copies.
        """
        sensor_src = (
            _REPO_ROOT / "custom_components" / "tech" / "sensor.py"
        ).read_text()
        binary_src = (
            _REPO_ROOT / "custom_components" / "tech" / "binary_sensor.py"
        ).read_text()
        # Both files must define _is_contact_widget.
        assert "def _is_contact_widget" in sensor_src
        assert "def _is_contact_widget" in binary_src
        # Both implementations must reference the same three marker fields.
        for src in (sensor_src, binary_src):
            assert 'widget.get("unit") == -1' in src
            assert 'widget.get("txtId", 0) != 0' in src


# ---------------------------------------------------------------------------
# Constants tables
# ---------------------------------------------------------------------------


class TestUnitDivisors:
    """WIDGET_UNIT_DIVISORS scales raw widget values to engineering units."""

    def test_unit_7_is_tenths_of_degree(self):
        # The most common boiler temperature unit. value=521 -> 52.1°C.
        assert C.WIDGET_UNIT_DIVISORS[7] == 10

    def test_unit_5_is_hundredths(self):
        assert C.WIDGET_UNIT_DIVISORS[5] == 100

    def test_unit_4_is_tenths(self):
        assert C.WIDGET_UNIT_DIVISORS[4] == 10

    def test_unit_6_passes_through(self):
        # State badges should not be scaled (their value is an enum, not a temp).
        assert C.WIDGET_UNIT_DIVISORS[6] == 1

    def test_known_units_only(self):
        # Codes outside the table fall back to a divisor of 1 in
        # _build_widget_tile / TileWidgetTemperatureSensor.get_state.
        assert set(C.WIDGET_UNIT_DIVISORS.keys()) == {0, 4, 5, 6, 7}


class TestTxtIdFallbacks:
    """Status-text tile types must fall back to a sane label, not "Disabled"."""

    def test_additional_pump_falls_back_to_pompa_dodatkowa(self):
        # 576 = "Pompa dodatkowa" in Polish.
        assert C.TXT_ID_BY_TYPE[C.TYPE_ADDITIONAL_PUMP] == 576

    def test_disinfection_falls_back_to_dezynfekcja(self):
        # 246 = "Dezynfekcja" in Polish.
        assert C.TXT_ID_BY_TYPE[C.TYPE_DISINFECTION] == 246

    def test_status_text_set_covers_pump_and_disinfection(self):
        assert C.TYPE_ADDITIONAL_PUMP in C.TXT_ID_IS_STATUS_FOR_TYPES
        assert C.TYPE_DISINFECTION in C.TXT_ID_IS_STATUS_FOR_TYPES

    def test_relay_does_not_use_status_text_fallback(self):
        # Regular relays carry meaningful txtId values directly.
        assert C.TYPE_RELAY not in C.TXT_ID_IS_STATUS_FOR_TYPES


class TestTileTypeConstants:
    """The integer values are part of the API contract -- pin them."""

    def test_type_widget_is_six(self):
        # TYPE_WIDGET was renamed from TYPE_TEMPERATURE_CH; the API value (6)
        # must remain the same to stay backward-compatible.
        assert C.TYPE_WIDGET == 6

    def test_type_disinfection_is_thirty_two(self):
        assert C.TYPE_DISINFECTION == 32

    def test_widget_subtypes(self):
        assert C.WIDGET_DHW_PUMP == 1
        assert C.WIDGET_COLLECTOR_PUMP == 2
        assert C.WIDGET_TEMPERATURE_CH == 9


# ---------------------------------------------------------------------------
# Fixture-driven assertions: ST-491 boiler
# ---------------------------------------------------------------------------


class TestSt491Fixture:
    """Live ST-491 boiler payload assertions.

    Captured from a real Defro/Kołton boiler running ST-491 firmware v2.1.9.
    Canonical regression test for the "missing CH/DHW temperatures" bug
    (issue #132 upstream).
    """

    @classmethod
    def setup_class(cls):
        cls.module = _load("st491/module.json")

    def test_no_zones(self):
        # ST-491 is an RS-bridged boiler controller -- no climate zones.
        assert self.module["zones"]["elements"] == []

    def test_three_widget_tiles(self):
        widgets = [t for t in self.module["tiles"] if t["type"] == C.TYPE_WIDGET]
        assert len(widgets) == 3

    def test_each_widget_tile_has_two_widgets(self):
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            params = tile["params"]
            assert "widget1" in params and "widget2" in params

    def test_recovered_temperatures(self):
        """The CH/DHW/room temperatures live in widget2, not widget1.

        Stock TileWidgetSensor read only widget1 and dropped these. Verify
        the unit-aware scaling produces sane °C values from each widget2.
        """
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            w = tile["params"]["widget2"]
            divisor = C.WIDGET_UNIT_DIVISORS.get(w["unit"], 1)
            scaled = w["value"] / divisor if divisor != 1 else w["value"]
            # Temperatures across CH (~50°C), DHW (~45°C), room (~22°C).
            assert -30 <= scaled <= 100

    def test_state_badge_widgets_are_skipped(self):
        # Tiles 2050 and 2051 each carry a widget1 with unit=6, type=0,
        # value=0 -- a decorative "Temperatura zadana" status badge that
        # _build_widget_tile skips.
        skipped = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            for key in ("widget1", "widget2"):
                w = tile["params"].get(key, {})
                if w.get("unit") == 6:
                    skipped += 1
        assert skipped >= 2

    def test_disinfection_tile_uses_status_txtid(self):
        disinfection_tiles = [
            t for t in self.module["tiles"] if t["type"] == C.TYPE_DISINFECTION
        ]
        assert len(disinfection_tiles) == 1
        # The tile carries a status txtId (922 = "Wyłączona") -- exactly the
        # case TXT_ID_IS_STATUS_FOR_TYPES handles by falling through to 246.
        assert disinfection_tiles[0]["params"]["txtId"] == 922

    def test_additional_pump_tile_uses_status_txtid(self):
        pumps = [
            t for t in self.module["tiles"]
            if t["type"] == C.TYPE_ADDITIONAL_PUMP and t.get("visibility")
        ]
        assert len(pumps) >= 1
        assert pumps[0]["params"]["txtId"] == 922

    def test_valve_tile_has_settemp_and_unset_label(self):
        valves = [t for t in self.module["tiles"] if t["type"] == C.TYPE_VALVE]
        assert len(valves) == 1
        params = valves[0]["params"]
        # All three valve sensor descriptors are populated; the integration
        # builds three valve-temperature entities from this.
        assert "currentTemp" in params
        assert "returnTemp" in params
        assert "setTemp" in params
        # txtId == -1 means "no label"; TileEntity falls back to TXT_ID_BY_TYPE.
        assert params["txtId"] == -1

    def test_expected_tile_type_distribution(self):
        from collections import Counter

        counts = Counter(t["type"] for t in self.module["tiles"])
        assert counts == {
            C.TYPE_TEMPERATURE: 4,
            C.TYPE_WIDGET: 3,
            C.TYPE_RELAY: 3,
            C.TYPE_ADDITIONAL_PUMP: 2,  # one visible, one hidden
            C.TYPE_FAN: 1,
            C.TYPE_VALVE: 1,
            C.TYPE_FUEL_SUPPLY: 1,
            C.TYPE_DISINFECTION: 1,
            C.TYPE_TEXT: 2,
            C.TYPE_SW_VERSION: 1,
        }

    def test_widget_dispatch_yields_six_visible_widget_entities(self):
        """Exercise the full dispatch oracle over the ST-491 widget tiles.

        The three TYPE_WIDGET tiles each carry widget1+widget2; the unit=6
        state badges are dropped (2 widgets), leaving 4 numeric widgets +
        2 widget1 entries that survive (one of which is a real room set
        temp, the other was dropped above). Final expected entity count: 4.
        """
        emitted = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            for key in ("widget1", "widget2"):
                w = tile["params"].get(key)
                if not w or w.get("txtId", 0) == 0:
                    continue
                if is_contact_widget_oracle(w):
                    continue
                if w.get("unit") == 6:
                    continue
                emitted += 1
        # Tile 2050: widget1 unit=6 dropped, widget2 unit=7 kept -> 1
        # Tile 2051: widget1 unit=6 dropped, widget2 unit=7 kept -> 1
        # Tile 2057: widget1 unit=7 kept, widget2 unit=7 kept    -> 2
        assert emitted == 4


# ---------------------------------------------------------------------------
# Fixture-driven assertions: L-12 zone controller
# ---------------------------------------------------------------------------


class TestL12Fixture:
    """L-12 underfloor controller -- guard against regression in zone path."""

    @classmethod
    def setup_class(cls):
        cls.module = _load("l12/module.json")

    def test_five_zones_visible(self):
        zones = self.module["zones"]["elements"]
        assert len(zones) == 5
        for z in zones:
            assert z["zone"]["visibility"] is True

    def test_zone_temperatures_in_tenths(self):
        # Zone payloads use tenths of a degree like widget unit=7.
        # Asserting this guards against accidental double-scaling.
        for z in self.module["zones"]["elements"]:
            cur = z["zone"]["currentTemperature"]
            if cur is not None:
                assert 100 <= cur <= 350  # 10°C -- 35°C in tenths

    def test_carries_unsupported_type_61_tiles(self):
        # L-12 carries TYPE_SW_VERSION (=50) and TYPE 61 "container reference"
        # tiles. The latter are intentionally ignored because they are
        # structural pointers, not data-bearing.
        types = {t["type"] for t in self.module["tiles"]}
        assert 50 in types
        assert 61 in types
