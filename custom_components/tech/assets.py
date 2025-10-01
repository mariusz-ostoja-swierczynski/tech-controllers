"""Helper utilities for working with integration assets."""

from __future__ import annotations

import logging
from typing import Any, Iterable

from .const import DEFAULT_ICON, ICON_BY_ID, ICON_BY_TYPE, TXT_ID_BY_TYPE

_LOGGER = logging.getLogger(__name__)

_REDACTED_VALUE = "***HIDDEN***"

TranslationsType = dict[str, Any]


TRANSLATIONS: TranslationsType | None = None


def redact(entry_data: dict[str, Any], keys: Iterable[str]) -> str:
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
            sanitized_data[key] = _REDACTED_VALUE
    return str(sanitized_data)


async def load_subtitles(language: str, api) -> None:
    """Load subtitles for the specified language.

    Args:
        language (str): The language code for the subtitles. Defaults to "pl".
        api: object to use Tech api

    Returns:
        None

    """
    global TRANSLATIONS  # noqa: PLW0603 # pylint: disable=global-statement
    TRANSLATIONS = await api.get_translations(language)


def get_text(text_id: int) -> str:
    """Get text by id."""
    if TRANSLATIONS is not None and text_id != 0:
        return TRANSLATIONS.get("data", {}).get(str(text_id), f"txtId {text_id}")
    return f"txtId {text_id}"


def get_id_from_text(text: str) -> int:
    """Get id from text (reverse lookup needed for migration)."""
    if text:
        _LOGGER.debug("Looking up translation id for text: %s", text)
        if TRANSLATIONS is not None:
            for key, value in TRANSLATIONS.get("data", {}).items():
                if value == text:
                    return int(key)
    return 0


def get_text_by_type(text_type: int) -> str:
    """Get text by type."""
    text_id = TXT_ID_BY_TYPE.get(text_type, f"type {text_type}")
    return get_text(text_id)


def get_icon(icon_id: int) -> str:
    """Get icon by id."""
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type: int) -> str:
    """Get icon by type."""
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)
