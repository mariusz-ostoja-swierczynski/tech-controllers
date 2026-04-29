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
ACTUATORS_OPEN = "actuatorsOpen"
INCLUDE_HUB_IN_NAME = "include_hub_in_name"
UNDERFLOOR = "underfloor"
WINDOW_SENSORS = "windowsSensors"
WINDOW_STATE = "windowState"
MODE = "mode"
CURRENT_STATE = "currentState"
FLOOR_PUMP = "floorPump"
SENSOR_TYPE = "sensorType"
EVENTS = "events"
CORRECT_WORK = "correctWork"
NO_COMMUNICATION = "noCommunication"
SENSOR_DAMAGED = "sensorDamaged"
LOW_BATTERY = "lowBattery"
LOW_SIGNAL = "lowSignal"
TEMP_TOO_HIGH = "tempTooHigh"
TEMP_TOO_LOW = "tempTooLow"
SERVICE_ERROR = "serviceError"
ZONE_STATE = "zoneState"

DEFAULT_ICON = "mdi:eye"

PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

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
TYPE_OPEN_THERM = 252

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
    TYPE_OPEN_THERM: "mdi:home-thermometer",
}

# map type -> txtId
TXT_ID_BY_TYPE = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_FAN: 4135,
    TYPE_VALVE: 991,
    TYPE_MIXING_VALVE: 5731,
    TYPE_FUEL_SUPPLY: 961,
    TYPE_OPEN_THERM: 4633,
}

# Valve sensor measured values
VALVE_SENSOR_RETURN_TEMPERATURE = {"txt_id": 747, "state_key": "returnTemp"}
VALVE_SENSOR_SET_TEMPERATURE = {"txt_id": 1065, "state_key": "setTemp"}
VALVE_SENSOR_CURRENT_TEMPERATURE = {"txt_id": 2010, "state_key": "currentTemp"}

# OpenTherm measured values
OPENTHERM_CURRENT_TEMP = {"txt_id": 127, "state_key": "currentTemp"}
OPENTHERM_CURRENT_TEMP_DHW = {"txt_id": 128, "state_key": "currentTempDHW"}
OPENTHERM_SET_TEMP = {"txt_id": 1058, "state_key": "setCurrentTemp"}
OPENTHERM_SET_TEMP_DHW = {"txt_id": 1059, "state_key": "setTempDHW"}
OPENTHERM_MODULATION = {"txt_id": 428, "state_key": "modulationPercentage"}

# Menu types
MENU_TYPE_USER = "MU"
MENU_TYPE_INSTALLER = "MI"
MENU_TYPE_SERVICE = "MS"
MENU_TYPE_MANUFACTURER = "MP"
MENU_TYPES = [MENU_TYPE_USER, MENU_TYPE_INSTALLER]

# Menu item types
MENU_ITEM_TYPE_GROUP = 0
MENU_ITEM_TYPE_VALUE = {1, 2, 3, 4, 5}
MENU_ITEM_TYPE_CODE = 6
MENU_ITEM_TYPE_TIME_MODE = 7
MENU_ITEM_TYPE_ON_OFF = 10
MENU_ITEM_TYPE_CHOICE = {11, 111, 112}
MENU_ITEM_TYPE_DIALOGUE = 20
MENU_ITEM_TYPE_UNIVERSAL_VALUE = 106

# Menu depth filtering thresholds. Tech menus on multi-zone controllers
# (notably L-12 with ~4100 MI items) are deeply nested and exposing every
# leaf as a HA entity produces unusable amounts of registry noise (#187).
# Items deeper than ``MENU_DEPTH_REGISTRATION_LIMIT`` are not registered as
# entities at all; items at depth > ``MENU_DEPTH_DEFAULT_ENABLED_LIMIT``
# are registered but disabled by default so users can opt into the deeper
# parameters they care about (#189: OpenTherm options live at depth 1-3).
MENU_DEPTH_REGISTRATION_LIMIT: Final = 3
MENU_DEPTH_DEFAULT_ENABLED_LIMIT: Final = 1

# Value format types for menu items
VALUE_FORMAT_NORMAL = 1
VALUE_FORMAT_TENTH = 2
VALUE_FORMAT_MIN_SEC = 3
VALUE_FORMAT_HOUR_MIN = 4
VALUE_FORMAT_H_MIN_DAY = 5

TECH_SUPPORTED_LANGUAGES = [
    "en",
    "fr",
    "it",
    "es",
    "nl",
    "pl",
    "de",
    "cs",
    "sk",
    "hu",
    "ro",
    "lt",
    "et",
    "ru",
    "si",
    "hr",
]
