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
import re
import sys
import types

# ---------------------------------------------------------------------------
# Stub Home Assistant so that const.py can be imported without booting HA.
# const.py needs the platform enum, the sensor device/state classes and the unit
# constants. A stand-in that answers any attribute with its own name is enough
# for the latter two, because these tests compare the widget table against
# itself rather than against Home Assistant's real values.
# ---------------------------------------------------------------------------
_ha = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
_ha.__path__ = []
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


class _AnyMember:
    """Stand-in for a Home Assistant enum; any attribute names itself."""

    def __getattr__(self, name: str) -> str:
        """Return the attribute name lowercased."""
        return name.lower()


_ha_const.Platform = _Platform
_ha_const.PERCENTAGE = "%"
for _unit_class in (
    "UnitOfElectricPotential",
    "UnitOfEnergy",
    "UnitOfPower",
    "UnitOfPressure",
    "UnitOfTemperature",
    "UnitOfTime",
    "UnitOfVolume",
    "UnitOfVolumeFlowRate",
):
    setattr(_ha_const, _unit_class, _AnyMember())

_ha_components = sys.modules.setdefault(
    "homeassistant.components", types.ModuleType("homeassistant.components")
)
_ha_components.__path__ = []
_ha_sensor = sys.modules.setdefault(
    "homeassistant.components.sensor",
    types.ModuleType("homeassistant.components.sensor"),
)
_ha_sensor_const = sys.modules.setdefault(
    "homeassistant.components.sensor.const",
    types.ModuleType("homeassistant.components.sensor.const"),
)
_ha_sensor_const.SensorDeviceClass = _AnyMember()
_ha_sensor_const.SensorStateClass = _AnyMember()
_ha_components.sensor = _ha_sensor
_ha_sensor.const = _ha_sensor_const


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"
_CONST_PATH = _TECH_DIR / "const.py"


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


def normalised_function(source: str, function_name: str) -> list[str]:
    """Return a function's code lines, without its docstring or signature.

    The predicates sensor.py and binary_sensor.py both define have to stay
    identical in behaviour. Comments, docstrings and type annotations may
    differ; the logic may not. Reducing both to their code lines makes that
    comparable.
    """
    match = re.search(
        rf"^def {function_name}\b.*?(?=^\S|\Z)", source, re.MULTILINE | re.DOTALL
    )
    assert match is not None, f"no definition of {function_name} in the source"

    lines = match.group(0).splitlines()[1:]  # drop `def ...:` and its annotations
    body = re.sub(r'""".*?"""', "", "\n".join(lines), flags=re.DOTALL)
    return [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def predicate_body(path: pathlib.Path, function_name: str) -> list[str]:
    """Return ``normalised_function`` for a function in the given file."""
    return normalised_function(path.read_text(), function_name)


def is_contact_widget_oracle(widget: dict, sibling: dict | None = None) -> bool:
    """Mirror :func:`sensor._is_contact_widget` for use as a test oracle.

    A dry contact comes as a TYPE_WIDGET tile built entirely of contact widgets,
    so the sibling slot has to carry the marker too: a lone ``unit == -1``
    widget next to a visible reading is the API's "value invisible" and not a
    contact (issue #221). No sibling models a tile whose other slot is empty.

    If sensor.py / binary_sensor.py change the rule, update this oracle and
    re-run the tests so we know both implementations still agree.
    """

    def marker(candidate: dict | None) -> bool:
        """Return whether one widget payload carries the contact marker."""
        return bool(candidate) and (
            candidate.get("unit") == -1
            and candidate.get("type") == 0
            and candidate.get("txtId", 0) != 0
        )

    return marker(widget) and (sibling is None or marker(sibling))


def is_flag_widget_oracle(widget: dict, sibling: dict | None = None) -> bool:
    """Mirror :func:`sensor._is_flag_widget` for use as a test oracle.

    A value type 28 widget without a label of its own is named after its
    sibling, so it is exposed whenever either slot carries a label (issue #221).

    If sensor.py / binary_sensor.py change the rule, update this oracle and
    re-run the tests so we know both implementations still agree.
    """
    txt_id = widget.get("txtId") or (sibling or {}).get("txtId", 0)
    return widget.get("unit") == 28 and txt_id != 0


def sibling_of(tile: dict, widget_key: str) -> dict | None:
    """Return the tile's other widget payload, as the platforms' helper does."""
    params = tile.get("params", {})
    return params.get("widget2" if widget_key == "widget1" else "widget1")


def has_pump_widget_oracle(params: dict) -> bool:
    """Mirror :func:`binary_sensor._has_pump_widget` for use as a test oracle.

    A tile gets a statusId ON/OFF binary sensor when it carries a pump-type
    widget (``type`` 1 or 2) whose *value type* is a pump quantity: a
    temperature or a percentage. Issue #221 narrowed the rule to that, because
    heat pumps mark every reading with the pump subtype and the tile's pressure,
    energy, flow and runtime readings were raising phantom ON/OFF sensors.

    If binary_sensor.py changes the rule, update this oracle and re-run the tests
    so we know the fixtures still reflect it.
    """

    def is_pump_reading(widget: dict) -> bool:
        """Return whether one widget's value type is a pump quantity."""
        metadata = C.widget_unit(widget.get("unit"))
        return (
            metadata.device_class == "temperature"
            or metadata.unit == C.widget_unit(8).unit
        )

    for key in ("widget1", "widget2"):
        widget = params.get(key)
        if not widget:
            continue
        if widget.get("type") not in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP):
            continue
        if is_pump_reading(widget):
            return True
    return False


