"""pytest fixtures."""
from collections.abc import AsyncGenerator
import json
import socket
from unittest.mock import AsyncMock

import aiohttp
from aioresponses import aioresponses
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

# from homeassistant.components import mqtt
from custom_components.tech.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from tests.common import load_fixture


async def test_async_setup(hass):
    """Test the component get setup."""
    assert await async_setup_component(hass, DOMAIN, {}) is True


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test dir."""
    yield


# Test that enabling the socket fixture allows us to create a TCP socket
#
# This test is a sanity check that the socket fixture is actually doing its job
@pytest.mark.usefixtures("socket_enabled")
def test_explicitly_enable_socket():
    """Test that enabling the socket fixture allows us to create a TCP socket.

    This test is a sanity check that the socket fixture is actually doing its job

    Args:
        None

    Returns:
        None

    """
    assert socket.socket(socket.AF_INET, socket.SOCK_STREAM)


@pytest.fixture
def TechMock() -> AsyncMock:
    """Async Mock Fixture."""
    TechMock = AsyncMock()
    TechMock.authenticate = AsyncMock(
        return_value=json.loads(load_fixture("auth.json", DOMAIN))
    )
    return TechMock

@pytest.fixture(name="config_entry")
def mock_config_entry_fixture(hass: HomeAssistant) -> MockConfigEntry:
    """Mock a config entry."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Home",
        entry_id="95f248426cf801c3d41c8d68a602072b",
        version=2,
        minor_version=1,
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
    mock_entry.add_to_hass(hass)

    return mock_entry

@pytest.fixture(autouse=True)
def expected_lingering_tasks() -> bool:
    """Temporary ability to bypass test failures.

    Parametrize to True to bypass the pytest failure.
    @pytest.mark.parametrize("expected_lingering_tasks", [True])

    This should be removed when all lingering tasks have been cleaned up.
    """
    return True


@pytest.fixture(
    name="client_session",
    # Use an auto-use fixture to make the session available in tests.
    # The session is yielded and closed by the fixture.
    autouse=True,
)
async def client_session_fixture() -> AsyncGenerator:
    """Yield a client session for use in aiohttp tests."""
    session = aiohttp.ClientSession()
    try:
        yield session
    finally:
        await session.close()


# # Fixtures for mocked responses
# @pytest.fixture
# def mock_auth_response():
#     return {
#         "authenticated": True,
#         "user_id": "1234",
#         "token": "abc123def456"
#     }

# @pytest.fixture
# def mock_get_response():
#     return {
#         "data": [
#             {"id": 1, "name": "Module 1"},
#             {"id": 2, "name": "Module 2"}
#         ]
#     }

# @pytest.fixture
# def mock_post_response():
#     return {"success": True, "message": "Data posted successfully"}

# # Custom mock class for ClientResponse
# class MockClientResponse(Mock):
#     def __init__(self, payload, status=200):
#         super().__init__(spec=aiohttp.ClientResponse)
#         self.status = status
#         self.payload = payload
#         self.content = json.dumps(payload).encode('utf-8')

#     async def json(self):
#         return self.payload

#     async def text(self):
#         return json.dumps(self.payload)

#     async def read(self):
#         return self.content

#     async def release(self):
#         pass

# # Custom aioresponses context manager
# class AioresponsesContext:
#     def __init__(self):
#         self.responses = []

#     def __enter__(self):
#         self._patcher = Mock()
#         self._patcher.start()
#         return self

#     def __exit__(self, exc_type, exc_val, exc_tb):
#         self._patcher.stop()

#     def mock(self, method, url, payload, status=200):
#         mock_response = MockClientResponse(payload, status)
#         self.responses.append(mock_response)
#         self._patcher.patch(method.upper(), url, return_value=mock_response)