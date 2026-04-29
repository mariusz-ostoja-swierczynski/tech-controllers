"""Constants for the Tech Sterowniki integration.

The Tech eModul cloud API (https://emodul.eu/api/v1/) is undocumented;
this module is the single source of truth for the field names, tile types,
widget subtypes and unit codes the integration relies on. Constants are
grouped into the following sections:

* **Config-entry / API field keys** -- string keys used inside config_entry
  data, device dicts and tile params payloads.
* **Platform list & polling** -- HA platform registration and refresh cadence.
* **Tile types** -- ``params.type`` values returned by the ``/tiles`` API.
  Each type is dispatched to a builder in :mod:`sensor` /
  :mod:`binary_sensor` (see :data:`sensor._TILE_ENTITY_BUILDERS`).
* **Widget subtypes & unit divisors** -- structure of the inner widget
  payloads carried by ``TYPE_WIDGET`` (=6) tiles.
* **Icon and txtId mapping tables** -- per-icon-id / per-tile-type defaults
  used when the per-tile data is missing or carries a status string instead
  of an entity label.
* **Valve / OpenTherm sensor descriptors** -- declarative lists driving
  conditional creation of valve and OpenTherm sub-entities.
* **Menu types & item types** -- the four Tech menu trees and the item-type
  enum that decides which HA platform a menu entry is mapped to.

Entity-naming protocol (relevant when reading :mod:`entity` and the tile
sensor classes): ``_attr_has_entity_name = True`` causes Home Assistant to
prepend the *device* name to the entity name automatically. The integration
therefore stores only the per-tile label in ``self._name`` and lets HA
combine it with the device. The ``INCLUDE_HUB_IN_NAME`` config flag is
preserved for backward compatibility but is now effectively a no-op for
tile-derived entities.
"""

from datetime import timedelta
from typing import Final

from homeassistant.const import Platform

# ---------------------------------------------------------------------------
# Config-entry and API field keys
# ---------------------------------------------------------------------------
DOMAIN = "tech"  # Home Assistant integration domain (must match manifest.json)
CONTROLLER = "controller"  # config_entry.data sub-dict containing one module
CONTROLLERS = "controllers"  # legacy: a list of controllers (multi-module)
VER = "version"  # firmware version reported by SW_VERSION tile
UDID = "udid"  # 32-char Tech module identifier (== device unique_id root)
USER_ID = "user_id"  # numeric Tech account id (used in /users/{id}/... URLs)
SIGNAL_STRENGTH = "signalStrength"  # wireless tile RSSI %, may be None
TILES = "tiles"  # /modules/{udid} response key
VISIBILITY = "visibility"  # tile.visibility -- hidden tiles are skipped
VALUE = "value"  # numeric reading inside widget payloads and menu items
MANUFACTURER = "TechControllers"  # ATTR_MANUFACTURER in DeviceInfo
WORKING_STATUS = "workingStatus"  # bool: relay/pump on/off in tile payload
ACTUATORS = "actuators"  # zone payload: list of valve actuator descriptors
BATTERY_LEVEL = "batteryLevel"  # wireless temp sensor %, may be None
ACTUATORS_OPEN = "actuatorsOpen"  # zone payload: count of opened actuators
INCLUDE_HUB_IN_NAME = "include_hub_in_name"  # config flag (now effectively a no-op for tile entities)
UNDERFLOOR = "underfloor"  # zone payload: optional underfloor sub-config
WINDOW_SENSORS = "windowsSensors"  # zone payload: list of window-sensor descriptors
WINDOW_STATE = "windowState"  # individual window sensor open/closed key
MODE = "mode"  # zone payload sub-key: schedule/constant-temp mode
CURRENT_STATE = "currentState"  # actuator/window sensor current state field
FLOOR_PUMP = "floorPump"  # underfloor pump descriptor key
SENSOR_TYPE = "sensorType"  # actuator/sensor variant code
EVENTS = "events"  # zone payload: list of alarm flags (correctWork etc.)
CORRECT_WORK = "correctWork"  # event key: device functioning normally
NO_COMMUNICATION = "noCommunication"  # event key: lost RF link
SENSOR_DAMAGED = "sensorDamaged"
LOW_BATTERY = "lowBattery"
LOW_SIGNAL = "lowSignal"
TEMP_TOO_HIGH = "tempTooHigh"
TEMP_TOO_LOW = "tempTooLow"
SERVICE_ERROR = "serviceError"
ZONE_STATE = "zoneState"  # "noAlarm", "zoneOff", "zoneOn", "zoneUnregistered"

DEFAULT_ICON = "mdi:eye"  # fallback when neither iconId nor type maps to an icon

# ---------------------------------------------------------------------------
# Platform list & polling cadence
# ---------------------------------------------------------------------------
# All platforms the integration forwards to. Order is irrelevant; HA loads
# them in parallel via async_forward_entry_setups.
PLATFORMS = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CLIMATE,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]

