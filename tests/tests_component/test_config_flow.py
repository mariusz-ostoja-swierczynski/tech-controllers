# from unittest.mock import patch
from http import HTTPStatus
import json
from unittest import mock
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

# from homeassistant import config_entries, core
from custom_components.tech import config_flow
from custom_components.tech.const import CONTROLLER, CONTROLLERS, DOMAIN, USER_ID
from custom_components.tech.tech import Tech, TechError
from homeassistant import data_entry_flow
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from tests.common import load_fixture

CONFIG = {
    CONF_USERNAME: "test",
    CONF_PASSWORD: "foo",
}

@pytest.fixture
def tech_user_input():
    """Simulate user input."""
    return {
        config_flow.CONF_USERNAME: "test",
        config_flow.CONF_PASSWORD: "test",
    }

async def test_show_form(hass: HomeAssistant) -> None:
    """Test that the form is served with no input."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

@pytest.mark.asyncio
async def test_validate_input(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test that errors are shown when API key is invalid."""

    auth = load_fixture("auth.json", DOMAIN)
    modules = load_fixture("get_modules.json", DOMAIN)

    aioclient_mock.post(
        "https://emodul.eu/api/v1/authentication", text=auth
    )

    aioclient_mock.get(
        "https://emodul.eu/api/v1/users/240471648/modules", text=modules
    )

    result = await config_flow.validate_input(hass, CONFIG)

    assert result[USER_ID] == str(json.loads(auth)[USER_ID])
    assert result[CONF_TOKEN] == str(json.loads(auth)[CONF_TOKEN])
    assert result[CONTROLLERS] == json.loads(modules)

@pytest.mark.asyncio
async def test_invalid_credentials(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    """Test that errors are shown when API key is invalid."""
    aioclient_mock.post(
        "https://emodul.eu/api/v1/authentication",
        exc=TechError(
            HTTPStatus.UNAUTHORIZED, {"error":{"authenticated":"false"}}
        ),
    )

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}, data=CONFIG
    )

    assert result["errors"] == {'base': 'invalid_auth'}


@pytest.mark.asyncio
async def test_flow_user_init(hass):
    """Test the initialization of the form for step of the config flow."""
    result = await hass.config_entries.flow.async_init(
        config_flow.DOMAIN, context={"source": "user"}
    )
    expected = {
        "data_schema": config_flow.DATA_SCHEMA,
        "description_placeholders": None,
        "errors": {},
        "flow_id": mock.ANY,
        "handler": config_flow.DOMAIN,
        "last_step": None,
        "step_id": "user",
        "type": "form",
        "preview": None,
    }
    assert expected == result


# async def test_flow_user_creates_config_entry(
#         hass, tech_user_input
# ):
#     """Test the config entry is successfully created."""
#     result = await hass.config_entries.flow.async_init(
#         config_flow.DOMAIN, context={"source": "user"}
#     )
#     await hass.config_entries.flow.async_configure(
#         result["flow_id"],
#         user_input={**tech_user_input},
#     )
#     await hass.async_block_till_done()

#     # Retrieve the created entry and verify data
#     entries = hass.config_entries.async_entries(config_flow.DOMAIN)
#     assert len(entries) == 1
#     assert entries[0].data == {
#         "user_id": "240471648",
#         "token": "eyJhbGciOiJIUzI1NiJ9.eyJ1c2VybmFtZSI6InRlc3QiLCJ1c2VyX2lkIjoyNDA0NzE2NDgsImlhdCI6MTcxMDc1Mzc1NH0.bu53U2Y_yX-4nsZaxNjRqerxEvI5bF1RAnI89Ob4UVE",
#     }


async def test_create_entry(
    hass: HomeAssistant,
) -> None:
    """Test creating a config entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    # Check that the config flow shows the user/pass as the first step
    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"

    # Choose config for a time config
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], user_input={"next_step_id": "select_controllers"}
    )

    # Check that the config flow shows the form for the config name
    assert result["type"] == data_entry_flow.RESULT_TYPE_FORM

    # result = await hass.config_entries.flow.async_init(
    #     DOMAIN, context={"source": SOURCE_USER}, data={"type": integration_type}
    # )
    # assert result["type"] == data_entry_flow.FlowResultType.FORM
    # assert result["step_id"] == input_form_step

    # Test errors that can arise:
    # with patch.object(cloud_api.air_quality, patched_method, response):
    #     result = await hass.config_entries.flow.async_configure(
    #         result["flow_id"], user_input=config
    #     )
    #     assert result["type"] == data_entry_flow.FlowResultType.FORM
    #     assert result["errors"] == errors

    # # Test that we can recover and finish the flow after errors occur:
    # result = await hass.config_entries.flow.async_configure(
    #     result["flow_id"], user_input=config
    # )
    # assert result["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
    # assert result["title"] == entry_title
    # # assert result["data"] == {**config, CONF_INTEGRATION_TYPE: integration_type}
