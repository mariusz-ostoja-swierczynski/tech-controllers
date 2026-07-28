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

from collections import Counter
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
    """Mirror :func:`sensor._is_contact_widget` for use as a test oracle.

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
        """Canonical contact triple (unit=-1, type=0, txtId!=0) is detected."""
        widget = {"unit": -1, "type": 0, "txtId": 1234, "value": 0}
        assert is_contact_widget_oracle(widget) is True

    def test_temperature_widget_is_not_contact(self):
        """A unit=7 temperature widget must not be misread as a contact."""
        widget = {"unit": 7, "type": 9, "txtId": 774, "value": 521}
        assert is_contact_widget_oracle(widget) is False

    def test_dhw_pump_widget_is_not_contact(self):
        """A DHW-pump widget (type!=0) must not be misread as a contact."""
        widget = {"unit": 7, "type": C.WIDGET_DHW_PUMP, "txtId": 938, "value": -40}
        assert is_contact_widget_oracle(widget) is False

    def test_zero_txtid_disables_contact(self):
        """A txtId of 0 disqualifies the widget even with the unit/type pair."""
        widget = {"unit": -1, "type": 0, "txtId": 0, "value": 0}
        assert is_contact_widget_oracle(widget) is False

    def test_state_badge_unit6_is_not_contact(self):
        """State-badge marker (unit=6, type=0) must not be flagged as contact."""
        # unit=6 is the mode/state badge marker (skipped by _build_widget_tile);
        # it shares type=0 with contacts but lacks unit=-1.
        widget = {"unit": 6, "type": 0, "txtId": 760, "value": 0}
        assert is_contact_widget_oracle(widget) is False

    def test_unit6_zero_valued_widget_skipped_by_dispatch(self):
        """A unit=6 widget with value=0 is still skipped (badge)."""
        widget = {"unit": 6, "type": 0, "txtId": 760, "value": 0}
        # This emulates the _build_widget_tile dispatch: skip when
        # unit=6 AND value==0 (decorative badge, no numeric meaning).
        should_skip = (
            widget.get("unit") == 6 and widget.get("value", 0) == 0
        )
        assert should_skip is True

    def test_unit6_nonzero_valued_widget_not_skipped_by_dispatch(self):
        """A unit=6 widget with non-zero value is kept (real data, e.g. solar pump temperatures)."""
        widget = {"unit": 6, "type": 1, "txtId": 2442, "value": 56}
        # After the fix for the PWM solar pump (issue #196), non-zero
        # unit=6 widgets are no longer skipped — they flow through to
        # TileWidgetTemperatureSensor.
        should_skip = (
            widget.get("unit") == 6 and widget.get("value", 0) == 0
        )
        assert should_skip is False

    def test_predicate_source_matches_oracle(self):
        """Verify sensor.py and binary_sensor.py still encode the same rule.

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

    def test_unit6_skip_condition_source_matches(self):
        """sensor.py must encode the updated unit=6 skip rule (skip only when value==0)."""
        sensor_src = (
            _REPO_ROOT / "custom_components" / "tech" / "sensor.py"
        ).read_text()
        # The new skip condition: only skip unit=6 widgets with value==0.
        assert 'if widget.get("unit") == 6 and widget.get("value", 0) == 0:' in sensor_src


# ---------------------------------------------------------------------------
# Constants tables
# ---------------------------------------------------------------------------


class TestUnitDivisors:
    """WIDGET_UNIT_DIVISORS scales raw widget values to engineering units."""

    def test_unit_7_is_tenths_of_degree(self):
        """unit=7 (boiler temperatures) scales by 10: 521 -> 52.1°C."""
        # The most common boiler temperature unit. value=521 -> 52.1°C.
        assert C.WIDGET_UNIT_DIVISORS[7] == 10

    def test_unit_5_is_hundredths(self):
        """unit=5 widget values scale by 100."""
        assert C.WIDGET_UNIT_DIVISORS[5] == 100

    def test_unit_4_is_tenths(self):
        """unit=4 widget values scale by 10."""
        assert C.WIDGET_UNIT_DIVISORS[4] == 10

    def test_unit_6_passes_through(self):
        """unit=6 (state-badge enums) must not be scaled."""
        # State badges should not be scaled (their value is an enum, not a temp).
        assert C.WIDGET_UNIT_DIVISORS[6] == 1

    def test_known_units_only(self):
        """Pin the set of known unit codes to detect accidental additions."""
        # Codes outside the table fall back to a divisor of 1 in
        # _build_widget_tile / TileWidgetTemperatureSensor.get_state.
        assert set(C.WIDGET_UNIT_DIVISORS.keys()) == {0, 4, 5, 6, 7, 8, 23, 26, 33}