# ---------------------------------------------------------------------------
# _is_contact_widget oracle
# ---------------------------------------------------------------------------


class TestIsContactWidget:
    """Verify the contact-widget marker triple behaves as documented."""

    def test_canonical_contact_returns_true(self):
        """A tile of contact widgets (unit=-1, type=0, labelled) is a contact."""
        widget = {"unit": -1, "type": 0, "txtId": 1234, "value": 0}
        sibling = {"unit": -1, "type": 0, "txtId": 1235, "value": 0}
        assert is_contact_widget_oracle(widget, sibling) is True

    def test_lone_invisible_value_is_not_a_contact(self):
        """A lone unit=-1 widget next to a visible reading is invisible, not a contact.

        Issue #221: the Kołton ST-5305 pairs a labelled unit=-1 widget with its
        "Enabled / Disabled" widget, and reading those 18 as contacts produced
        phantom opening sensors.
        """
        widget = {"unit": -1, "type": 0, "txtId": 4492, "value": 0}
        flag = {"unit": 28, "type": 1, "txtId": 0, "value": 1}
        reading = {"unit": 7, "type": 1, "txtId": 0, "value": 521}
        assert is_contact_widget_oracle(widget, flag) is False
        assert is_contact_widget_oracle(widget, reading) is False

    def test_half_a_contact_tile_is_not_a_contact_tile(self):
        """The sibling has to carry the marker itself, not just be invisible."""
        contact = {"unit": -1, "type": 0, "txtId": 834, "value": 0}
        placeholder = {"unit": -1, "type": 0, "txtId": 0, "value": 0}
        assert is_contact_widget_oracle(contact, placeholder) is False

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

    def test_predicate_bodies_match(self):
        """Verify sensor.py and binary_sensor.py encode the same rule.

        The earlier version of this test only looked for marker strings, which
        cannot tell a matching pair from one that has drifted - an added
        condition would still have passed. The two implementations are therefore
        compared as normalised source.
        """
        assert predicate_body(
            _TECH_DIR / "sensor.py", "_is_contact_widget"
        ) == predicate_body(_TECH_DIR / "binary_sensor.py", "_is_contact_widget")

    def test_the_comparison_notices_a_drifted_condition(self):
        """Verify the guard above cannot pass on a diverged pair.

        An extra condition is exactly the drift the string-based check missed, so
        the comparison is exercised against a deliberately divergent copy.
        """
        original = (
            "def _is_contact_widget(widget: dict) -> bool:\n"
            '    """Return whether the widget is a contact."""\n'
            "    return (\n"
            '        widget.get("unit") == -1\n'
            '        and widget.get("txtId", 0) != 0\n'
            "    )\n"
        )
        drifted = original.replace(
            'widget.get("txtId", 0) != 0', 'widget.get("txtId", 0) != 0\n        and widget.get("extra")'
        )

        assert normalised_function(original, "_is_contact_widget") != (
            normalised_function(drifted, "_is_contact_widget")
        )

    def test_unit6_skip_condition_source_matches(self):
        """sensor.py must encode the updated unit=6 skip rule (skip only when value==0)."""
        sensor_src = (
            _REPO_ROOT / "custom_components" / "tech" / "sensor.py"
        ).read_text()
        # The new skip condition: only skip unit=6 widgets with value==0.
        assert 'if widget.get("unit") == 6 and widget.get("value", 0) == 0:' in sensor_src


