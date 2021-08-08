"""Constants for the Tech Sterowniki integration."""

DOMAIN = "tech"

CONF_LANGUAGE = "language"

DEFAULT_ICON = "mdi:eye"

# tile type
TYPE_TEMPERATURE = 1
TYPE_FIRE_SENSOR = 2
TYPE_TEMPERATURE_CH = 6
TYPE_RELAY = 11
TYPE_ADDITIONAL_PUMP = 21
TYPE_FAN = 22
TYPE_VALVE = 23
TYPE_FUEL_SUPPLY = 31
TYPE_TEXT = 40

ICON_BY_ID = {
    3: "mdi:animation-play",  # mode
    17: "mdi:arrow-right-drop-circle-outline",  # pump
    50: "mdi:tune-vertical",  # state
    101: "mdi:cogs",  # feeder
}

ICON_BY_TYPE = {
    TYPE_FIRE_SENSOR: "mdi:fire",
    TYPE_ADDITIONAL_PUMP: "mdi:arrow-right-drop-circle-outline",
    TYPE_FAN: "mdi:fan",
    TYPE_VALVE: "mdi:valve",
}

TXT_ID_BY_TYPE = {
    TYPE_FIRE_SENSOR: 205,
    TYPE_FAN: 4135,
    TYPE_VALVE: 991,
    TYPE_FUEL_SUPPLY: 961,
}

SUPPORTED_LANGUAGES = {
    "English": "en",
    "Polski": "pl",
    "Deutsch": "de",
    "Čeština": "cs",
    "Slovenský": "sk",
    "Magyar": "hu",
    "Pусский": "ru",
}