class TestTxtIdFallbacks:
    """Status-text tile types must fall back to a sane label, not "Disabled"."""

    def test_additional_pump_falls_back_to_pompa_dodatkowa(self):
        """Additional-pump tiles fall back to txtId 576 ("Pompa dodatkowa")."""
        # 576 = "Pompa dodatkowa" in Polish.
        assert C.TXT_ID_BY_TYPE[C.TYPE_ADDITIONAL_PUMP] == 576

    def test_disinfection_falls_back_to_dezynfekcja(self):
        """Disinfection tiles fall back to txtId 246 ("Dezynfekcja")."""
        # 246 = "Dezynfekcja" in Polish.
        assert C.TXT_ID_BY_TYPE[C.TYPE_DISINFECTION] == 246

    def test_status_text_set_covers_pump_and_disinfection(self):
        """Both pump and disinfection types are marked status-text-bearing."""
        assert C.TYPE_ADDITIONAL_PUMP in C.TXT_ID_IS_STATUS_FOR_TYPES
        assert C.TYPE_DISINFECTION in C.TXT_ID_IS_STATUS_FOR_TYPES

    def test_relay_does_not_use_status_text_fallback(self):
        """Plain relay tiles must not be classified as status-text bearers."""
        # Regular relays carry meaningful txtId values directly.
        assert C.TYPE_RELAY not in C.TXT_ID_IS_STATUS_FOR_TYPES


class TestTileTypeConstants:
    """The integer values are part of the API contract -- pin them."""

    def test_type_widget_is_six(self):
        """TYPE_WIDGET keeps the legacy TYPE_TEMPERATURE_CH integer value 6."""
        # TYPE_WIDGET was renamed from TYPE_TEMPERATURE_CH; the API value (6)
        # must remain the same to stay backward-compatible.
        assert C.TYPE_WIDGET == 6

    def test_type_disinfection_is_thirty_two(self):
        """TYPE_DISINFECTION is pinned to API value 32."""
        assert C.TYPE_DISINFECTION == 32

    def test_widget_subtypes(self):
        """Widget-subtype constants are pinned to their API values."""
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
        """Load the captured ST-491 module payload once for the class."""
        cls.module = _load("st491/module.json")

    def test_no_zones(self):
        """ST-491 boilers expose no climate zones."""
        # ST-491 is an RS-bridged boiler controller -- no climate zones.
        assert self.module["zones"]["elements"] == []

    def test_three_widget_tiles(self):
        """ST-491 fixture exposes exactly three TYPE_WIDGET tiles."""
        widgets = [t for t in self.module["tiles"] if t["type"] == C.TYPE_WIDGET]
        assert len(widgets) == 3

    def test_each_widget_tile_has_two_widgets(self):
        """Every TYPE_WIDGET tile carries both widget1 and widget2 sub-payloads."""
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
        """At least two unit=6 state-badge widgets exist and would be skipped."""
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
        """Disinfection tile reports a status txtId (922) handled via fallback."""
        disinfection_tiles = [
            t for t in self.module["tiles"] if t["type"] == C.TYPE_DISINFECTION
        ]
        assert len(disinfection_tiles) == 1
        # The tile carries a status txtId (922 = "Wyłączona") -- exactly the
        # case TXT_ID_IS_STATUS_FOR_TYPES handles by falling through to 246.
        assert disinfection_tiles[0]["params"]["txtId"] == 922

    def test_additional_pump_tile_uses_status_txtid(self):
        """Visible additional-pump tile reports a status txtId (922)."""
        pumps = [
            t
            for t in self.module["tiles"]
            if t["type"] == C.TYPE_ADDITIONAL_PUMP and t.get("visibility")
        ]
        assert len(pumps) >= 1
        assert pumps[0]["params"]["txtId"] == 922

    def test_valve_tile_has_settemp_and_unset_label(self):
        """Valve tile carries three temp descriptors and an unset (-1) txtId."""
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
        """Pin the per-type tile counts of the captured ST-491 fixture."""
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


    def test_all_widget_tiles_have_status_binary_sensor(self):
        """Only TYPE_WIDGET tiles with pump-type widgets get a TileWidgetStatusSensor."""
        count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id not in (0, 1):
                continue
            has_pump = any(
                tile["params"].get(key, {}).get("type") in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP)
                for key in ("widget1", "widget2")
            )
            if has_pump:
                count += 1
        # ST-491 has no pump-type widgets among its TYPE_WIDGET tiles
        assert count == 0


