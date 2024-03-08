"""Assets for translations."""
import logging

from .const import DEFAULT_ICON, ICON_BY_ID, ICON_BY_TYPE, TXT_ID_BY_TYPE

logging.basicConfig(level=logging.DEBUG)
_LOGGER = logging.getLogger(__name__)

TRANSLATIONS = None


async def load_subtitles(language, api):
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
    if text_id != 0:
        return TRANSLATIONS["data"].get(str(text_id), f"txtId {text_id}")
    else:
        return f"txtId {text_id}"


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