# Coordinator polling cadence. The eModul cloud rate-limits aggressive
# polling, and the boiler tile data does not change faster than ~60s anyway.
SCAN_INTERVAL: Final = timedelta(seconds=60)
API_TIMEOUT: Final = 60

# ---------------------------------------------------------------------------
# Tile types  (the ``type`` field on each tile in the /tiles API response)
# ---------------------------------------------------------------------------
# Each constant maps to a builder in :data:`sensor._TILE_ENTITY_BUILDERS`
# (or to a branch in binary_sensor's async_setup_entry). Unknown tile types
# are silently dropped, so adding a new type means adding a builder too.
TYPE_TEMPERATURE = 1  # Wired/wireless temperature sensor (zone-attached)
TYPE_FIRE_SENSOR = 2  # Smoke/fire alarm input -- "firingUp" boolean
TYPE_WIDGET = 6  # Universal "status with widgets" tile (carries widget1+widget2)
TYPE_RELAY = 11  # Generic on/off relay (Pompa CO, Pompa CWU, Podajnik...)
TYPE_ADDITIONAL_PUMP = 21  # Aux pump tile -- txtId is a status string, not a label
TYPE_FAN = 22  # Boiler combustion-air fan -- carries ``gear`` % field
TYPE_VALVE = 23  # Built-in mixing valve with currentTemp/returnTemp/setTemp
TYPE_MIXING_VALVE = 24  # Stand-alone mixing valve module (similar shape)
TYPE_FUEL_SUPPLY = 31  # Fuel feeder progress -- ``percentage`` + ``hours``
TYPE_DISINFECTION = 32  # Anti-Legionella cycle -- ``percentage`` + status txtId
TYPE_TEXT = 40  # Text/status tile (statusId + headerId, no numeric value)
TYPE_SW_VERSION = 50  # Carries controllerName + version (used for device_info)
TYPE_OPEN_THERM = 252  # OpenTherm boiler -- carries 4-5 sub-temperature values

# ---------------------------------------------------------------------------
# Widget subtypes  (``params.widgetN.type`` inside TYPE_WIDGET tiles)
# ---------------------------------------------------------------------------
# A TYPE_WIDGET tile carries up to two ``widgetN`` payloads. Each widget has
# its own type/unit/value triple; the *widget* type below is unrelated to the
# tile-level type above. Only documented values are listed -- additional codes
# are treated as a generic numeric reading (see :func:`sensor._build_widget_tile`).
WIDGET_DHW_PUMP = 1  # DHW pump set vs current temperature pair
WIDGET_COLLECTOR_PUMP = 2  # Solar collector pump duty cycle (percentage)
WIDGET_TEMPERATURE_CH = 9  # Central-heating temperature reading

# ``params.widgetN.unit`` codes seen in the wild and the divisor that turns
# the integer ``value`` into a human-readable measurement. Codes not listed
# here default to a divisor of 1 (raw value passthrough).
#  * 0   -- raw integer (no scaling)
#  * 4   -- tenths of a degree (rare; observed on some firmware variants)
#  * 5   -- hundredths (sub-degree precision)
#  * 6   -- enum/mode badge (no numeric meaning -- :func:`_build_widget_tile`
#           skips these to avoid creating useless "always 0" sensors)
#  * 7   -- tenths of a degree (the most common boiler temperature unit)
#  * -1  -- contact widget marker (handled by binary_sensor, not scaled here)
WIDGET_UNIT_DIVISORS = {0: 1, 4: 10, 5: 100, 6: 1, 7: 10}

# ---------------------------------------------------------------------------
# Icon mapping tables
# ---------------------------------------------------------------------------
# Some tiles carry a numeric ``iconId``. Mapping it to a Material Design Icon
# (mdi:*) keeps the HA UI visually consistent with the eModul mobile app.
ICON_BY_ID = {
    3: "mdi:animation-play",  # mode badge
    17: "mdi:arrow-right-drop-circle-outline",  # pump indicator
    50: "mdi:tune-vertical",  # state/configuration tile
    101: "mdi:cogs",  # fuel feeder
    167: "mdi:electric-switch",  # contact input (EU-i-3+ etc.)
}

# Fallback used when a tile has no iconId but the type implies an icon.
ICON_BY_TYPE = {
    TYPE_FIRE_SENSOR: "mdi:fire",
    TYPE_ADDITIONAL_PUMP: "mdi:arrow-right-drop-circle-outline",
    TYPE_FAN: "mdi:fan",
    TYPE_VALVE: "mdi:valve",
    TYPE_MIXING_VALVE: "mdi:valve",  # TODO: find a better icon
    TYPE_OPEN_THERM: "mdi:home-thermometer",
}