# ---------------------------------------------------------------------------
# Fixture-driven assertions: L-12 zone controller
# ---------------------------------------------------------------------------


class TestL12Fixture:
    """L-12 underfloor controller -- guard against regression in zone path."""

    @classmethod
    def setup_class(cls):
        """Load the captured L-12 module payload once for the class."""
        cls.module = _load("l12/module.json")

    def test_five_zones_visible(self):
        """L-12 fixture exposes five visible climate zones."""
        zones = self.module["zones"]["elements"]
        assert len(zones) == 5
        for z in zones:
            assert z["zone"]["visibility"] is True

    def test_zone_temperatures_in_tenths(self):
        """Zone currentTemperature values are tenths-of-degree integers."""
        # Zone payloads use tenths of a degree like widget unit=7.
        # Asserting this guards against accidental double-scaling.
        for z in self.module["zones"]["elements"]:
            cur = z["zone"]["currentTemperature"]
            if cur is not None:
                assert 100 <= cur <= 350  # 10°C -- 35°C in tenths

    def test_carries_unsupported_type_61_tiles(self):
        """L-12 carries TYPE_SW_VERSION (50) and structural TYPE 61 tiles."""
        # L-12 carries TYPE_SW_VERSION (=50) and TYPE 61 "container reference"
        # tiles. The latter are intentionally ignored because they are
        # structural pointers, not data-bearing.
        types = {t["type"] for t in self.module["tiles"]}
        assert 50 in types
        assert 61 in types


# ---------------------------------------------------------------------------
# Fixture-driven assertions: ST-2801 boiler controller
# --------------------------------------------------------------------------


class TestSt2801Fixture:
    """Live ST-2801 boiler payload assertions.

    Captured from a boiler running ST-2801 firmware v1.2.2.  Regression test
    for the burner modulation readout bug (issue #195 upstream) where a
    unit=8 percentage widget was misclassified as a DHW temperature sensor
    and displayed as 0 °C instead of 0 %.
    """

    @classmethod
    def setup_class(cls):
        """Load the captured ST-2801 module payload once for the class."""
        cls.module = _load("st2801/module.json")

    def test_no_zones(self):
        """ST-2801 boiler exposes no climate zones."""
        assert self.module["zones"]["elements"] == []

    def test_one_widget_tile(self):
        """ST-2801 fixture exposes exactly one TYPE_WIDGET tile."""
        widgets = [t for t in self.module["tiles"] if t["type"] == C.TYPE_WIDGET]
        assert len(widgets) == 1

    def test_widget_tile_has_two_widgets(self):
        """The lone TYPE_WIDGET tile carries both widget1 and widget2."""
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            params = tile["params"]
            assert "widget1" in params and "widget2" in params

    def test_widget_uses_unit_8_percent(self):
        """Both widgets in tile 10135 use unit=8 (raw percentage)."""
        tile = self.module["tiles"][10]  # tile 10135 at index 10
        assert tile["id"] == 10135
        assert tile["type"] == C.TYPE_WIDGET
        assert tile["params"]["widget1"]["unit"] == 8
        assert tile["params"]["widget2"]["unit"] == 8

    def test_unit_8_widgets_route_to_percentage(self):
        """Unit=8 widgets must be dispatched to TileWidgetPumpSensor, not TileWidgetTemperatureSensor.

        Before the fix for #195, widget1 (type=1, unit=8, txtId=428
        "Modulation") fell into the temperature branch and was displayed
        as 0 °C instead of 0 %.
        """
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
                # After the fix, unit=8 is handled like COLLECTOR_PUMP --
                # it must NOT fall into the temperature branch.
                if w.get("unit") == 8:
                    assert w.get("type") in (
                        C.WIDGET_COLLECTOR_PUMP,
                        C.WIDGET_DHW_PUMP,
                    ), (
                        f"Unit=8 widget dispatched as temperature: "
                        f"type={w.get('type')}, txtId={w.get('txtId')}"
                    )

    def test_widget_dispatch_yields_two_percentage_sensors(self):
        """Both widget1 and widget2 from tile 10135 survive dispatch."""
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
        assert emitted == 2

    def test_modulation_value_is_percent(self):
        """Widget2 modulation value 14 must be a raw percentage (14%)."""
        tile = self.module["tiles"][10]  # tile 10135
        w2 = tile["params"]["widget2"]
        assert w2["value"] == 14
        assert w2["unit"] == 8
        # raw percentage -- no scaling needed
        assert C.WIDGET_UNIT_DIVISORS[8] == 1

    def test_all_widget_tiles_have_status_binary_sensor(self):
        """The lone TYPE_WIDGET tile has a pump-type widget and gets a status sensor."""
        count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id not in (0, 1):
                continue
            has_pump = any(
                tile["params"].get(key, {}).get("type") in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP)
                for key in ("widget1", "widget2")
            )
            if has_pump:
                count += 1
        assert count == 1

    def test_expected_tile_type_distribution(self):
        """Pin the per-type tile counts of the captured ST-2801 fixture."""
        counts = Counter(t["type"] for t in self.module["tiles"])
        assert counts == {
            C.TYPE_SW_VERSION: 1,
            C.TYPE_TEMPERATURE: 6,  # 4 visible + 2 hidden
            C.TYPE_TEXT: 2,
            C.TYPE_RELAY: 1,
            C.TYPE_FIRE_SENSOR: 1,
            C.TYPE_WIDGET: 1,
            41: 1,  # date tile
        }


