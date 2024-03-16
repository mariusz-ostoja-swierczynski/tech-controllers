"""Assets for translations."""
import logging
from typing import Any

from .const import DEFAULT_ICON, ICON_BY_ID, ICON_BY_TYPE, TXT_ID_BY_TYPE
from .tech import Tech

_LOGGER: logging.Logger = logging.getLogger(__name__)

TRANSLATIONS: dict[str, Any] = {}


async def load_subtitles(
    api: Tech,
    language: str = "pl",
) -> None:
    """Load subtitles for the specified language.

    Args:
        api (Tech, required): object to use Tech api
        language (str, optional): The language code for the subtitles. Defaults to "pl".

    Returns:
        None

    """
    global TRANSLATIONS  # noqa: PLW0603
    TRANSLATIONS = await api.get_translations(language)


def get_text(text_id: int) -> str:
    """Get text by id.

    Args:
        text_id (int): The ID of the text to retrieve.

    Returns:
        str: The text corresponding to the ID, or a default string if not found.

    """
    if text_id != 0:
        return TRANSLATIONS["data"].get(str(text_id), f"txtId {text_id}")
    else:
        return f"txtId {text_id}"


def get_text_by_type(text_type: int) -> str:
    """Get text by type.

    Args:
        text_type (int): The type of the text to retrieve.

    Returns:
        str: The text corresponding to the type, or a default string if not found.

    """
    text_id: int = TXT_ID_BY_TYPE.get(text_type, text_type)
    return get_text(text_id)


def get_icon(icon_id: int) -> str:
    """Get icon by id.

    Args:
        icon_id (int): The ID of the icon to retrieve.

    Returns:
        str: The icon corresponding to the ID, or a default string if not found.

    """
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type: int) -> str:
    """Get icon by type.

    Args:
        icon_type (int): The type of the icon to retrieve.

    Returns:
        str: The icon corresponding to the type, or a default string if not found.

    """
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)
