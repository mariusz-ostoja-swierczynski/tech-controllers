"""Helper utilities for working with integration assets."""

from __future__ import annotations

from collections.abc import Iterable
import logging
from typing import Any

from .const import DEFAULT_ICON, ICON_BY_ID, ICON_BY_TYPE, TXT_ID_BY_TYPE

_LOGGER = logging.getLogger(__name__)

_REDACTED_VALUE = "***HIDDEN***"

TranslationsType = dict[str, Any]


TRANSLATIONS: TranslationsType | None = None


def redact(entry_data: dict[str, Any], keys: Iterable[str]) -> str:
    """Return a string representation of ``entry_data`` with selected keys masked.

    Args:
        entry_data: Source mapping that may contain sensitive values.
        keys: Sequence of keys whose values should be replaced.

    Returns:
        Stringified version of ``entry_data`` with sensitive values replaced by
        ``***HIDDEN***``.

    """
    sanitized_data = entry_data.copy()
    for key in keys:
        if key in sanitized_data:
            sanitized_data[key] = _REDACTED_VALUE
    return str(sanitized_data)


async def load_subtitles(language: str, api) -> None:
    """Load translated subtitles for the active integration language.

    Args:
        language: Home Assistant language code to retrieve from the API.
        api: Authenticated Tech API client exposing ``get_translations``.

    """
    global TRANSLATIONS  # noqa: PLW0603 # pylint: disable=global-statement
    TRANSLATIONS = await api.get_translations(language)


def get_text(text_id: int) -> str:
    """Return the translated string for a subtitle identifier."""
    if TRANSLATIONS is not None and text_id != 0:
        return TRANSLATIONS.get("data", {}).get(str(text_id), f"txtId {text_id}")
    return f"txtId {text_id}"


def get_id_from_text(text: str) -> int:
    """Return the translation identifier for a given text value."""
    if text:
        _LOGGER.debug("Looking up translation id for text: %s", text)
        if TRANSLATIONS is not None:
            for key, value in TRANSLATIONS.get("data", {}).items():
                if value == text:
                    return int(key)
    return 0


def get_text_by_type(text_type: int) -> str:
    """Return the translated label associated with a tile type."""
    text_id = TXT_ID_BY_TYPE.get(text_type, f"type {text_type}")
    return get_text(text_id)


def get_icon(icon_id: int) -> str:
    """Return the Material Design icon name mapped to ``icon_id``."""
    return ICON_BY_ID.get(icon_id, DEFAULT_ICON)


def get_icon_by_type(icon_type: int) -> str:
    """Return the default icon assigned to the provided tile type."""
    return ICON_BY_TYPE.get(icon_type, DEFAULT_ICON)
