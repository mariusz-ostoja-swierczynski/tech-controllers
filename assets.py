import logging
import os
import json
from .const import (
    DEFAULT_ICON,
    ICON_BY_ID,
    ICON_BY_TYPE,
    TXT_ID_BY_TYPE,
)

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

_subtitles = None


def loadSubtitles(language="pl"):
    global _subtitles
    _LOGGER.debug("loading emodul.%s.json", language)
    filename = os.path.join(os.path.dirname(__file__), "translations", f"emodul.{language}.json")
    f = open(filename, "r")
    data = json.loads(f.read())
    _subtitles = data["subtitles"]


def get_text(id) -> str:
    return _subtitles.get(str(id), f"txtId {id}")


def get_text_by_type(type) -> str:
    id = TXT_ID_BY_TYPE.get(type, f"type {type}")
    return get_text(id)


def get_icon(id) -> str:
    return ICON_BY_ID.get(id, DEFAULT_ICON)


def get_icon_by_type(type) -> str:
    return ICON_BY_TYPE.get(type, DEFAULT_ICON)
