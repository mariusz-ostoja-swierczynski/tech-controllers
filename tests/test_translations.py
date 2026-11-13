"""Tests ensuring translation key parity and correct entity namespaces.

Every file under ``custom_components/tech/translations`` must contain exactly
the same set of (nested) keys. Only the string values may differ between
languages.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from . import test_platform_device_info as support

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TRANSLATIONS_DIR = _REPO_ROOT / "custom_components" / "tech" / "translations"
_STRINGS_PATH = _TRANSLATIONS_DIR.parent / "strings.json"
_REFERENCE_LANG = "en"


def _collect_keys(data: object, prefix: str = "") -> set[str]:
    """Return the set of dotted key paths for every leaf/branch in ``data``."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys |= _collect_keys(value, path)
    return keys


def _load(path: pathlib.Path) -> dict:
    """Load and parse a JSON translation file."""
    return json.loads(path.read_text(encoding="utf-8"))


def _translation_files() -> list[pathlib.Path]:
    """Return the sorted list of translation JSON files."""
    return sorted(_TRANSLATIONS_DIR.glob("*.json"))


def test_translation_files_exist() -> None:
    """There should be translation files and a reference language present."""
    files = _translation_files()
    assert files, f"No translation files found in {_TRANSLATIONS_DIR}"
    assert (_TRANSLATIONS_DIR / f"{_REFERENCE_LANG}.json").exists(), (
        f"Missing reference translation file '{_REFERENCE_LANG}.json'"
    )


@pytest.mark.parametrize(
    "path",
    [f for f in _translation_files() if f.stem != _REFERENCE_LANG],
    ids=lambda p: p.stem,
)
def test_translation_keys_match_reference(path: pathlib.Path) -> None:
    """Each translation file must share the exact key set of the reference."""
    reference_keys = _collect_keys(_load(_TRANSLATIONS_DIR / f"{_REFERENCE_LANG}.json"))
    keys = _collect_keys(_load(path))

    missing = reference_keys - keys
    extra = keys - reference_keys

    assert not missing and not extra, (
        f"Translation '{path.name}' key mismatch vs '{_REFERENCE_LANG}.json':\n"
        f"  missing: {sorted(missing)}\n"
        f"  extra:   {sorted(extra)}"
    )


@pytest.mark.parametrize(
    "path", [_STRINGS_PATH, *_translation_files()], ids=lambda path: path.name
)
def test_schedule_problem_name_uses_binary_sensor_namespace(path: pathlib.Path) -> None:
    """Resolve the real problem entity's name in its binary sensor platform."""
    entity_type = support.binary_sensor.ScheduleProblemSensor
    assert issubclass(entity_type, support.BinarySensorEntity)
    translation_key = entity_type._attr_translation_key
    entities = _load(path)["entity"]
    binary_sensor_names = entities.get("binary_sensor", {})

    assert translation_key in binary_sensor_names, (
        f"{path.name} lacks entity.binary_sensor.{translation_key}"
    )
    assert binary_sensor_names[translation_key]["name"].strip()
    assert translation_key not in entities.get("sensor", {})


@pytest.mark.parametrize(
    "path", [_STRINGS_PATH, *_translation_files()], ids=lambda path: path.name
)
def test_zone_alarm_state_name_uses_binary_sensor_namespace(
    path: pathlib.Path,
) -> None:
    """Resolve the zone alarm state binary sensor's name in its own platform."""
    entity_type = support.binary_sensor.ZoneStateSensor
    assert issubclass(entity_type, support.BinarySensorEntity)
    translation_key = entity_type._attr_translation_key
    assert translation_key == "zone_state_entity"
    entities = _load(path)["entity"]
    binary_sensor_names = entities.get("binary_sensor", {})

    assert translation_key in binary_sensor_names, (
        f"{path.name} lacks entity.binary_sensor.{translation_key}"
    )
    assert binary_sensor_names[translation_key]["name"].strip()
