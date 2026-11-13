"""Exercise target resolution and one-time registration directly.

The service tests drive both actions through Home Assistant; these tests call
``_resolve_targets`` and ``_controller_udid`` with a synthetic registry, so each
guard that rejects a target is covered without a fixture that happens to hit it.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from custom_components.tech import services
from custom_components.tech.const import CONTROLLER, DOMAIN
from custom_components.tech.coordinator import TechCoordinator
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError

UDID_VALUE = "b" * 32


class _FakeRegistry:
    """A minimal entity registry keyed by entity id."""

    def __init__(self, entries: dict[str, Any]) -> None:
        """Store the entries ``async_get`` should answer with."""
        self.entries = entries

    def async_get(self, entity_id: str) -> Any:
        """Return the chosen entry for ``entity_id``, if any."""
        return self.entries.get(entity_id)


def _registry_entry(
    entity_id: str = "climate.fake",
    *,
    unique_id: str = f"{UDID_VALUE}_1_zone_climate",
    platform: str = DOMAIN,
    config_entry_id: str | None = "entry",
) -> SimpleNamespace:
    """Return an entity-registry entry shaped like Home Assistant's."""
    return SimpleNamespace(
        entity_id=entity_id,
        unique_id=unique_id,
        platform=platform,
        config_entry_id=config_entry_id,
    )


def _coordinator(data: Any, entry_data: dict[str, Any]) -> TechCoordinator:
    """Build a coordinator without running the real constructor."""
    coordinator = TechCoordinator.__new__(TechCoordinator)
    coordinator.data = data
    cast("Any", coordinator).config_entry = SimpleNamespace(data=entry_data)
    return coordinator


def _config_entry(
    *,
    runtime_data: Any,
    entry_id: str = "entry",
    controller: Any = None,
) -> SimpleNamespace:
    """Return a config entry shaped like a Tech one for target resolution."""
    return SimpleNamespace(
        entry_id=entry_id,
        data={} if controller is None else {CONTROLLER: controller},
        runtime_data=runtime_data,
    )


def _call(hass: HomeAssistant, **data: Any) -> ServiceCall:
    """Return a call to the schedule action whose target is ``data``."""
    return ServiceCall(hass, DOMAIN, services.SERVICE_SET_ZONE_SCHEDULE, data)


def _patch_resolution(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    *,
    entry: Any,
    registry_entry: Any,
    entity_id: str = "climate.fake",
) -> ServiceCall:
    """Patch both registries and return a call targeting ``entity_id``."""
    registry = _FakeRegistry({entity_id: registry_entry})
    monkeypatch.setattr(services.er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        hass.config_entries, "async_get_entry", lambda _entry_id: entry
    )
    return _call(hass, entity_id=entity_id)


def _assert_target_invalid(hass: HomeAssistant, call: ServiceCall) -> None:
    """Run resolution and assert that it rejects the target."""
    with pytest.raises(HomeAssistantError) as excinfo:
        services._resolve_targets(hass, call)
    assert excinfo.value.translation_key == "zone_target_invalid"


async def test_resolve_targets_without_a_target_raises(
    hass: HomeAssistant,
) -> None:
    """A call that names no target resolves to nothing and is rejected."""
    _assert_target_invalid(hass, _call(hass))


async def test_resolve_targets_skips_foreign_platform(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entity of another integration is not a Tech zone target."""
    coordinator = _coordinator({}, {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": UDID_VALUE}
    )
    registry_entry = _registry_entry(platform="other")

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_zone_suffix_without_zone_id(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A suffix without a numeric zone part does not identify a zone."""
    coordinator = _coordinator({}, {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": UDID_VALUE}
    )
    registry_entry = _registry_entry(unique_id=f"{UDID_VALUE}_x_zone_climate")

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_entry_without_config_entry_id(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An orphan registry entry names no config entry to write through."""
    coordinator = _coordinator({}, {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": UDID_VALUE}
    )
    registry_entry = _registry_entry(config_entry_id=None)

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_unknown_config_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A registry entry pointing at a removed config entry is ignored."""
    registry_entry = _registry_entry()

    call = _patch_resolution(
        hass, monkeypatch, entry=None, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_entry_without_coordinator(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An entry whose runtime data is not a coordinator cannot be written."""
    entry = _config_entry(
        runtime_data=SimpleNamespace(), controller={"udid": UDID_VALUE}
    )
    registry_entry = _registry_entry()

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_coordinator_without_mapping_data(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A coordinator that has not polled a mapping payload is ignored."""
    coordinator = _coordinator([], {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": UDID_VALUE}
    )
    registry_entry = _registry_entry()

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_skips_mismatched_controller(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A unique id naming another controller than the entry is ignored."""
    coordinator = _coordinator({}, {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": "c" * 32}
    )
    registry_entry = _registry_entry()

    call = _patch_resolution(
        hass, monkeypatch, entry=entry, registry_entry=registry_entry
    )

    _assert_target_invalid(hass, call)


async def test_resolve_targets_deduplicates_zone_targets(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two entity ids of the same zone produce one write target."""
    coordinator = _coordinator({}, {CONTROLLER: {"udid": UDID_VALUE}})
    entry = _config_entry(
        runtime_data=coordinator, controller={"udid": UDID_VALUE}
    )
    registry = _FakeRegistry(
        {
            "climate.fake_one": _registry_entry("climate.fake_one"),
            "climate.fake_two": _registry_entry("climate.fake_two"),
        }
    )
    monkeypatch.setattr(services.er, "async_get", lambda _hass: registry)
    monkeypatch.setattr(
        hass.config_entries, "async_get_entry", lambda _entry_id: entry
    )

    targets = services._resolve_targets(
        hass, _call(hass, entity_id=["climate.fake_one", "climate.fake_two"])
    )

    assert len(targets) == 1
    assert targets[0][0] is coordinator
    assert targets[0][1] == 1


async def test_controller_udid_without_controller_raises(
    hass: HomeAssistant,
) -> None:
    """A resolved entry with no controller cannot name its controller."""
    coordinator = _coordinator({}, {})

    with pytest.raises(HomeAssistantError) as excinfo:
        services._controller_udid(coordinator)

    assert excinfo.value.translation_key == "zone_target_invalid"


async def test_async_register_services_registers_once(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A second registration returns early and keeps both services."""
    await services.async_register_services(hass)
    assert hass.services.has_service(DOMAIN, services.SERVICE_SET_ZONE_SCHEDULE)
    assert hass.services.has_service(DOMAIN, services.SERVICE_SET_ZONE_CONSTANT)

    def _unexpected(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("the services were registered a second time")

    monkeypatch.setattr(type(hass.services), "async_register", _unexpected)

    await services.async_register_services(hass)

    assert hass.services.has_service(DOMAIN, services.SERVICE_SET_ZONE_SCHEDULE)
    assert hass.services.has_service(DOMAIN, services.SERVICE_SET_ZONE_CONSTANT)
