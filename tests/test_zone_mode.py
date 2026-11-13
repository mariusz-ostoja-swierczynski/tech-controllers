"""Mocked payload checks for the zone-mode write methods.

The transport is an ``AsyncMock``; the production methods build the path and
body under test. No credentials or household data are used.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import pytest

from . import test_platform_device_info as support

tech = support._load_tech_module("tech")

_MODULE = "module123"
_ZONE = 3
_MODE = 7
_PATH = f"users/user123/modules/{_MODULE}/zones"


def _instance() -> Any:
    """Return an authenticated client whose POST is mocked."""
    instance = tech.Tech(None, user_id="user123", token="token")
    instance.post = AsyncMock(return_value={"status": "success"})
    return instance


async def test_set_zone_constant_permanent_without_duration() -> None:
    """A missing duration keeps the permanent constant-temperature mode."""
    instance = _instance()

    result = await instance.set_zone_constant(_MODULE, _ZONE, _MODE, 22.5)

    assert instance.post.await_count == 1
    assert instance.post.await_args.args[0] == _PATH
    assert json.loads(instance.post.await_args.args[1]) == {
        "mode": {
            "id": _MODE,
            "parentId": _ZONE,
            "mode": "constantTemp",
            "constTempTime": 0,
            "setTemperature": 225,
            "scheduleIndex": 0,
        }
    }
    assert result == {"status": "success"}


async def test_set_zone_constant_permanent_with_zero_duration() -> None:
    """A zero duration also keeps the permanent constant-temperature mode."""
    instance = _instance()

    await instance.set_zone_constant(_MODULE, _ZONE, _MODE, 19.5, 0)

    assert instance.post.await_count == 1
    assert instance.post.await_args.args[0] == _PATH
    assert json.loads(instance.post.await_args.args[1]) == {
        "mode": {
            "id": _MODE,
            "parentId": _ZONE,
            "mode": "constantTemp",
            "constTempTime": 0,
            "setTemperature": 195,
            "scheduleIndex": 0,
        }
    }


async def test_set_zone_constant_timed() -> None:
    """A positive duration switches to time-limited mode with its minutes."""
    instance = _instance()

    await instance.set_zone_constant(_MODULE, _ZONE, _MODE, 21.5, 90)

    assert instance.post.await_count == 1
    assert instance.post.await_args.args[0] == _PATH
    assert json.loads(instance.post.await_args.args[1]) == {
        "mode": {
            "id": _MODE,
            "parentId": _ZONE,
            "mode": "timeLimit",
            "constTempTime": 90,
            "setTemperature": 215,
            "scheduleIndex": 0,
        }
    }


async def test_set_zone_local_schedule() -> None:
    """A local schedule is posted to the zone's local_schedule route."""
    instance = _instance()
    schedule = {"p0Intervals": [{"start": 300, "stop": 420, "temp": 210}]}

    await instance.set_zone_local_schedule(_MODULE, _ZONE, _MODE, schedule)

    assert instance.post.await_count == 1
    assert instance.post.await_args.args[0] == f"{_PATH}/{_ZONE}/local_schedule"
    assert json.loads(instance.post.await_args.args[1]) == {
        "modeId": _MODE,
        "schedule": schedule,
    }


async def test_set_zone_global_schedule() -> None:
    """A global schedule carries its name and the zones it applies to."""
    instance = _instance()
    schedule = {"p0Intervals": [{"start": 0, "stop": 360, "temp": 200}]}
    set_in_zones = [{"zoneId": _ZONE}, {"zoneId": 4}]

    await instance.set_zone_global_schedule(
        _MODULE, _ZONE, _MODE, schedule, "Night", set_in_zones
    )

    assert instance.post.await_count == 1
    assert instance.post.await_args.args[0] == f"{_PATH}/{_ZONE}/global_schedule"
    assert json.loads(instance.post.await_args.args[1]) == {
        "modeId": _MODE,
        "schedule": schedule,
        "scheduleName": "Night",
        "setInZones": set_in_zones,
    }


@pytest.mark.parametrize(
    ("method_name", "args"),
    [
        ("set_zone_constant", (_MODULE, _ZONE, _MODE, 22.5)),
        ("set_zone_local_schedule", (_MODULE, _ZONE, _MODE, {"p0Intervals": []})),
        (
            "set_zone_global_schedule",
            (_MODULE, _ZONE, _MODE, {"p0Intervals": []}, "Night", [{"zoneId": _ZONE}]),
        ),
    ],
)
async def test_zone_mode_write_requires_authentication(
    method_name: str, args: tuple[Any, ...]
) -> None:
    """Every write raises 401 before any POST is sent when unauthenticated."""
    instance = _instance()
    instance.authenticated = False

    with pytest.raises(tech.TechError) as exception_info:
        await getattr(instance, method_name)(*args)

    assert exception_info.value.status_code == 401
    assert exception_info.value.status == "Unauthorized"
    assert instance.post.await_count == 0
