"""Constants for the Tech Sterowniki integration.

Contains various constant values used throughout the integration.
"""

from datetime import timedelta
from typing import Any, Final

from homeassistant.const import Platform

DOMAIN: Final[str] = "tech"
CONTROLLER: Final[str] = "controller"
CONTROLLERS: Final[str] = "controllers"
VER: Final[str] = "version"
UDID: Final[str] = "udid"
USER_ID: Final[str] = "user_id"
TILES: Final[str] = "tiles"
VISIBILITY: Final[str] = "visibility"
VALUE: Final[str] = "value"
MANUFACTURER: Final[str] = "TechControllers"


DEFAULT_ICON: Final[str] = "mdi:eye"

PLATFORMS: Final[list[Platform]] = [
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.SENSOR,
]

SCAN_INTERVAL: Final[timedelta] = timedelta(seconds=60)
API_TIMEOUT: Final[int] = 60

# tile type
TYPE_TEMPERATURE: Final[int] = 1
TYPE_FIRE_SENSOR: Final[int] = 2
TYPE_TEMPERATURE_CH: Final[int] = 6
TYPE_RELAY: Final[int] = 11
TYPE_ADDITIONAL_PUMP: Final[int] = 21
TYPE_FAN: Final[int] = 22
TYPE_VALVE: Final[int] = 23
TYPE_MIXING_VALVE: Final[int] = 24
TYPE_FUEL_SUPPLY: Final[int] = 31
TYPE_TEXT: Final[int] = 40
TYPE_SW_VERSION: Final[int] = 50

# map iconId -> icon name
ICON_BY_ID: Final[dict[int, str]] = {
    3: "mdi:animation-play",
    17: "mdi:arrow-right-drop-circle-outline",
    50: "mdi:tune-vertical",
    101: "mdi:cogs",
}

# map type -> icon name
ICON_BY_TYPE: Final[dict[int, str]] = {
    TYPE_FIRE_SENSOR: "mdi:fire",
    TYPE_ADDITIONAL_PUMP: "mdi:arrow-right-drop-circle-outline",
    TYPE_FAN: "mdi:fan",
    TYPE_VALVE: "mdi:valve",
    TYPE_MIXING_VALVE: "mdi:valve",  # TODO: find a better icon
}

# map type -> txtId
TXT_ID_BY_TYPE: Final[dict[int, int]] = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_FAN: 4135,
    TYPE_VALVE: 991,
    TYPE_MIXING_VALVE: 5731,
    TYPE_FUEL_SUPPLY: 961,
}

VALVE_SENSOR_RETURN_TEMPERATURE: Final[dict[str, Any]] = {
    "txt_id": 747,
    "state_key": "returnTemp",
}
VALVE_SENSOR_SET_TEMPERATURE: Final[dict[str, Any]] = {
    "txt_id": 1065,
    "state_key": "setTemp",
}
VALVE_SENSOR_CURRENT_TEMPERATURE: Final[dict[str, Any]] = {
    "txt_id": 2010,
    "state_key": "currentTemp",
}
