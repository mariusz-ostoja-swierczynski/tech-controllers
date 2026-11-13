"""Drive the zone-mode actions the way an automation does.

The fixture carries zones in ``constantTemp``, ``globalSchedule`` and
``localSchedule`` modes plus a zone whose controller reports no mode at all.
These tests call the two actions through Home Assistant and check both halves
that matter: exactly one request with the documented path and body on success,
and a translated error with no request at all when validation fails.
"""

from __future__ import annotations

import json
from typing import Any, Protocol
from unittest.mock import AsyncMock

from common import UDID, set_up
import pytest

from custom_components.tech.const import DOMAIN
from custom_components.tech.schedules import ScheduleSelectionError
from custom_components.tech.services import _schedule_error
from custom_components.tech.tech import TechError
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er


class _PostCall(Protocol):
    """One recorded API write, as the mocked client exposed it."""

    @property
    def args(self) -> tuple[Any, ...]:
        """Return the positional arguments the client was called with."""
        ...


def _climate_entity(hass: HomeAssistant, zone_id: int) -> str:
    """Return the one climate entity a zone's unique id names."""
    registry = er.async_get(hass)
    matches = [
        entry.entity_id
        for entry in registry.entities.values()
        if entry.entity_id.startswith("climate.")
        and entry.unique_id == f"{UDID}_{zone_id}_zone_climate"
    ]
    assert len(matches) == 1
    return matches[0]


def _sensor_entity(hass: HomeAssistant) -> str:
    """Return a sensor entity owned by this controller, not a climate one."""
    registry = er.async_get(hass)
    matches = sorted(
        entry.entity_id
        for entry in registry.entities.values()
        if entry.platform == DOMAIN
        and entry.entity_id.startswith("sensor.")
        and entry.unique_id.startswith(f"{UDID}_")
    )
    assert matches
    return matches[0]


def _body(call: _PostCall) -> dict:
    """Return the JSON body the write path was called with."""
    return json.loads(call.args[1])


async def test_services_are_registered(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Setting the entry up registers both zone-mode actions."""
    await set_up(hass, "zone_modes", monkeypatch)

    assert hass.services.has_service(DOMAIN, "set_zone_schedule")
    assert hass.services.has_service(DOMAIN, "set_zone_constant")


async def test_set_zone_schedule_global_posts_expected_body(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A global selection writes its template and the zones that use that slot."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    await hass.services.async_call(
        DOMAIN,
        "set_zone_schedule",
        {"entity_id": entity_id, "source": "global", "index": 2},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones/1/global_schedule"
    body = _body(call)
    assert body["modeId"] == 101
    assert body["schedule"]["id"] == 303
    assert body["schedule"]["index"] == 2
    assert body["schedule"]["p0Intervals"] == [
        {"start": 330, "stop": 660, "temp": 210}
    ]
    assert body["scheduleName"] == "Global 2"
    assert body["setInZones"] == [
        {"zoneId": 1, "modeId": 101},
        {"zoneId": 2, "modeId": 102},
    ]


async def test_set_zone_schedule_local_posts_expected_body(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A local selection cleans the zone's own template before writing it."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    await hass.services.async_call(
        DOMAIN,
        "set_zone_schedule",
        {"entity_id": entity_id, "source": "local"},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones/1/local_schedule"
    body = _body(call)
    assert body["modeId"] == 101
    assert body["schedule"]["id"] == 201
    assert {"start": 1200, "stop": 1440, "temp": 205} in body["schedule"][
        "p0Intervals"
    ]
    assert body["schedule"]["p1Intervals"] == []
    assert "6100" not in json.dumps(body)


async def test_set_zone_constant_permanent_omits_duration(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a duration the zone keeps the temperature until it is changed."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    await hass.services.async_call(
        DOMAIN,
        "set_zone_constant",
        {"entity_id": entity_id, "temperature": 21.5},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones"
    mode = _body(call)["mode"]
    assert mode["id"] == 101
    assert mode["parentId"] == 1
    assert mode["mode"] == "constantTemp"
    assert mode["constTempTime"] == 0
    assert mode["setTemperature"] == 215


async def test_set_zone_constant_time_limit(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A duration turns the write into a time-limited constant temperature."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    await hass.services.async_call(
        DOMAIN,
        "set_zone_constant",
        {"entity_id": entity_id, "temperature": 21.5, "duration_minutes": 120},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones"
    mode = _body(call)["mode"]
    assert mode["mode"] == "timeLimit"
    assert mode["constTempTime"] == 120
    assert mode["setTemperature"] == 215


async def test_set_zone_schedule_rejects_invalid_global_slot(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The deliberately invalid fifth template is refused before any write."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_zone_schedule",
            {"entity_id": entity_id, "source": "global", "index": 4},
            blocking=True,
        )

    assert excinfo.value.translation_key in {"schedule_invalid", "schedule_not_found"}
    assert post.await_count == 0


async def test_set_zone_schedule_rejects_non_climate_target(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sensor of the same controller is not a zone climate target."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _sensor_entity(hass)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_zone_schedule",
            {"entity_id": entity_id, "source": "local"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "zone_target_invalid"
    assert post.await_count == 0


async def test_set_zone_schedule_requires_index_for_global(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A global selection without an index is refused before any write."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_zone_schedule",
            {"entity_id": entity_id, "source": "global"},
            blocking=True,
        )

    assert excinfo.value.translation_key == "schedule_index_required"
    assert post.await_count == 0


async def test_set_zone_constant_rejects_missing_mode(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone whose controller reports no mode id cannot be written."""
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 4)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_zone_constant",
            {"entity_id": entity_id, "temperature": 20},
            blocking=True,
        )

    assert excinfo.value.translation_key == "zone_mode_missing"
    assert post.await_count == 0


