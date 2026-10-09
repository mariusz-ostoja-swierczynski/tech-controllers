"""Unit tests for the controller-selection step of the Tech config flow.

Like :mod:`test_assets` and :mod:`test_widget_logic`, these tests stub the
``homeassistant`` package just enough to import ``config_flow.py`` and then
drive the flow with a fake ``hass``, so no Home Assistant install is needed.

The regression they guard: ``controllers_schema`` declares
``INCLUDE_HUB_IN_NAME`` with ``default=False``, while Home Assistant hands the
flow step the schema-*validated* payload (``data_entry_flow`` calls
``data_schema(user_input)``). Voluptuous fills the key in even when the checkbox
was left unticked, so deciding the flag by the key's presence always yields
True - only the key's value reflects the user's choice.
"""

from __future__ import annotations

import asyncio
import importlib.util
import pathlib
import sys
import types
from typing import Any

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TECH_DIR = _REPO_ROOT / "custom_components" / "tech"

_FAKE_NAMES = (
    "homeassistant",
    "homeassistant.const",
    "homeassistant.config_entries",
    "homeassistant.core",
    "homeassistant.exceptions",
    "homeassistant.helpers",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.config_validation",
    "homeassistant.helpers.redact",
)


class _ConfigEntry:
    """Stand-in for ``homeassistant.config_entries.ConfigEntry``."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


class _ConfigFlowBase:
    """Stand-in for ``homeassistant.config_entries.ConfigFlow``."""

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Accept the ``domain=`` class keyword the real base takes."""
        super().__init_subclass__()

    def async_abort(self, reason: str) -> dict[str, Any]:
        """Return an abort result the way the flow expects."""
        return {"type": "abort", "reason": reason}

    def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
        """Return a form result the way the flow expects."""
        return {"type": "form", **kwargs}

    async def async_set_unique_id(self, unique_id: str) -> None:
        """Record the unique id the flow would claim."""
        self.unique_id = unique_id

    def _abort_if_unique_id_configured(self) -> None:
        """Pretend the unique id is always free."""


class _Handlers:
    """Stand-in for ``config_entries.HANDLERS``, used as a class decorator."""

    def __init__(self) -> None:
        self.registered: dict[str, Any] = {}

    def register(self, domain: str):
        """Return the decorator that registers the flow class."""

        def decorator(cls):
            self.registered[domain] = cls
            return cls

        return decorator


class _Platform:
    """Stand-in for ``homeassistant.const.Platform``; only the names matter."""

    BINARY_SENSOR = "binary_sensor"
    BUTTON = "button"
    CLIMATE = "climate"
    NUMBER = "number"
    SELECT = "select"
    SENSOR = "sensor"
    SWITCH = "switch"


def _identity(value):
    """Stand-in for the ``cv.string`` / ``cv.multi_select`` validators."""
    return value


def _fake_module(name: str) -> types.ModuleType:
    """Build the stub for one ``homeassistant`` module."""
    module = types.ModuleType(name)
    if name == "homeassistant.const":
        for attribute, value in (
            ("ATTR_ID", "id"),
            ("CONF_NAME", "name"),
            ("CONF_PASSWORD", "password"),
            ("CONF_TOKEN", "token"),
            ("CONF_USERNAME", "username"),
        ):
            setattr(module, attribute, value)
        module.Platform = _Platform
    elif name == "homeassistant.config_entries":
        module.ConfigFlow = _ConfigFlowBase
        module.ConfigEntry = _ConfigEntry
        module.ConfigFlowResult = dict
        module.SOURCE_USER = "user"
        module.CONN_CLASS_CLOUD_POLL = "cloud_poll"
        module.HANDLERS = _Handlers()
    elif name == "homeassistant.core":
        module.HomeAssistant = object
    elif name == "homeassistant.exceptions":
        module.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    elif name == "homeassistant.helpers.config_validation":
        module.multi_select = lambda options: _identity
        module.string = _identity
    elif name == "homeassistant.helpers.redact":
        module.async_redact_data = lambda data, keys: data
    elif name == "homeassistant.helpers.aiohttp_client":
        module.async_get_clientsession = lambda hass: None
    return module


def _install_fakes() -> dict[str, types.ModuleType | None]:
    """Install the stubs, returning the previous ``sys.modules`` entries."""
    previous = {name: sys.modules.get(name) for name in _FAKE_NAMES}
    modules = {name: _fake_module(name) for name in _FAKE_NAMES}
    # Link children to their parents so ``from homeassistant import x`` works.
    for parent, children in (
        ("homeassistant", ("config_entries", "const", "core", "exceptions", "helpers")),
        ("homeassistant.helpers", ("aiohttp_client", "config_validation", "redact")),
    ):
        modules[parent].__path__ = []
        for child in children:
            setattr(modules[parent], child, modules[f"{parent}.{child}"])
    sys.modules.update(modules)
    return previous