# ---------------------------------------------------------------------------
# txtId fallbacks
# ---------------------------------------------------------------------------
# When a tile has no ``txtId`` (or the per-tile txtId carries a status string
# rather than a label -- see :data:`TXT_ID_IS_STATUS_FOR_TYPES`), fall back
# to a hard-coded txtId per tile type. The numbers are looked up in the Tech
# i18n translation pack at startup (see :func:`assets.load_subtitles`).
TXT_ID_BY_TYPE = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_ADDITIONAL_PUMP: 576,  # "Pompa dodatkowa" -- per-tile txtId is "Disabled"
    TYPE_FAN: 4135,
    TYPE_VALVE: 991,
    TYPE_MIXING_VALVE: 5731,
    TYPE_FUEL_SUPPLY: 961,
    TYPE_DISINFECTION: 246,  # "Dezynfekcja" -- per-tile txtId is "Disabled"
    TYPE_OPEN_THERM: 4633,
}

# Tile types whose ``params.txtId`` carries a *status* string ("Wyłączona"
# / "Active" / "Disabled") rather than an entity label. :class:`TileEntity`
# detects membership and falls through to :data:`TXT_ID_BY_TYPE` instead of
# rendering "Disabled" as the entity name.
TXT_ID_IS_STATUS_FOR_TYPES: frozenset[int] = frozenset(
    {TYPE_ADDITIONAL_PUMP, TYPE_DISINFECTION}
)

# ---------------------------------------------------------------------------
# Valve sensor descriptors
# ---------------------------------------------------------------------------
# A TYPE_VALVE/TYPE_MIXING_VALVE tile may carry up to three temperature
# fields. The descriptor format (``txt_id``, ``state_key``) is consumed by
# :func:`sensor._build_valve_tile`, which conditionally creates one
# :class:`TileValveTemperatureSensor` per non-null state_key.
VALVE_SENSOR_RETURN_TEMPERATURE = {"txt_id": 747, "state_key": "returnTemp"}
VALVE_SENSOR_SET_TEMPERATURE = {"txt_id": 1065, "state_key": "setTemp"}
VALVE_SENSOR_CURRENT_TEMPERATURE = {"txt_id": 2010, "state_key": "currentTemp"}

# ---------------------------------------------------------------------------
# OpenTherm sensor descriptors
# ---------------------------------------------------------------------------
# Same descriptor shape as the valve sensors above, but consumed by
# :func:`sensor._build_open_therm_tile` for TYPE_OPEN_THERM tiles.
OPENTHERM_CURRENT_TEMP = {"txt_id": 127, "state_key": "currentTemp"}
OPENTHERM_CURRENT_TEMP_DHW = {"txt_id": 128, "state_key": "currentTempDHW"}
OPENTHERM_SET_TEMP = {"txt_id": 1058, "state_key": "setCurrentTemp"}
OPENTHERM_SET_TEMP_DHW = {"txt_id": 1059, "state_key": "setTempDHW"}
OPENTHERM_MODULATION = {"txt_id": 428, "state_key": "modulationPercentage"}

# ---------------------------------------------------------------------------
# Menu trees and item types
# ---------------------------------------------------------------------------
# The Tech API exposes four hierarchical menu trees per controller. Each is
# fetched from /users/{uid}/modules/{udid}/menu/{TYPE}/. Only USER and
# INSTALLER menus are loaded by default -- SERVICE and MANUFACTURER menus
# are deeply nested, frequently locked, and not currently mapped to entities.
MENU_TYPE_USER = "MU"
MENU_TYPE_INSTALLER = "MI"
MENU_TYPE_SERVICE = "MS"
MENU_TYPE_MANUFACTURER = "MP"
MENU_TYPES = [MENU_TYPE_USER, MENU_TYPE_INSTALLER]

# A menu item's ``type`` field decides which HA platform it is mapped to:
#   - GROUP             -> not an entity (organisational header)
#   - VALUE / UNIVERSAL -> NumberEntity (set integer/decimal value)
#   - CODE / TIME_MODE  -> currently unmapped
#   - ON_OFF            -> SwitchEntity
#   - CHOICE            -> SelectEntity
#   - DIALOGUE          -> ButtonEntity (one-shot action)
MENU_ITEM_TYPE_GROUP = 0
MENU_ITEM_TYPE_VALUE = {1, 2, 3, 4, 5}
MENU_ITEM_TYPE_CODE = 6
MENU_ITEM_TYPE_TIME_MODE = 7
MENU_ITEM_TYPE_ON_OFF = 10
MENU_ITEM_TYPE_CHOICE = {11, 111, 112}
MENU_ITEM_TYPE_DIALOGUE = 20
MENU_ITEM_TYPE_UNIVERSAL_VALUE = 106

# Format codes embedded in a numeric menu item's ``params.format`` field.
# Used by :class:`number.MenuNumberEntity` to scale set/get values (only
# NORMAL and TENTH are currently honoured).
VALUE_FORMAT_NORMAL = 1  # raw integer (1, 2, 3, ...)
VALUE_FORMAT_TENTH = 2  # value/10 (e.g. setpoint 225 -> 22.5°C)
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