async def test_set_zone_schedule_accepts_zone_device_target(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A zone device target expands to its climate and non-climate entities.

    Home Assistant turns the device target into every entity of the zone,
    including its temperature and schedule sensors; the service ignores those
    non-climate siblings and writes through the one climate entity, which is
    the only target carrying both the controller and the zone id.
    """
    post = AsyncMock(return_value={"status": "success"})
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    registry_entry = er.async_get(hass).async_get(_climate_entity(hass, 1))
    assert registry_entry is not None
    assert registry_entry.device_id is not None

    await hass.services.async_call(
        DOMAIN,
        "set_zone_schedule",
        {"device_id": registry_entry.device_id, "source": "local"},
        blocking=True,
    )

    assert post.await_count == 1
    call = post.await_args
    assert call is not None
    assert call.args[0] == f"users/42/modules/{UDID}/zones/1/local_schedule"


@pytest.mark.parametrize(
    ("reason", "translation_key"),
    [
        ("unsupported", "schedule_unsupported"),
        ("missing", "schedule_not_found"),
        ("not_settled", "schedule_not_settled"),
        ("invalid", "schedule_invalid"),
        ("mode_missing", "zone_mode_missing"),
    ],
)
def test_schedule_error_reasons_map_to_translation_keys(
    reason: str, translation_key: str
) -> None:
    """Every preparation reason becomes its own translated service error."""
    error = _schedule_error(ScheduleSelectionError(reason), "global")

    assert error.translation_key == translation_key
    assert str(error)
    if reason == "missing":
        assert str(error) == "This zone has no global schedule to activate."


async def test_set_zone_constant_maps_controller_refusal(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A controller refusal reaches the user as a translated write error."""
    post = AsyncMock(side_effect=TechError(422, "Invalid JSON data"))
    await set_up(hass, "zone_modes", monkeypatch, post=post)
    entity_id = _climate_entity(hass, 1)

    with pytest.raises(HomeAssistantError) as excinfo:
        await hass.services.async_call(
            DOMAIN,
            "set_zone_constant",
            {"entity_id": entity_id, "temperature": 20},
            blocking=True,
        )

    assert excinfo.value.translation_key == "zone_write_failed"
    assert excinfo.value.translation_placeholders == {"error": "Invalid JSON data"}
    assert post.await_count == 1
