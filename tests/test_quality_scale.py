"""Tests for the integration quality scale declaration.

``custom_components/tech/quality_scale.yaml`` records the Home Assistant
integration quality scale rules this integration meets, following
https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/
Nothing in Home Assistant checks it for a custom component -- hassfest skips the
quality scale for anything that is not built in, HACS does not read it, and the
frontend shows the tier badge only for built-in integrations -- so these tests
are what keeps the file honest: the rule set is pinned to the Bronze tier the
project targets, the statuses are the ones the schema allows, and every rule
that is not plainly ``done`` carries the reason it is not.

The rule ids are the docs slugs with underscores, which is the naming the
quality scale file uses.
"""

from __future__ import annotations

import json
import pathlib

import pytest
import yaml

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"
_QUALITY_SCALE_FILE = _TECH_DIR / "quality_scale.yaml"
_MANIFEST_FILE = _TECH_DIR / "manifest.json"

_TIER = "bronze"

# The Bronze tier, from the rules index page. Pinned on purpose: adding a rule
# here (or dropping one) is a deliberate statement about what the project
# claims, so it should show up in a review rather than drift with the file.
_BRONZE_RULES = frozenset(
    {
        "action_setup",
        "appropriate_polling",
        "brands",
        "common_modules",
        "config_flow",
        "config_flow_test_coverage",
        "dependency_transparency",
        "docs_actions",
        "docs_conditions",
        "docs_high_level_description",
        "docs_installation_instructions",
        "docs_removal_instructions",
        "docs_triggers",
        "entity_event_setup",
        "entity_unique_id",
        "has_entity_name",
        "runtime_data",
        "test_before_configure",
        "test_before_setup",
        "unique_config_entry",
    }
)

_STATUSES = frozenset({"todo", "done", "exempt"})


def _declaration() -> dict:
    """Return the parsed quality scale file."""
    return yaml.safe_load(_QUALITY_SCALE_FILE.read_text(encoding="utf-8"))


def _entries() -> dict[str, dict[str, str]]:
    """Return the declared rules normalised to ``{status, comment}`` mappings."""
    entries: dict[str, dict[str, str]] = {}
    for rule, value in _declaration()["rules"].items():
        if isinstance(value, str):
            entries[rule] = {"status": value, "comment": ""}
        else:
            entries[rule] = {
                "status": value["status"],
                "comment": value.get("comment", ""),
            }
    return entries


def test_declaration_covers_the_bronze_tier() -> None:
    """The file declares exactly the Bronze rules, no more and no less.

    Only Bronze is tracked today: listing the tiers above it would claim we
    track rules nobody has looked at yet.
    """
    assert set(_declaration()["rules"]) == set(_BRONZE_RULES)


@pytest.mark.parametrize("rule", sorted(_BRONZE_RULES))
def test_every_rule_uses_an_allowed_status(rule: str) -> None:
    """Each status is one the quality scale schema allows."""
    assert _entries()[rule]["status"] in _STATUSES


@pytest.mark.parametrize("rule", sorted(_BRONZE_RULES))
def test_a_rule_that_is_not_plainly_done_says_why(rule: str) -> None:
    """Anything but the bare ``done`` scalar carries a comment.

    A ``todo`` or an ``exempt`` without a reason is not reviewable: the next
    reader cannot tell an oversight from a decision. The schema makes the
    comment mandatory for the mapping form, and this keeps us to it.
    """
    entry = _entries()[rule]

    if entry["status"] != "done":
        assert entry["comment"].strip()


def test_manifest_declares_the_same_tier() -> None:
    """The manifest announces the tier the file tracks, and has owners for it.

    Home Assistant requires a graded integration to name code owners, and it is
    the manifest key -- not this file -- that the frontend and the browser
    read.
    """
    manifest = json.loads(_MANIFEST_FILE.read_text(encoding="utf-8"))

    assert manifest["quality_scale"] == _TIER
    assert manifest["codeowners"]
