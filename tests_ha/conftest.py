"""Fixtures for the tests that run against a real Home Assistant.

These tests live in their own directory because they use
pytest-homeassistant-custom-component and therefore a real ``homeassistant``
package, while the suites in ``tests/`` replace that package with stubs when
they are imported. One pytest process cannot have both.
"""

from __future__ import annotations

import pathlib
import sys
from unittest.mock import AsyncMock

import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

# The tests import the integration itself, and Home Assistant loads it from
# <config_dir>/custom_components; both need the repository root importable.
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from custom_components.tech.tech import Tech  # noqa: E402


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Let Home Assistant load ``custom_components.tech``."""
    yield


@pytest.fixture(autouse=True)
def offline_integration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the integration from calling the Tech API.

    Home Assistant sets a created config entry up right away, and these tests are
    about the flow, not about the data behind it. The client's transport answers
    with an empty envelope, which is enough for the coordinator and for the
    platforms to come up with no data and no entities.
    """
    empty = AsyncMock(return_value={"status": "success", "data": {"elements": []}})
    monkeypatch.setattr(Tech, "get", empty)
    monkeypatch.setattr(Tech, "post", empty)


@pytest.fixture
def hass_config_dir(tmp_path: pathlib.Path) -> str:
    """Give Home Assistant a config dir that can see this repository.

    Home Assistant loads custom integrations from ``<config_dir>/custom_components``,
    so that directory is linked into a throwaway config dir: the integration is
    found, and nothing Home Assistant writes during a test lands in the
    repository.
    """
    (tmp_path / "custom_components").symlink_to(_REPO_ROOT / "custom_components")
    return str(tmp_path)
