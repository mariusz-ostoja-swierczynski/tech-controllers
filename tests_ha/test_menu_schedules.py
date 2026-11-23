"""Decode weekly menu programs with synthetic, offline payloads."""

from __future__ import annotations

from copy import deepcopy

import pytest

from custom_components.tech import menu_schedules as decoder


def _item(tree, item_id, item_type, params, parent=0):
    return {
        "menuType": tree,
        "id": item_id,
        "type": item_type,
        "parentId": parent,
        "access": True,
        "params": params,
        "duringChange": None,
    }


def _snapshot():
    mu = [
        _item("MU", 3203, 1, {"value": 60, "format": 1, "min": 5, "max": 80}),
        _item("MU", 3200, 11, {"value": 2}),
        _item("MU", 3205, 10, {"value": 1}),
    ]
    mi = [
        _item("MI", 10370, 11, {"value": 0}),
        {**_item("MI", 30667, 10, {"value": 0}, 30666), "access": False},
    ]
    for day in range(7):
        mu.append(
            _item(
                "MU",
                3206 + day,
                12,
                {
                    "dayId": day,
                    "min": -20,
                    "max": 20,
                    "valueObjId": 3203,
                    "values": [0] * 24
                    if day == 4
                    else [3, 3, 3, 15, 15, 15, 10 if day in (0, 6) else 30],
                },
                30028,
            )
        )
        mi.append(
            _item(
                "MI",
                10441 + day * 3,
                13,
                {
                    "dayId": day,
                    "noZones": 48,
                    "daySubtitles": 0,
                    "value": 0
                    if day == 4
                    else 93824992215045
                    if day in (0, 6)
                    else 93824992215040,
                },
                30666,
            )
        )
    return {
        "MU": {"status": "ok", "elements": mu},
        "MI": {"status": "ok", "elements": mi},
    }


def _day(snapshot, tree="MU", day=1):
    return next(
        item
        for item in snapshot[tree]["elements"]
        if item.get("type") in (12, 13) and item["params"]["dayId"] == day
    )


def _decode(snapshot, index=0, success=True):
    return decoder.weekly_schedule(snapshot, decoder.PROFILES[index], success)


