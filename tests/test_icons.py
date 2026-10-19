"""Tests for the icon translations.

``icons.json`` names the icons this integration chooses for the entities it also
names, by translation key. Home Assistant resolves them from the file rather than
from the state machine, so the file and the entities have to agree: a key no
entity uses is dead weight, and a value that is not an ``mdi:`` name cannot be
rendered.

Icons that depend on an entity's state, and the ones the controller itself sends
for a tile, stay on the entity: neither can be expressed as a name in a file.
"""

from __future__ import annotations

import json
import pathlib

_TECH_DIR = pathlib.Path(__file__).resolve().parents[1] / "custom_components" / "tech"
_ICONS_FILE = _TECH_DIR / "icons.json"
_STRINGS_FILE = _TECH_DIR / "strings.json"


def _icons() -> dict:
    """Return the parsed icon translations."""
    return json.loads(_ICONS_FILE.read_text(encoding="utf-8"))


def test_every_icon_has_an_entity_that_names_it() -> None:
    """Each key in the file is a translation key an entity really uses.

    A key nothing refers to means an entity lost its translation key, or that the
    file kept one after the entity using it was removed.
    """
    strings = json.loads(_STRINGS_FILE.read_text(encoding="utf-8"))

    for platform, entities in _icons().get("entity", {}).items():
        for key in entities:
            assert key in strings.get("entity", {}).get(platform, {}), (platform, key)


def test_every_icon_is_a_material_design_name() -> None:
    """The values are names the frontend can resolve."""
    for platform, entities in _icons().get("entity", {}).items():
        for key, icons in entities.items():
            assert icons["default"].startswith("mdi:"), (platform, key)
