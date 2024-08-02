"""Assets for translations."""

import logging

from .const import DEFAULT_ICON, ICON_BY_ID, ICON_BY_TYPE, TXT_ID_BY_TYPE

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

TRANSLATIONS = None


def redact(entry_data: dict, keys: list) -> str:
    """Return a copy of entry_data with the specified fields redacted.

    Args:
        entry_data (dict): The data to redact.
        keys (list): The list of keys to redact.

    Returns:
        str: The redacted data.

    """
    sanitized_data = entry_data.copy()
    for key in keys:
        if key in sanitized_data:
            sanitized_data[key] = "***HIDDEN***"
    return str(sanitized_data)


async def load_subtitles(language: str, api):
    """Load subtitles for the specified language.

    Args:
        language (str): The language code for the subtitles. Defaults to "pl".
        api: object to use Tech api

    Returns:
        None

    """
    global TRANSLATIONS  # noqa: PLW0603
    TRANSLATIONS = await api.get_translations(language)


def get_text(text_id) -> str:
    """Get text by id."""
    if TRANSLATIONS is not None and text_id != 0:
        return TRANSLATIONS["data"].get(str(text_id), f"txtId {text_id}")
    return f"txtId {text_id}"


def get_id_from_text(text) -> int:
    """Get id from text (reverse lookup needed for migration)."""
    if text != "":
        _LOGGER.debug("👰 text to lookup: %s", text)
        if TRANSLATIONS is not None:
            return int(
                [key for key, value in TRANSLATIONS["data"].items() if value == text][0]
            )
    return 0


def get_text_by_type(text_type) -> str:
    """Get text by type."""
    text_id = TXT_ID_BY_TYPE.get(text_type, f"type {text_type}")
    return get_text(text_id)


def get_icon(icon_id) -> str:
    """Get icon by id."""
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type) -> str:
    """Get icon by type."""
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)