def test_recorded_shape_formulas_day_order_and_sparse_windows():
    """Recorded shape formulas day order and sparse windows."""
    snapshot = _snapshot()
    assert decoder.supported_profiles(snapshot) == list(decoder.PROFILES)
    dhw, circulation = _decode(snapshot), _decode(snapshot, 1)
    assert dhw["status"] == circulation["status"] == "ready"
    assert list(dhw["days"]) == [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    assert [day["day_id"] for day in dhw["days"].values()] == [1, 2, 3, 4, 5, 6, 0]
    assert dhw["days"]["monday"]["intervals"] == [
        {"start": 0, "stop": 180, "offset": -17, "target": 43},
        {"start": 180, "stop": 360, "offset": -5, "target": 55},
        {"start": 360, "stop": 420, "offset": 10, "target": 70},
        {"start": 420, "stop": 1440, "offset": 0, "target": 60},
    ]
    assert dhw["days"]["thursday"]["intervals"] == [
        {"start": 0, "stop": 1440, "offset": -20, "target": 40}
    ]
    assert dhw["days"]["sunday"]["intervals"][2]["target"] == 50
    assert dhw["base_value"] == 60 and dhw["base_format"] == 1
    assert dhw["schedule_selected"] is circulation["schedule_selected"] is True
    assert circulation["mode_value"] == 0
    assert circulation["days"]["thursday"]["valid"] is True
    assert circulation["days"]["thursday"]["intervals"] == []
    assert circulation["days"]["monday"]["intervals"] == [
        {"start": hour * 60, "stop": hour * 60 + 30, "allowed": True}
        for hour in range(8, 24)
    ]
    assert circulation["days"]["sunday"]["intervals"][:2] == [
        {"start": 0, "stop": 30, "allowed": True},
        {"start": 60, "stop": 90, "allowed": True},
    ]
    assert dhw["time_basis"] == "controller_local" and dhw["timezone_verified"] is False
    assert (
        dhw["schema_version"] == 1 and dhw["schedule_type"] == "temperature_correction"
    )


def test_empty_array_uses_base_and_target_is_not_clamped():
    """Empty array uses base and target is not clamped."""
    snapshot = _snapshot()
    _day(snapshot)["params"]["values"] = []
    assert _decode(snapshot)["days"]["monday"]["intervals"] == [
        {"start": 0, "stop": 1440, "offset": 0, "target": 60}
    ]
    snapshot["MU"]["elements"][0]["params"]["value"] = 80
    _day(snapshot)["params"]["values"] = [40] * 24
    assert _decode(snapshot)["days"]["monday"]["intervals"] == [
        {"start": 0, "stop": 1440, "offset": 20, "target": 100}
    ]


@pytest.mark.parametrize(
    "values",
    [
        None,
        [None],
        [True],
        [1.0],
        ["1"],
        [-1],
        [41],
        [0] * 25,
        {},
        "",
        [float("nan")],
        [float("inf")],
    ],
)
def test_invalid_corrections_never_receive_base_fallback(values):
    """Invalid corrections never receive base fallback."""
    snapshot = _snapshot()
    _day(snapshot)["params"]["values"] = values
    result = _decode(snapshot)
    assert result["status"] == "invalid"
    assert result["days"]["monday"]["valid"] is False
    assert result["days"]["monday"]["intervals"] == []
    assert result["days"]["tuesday"]["valid"] is True


@pytest.mark.parametrize(
    "params",
    [
        {"min": 21, "max": 20},
        {"min": False},
        {"valueObjId": 3204},
        {"valueObjId": True},
        {"dayId": 7},
        {"dayId": True},
    ],
)
def test_invalid_type12_metadata(params):
    """Invalid type12 metadata."""
    snapshot = _snapshot()
    _day(snapshot)["params"].update(params)
    result = _decode(snapshot)
    assert result["status"] == "invalid"
    assert result["days"]["monday"]["intervals"] == []


def test_range_consistency_missing_day_and_duplicate_id_are_explicit():
    """Range consistency missing day and duplicate id are explicit."""
    snapshot = _snapshot()
    _day(snapshot)["params"]["min"] = -19
    assert "inconsistent_range" in _decode(snapshot)["errors"]
    snapshot = _snapshot()
    day = _day(snapshot)
    snapshot["MU"]["elements"].remove(day)
    result = _decode(snapshot)
    assert result["status"] == "missing" and result["days"]["monday"]["valid"] is False
    duplicate = deepcopy(_day(snapshot, day=2))
    duplicate["params"]["dayId"] = 1
    snapshot["MU"]["elements"].append(duplicate)
    assert _decode(snapshot)["status"] == "invalid"
    snapshot["MU"]["elements"].append(deepcopy(duplicate))
    assert "duplicate_day" in _decode(snapshot)["days"]["monday"]["errors"]


@pytest.mark.parametrize("value", [None, True, False, "60", 60.0, 0, -1, -9999, 81])
def test_bad_base_clears_every_dependent_target(value):
    """Bad base clears every dependent target."""
    snapshot = _snapshot()
    snapshot["MU"]["elements"][0]["params"]["value"] = value
    result = _decode(snapshot)
    assert result["status"] == "invalid" and result["base_value"] is None
    assert all(
        not day["valid"] and not day["intervals"] for day in result["days"].values()
    )


@pytest.mark.parametrize(
    ("width", "bit"), [(width, bit) for width in (24, 48) for bit in range(width)]
)
def test_every_timer_bit_has_exact_controller_clock_boundaries(width, bit):
    """Every timer bit has exact controller clock boundaries."""
    snapshot = _snapshot()
    _day(snapshot, "MI")["params"].update(noZones=width, value=1 << bit)
    day = _decode(snapshot, 1)["days"]["monday"]
    assert day["valid"] is True
    step = 1440 // width
    assert day["intervals"] == [
        {"start": bit * step, "stop": (bit + 1) * step, "allowed": True}
    ]


@pytest.mark.parametrize("width", [24, 48])
def test_all_on_and_adjacent_timer_bits_merge_without_crossing_gaps(width):
    """All on and adjacent timer bits merge without crossing gaps."""
    snapshot = _snapshot()
    params = _day(snapshot, "MI")["params"]
    params.update(noZones=width, value=(1 << width) - 1)
    assert _decode(snapshot, 1)["days"]["monday"]["intervals"] == [
        {"start": 0, "stop": 1440, "allowed": True}
    ]
    params["value"] = 0b1011
    step = 1440 // width
    assert _decode(snapshot, 1)["days"]["monday"]["intervals"] == [
        {"start": 0, "stop": 2 * step, "allowed": True},
        {"start": 3 * step, "stop": 4 * step, "allowed": True},
    ]


@pytest.mark.parametrize(
    "params",
    [{"value": value} for value in [None, True, False, "0", 1.0, -1, 1 << 48]]
    + [{"noZones": width} for width in [None, True, 0, 23, 25, 47, 49, "48"]]
    + [{"daySubtitles": 1}, {"daySubtitles": False}],
)
def test_invalid_timer_is_distinct_from_all_off(params):
    """Invalid timer is distinct from all off."""
    snapshot = _snapshot()
    _day(snapshot, "MI")["params"].update(params)
    result = _decode(snapshot, 1)
    assert result["status"] == "invalid"
    assert result["days"]["monday"]["valid"] is False
    assert result["days"]["monday"]["intervals"] == []


@pytest.mark.parametrize(
    ("flag", "expected"),
    [
        (None, "ready"),
        (False, "ready"),
        ("f", "ready"),
        (True, "pending"),
        ("t", "pending"),
        (0, "invalid"),
        (1, "invalid"),
        ("", "invalid"),
        ("false", "invalid"),
        ("true", "invalid"),
    ],
)
def test_full_get_change_flags_do_not_use_truthiness(flag, expected):
    """Full get change flags do not use truthiness."""
    snapshot = _snapshot()
    _day(snapshot)["duringChange"] = flag
    result = _decode(snapshot)
    assert result["status"] == expected
    assert result["days"]["monday"]["valid"] is (expected == "ready")
    assert result["days"]["tuesday"]["valid"] is True


def test_missing_flag_allowed_pending_base_and_status_precedence():
    """Missing flag allowed pending base and status precedence."""
    snapshot = _snapshot()
    _day(snapshot).pop("duringChange")
    assert _decode(snapshot)["status"] == "ready"
    snapshot["MU"]["elements"][0]["duringChange"] = "t"
    result = _decode(snapshot)
    assert result["status"] == "pending"
    assert all(day["intervals"] == [] for day in result["days"].values())
    snapshot["MU"]["elements"].remove(_day(snapshot, day=2))
    assert _decode(snapshot)["status"] == "missing"
    _day(snapshot)["params"]["values"] = None
    assert _decode(snapshot)["status"] == "invalid"


@pytest.mark.parametrize(
    ("mode", "weekly", "selected"),
    [(2, 1, True), (2, 0, False), (1, 1, False), (3, 1, False)],
)
def test_dhw_selection_is_separate_from_preserved_table(mode, weekly, selected):
    """Dhw selection is separate from preserved table."""
    snapshot = _snapshot()
    snapshot["MU"]["elements"][1]["params"]["value"] = mode
    snapshot["MU"]["elements"][2]["params"]["value"] = weekly
    result = _decode(snapshot)
    assert result["status"] == "ready" and result["schedule_selected"] is selected
    assert result["days"]["monday"]["valid"] is True


@pytest.mark.parametrize(("mode", "selected"), [(0, True), (1, False), (2, False)])
def test_circulation_mode_ignores_inaccessible_placeholder(mode, selected):
    """Circulation mode ignores inaccessible placeholder."""
    snapshot = _snapshot()
    snapshot["MI"]["elements"][0]["params"]["value"] = mode
    result = _decode(snapshot, 1)
    assert result["status"] == "ready" and result["schedule_selected"] is selected


@pytest.mark.parametrize("index", [0, 1])
@pytest.mark.parametrize("fault", ["missing", "pending", "invalid"])
def test_selector_faults_never_guess_applicability(index, fault):
    """Selector faults never guess applicability."""
    snapshot = _snapshot()
    elements = snapshot["MU" if index == 0 else "MI"]["elements"]
    item = elements[1 if index == 0 else 0]
    if fault == "missing":
        elements.remove(item)
    elif fault == "pending":
        item["duringChange"] = "t"
    else:
        item["params"]["value"] = False
    result = _decode(snapshot, index)
    assert result["status"] == fault and result["schedule_selected"] is None
    assert result["days"]["monday"]["valid"] is True


@pytest.mark.parametrize(
    "limit",
    [
        "MAX_MENU_ELEMENTS",
        "MAX_MENU_JSON_VALUES",
        "MAX_MENU_JSON_DEPTH",
        "MAX_MENU_TEXT_CHARS",
    ],
)
def test_bounded_tree(monkeypatch: pytest.MonkeyPatch, limit: str) -> None:
    """Large trees do not produce a partial configuration that looks usable."""
    monkeypatch.setattr(decoder, limit, 1)
    snapshot = _snapshot()
    assert decoder.supported_profiles(snapshot) == []
    assert _decode(snapshot)["errors"] == ["menu_resource_limit"]


def test_missing_sources_and_failed_refresh() -> None:
    """Do not advertise an unsupported schedule or a cached selection."""
    assert decoder.supported_profiles(None) == []
    assert decoder.supported_profiles({"MU": {"elements": [None]}}) == []
    assert decoder.supported_profiles({"MU": {"elements": None}}) == []
    assert _decode(None)["status"] is None
    assert _decode({"MU": {"elements": []}})["errors"] == ["menu_malformed"]
    assert _decode({"MU": {"status": "error"}})["status"] is None
    assert _decode({"MU": {"status": "ok", "elements": [None]}})["errors"] == [
        "menu_malformed"
    ]
    assert _decode(_snapshot(), success=False)["source_status"] == "coordinator_error"


@pytest.mark.parametrize("item_id", [None, {}, 3207.0])
def test_duplicate_day_cannot_be_hidden_by_flattening(item_id) -> None:
    """Check the original list, so duplicate ids cannot mask one reported day."""
    snapshot = _snapshot()
    day = _day(snapshot)
    snapshot["MU"]["elements"].append({**day, "id": item_id})
    assert _decode(snapshot)["status"] == "invalid"
    assert not _decode(snapshot)["days"]["monday"]["valid"]