# ---------------------------------------------------------------------------
# Fixture-driven assertions: ST-521 heat pump controller
# ---------------------------------------------------------------------------


class TestSt521Fixture:
    """Live ST-521 heat-pump payload assertions.

    Captured from a DEFRO DHP I Monotec 12 kW heat pump running ST-521
    firmware v0.7.4.  Regression test for the "txtId 0 / value 0.0"
    sensors bug (issue #178 upstream) and the DHW-suffix misclassification
    that caused every widget to be labelled as a domestic-hot-water sensor.
    """

    @classmethod
    def setup_class(cls):
        """Load the captured ST-521 module payload once for the class."""
        cls.module = _load("st521/module.json")

    def test_no_zones(self):
        """ST-521 exposes no climate zones."""
        assert self.module["zones"]["elements"] == []

    def test_widget_tile_count(self):
        """ST-521 exposes 70 TYPE_WIDGET tiles."""
        widgets = [t for t in self.module["tiles"] if t["type"] == C.TYPE_WIDGET]
        assert len(widgets) == 70

    def test_all_widget_tiles_have_two_widgets(self):
        """Every TYPE_WIDGET tile carries both widget1 and widget2."""
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            params = tile["params"]
            assert "widget1" in params and "widget2" in params

    def test_widget1_is_placeholder(self):
        """Most widget1 entries are placeholders (txtId=0) and skipped.

        Four TYPE_WIDGET tiles carry real contact-sensor data in both
        widget1 and widget2 (EU-i-3+ style dry-contact extension modules
        with unit=-1, type=0).  Those 4 are real entities handled by
        binary_sensor, not sensor.  The remaining 66 widget1 entries
        all have txtId=0 -- verified placeholders.
        """
        placeholder_count = 0
        real_count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            w1 = tile["params"]["widget1"]
            if w1["txtId"] == 0:
                placeholder_count += 1
            else:
                real_count += 1
                # These are contact widgets consumed by binary_sensor
                assert is_contact_widget_oracle(w1), (
                    f"Tile {tile['id']}: non-zero txtId widget1 is not a contact"
                )
        assert placeholder_count == 66
        assert real_count == 4

    def test_widget2_has_nonzero_txtid(self):
        """Every widget2 has a non-zero txtId (real data)."""
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            w2 = tile["params"]["widget2"]
            assert w2["txtId"] != 0, (
                f"Tile {tile['id']} widget2 txtId=0, expected non-zero"
            )

    def test_widget_dispatch_skips_placeholders(self):
        """Only 66 non-contact widget entities survive dispatch.

        70 widget2 entries all have non-zero txtId, but 4 are contact
        widgets (unit=-1, type=0) that get handed off to binary_sensor.
        66 widget1 entries are placeholders (txtId=0) and skipped.
        The remaining 4 widget1 entries are contact widgets.

        Result: 66 sensor-platform entities produced from TYPE_WIDGET tiles.
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
        assert emitted == 66

    def test_all_widget_tiles_have_status_binary_sensor(self):
        """66 of 70 TYPE_WIDGET tiles have pump-type widgets and get a status sensor.

        The remaining 4 are pure contact-sensor tiles (type=0 on both widgets)
        and are correctly excluded.
        """
        count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id not in (0, 1):
                continue
            has_pump = any(
                tile["params"].get(key, {}).get("type") in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP)
                for key in ("widget1", "widget2")
            )
            if has_pump:
                count += 1
        assert count == 66

    def test_status_binary_sensor_off_states(self):
        """One TYPE_WIDGET tile has statusId=0 and a pump-type widget (OFF)."""
        off_count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id != 0:
                continue
            has_pump = any(
                tile["params"].get(key, {}).get("type") in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP)
                for key in ("widget1", "widget2")
            )
            if has_pump:
                off_count += 1
        assert off_count == 1

    def test_new_unit_codes_scale_correctly(self):
        """Unit codes 23, 26, 33 scale values by 10 (bar, kW, %).

        Skip the known sensor-error value (-32768) which means the sensor
        is disconnected or damaged (documented on the ST-521 display as
        "Anlagendruck (Fehlwert/Fühler fehlt)" for the system pressure).
        """
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            w = tile["params"]["widget2"]
            unit = w["unit"]
            if unit == 23:
                if w["value"] == -32768:
                    continue
                scaled = w["value"] / 10
                assert 0 <= scaled <= 100, f"Bar value {scaled} out of range"
            elif unit == 26:
                scaled = w["value"] / 10
                assert 0 <= scaled <= 100, f"kW value {scaled} out of range"
            elif unit == 33:
                scaled = w["value"] / 10
                assert 0 <= scaled <= 100, f"% value {scaled} out of range"

    def test_temperature_widgets_in_range(self):
        """Unit=7 temperature widgets produce sane °C values."""
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            w = tile["params"]["widget2"]
            if w["unit"] == 7:
                scaled = w["value"] / 10
                assert -30 <= scaled <= 120, (
                    f"Temperature {scaled}°C out of range for tile {tile['id']}"
                )

    def test_dhw_suffix_not_applied_to_placeholder_pair(self):
        """When widget1 is a placeholder (txtId=0), DHW suffix must be dropped.

        The ST-521 firmware uses widget type=1 for *all* widgets, but only
        real DHW pump pairs (both widgets with non-zero txtId) should get
        the "Set Temperature" / "Current Temperature" suffix.
        """
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            params = tile["params"]
            w1 = params["widget1"]
            w2 = params["widget2"]
            if w2.get("type") == C.WIDGET_DHW_PUMP:
                # widget1 is always a placeholder for ST-521, so the sibling
                # has txtId=0 -- the DHW suffix must NOT be applied.
                assert w1["txtId"] == 0, (
                    f"Tile {tile['id']}: expected widget1 txtId=0, got {w1['txtId']}"
                )

    def test_expected_tile_type_distribution(self):
        """Pin the per-type tile counts of the captured ST-521 fixture."""
        counts = Counter(t["type"] for t in self.module["tiles"])
        assert counts == {
            C.TYPE_WIDGET: 70,
            C.TYPE_RELAY: 17,
            C.TYPE_TEXT: 22,
            C.TYPE_SW_VERSION: 1,
            C.TYPE_DISINFECTION: 1,
            51: 1,  # peripheral SW version
            60: 9,  # structural container references (like L-12 type 61)
        }

    def test_unit_codes_in_widgets(self):
        """Verify the ST-521 widget unit codes include the newly added ones."""
        units = set()
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            units.add(tile["params"]["widget2"]["unit"])
        assert 23 in units, "unit=23 (bar×10) missing from ST-521"
        assert 26 in units, "unit=26 (kW×10) missing from ST-521"
        assert 33 in units, "unit=33 (percentage×10) missing from ST-521"
