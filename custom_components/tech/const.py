"""Constants for the Tech Sterowniki integration."""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

DOMAIN = "tech"
CONTROLLER = "controller"
CONTROLLERS = "controllers"
VER = "version"
UDID = "udid"
USER_ID = "user_id"
SIGNAL_STRENGTH = "signalStrength"
TILES = "tiles"
VISIBILITY = "visibility"
VALUE = "value"
MANUFACTURER = "TechControllers"
WORKING_STATUS = "workingStatus"
ACTUATORS = "actuators"
BATTERY_LEVEL = "batteryLevel"
SIGNAL_STRENGTH = "signalStrength"
ACTUATORS_OPEN = "actuatorsOpen"
INCLUDE_HUB_IN_NAME = "include_hub_in_name"
WINDOW_SENSORS = "windowsSensors"
WINDOW_STATE = "windowState"

DEFAULT_ICON = "mdi:eye"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.SENSOR, Platform.CLIMATE]

SCAN_INTERVAL: Final = timedelta(seconds=60)
API_TIMEOUT: Final = 60

# tile type
TYPE_TEMPERATURE = 1
TYPE_FIRE_SENSOR = 2
TYPE_TEMPERATURE_CH = 6
TYPE_RELAY = 11
TYPE_ADDITIONAL_PUMP = 21
TYPE_FAN = 22
TYPE_VALVE = 23
TYPE_MIXING_VALVE = 24
TYPE_FUEL_SUPPLY = 31
TYPE_TEXT = 40
TYPE_SW_VERSION = 50

# map iconId -> icon name
ICON_BY_ID = {
    3: "mdi:animation-play",  # mode
    17: "mdi:arrow-right-drop-circle-outline",  # pump
    50: "mdi:tune-vertical",  # state
    101: "mdi:cogs",  # feeder
}

# map type -> icon name
ICON_BY_TYPE = {
    TYPE_FIRE_SENSOR: "mdi:fire",
    TYPE_ADDITIONAL_PUMP: "mdi:arrow-right-drop-circle-outline",
    TYPE_FAN: "mdi:fan",
    TYPE_VALVE: "mdi:valve",
    TYPE_MIXING_VALVE: "mdi:valve",  # TODO: find a better icon
}

# map type -> txtId
TXT_ID_BY_TYPE = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_FAN: 4135,
    TYPE_VALVE: 991,
    TYPE_MIXING_VALVE: 5731,
    TYPE_FUEL_SUPPLY: 961,
}

VALVE_SENSOR_RETURN_TEMPERATURE = {"txt_id": 747, "state_key": "returnTemp"}
VALVE_SENSOR_SET_TEMPERATURE = {"txt_id": 1065, "state_key": "setTemp"}
VALVE_SENSOR_CURRENT_TEMPERATURE = {"txt_id": 2010, "state_key": "currentTemp"}