class TestIsFlagWidget:
    """Verify the value type 28 enable/disable marker."""

    def test_canonical_flag_returns_true(self):
        """A labelled unit=28 widget is a flag."""
        widget = {"unit": 28, "type": 1, "txtId": 4640, "value": 1}
        assert is_flag_widget_oracle(widget) is True

    def test_widget_type_is_not_part_of_the_marker(self):
        """Real payloads carry flags as type=1, so type must not disqualify."""
        widget = {"unit": 28, "type": 1, "txtId": 4640, "value": 0}
        assert is_flag_widget_oracle(widget) is True

    def test_markers_stay_disjoint(self):
        """No widget may be claimed by both the contact and the flag rule."""
        flag = {"unit": 28, "type": 1, "txtId": 4640, "value": 1}
        contact = {"unit": -1, "type": 0, "txtId": 1234, "value": 1}
        assert is_contact_widget_oracle(flag) is False
        assert is_flag_widget_oracle(contact) is False

    def test_zero_txtid_disables_flag_without_a_sibling_label(self):
        """An unlabelled flag with no label to borrow stays hidden."""
        widget = {"unit": 28, "type": 1, "txtId": 0, "value": 1}
        placeholder = {"unit": -1, "type": 0, "txtId": 0, "value": 0}
        assert is_flag_widget_oracle(widget) is False
        assert is_flag_widget_oracle(widget, placeholder) is False

    def test_sibling_label_exposes_an_unlabelled_flag(self):
        """A unit=28 widget without its own label takes the sibling's.

        Issue #221: the Kołton ST-5305 carries 18 of these, with the label on the
        unit=-1 widget next to the state, so they used to be dropped (or, on the
        intermediate branch, published as 0/1 sensors named "<label> Set
        Temperature").
        """
        widget = {"unit": 28, "type": 1, "txtId": 0, "value": 1}
        sibling = {"unit": -1, "type": 0, "txtId": 4492, "value": 0}
        assert is_flag_widget_oracle(widget, sibling) is True

    def test_temperature_widget_is_not_a_flag(self):
        """A unit=7 temperature widget must not be misread as a flag."""
        widget = {"unit": 7, "type": 9, "txtId": 774, "value": 521}
        assert is_flag_widget_oracle(widget) is False

    def test_predicate_source_matches_oracle(self):
        """Verify sensor.py and binary_sensor.py still encode the same rule."""
        sensor_src = (
            _REPO_ROOT / "custom_components" / "tech" / "sensor.py"
        ).read_text()
        binary_src = (
            _REPO_ROOT / "custom_components" / "tech" / "binary_sensor.py"
        ).read_text()
        for src in (sensor_src, binary_src):
            assert "def _is_flag_widget" in src
            assert 'widget.get("unit") == 28' in src


# ---------------------------------------------------------------------------
# Mirrored widget predicates
# ---------------------------------------------------------------------------

# sensor.py and binary_sensor.py each decide which widgets they own, and both
# have to reach the same verdict: a diverged copy claims a widget twice or drops
# it. The two copies are compared as normalised source, so a docstring or a
# comment may differ while the logic may not.
MIRRORED_WIDGET_PREDICATES = (
    "_sibling_widget",
    "_is_contact_marker",
    "_is_contact_widget",
    "_widget_txt_id",
    "_is_flag_widget",
)


class TestMirroredWidgetPredicates:
    """Every shared widget predicate must stay identical in both platforms."""

    def test_the_two_platforms_encode_the_same_rule(self):
        """Compare both copies of each predicate, ignoring comments."""
        for function_name in MIRRORED_WIDGET_PREDICATES:
            assert predicate_body(
                _TECH_DIR / "sensor.py", function_name
            ) == predicate_body(
                _TECH_DIR / "binary_sensor.py", function_name
            ), function_name


# ---------------------------------------------------------------------------
# Constants tables
# ---------------------------------------------------------------------------


