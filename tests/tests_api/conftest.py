"""pytest fixtures."""

from collections.abc import AsyncGenerator
import json

import aiohttp
import pytest

from custom_components.tech.const import DOMAIN
from tests.common import load_fixture


@pytest.fixture(scope="module")
def valid_credentials():
    """Fixture to provide valid credentials."""
    # The demo account's own credentials, the ones this module's docstring
    # publishes. The token is a placeholder rather than a recorded one: it is
    # never sent anywhere -- a client built with it is authenticated by
    # construction, which is what one of the tests below checks -- and a real
    # token is a credential besides going stale.
    yield {
        "username": "test",
        "password": "test",
        "user_id": 240471648,
        "token": "REDACTED",
    }


@pytest.fixture(scope="module")
def invalid_credentials():
    """Fixture to provide invalid credentials."""
    yield {"username": "test_wrong", "password": "test_wrong"}


@pytest.fixture(scope="module")
def module_data():
    """Fixture to provide module data."""
    yield {
        "module_id": "8623dddc28f834922d97b76f2096873c",
        "wrong_module_id": "1234567",
        "zone_id": 101,
        "tile_id": 4063,
        "target_temp": 25,
    }


@pytest.fixture(
    name="mock_set_const_temp_response",
    # Fixture to provide a mock response for set_const_temp
)
def mock_set_const_temp_response_fixture() -> dict:
    """Load the fixture for set_constant_temp and return it as a dictionary."""
    return json.loads(load_fixture("set_constant_temp.json", DOMAIN))


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