def _load_tech_module(name: str):
    """Load ``custom_components.tech.<name>`` without executing ``__init__.py``."""
    full_name = f"custom_components.tech.{name}"
    if full_name in sys.modules:
        return sys.modules[full_name]
    for package, path in (
        ("custom_components", _REPO_ROOT / "custom_components"),
        ("custom_components.tech", _TECH_DIR),
    ):
        if package not in sys.modules:
            module = types.ModuleType(package)
            module.__path__ = [str(path)]
            sys.modules[package] = module
    spec = importlib.util.spec_from_file_location(full_name, _TECH_DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_previous_modules = _install_fakes()
try:
    const = _load_tech_module("const")
    _load_tech_module("tech")
    config_flow = _load_tech_module("config_flow")
finally:
    for _name, _previous in _previous_modules.items():
        if _previous is None:
            sys.modules.pop(_name, None)
        else:
            sys.modules[_name] = _previous


class _FakeConfigEntries:
    """Records the config entries handed to ``async_add``."""

    def __init__(self) -> None:
        self.added: list[Any] = []

    async def async_add(self, entry):
        """Record and return the entry."""
        self.added.append(entry)
        return entry


class _FakeHass:
    """A ``hass`` with only the attribute the flow touches."""

    def __init__(self) -> None:
        self.config_entries = _FakeConfigEntries()


def _controller_payload(controller_id: int = 1, name: str = "L-8 DEMO") -> dict:
    """Build a controller payload in the shape the flow stores."""
    return {
        const.CONTROLLER: {
            "id": controller_id,
            "name": name,
            "udid": "a" * 32,
            "version": "TECH: demo (v1)",
        },
        const.USER_ID: "240471648",
        "token": "secret",
        const.VER: f"TECH: demo (v1): {name}",
    }


def _flow(controllers: list[dict]):
    """Build a flow instance with a fake hass and discovered controllers."""
    flow = config_flow.ConfigFlow.__new__(config_flow.ConfigFlow)
    flow.hass = _FakeHass()
    flow._controllers = controllers
    flow._init_info = None
    return flow


def _validated(submitted: dict) -> dict:
    """Run the controller form schema over a submitted payload."""
    schema = config_flow.controllers_schema(controllers=[_controller_payload()])
    return schema(submitted)


def test_unticked_checkbox_stores_false() -> None:
    """Leaving the checkbox unticked must store the flag as False."""
    validated = _validated({const.CONTROLLERS: ["1"]})

    # The schema fills the default, so the key is there even when unticked.
    assert const.INCLUDE_HUB_IN_NAME in validated
    assert validated[const.INCLUDE_HUB_IN_NAME] is False

    flow = _flow([_controller_payload()])
    asyncio.run(flow._async_finish_controller(validated))

    (entry,) = flow.hass.config_entries.added
    assert entry.data[const.INCLUDE_HUB_IN_NAME] is False


def test_ticked_checkbox_stores_true() -> None:
    """Ticking the checkbox must store the flag as True."""
    validated = _validated(
        {const.CONTROLLERS: ["1"], const.INCLUDE_HUB_IN_NAME: True}
    )
    assert validated[const.INCLUDE_HUB_IN_NAME] is True

    flow = _flow([_controller_payload()])
    asyncio.run(flow._async_finish_controller(validated))

    (entry,) = flow.hass.config_entries.added
    assert entry.data[const.INCLUDE_HUB_IN_NAME] is True


def test_key_presence_cannot_decide_the_flag() -> None:
    """Pin down why the flow must read the value and not test for the key.

    This is the pre-fix bug in one place: the validated payload always carries
    the key, so the old ``INCLUDE_HUB_IN_NAME in user_input`` check evaluated to
    True for an unticked checkbox as well. Only the value distinguishes them.
    """
    validated = _validated({const.CONTROLLERS: ["1"]})

    # Presence is always True, which is what the old check tested.
    assert const.INCLUDE_HUB_IN_NAME in validated
    # The value is what the flow now stores, and it reflects the unticked box.
    assert validated[const.INCLUDE_HUB_IN_NAME] is False


def test_no_selection_aborts_without_adding_entries() -> None:
    """An empty selection aborts and stores nothing."""
    flow = _flow([_controller_payload()])
    result = asyncio.run(
        flow._async_finish_controller({const.CONTROLLERS: []})
    )
    assert result == {"type": "abort", "reason": "no_modules"}
    assert flow.hass.config_entries.added == []