class TestUnitDivisors:
    """WIDGET_UNITS scales raw widget values and carries their HA metadata."""

    def test_unit_7_is_tenths_of_degree(self):
        """unit=7 (boiler temperatures) scales by 10: 521 -> 52.1°C."""
        # The most common boiler temperature unit. value=521 -> 52.1°C.
        assert C.widget_unit(7).divisor == 10

    def test_unit_5_is_hundredths(self):
        """unit=5 widget values scale by 100."""
        assert C.widget_unit(5).divisor == 100

    def test_unit_4_is_tenths(self):
        """unit=4 widget values scale by 10."""
        assert C.widget_unit(4).divisor == 10

    def test_unit_6_passes_through(self):
        """unit=6 (state-badge enums) must not be scaled."""
        # State badges should not be scaled (their value is an enum, not a temp).
        assert C.widget_unit(6).divisor == 1

    def test_elapsed_time_counters_are_registered_disabled(self):
        """Value types 3 and 13 are counters, so their entities stay switched off.

        Issue #221: the reporter asked for his eight numbered compressor
        run-time/downtime counters to stay out of the way. The payload has no
        counter-specific marker -- only the value types, which the same
        controller also uses for three other duration readings -- so the family
        is registered disabled and any reading a user wants is one toggle away.
        """
        assert C.widget_unit(3).enabled_default is False
        assert C.widget_unit(C.WIDGET_UNIT_TIME_OF_DAY).enabled_default is False
        # Everything else starts enabled, including the other durations (16/17),
        # the temperatures and the measurements.
        for code in (0, 6, 7, 8, 16, 17, 23, 26, 32, 38, 39):
            assert C.widget_unit(code).enabled_default is True, code

    def test_every_documented_code_is_present(self):
        """The table covers every value type the API documents (issue #221)."""
        # The API's "Data types format" table runs from -1 (invisible) to 42
        # (cubic metres). A missing code would fall back to the ordinary-value
        # entry, so coverage is pinned rather than assumed.
        assert set(C.WIDGET_UNITS) == set(range(-1, 43))

    def test_divisors_cover_the_documented_transformations(self):
        """Every code the API divides carries the documented divisor."""
        assert {
            code: C.widget_unit(code).divisor
            for code in (4, 5, 7, 19, 21, 22, 23, 26, 30, 33, 36, 38, 40)
        } == {
            4: 10,
            5: 100,
            7: 10,
            19: 10,
            21: 10,
            22: 10,
            23: 10,
            26: 10,
            30: 100,
            33: 10,
            36: 100,
            38: 10,
            40: 1000,
        }

    def test_unit_19_is_tenths_of_a_kwh(self):
        """unit=19 is "kWh with a decimal point": 1234 -> 123.4 kWh."""
        # Issue #221: value type 19 was published with divisor 1. The API names
        # the decimal point without stating the transformation, and the eModul
        # app's formatter does `case 19: t *= 0.1; t.toFixed(1)`, so the value
        # is tenths of a kWh, exactly like the other "with a decimal point"
        # codes (21 MWh, 26 kW).
        assert C.widget_unit(19).divisor == 10
        assert C.widget_unit(19).precision == 1

    def test_unit_39_is_a_flow_rate_in_litres_per_hour(self):
        """unit=39 carries the unit the eModul app labels it with (issue #221).

        The API prose calls value type 39 "Value l / m" and stops there; the app
        renders it with the same string as value type 30, which is litres per
        hour, and applies no transformation, so the raw integer is published
        as-is.
        """
        entry = C.widget_unit(39)
        assert entry.unit is not None
        assert entry.unit != C.widget_unit(0).unit
        assert entry.device_class == "volume_flow_rate"
        assert entry.state_class == "measurement"
        assert entry.divisor == 1


