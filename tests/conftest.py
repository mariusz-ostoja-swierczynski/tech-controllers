"""Load the complete Home Assistant stubs before any test module imports.

Several test modules install partial ``homeassistant`` stubs at import time, and
the order they are imported in then decides which stub the integration's modules
bind. Importing the platform-device tests here installs the complete set first,
so the collection order no longer matters.
"""

from __future__ import annotations

from . import test_platform_device_info  # noqa: F401
