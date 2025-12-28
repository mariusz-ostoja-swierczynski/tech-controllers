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

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.SENSOR, Platform.FAN, Platform.NUMBER, Platform.SELECT, Platform.BUTTON, Platform.SWITCH]

SCAN_INTERVAL: Final = timedelta(seconds=60)
API_TIMEOUT: Final = 60

# tile type
TYPE_TEMPERATURE = 1
TYPE_FIRE_SENSOR = 2
TYPE_TEMPERATURE_CH = 6
TYPE_RELAY = 11
TYPE_ADDITIONAL_PUMP = 21
TYPE_FAN = 22
TYPE_RECUPERATION = 122  # Custom type for recuperation units
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
    TYPE_RECUPERATION: "mdi:air-filter",
    TYPE_VALVE: "mdi:valve",
    TYPE_MIXING_VALVE: "mdi:valve",  # TODO: find a better icon
    TYPE_OPEN_THERM: "mdi:home-thermometer",
}

# map type -> txtId
TXT_ID_BY_TYPE = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_FAN: 4135,
    TYPE_RECUPERATION: 4135,  # Using same txt_id as fan for now
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

# Recuperation flow sensor measured values
RECUPERATION_EXHAUST_FLOW = {"txt_id": 6131, "widget": "widget2", "name": "exhaust_flow"}
RECUPERATION_SUPPLY_FLOW = {"txt_id": 6132, "widget": "widget1", "name": "supply_flow"}
RECUPERATION_SUPPLY_FLOW_ALT = {"txt_id": 5994, "widget": "widget2", "name": "supply_flow"}

# Recuperation temperature sensors (common txtIds)
RECUPERATION_TEMP_SENSORS = [
    {"txt_id": 119, "name": "Supply Air Temperature", "device_class": "temperature"},
    {"txt_id": 120, "name": "Exhaust Air Temperature", "device_class": "temperature"},
    {"txt_id": 121, "name": "External Air Temperature", "device_class": "temperature"},
    {"txt_id": 122, "name": "Discharge Air Temperature", "device_class": "temperature"},
    {"txt_id": 126, "name": "Supply Air Temperature", "device_class": "temperature"},
    {"txt_id": 127, "name": "Exhaust Air Temperature", "device_class": "temperature"},
    {"txt_id": 5995, "name": "Fresh Air Temperature", "device_class": "temperature"},
    {"txt_id": 5996, "name": "Extract Air Temperature", "device_class": "temperature"},
    {"txt_id": 5997, "name": "Supply Air Temperature", "device_class": "temperature"},
    {"txt_id": 5998, "name": "Exhaust Air Temperature", "device_class": "temperature"},
    {"txt_id": 5999, "name": "Heat Exchanger Temperature", "device_class": "temperature"},
    {"txt_id": 6000, "name": "Preheater Temperature", "device_class": "temperature"},
]

# Recuperation speed control endpoints (ido_id mapping)
RECUPERATION_SPEED_ENDPOINTS = {
    1: {"ido_id": 1737},  # Low speed
    2: {"ido_id": 1748},  # Medium speed
    3: {"ido_id": 1739},  # High speed
}

# Default values for speed configuration (can be overridden by user)
DEFAULT_SPEED_VALUES = {
    1: 120,  # Low speed default - 120 m³/h
    2: 280,  # Medium speed default - 280 m³/h
    3: 390,  # High speed default - 390 m³/h
}

# Speed configuration ranges for each gear
SPEED_RANGES = {
    1: {"min": 60, "max": 280, "step": 10},   # Speed 1: 60-280 m³/h
    2: {"min": 120, "max": 400, "step": 10},  # Speed 2: 120-400 m³/h
    3: {"min": 280, "max": 400, "step": 10},  # Speed 3: 280-400 m³/h
}

# Configuration keys for storing user values
SPEED_CONFIG_KEYS = {
    1: "recuperation_speed_1_flow",
    2: "recuperation_speed_2_flow",
    3: "recuperation_speed_3_flow",
}

# Humidity sensor txtId values (unit: 8, type: 2)
# 2024: Room wireless sensor 1
# 2025: Room wireless sensor 2
# 2027: Bathroom wireless sensor 4
# 2658: Bathroom 2 wireless sensor 5
# TODO: Add txtId for bathroom 3 wireless sensor 6 when available
HUMIDITY_SENSOR_TXT_IDS = [2024, 2025, 2027, 2658]

# Party mode settings
PARTY_MODE_IDO_ID = 1447
PARTY_MODE_MIN_MINUTES = 15
PARTY_MODE_MAX_MINUTES = 720

# Direct gear control settings
GEAR_CONTROL_IDO_ID = 1833
GEAR_OPTIONS = {
    "stop": 0,          # Stop fan
    "speed_1": 1,       # Speed 1
    "speed_2": 2,       # Speed 2
    "speed_3": 3,       # Speed 3
}
GEAR_OPTIONS_REVERSE = {v: k for k, v in GEAR_OPTIONS.items()}

# Fan mode select settings (timed mode changes)
FAN_MODE_IDO_ID = 1966
FAN_MODE_OPTIONS = {
    "stop": 0,          # Stop fan
    "speed_1": 1,       # Speed 1
    "speed_2": 2,       # Speed 2
    "speed_3": 3,       # Speed 3
}
FAN_MODE_OPTIONS_REVERSE = {v: k for k, v in FAN_MODE_OPTIONS.items()}

# Filter management settings (values from Tech Defro DRX recuperation system)
# These are the allowed range for filter replacement reminder in the device settings
FILTER_ALARM_IDO_ID = 2080
FILTER_ALARM_MIN_DAYS = 30   # Minimum days for filter alarm setting
FILTER_ALARM_MAX_DAYS = 120  # Maximum days for filter alarm setting

# Filter usage tracking
FILTER_USAGE_IDO_ID = 2081

# Ventilation parameters settings
VENTILATION_ROOM_IDO_ID = 2170
VENTILATION_BATHROOM_IDO_ID = 2171
CO2_THRESHOLD_IDO_ID = 2115
HYSTERESIS_IDO_ID = 2239

# Flow balancing setting
FLOW_BALANCING_IDO_ID = 1733

# Ventilation parameter ranges
VENTILATION_MIN_PERCENT = 10
VENTILATION_MAX_PERCENT = 90
CO2_MIN_PPM = 400
CO2_MAX_PPM = 2000
HYSTERESIS_MIN_PERCENT = 5
HYSTERESIS_MAX_PERCENT = 10

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