class TestHoursAndMinutesValues:
    """Value type 13 is a two-field reading, for clocks and for counters."""

    def test_the_raw_value_is_split_into_two_fields(self):
        """The API stores a count and the controller shows count//60 : count%60."""
        # 889 = 14 * 60 + 49, 1041 = 17 * 60 + 21, so those read as times of day.
        assert C.widget_hours_and_minutes(0) == "00:00"
        assert C.widget_hours_and_minutes(889) == "14:49"
        assert C.widget_hours_and_minutes(1041) == "17:21"
        assert C.widget_hours_and_minutes(1439) == "23:59"

    def test_the_first_field_is_not_bounded(self):
        """Controllers also use the type for counters, so 24 h and up is fine.

        Issue #221: the reporter's Kołton counts its compressor downtime in a
        type 13 field, and its history advanced 205:00 -> 226:00 over about
        twenty minutes -- one per second, so the field counts seconds and 2190 is
        36 minutes 30 seconds. A field whose raw value counts minutes renders the
        same two fields, so the string is right either way; it is the unit that
        the payload does not state.
        """
        assert C.widget_hours_and_minutes(1440) == "24:00"
        assert C.widget_hours_and_minutes(2190) == "36:30"  # 36 min 30 s, or 36 h 30 min
        assert C.widget_hours_and_minutes(6000) == "100:00"

    def test_values_the_format_cannot_express_are_unknown(self):
        """Negative, fractional and non-numeric values are not readings."""
        # -29536 is the sentinel the Kołton ST-5305 payload carries in one of its
        # seven value type 13 widgets.
        for value in (-1, -29536, 2.5, None, "889", True):
            assert C.widget_hours_and_minutes(value) is None

    def test_the_reading_carries_no_numeric_metadata(self):
        """HA rejects a non-numeric state when a unit, class or precision wants one."""
        entry = C.widget_unit(C.WIDGET_UNIT_TIME_OF_DAY)
        assert (entry.unit, entry.state_class, entry.precision) == (None, None, None)


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
            divisor = C.widget_unit(w["unit"]).divisor
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
                if is_contact_widget_oracle(w, sibling_of(tile, key)):
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
            if has_pump_widget_oracle(tile["params"]):
                count += 1
        # ST-491's TYPE_WIDGET tiles carry CH/DHW temperatures (type=9) and no
        # pump-type widget at all
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
                if is_contact_widget_oracle(w, sibling_of(tile, key)):
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
                if is_contact_widget_oracle(w, sibling_of(tile, key)):
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
        assert C.widget_unit(8).divisor == 1

    def test_all_widget_tiles_have_status_binary_sensor(self):
        """The lone TYPE_WIDGET tile has a pump-type widget and gets a status sensor."""
        count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id not in (0, 1):
                continue
            if has_pump_widget_oracle(tile["params"]):
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
                assert is_contact_widget_oracle(w1, sibling_of(tile, "widget1")), (
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
                if is_contact_widget_oracle(w, sibling_of(tile, key)):
                    continue
                if w.get("unit") == 6:
                    continue
                emitted += 1
        assert emitted == 66

    def test_all_widget_tiles_have_status_binary_sensor(self):
        """35 of 70 TYPE_WIDGET tiles get a statusId ON/OFF sensor.

        Only tiles whose pump-type widget reads a pump quantity qualify: a
        temperature (30 tiles at unit=7) or a percentage (4 at unit=8, 1 at
        unit=33). The 4 pure contact tiles and the readings that happen to carry
        the pump subtype -- energy, pressure, COP, flow, runtime -- do not
        (issue #221).
        """
        count = 0
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            status_id = tile["params"].get("statusId")
            if status_id not in (0, 1):
                continue
            if has_pump_widget_oracle(tile["params"]):
                count += 1
        assert count == 35

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

    def test_documented_value_type_divisors(self):
        """The API's value-type table divisors are all present."""
        documented = {21: 10, 22: 10, 30: 100, 36: 100, 40: 1000}
        assert {unit: C.widget_unit(unit).divisor for unit in documented} == documented

        # 38 (COP) is inferred rather than stated: the API documents decimal
        # places without a transformation, and reported COP values divide by 10.
        assert C.widget_unit(38).divisor == 10


# ---------------------------------------------------------------------------
# Fixture-driven assertions: Kołton ST-5305 heat pump
# ---------------------------------------------------------------------------


class TestKoltonSt5305Fixture:
    """Live Kołton ST-5305 heat pump payload (issue #221).

    Attached to the issue by the reporter and kept as the permanent regression
    fixture for widget value types. The controller reports no temperature widget
    at all - its value types are -1, 0, 3, 8, 13, 23, 26, 28, 32, 38 and 39 -
    yet every reading used to be published as degrees Celsius with the
    temperature device class.
    """

    @classmethod
    def setup_class(cls):
        """Load the captured ST-5305 module payload once for the class."""
        cls.module = _load("kolton_st5305/module.json")

    def widgets(self):
        """Yield ``(tile, slot, params, widget)`` for every widget payload."""
        for tile in self.module["tiles"]:
            if tile["type"] != C.TYPE_WIDGET:
                continue
            params = tile["params"]
            for key in ("widget1", "widget2"):
                widget = params.get(key)
                if widget:
                    yield tile, key, params, widget

    def test_tile_counts(self):
        """98 tiles, 52 of them TYPE_WIDGET."""
        assert len(self.module["tiles"]) == 98
        assert sum(1 for t in self.module["tiles"] if t["type"] == C.TYPE_WIDGET) == 52

    def test_value_type_histogram(self):
        """The payload's value types, pinned so the fixture cannot drift."""
        assert Counter(w["unit"] for *_, w in self.widgets()) == {
            -1: 52,
            0: 11,
            3: 4,
            8: 4,
            13: 7,
            23: 2,
            26: 2,
            28: 18,
            32: 2,
            38: 1,
            39: 1,
        }

    def test_no_widget_reports_a_temperature(self):
        """No unit 6/7 widget exists, so nothing here may become a temperature."""
        assert {w["unit"] for *_, w in self.widgets()}.isdisjoint({6, 7})

    def test_the_invisible_widgets_are_not_contacts(self):
        """All 52 unit=-1 widgets are invisible values; none of them is a contact.

        34 carry no label of their own (placeholders) and the other 18 carry the
        label belonging to the value type 28 widget beside them - those used to
        be published as opening sensors.
        """
        invisible = [(t, k, w) for t, k, _, w in self.widgets() if w["unit"] == -1]
        assert len(invisible) == 52
        assert sum(1 for _, _, w in invisible if w["txtId"] != 0) == 18
        for tile, key, widget in invisible:
            assert (
                is_contact_widget_oracle(widget, sibling_of(tile, key)) is False
            ), (tile["id"], key)

    def test_the_state_widgets_are_flags_named_by_their_sibling(self):
        """The 18 unit=28 widgets borrow the label of the widget next to them."""
        flags = [(t, k, w) for t, k, _, w in self.widgets() if w["unit"] == 28]
        assert len(flags) == 18
        for tile, key, widget in flags:
            sibling = sibling_of(tile, key)
            assert widget["txtId"] == 0, tile["id"]
            assert is_flag_widget_oracle(widget, sibling) is True, tile["id"]
            assert sibling["unit"] == -1 and sibling["txtId"] != 0, tile["id"]

    def test_time_widgets_are_minutes(self):
        """Seven value type 13 widgets: six usable counts and one bad value."""
        values = sorted(w["value"] for *_, w in self.widgets() if w["unit"] == 13)
        assert values == [-29536, 0, 0, 0, 0, 0, 1041]
        assert C.widget_hours_and_minutes(1041) == "17:21"
        # -29536 is negative, so it is unknown rather than a negative reading.
        assert C.widget_hours_and_minutes(-29536) is None
        # The reporter's own counter reading from these fields. His history shows
        # the raw value counting seconds (205:00 -> 226:00 in ~20 min), so this is
        # 36 min 30 s; a minutes-valued field would split identically.
        assert C.widget_hours_and_minutes(2190) == "36:30"

    def test_power_cop_and_kelvin_readings(self):
        """Power and COP are tenths; a kelvin difference takes no class."""
        assert C.widget_unit(26).divisor == 10
        assert C.widget_unit(38).divisor == 10
        assert C.widget_unit(38).unit is None
        assert C.widget_unit(32).device_class is None
        assert [w["value"] for *_, w in self.widgets() if w["unit"] == 32] == [3, 10]

    def test_every_value_type_resolves_through_the_table(self):
        """No undocumented code: each one of them is a WIDGET_UNITS entry."""
        assert {w["unit"] for *_, w in self.widgets()} <= set(C.WIDGET_UNITS)

    def test_only_the_duty_cycle_tiles_get_a_status_sensor(self):
        """Four tiles qualify for a statusId ON/OFF sensor, not fifty-one.

        Every widget on this controller carries the pump subtype, so the rule
        has to require a pump *quantity* as well: only the percentage readings
        are the pumps' own duty cycle (issue #221).
        """
        status_tiles = [
            tile["id"]
            for tile in self.module["tiles"]
            if tile["type"] == C.TYPE_WIDGET
            and tile["params"].get("statusId") in (0, 1)
            and has_pump_widget_oracle(tile["params"])
        ]
        assert status_tiles == [1006, 1014, 1552, 2270]

    def test_the_old_rule_would_have_qualified_fifty_one_tiles(self):
        """Guard the numbers the reporter measured on his controller."""
        eligible = [
            tile
            for tile in self.module["tiles"]
            if tile["type"] == C.TYPE_WIDGET
            and tile["params"].get("statusId") in (0, 1)
            and any(
                tile["params"].get(key, {}).get("type")
                in (C.WIDGET_DHW_PUMP, C.WIDGET_COLLECTOR_PUMP)
                for key in ("widget1", "widget2")
            )
        ]
        assert len(eligible) == 51
