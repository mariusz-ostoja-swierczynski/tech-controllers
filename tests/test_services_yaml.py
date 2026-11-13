"""Tests for the action descriptions in ``services.yaml``.

Home Assistant builds the action editor from ``services.yaml``: the target
picker and every field's selector come from that file, while ``strings.json``
only supplies the names and descriptions. The schemas in ``services.py``
validate a call on the server, so without the descriptions the editor renders
an action with no target and no fields and submits nothing. These tests pin the
file's contract and keep its field keys in step with the translations.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
import yaml

_TECH_DIR = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "tech"
_SERVICES_FILE = _TECH_DIR / "services.yaml"
_STRINGS_FILE = _TECH_DIR / "strings.json"

_ACTIONS = ("set_zone_schedule", "set_zone_constant")


def _services() -> dict[str, Any]:
    """Return the parsed action descriptions."""
    return yaml.safe_load(_SERVICES_FILE.read_text(encoding="utf-8"))


def _strings() -> dict[str, Any]:
    """Return the parsed integration translations."""
    return json.loads(_STRINGS_FILE.read_text(encoding="utf-8"))


def test_both_actions_are_described() -> None:
    """Both registered actions have an entry in the action descriptions."""
    assert set(_services()) == set(_ACTIONS)


@pytest.mark.parametrize("action", _ACTIONS)
def test_action_targets_tech_climate_entities(action: str) -> None:
    """Each action offers only Tech climate entities as its target."""
    assert _services()[action]["target"] == {
        "entity": {"integration": "tech", "domain": "climate"}
    }


def test_set_zone_schedule_fields() -> None:
    """The schedule action offers one dropdown and no legacy fields."""
    fields = _services()["set_zone_schedule"]["fields"]

    assert set(fields) == {"schedule"}
    schedule = fields["schedule"]
    assert schedule["required"] is True
    assert schedule["example"] == "Weekend"
    selector = schedule["selector"]
    assert selector["select"]["mode"] == "dropdown"
    assert {"value": "local", "label": "Local schedule"} in selector["select"][
        "options"
    ]


def test_set_zone_constant_fields() -> None:
    """The constant action asks for a temperature and an optional duration."""
    fields = _services()["set_zone_constant"]["fields"]

    temperature = fields["temperature"]
    assert temperature["required"] is True
    assert temperature["selector"]["number"] == {
        "min": 5,
        "max": 35,
        "step": 0.1,
        "unit_of_measurement": "°C",
        "mode": "box",
    }

    duration = fields["duration_minutes"]
    assert duration["required"] is False
    assert duration["selector"]["number"] == {
        "min": 0,
        "max": 1440,
        "step": 1,
        "unit_of_measurement": "min",
        "mode": "box",
    }


@pytest.mark.parametrize("action", _ACTIONS)
def test_field_keys_match_the_translations(action: str) -> None:
    """The action editor's fields are exactly the ones strings.json names."""
    assert set(_services()[action]["fields"]) == set(
        _strings()["services"][action]["fields"]
    )


@pytest.mark.parametrize("action", _ACTIONS)
def test_action_description_holds_only_the_contract(action: str) -> None:
    """Names and descriptions stay in strings.json, not in services.yaml."""
    assert set(_services()[action]) == {"target", "fields"}
