"""Test Tech API.

This is a "live" test using real API and Tech provided demo account
(username: "test", password: "test").

"""

import json
import logging
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.tech import Tech, TechError, TechLoginError

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger(__name__)


class TestTechAPI:
    """Test cases for TECH API."""

    @pytest.mark.asyncio
    async def test_authenticate(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test authentication.

        Test that authenticate() returns the expected response from the API.

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        Returns:
            None

        """
        tech: Tech = Tech(
            client_session, valid_credentials["user_id"], valid_credentials["token"]
        )

        _LOGGER.debug("Authenticated: %s", tech.authenticated)
        assert tech.authenticated, "Authentication should be successful"

    @pytest.mark.asyncio
    async def test_authenticate_with_token(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test authentication.

        Test that authenticate() returns the expected response from the API.

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        Returns:
            None

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        _LOGGER.debug("Authenticated: %s", authenticated)
        assert authenticated, "Authentication should be successful"

    @pytest.mark.asyncio
    async def test_authenticate_failure(
        self,
        client_session: aiohttp.ClientSession,
        invalid_credentials: dict,
    ) -> None:
        """Test authentication failure.

        Test that authenticate() raises TechLoginError when
        the username and password are incorrect.

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            invalid_credentials (dict): Pytest fixture with invalid credentials.

        """
        tech: Tech = Tech(client_session)

        with pytest.raises(TechLoginError) as exception_info:
            await tech.authenticate(
                invalid_credentials["username"], invalid_credentials["password"]
            )
        _LOGGER.info("Exception: %s", exception_info)
        exception: TechLoginError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_list_modules(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test list_modules method.

        Test that list_modules() returns the list of modules

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        modules: dict = await tech.list_modules()
        assert isinstance(modules, list), "We should receive a list of modules"
        assert isinstance(modules[0], dict), "Modules should be dicts"
        assert modules[0]["id"] == 0, "First module id should be 0"

    @pytest.mark.asyncio
    async def test_list_modules_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test test_list_modules_failure method.

        Test that list_modules() raises and exception on failure

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        """
        tech: Tech = Tech(client_session)

        with pytest.raises(TechError) as exception_info:
            response: dict = await tech.list_modules()
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_get_module_data(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test get_module_data method.

        Test that get_module_data() returns the details of a module

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        module: dict = await tech.get_module_data(module_data["module_id"])
        assert isinstance(module, dict), "The module returned should be a dictionary"
        assert "zones" in module, "The module should have key 'zones'"
        assert "tiles" in module, "The module should have key 'tiles'"

    @pytest.mark.asyncio
    async def test_get_module_data_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test test_get_module_data_failure method.

        Test that get_module_data() raised an exception on failure

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        with pytest.raises(TechError) as exception_info:
            response = await tech.get_module_data(module_data["wrong_module_id"])
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 403, "Unexpected status code"
        assert (
            exception.status == '{"error":"User has no permission to module"}'
        ), "Unexpected error message"

    @pytest.mark.asyncio
    async def test_get_module_data_auth_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test test_get_module_data_auth_failure method.

        Test that get_module_data() raises an exception on failure on auth failure

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)
        tech.user_id = valid_credentials["user_id"]

        with pytest.raises(TechError) as exception_info:
            response = await tech.get_module_data(module_data["module_id"])
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_get_translations(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test get_translations method.

        Test that get_translations() returns a language dict

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        """
        tech: Tech = Tech(client_session)

        tech.user_id = valid_credentials["user_id"]

        with pytest.raises(TechError) as exception_info:
            response = await tech.get_translations("en")
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_get_translations_auth_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ) -> None:
        """Test test_get_translations_auth_failure method.

        Test that get_translations() raised an exception on auth failure

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        lang: dict = await tech.get_translations("en")
        assert isinstance(lang, dict), "The module returned should be a dictionary"
        assert lang["status"] == "success", "We should receive status == success"
        assert "data" in lang, "The module should have key 'data'"
        assert isinstance(
            lang["data"], dict
        ), "The data returned should be a dictionary"

    @pytest.mark.asyncio
    async def test_get_module_zones(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test get_module_zones method.

        Test that get_module_zones() returns given module zones

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        tech.modules.setdefault(
            module_data["module_id"], {"last_update": None, "zones": {}, "tiles": {}}
        )

        zones: dict = await tech.get_module_zones(module_data["module_id"])
        assert isinstance(zones, dict), "The zones returned should be a dictionary"
        assert 101 in zones, "The module should have key 101"
        assert isinstance(
            zones[101], dict
        ), "The zone data returned should be a dictionary"
        assert "zone" in zones[101], "The zone dict should have key zone"

    @pytest.mark.asyncio
    async def test_get_module_tiles(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test get_module_tiles method.

        Test that get_module_tiles() returns given module tiles

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        tech.modules.setdefault(
            module_data["module_id"], {"last_update": None, "zones": {}, "tiles": {}}
        )

        tiles: dict = await tech.get_module_tiles(module_data["module_id"])
        assert isinstance(tiles, dict), "The tiles returned should be a dictionary"
        assert 4063 in tiles, "The module should have key 101"
        assert isinstance(
            tiles[4063], dict
        ), "The tiles data returned should be a dictionary"
        assert "id" in tiles[4063], "The tiles dict should have key tiles"

    @pytest.mark.asyncio
    async def test_module_data(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test module_data method.

        Test that module_data() returns given module data

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        data: dict = await tech.module_data(module_data["module_id"])
        assert isinstance(data, dict), "The tiles returned should be a dictionary"
        assert "last_update" in data, "The module should have key last_update"
        assert "zones" in data, "The module should have key zones"
        assert isinstance(
            data["zones"], dict
        ), "The zones data returned should be a dictionary"
        assert "tiles" in data, "The module should have key tiles"
        assert isinstance(
            data["tiles"], dict
        ), "The tiles data returned should be a dictionary"

    @pytest.mark.asyncio
    async def test_get_zone(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test get_zone method.

        Test that get_zone() returns given zone data

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        tech.modules.setdefault(
            module_data["module_id"], {"last_update": None, "zones": {}, "tiles": {}}
        )

        zone: dict = await tech.get_zone(
            module_data["module_id"], module_data["zone_id"]
        )
        assert isinstance(zone, dict), "The data returned should be a dictionary"
        assert "zone" in zone, "The data should have key zones"
        assert isinstance(
            zone["zone"], dict
        ), "The zone data returned should be a dictionary"
        assert "id" in zone["zone"], "The zone dict should have key id"

    @pytest.mark.asyncio
    async def test_get_tile(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test get_tile method.

        Test that get_tile() returns given tile data

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        tech.modules.setdefault(
            module_data["module_id"], {"last_update": None, "zones": {}, "tiles": {}}
        )

        tile: dict = await tech.get_tile(
            module_data["module_id"], module_data["tile_id"]
        )
        assert isinstance(tile, dict), "The data returned should be a dictionary"
        assert "id" in tile, "The tile dict should have key id"
        assert tile["id"] == module_data["tile_id"], "The ID should match"

    @pytest.mark.asyncio
    async def test_set_const_temp(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test set_const_temp method.

        Test that set_const_temp() returns success.
        This is a fake test, as we can't set the actual temp on demo account,
        so we effecitvely test if we get the demo error response

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        data = await tech.module_data(module_data["module_id"])

        with pytest.raises(TechError) as exception_info:
            response = await tech.set_const_temp(
                module_data["module_id"],
                module_data["zone_id"],
                module_data["target_temp"],
            )
            assert isinstance(
                response, data
            ), "The data returned should be a dictionary"
            assert "error" in response, "We should get an error key on demo account"
            assert (
                response["error"] == "Demo account."
            ), "We should get an error key on demo account"
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert (
            exception.status == '{"error":"Demo account."}'
        ), "Unexpected error message"

    @pytest.mark.asyncio
    async def test_set_const_temp_auth_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test test_set_const_temp_auth_failure method.

        Test that set_const_temp() raises an exception on auth failure.

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)
        tech.user_id = valid_credentials["user_id"]

        await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )

        await tech.module_data(module_data["module_id"])

        tech.authenticated = False

        with pytest.raises(TechError) as exception_info:
            response = await tech.set_const_temp(
                module_data["module_id"],
                module_data["zone_id"],
                module_data["target_temp"],
            )
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_set_zone(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test set_zone method.

        Test that set_zone() returns success.
        This is a fake test, as we can't set the actual temp on demo account,
        so we effecitvely test if we get the demo error response

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)

        authenticated: bool = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated, "Authentication should be successful"

        data = await tech.module_data(module_data["module_id"])

        with pytest.raises(TechError) as exception_info:
            response = await tech.set_zone(
                module_data["module_id"], module_data["zone_id"], True
            )
            assert isinstance(
                response, data
            ), "The data returned should be a dictionary"
            assert "error" in response, "We should get an error key on demo account"
            assert (
                response["error"] == "Demo account."
            ), "We should get an error key on demo account"
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert (
            exception.status == '{"error":"Demo account."}'
        ), "Unexpected error message"

    @pytest.mark.asyncio
    async def test_set_zone_auth_failure(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
        module_data: dict,
    ) -> None:
        """Test set_zone method.

        Test that test_set_zone_auth_failure() raises an exception on auth failure.

        Args:
            client_session (aiohttp.ClientSession): The client session to use for the test.
            valid_credentials (dict): Pytest fixture with valid credentials.
            module_data (dict): Pytest fixture with module data.

        """
        tech: Tech = Tech(client_session)
        tech.user_id = valid_credentials["user_id"]

        await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )

        await tech.module_data(module_data["module_id"])

        tech.authenticated = False

        with pytest.raises(TechError) as exception_info:
            response = await tech.set_zone(
                module_data["module_id"], module_data["zone_id"], True
            )
            _LOGGER.info(response)
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == "Unauthorized", "Unexpected error message"

    @pytest.mark.asyncio
    async def test_set_const_temp_mock(
        self, client_session: aiohttp.ClientSession, mock_set_const_temp_response
    ):
        """Test that set_const_temp() sends correct data and returns the response."""
        module_udid = "123456789"
        zone_id = 1
        target_temp = 22.5

        # Set up the mock post method and the instance
        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_set_const_temp_response
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"
            instance.modules = {
                module_udid: {"zones": {zone_id: {"mode": {"id": 123}}}}
            }

            # Call the method
            result = await instance.set_const_temp(module_udid, zone_id, target_temp)

            # Verify that the mock was called with the expected arguments
            assert mock_post.called
            assert mock_post.call_args[0][0] == "users/user123/modules/123456789/zones"

            # Verify that the mock was called with the expected data
            expected_data = {
                "mode": {
                    "id": 123,
                    "parentId": zone_id,
                    "mode": "constantTemp",
                    "constTempTime": 60,
                    "setTemperature": int(target_temp * 10),
                    "scheduleIndex": 0,
                }
            }
            assert mock_post.called
            assert mock_post.call_args[0][0] == "users/user123/modules/123456789/zones"
            assert (
                mock_post.await_args is not None
                and mock_post.await_args[0][1] is not None
            ), "The argument should not be None"
            assert json.loads(mock_post.call_args[0][1]) == expected_data

            # Verify that the method returns the response
            assert result == mock_set_const_temp_response

    @pytest.mark.asyncio
    async def test_set_zone_mock(
        self, client_session: aiohttp.ClientSession, mock_set_const_temp_response
    ):
        """Test that set_zone() sends correct data and returns the response."""
        module_udid = "123456789"
        zone_id = 1

        # Set up the mock post method and the instance
        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_set_const_temp_response
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"
            instance.modules = {
                module_udid: {"zones": {zone_id: {"mode": {"id": 123}}}}
            }

            # Call the method
            result = await instance.set_zone(module_udid, zone_id, True)

            # Verify that the mock was called with the expected arguments
            assert mock_post.called
            assert mock_post.call_args[0][0] == "users/user123/modules/123456789/zones"

            # Verify that the mock was called with the expected data
            expected_data = {
                "zone": {"id": zone_id, "zoneState": "zoneOn" if True else "zoneOff"}
            }
            assert json.loads(mock_post.call_args[0][1]) == expected_data

            # Verify that the method returns the response
            assert result == mock_set_const_temp_response
