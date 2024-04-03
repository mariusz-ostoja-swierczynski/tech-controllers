"""Tests for Tech custom component."""

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tech.const import DOMAIN
from tests.common import load_fixture

TECH_API_URL = "https://emodul.eu/api/v1/"
TECH_API_LANG = "https://emodul.eu/api/v1/i18n/en"
TECH_API_MODULES = "https://emodul.eu/api/v1/users/240471648/modules/8623dddc28f834922d97b76f2096873c"


async def init_integration(hass, aioclient_mock) -> MockConfigEntry:
    """Set up the Tech integration in Home Assistant."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        entry_id="95f248426cf801c3d41c8d68a602072b",
        version=2,
        minor_version=2,
        data={
            "user_id": "240471648",
            "token": "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6InRlc3QiLCJ1c2VyX2lkIjoyNDA0NzE2NDgsImlhdCI6MTcxMTYzMTYxM30.cIJgIU3xoCHG8iVGSVpd8rDQdWxY6R5il3XkFqfhZ_U",
            "controller": {
            "id": 1,
            "default": "true",
            "name": "L-8 DEMO",
            "email": "",
            "type": "zones_controller",
            "controllerStatus": "active",
            "moduleStatus": "active",
            "additionalInformation": "null",
            "phoneNumber": "null",
            "zipCode": "34-120",
            "tag": "null",
            "country": "Polska",
            "gmtId": 30,
            "gmtTime": "1",
            "postcodePolicyAccepted": "true",
            "style": "zones",
            "version": "TECH: L8 (v.2.1.19)",
            "company": "tech",
            "udid": "8623dddc28f834922d97b76f2096873c"
            },
        "version": "TECH: L8 (v.2.1.19): L-8 DEMO"
        },
    )

    # aioclient_mock.get(TECH_API_URL, text=load_fixture("tech_module.json"))
    aioclient_mock.get(TECH_API_LANG, text=load_fixture("get_translations.json"))
    aioclient_mock.get(TECH_API_MODULES, text=load_fixture("get_module_data.json"))
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry
