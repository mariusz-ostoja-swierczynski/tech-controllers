"""Diagnostics support for the Tech Controllers integration.

Home Assistant offers a download of this per config entry, which is what a
reporter is asked for when something looks wrong. It carries the entry's data
with the secrets and the account's personal data taken out and a summary of
what the controller last reported, so a controller's zones, tiles and menu
items can be reasoned about without publishing the account's token, contact
details or the module's identifier.
"""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.redact import async_redact_data

TO_REDACT = {
    # The bearer token authenticates as the account.
    "token",
    # The user id identifies the account, and no debugging needs it.
    "user_id",
    "username",
    "password",
    # Personal data the account returns with a controller. A diagnostics file
    # is meant to be pasted into a public issue, so the owner's contact details
    # and address data must not travel with it.
    "email",
    "phoneNumber",
    "zipCode",
    # The controller's stable module identifier. It is not a credential, but it
    # identifies one physical device across reports, so it is redacted with the
    # account data. What is left (name, model and version, counts) is what a
    # report needs.
    "udid",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a controller's config entry.

    Args:
        hass: Home Assistant instance.
        entry: The config entry being diagnosed.

    Returns:
        The entry's data with its secrets removed, its options, and what the
        controller last reported.

    """
    coordinator = entry.runtime_data
    data = coordinator.data or {}

    return {
        "entry": {
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "controller": {
            "last_update_success": coordinator.last_update_success,
            "zones": len(data.get("zones", {})),
            "tiles": len(data.get("tiles", {})),
            "menus": len(data.get("menus", {})),
        },
    }
