"""Test Tech API.

This is a "live" test using real API and Tech provided demo account
(username: "test", password: "test").

"""

import json
import logging
from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from custom_components.tech.tech import Tech, TechError, TechLoginError

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
        assert exception.status == '{"error":"User has no permission to module"}', (
            "Unexpected error message"
        )

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
        assert isinstance(lang["data"], dict), (
            "The data returned should be a dictionary"
        )

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
        assert isinstance(zones[101], dict), (
            "The zone data returned should be a dictionary"
        )
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
        assert isinstance(tiles[4063], dict), (
            "The tiles data returned should be a dictionary"
        )
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
        assert isinstance(data["zones"], dict), (
            "The zones data returned should be a dictionary"
        )
        assert "tiles" in data, "The module should have key tiles"
        assert isinstance(data["tiles"], dict), (
            "The tiles data returned should be a dictionary"
        )

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
        assert isinstance(zone["zone"], dict), (
            "The zone data returned should be a dictionary"
        )
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
            assert isinstance(response, data), (
                "The data returned should be a dictionary"
            )
            assert "error" in response, "We should get an error key on demo account"
            assert response["error"] == "Demo account.", (
                "We should get an error key on demo account"
            )
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == '{"error":"Demo account."}', (
            "Unexpected error message"
        )

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
            assert isinstance(response, data), (
                "The data returned should be a dictionary"
            )
            assert "error" in response, "We should get an error key on demo account"
            assert response["error"] == "Demo account.", (
                "We should get an error key on demo account"
            )
        exception: TechError = exception_info.value
        assert exception.status_code == 401, "Unexpected status code"
        assert exception.status == '{"error":"Demo account."}', (
            "Unexpected error message"
        )

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

    # ==================== Tests for recuperation/fan control methods ====================

    @pytest.mark.asyncio
    async def test_set_fan_gear_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_fan_gear() sends correct data."""
        module_udid = "123456789"
        tile_id = 100
        gear = 2

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_fan_gear(module_udid, tile_id, gear)

            assert mock_post.called
            assert f"menu/MI/ido/{tile_id}" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"gear": gear}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_fan_gear_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_fan_gear() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_fan_gear("module", 100, 2)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_recuperation_speed_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_recuperation_speed() sends correct data for speed levels 1-3."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            # Test speed level 1
            result = await instance.set_recuperation_speed(module_udid, 1)
            assert mock_post.called
            assert "menu/MI/ido/1737" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": 120}

            # Test speed level 2
            await instance.set_recuperation_speed(module_udid, 2)
            assert "menu/MI/ido/1748" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": 280}

            # Test speed level 3
            await instance.set_recuperation_speed(module_udid, 3)
            assert "menu/MI/ido/1739" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": 390}

    @pytest.mark.asyncio
    async def test_set_recuperation_speed_off(self, client_session: aiohttp.ClientSession):
        """Test that set_recuperation_speed(0) turns off the recuperation."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            await instance.set_recuperation_speed(module_udid, 0)
            assert json.loads(mock_post.call_args[0][1]) == {"value": 0}

    @pytest.mark.asyncio
    async def test_set_recuperation_speed_invalid(self, client_session: aiohttp.ClientSession):
        """Test that set_recuperation_speed() raises error for invalid speed level."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_recuperation_speed("module", 5)
        assert exception_info.value.status_code == 400
        assert "Invalid speed level" in exception_info.value.status

    @pytest.mark.asyncio
    async def test_set_recuperation_speed_with_configured_values(
        self, client_session: aiohttp.ClientSession
    ):
        """Test set_recuperation_speed() with custom configured values."""
        module_udid = "123456789"
        configured_values = {1: 100, 2: 200, 3: 300}

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            await instance.set_recuperation_speed(module_udid, 2, configured_values)
            assert json.loads(mock_post.call_args[0][1]) == {"value": 200}

    @pytest.mark.asyncio
    async def test_set_party_mode_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_party_mode() sends correct data."""
        module_udid = "123456789"
        duration = 60

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_party_mode(module_udid, duration)

            assert mock_post.called
            assert "menu/MU/ido/1447" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": duration}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_party_mode_invalid_duration(self, client_session: aiohttp.ClientSession):
        """Test that set_party_mode() raises error for invalid duration."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        # Too short
        with pytest.raises(TechError) as exception_info:
            await instance.set_party_mode("module", 10)
        assert exception_info.value.status_code == 400

        # Too long
        with pytest.raises(TechError) as exception_info:
            await instance.set_party_mode("module", 800)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_fan_mode_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_fan_mode() sends correct data."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            for mode in range(4):
                await instance.set_fan_mode(module_udid, mode)
                assert "menu/MU/ido/1966" in mock_post.call_args[0][0]
                assert json.loads(mock_post.call_args[0][1]) == {"value": mode}

    @pytest.mark.asyncio
    async def test_set_fan_mode_invalid(self, client_session: aiohttp.ClientSession):
        """Test that set_fan_mode() raises error for invalid mode."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_fan_mode("module", 5)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_filter_alarm_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_filter_alarm() sends correct data."""
        module_udid = "123456789"
        days = 90

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_filter_alarm(module_udid, days)

            assert mock_post.called
            assert "menu/MI/ido/2080" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": days}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_filter_alarm_invalid_days(self, client_session: aiohttp.ClientSession):
        """Test that set_filter_alarm() raises error for invalid days."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        # Too few days
        with pytest.raises(TechError) as exception_info:
            await instance.set_filter_alarm("module", 20)
        assert exception_info.value.status_code == 400

        # Too many days
        with pytest.raises(TechError) as exception_info:
            await instance.set_filter_alarm("module", 150)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_get_filter_usage_mock(self, client_session: aiohttp.ClientSession):
        """Test that get_filter_usage() returns filter usage data."""
        module_udid = "123456789"

        with patch.object(Tech, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"value": 45}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.get_filter_usage(module_udid)

            assert mock_get.called
            assert "menu/MI/ido/2081" in mock_get.call_args[0][0]
            assert result == {"value": 45}

    @pytest.mark.asyncio
    async def test_get_filter_usage_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that get_filter_usage() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.get_filter_usage("module")
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_update_filter_data_mock(self, client_session: aiohttp.ClientSession):
        """Test that update_filter_data() sends correct request."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.update_filter_data(module_udid)

            assert mock_post.called
            assert "update/data/parents" in mock_post.call_args[0][0]
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_ventilation_room_parameter_mock(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_room_parameter() sends correct data."""
        module_udid = "123456789"
        percent = 50

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_ventilation_room_parameter(module_udid, percent)

            assert mock_post.called
            assert "menu/MI/ido/2170" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": percent}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_ventilation_room_parameter_invalid(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_room_parameter() raises error for invalid percent."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_ventilation_room_parameter("module", 5)
        assert exception_info.value.status_code == 400

        with pytest.raises(TechError) as exception_info:
            await instance.set_ventilation_room_parameter("module", 95)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_ventilation_bathroom_parameter_mock(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_bathroom_parameter() sends correct data."""
        module_udid = "123456789"
        percent = 70

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_ventilation_bathroom_parameter(module_udid, percent)

            assert mock_post.called
            assert "menu/MI/ido/2171" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": percent}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_co2_threshold_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_co2_threshold() sends correct data."""
        module_udid = "123456789"
        ppm = 800

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_co2_threshold(module_udid, ppm)

            assert mock_post.called
            assert "menu/MI/ido/2115" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": ppm}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_co2_threshold_invalid(self, client_session: aiohttp.ClientSession):
        """Test that set_co2_threshold() raises error for invalid ppm."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_co2_threshold("module", 300)
        assert exception_info.value.status_code == 400

        with pytest.raises(TechError) as exception_info:
            await instance.set_co2_threshold("module", 2500)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_hysteresis_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_hysteresis() sends correct data."""
        module_udid = "123456789"
        percent = 7

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.set_hysteresis(module_udid, percent)

            assert mock_post.called
            assert "menu/MI/ido/2239" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": percent}
            assert result == {"status": "success"}

    @pytest.mark.asyncio
    async def test_set_hysteresis_invalid(self, client_session: aiohttp.ClientSession):
        """Test that set_hysteresis() raises error for invalid percent."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_hysteresis("module", 3)
        assert exception_info.value.status_code == 400

        with pytest.raises(TechError) as exception_info:
            await instance.set_hysteresis("module", 15)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_flow_balancing_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_flow_balancing() sends correct data."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            # Test enabling
            await instance.set_flow_balancing(module_udid, True)
            assert "menu/MI/ido/1733" in mock_post.call_args[0][0]
            assert json.loads(mock_post.call_args[0][1]) == {"value": 1}

            # Test disabling
            await instance.set_flow_balancing(module_udid, False)
            assert json.loads(mock_post.call_args[0][1]) == {"value": 0}

    @pytest.mark.asyncio
    async def test_get_current_gear_mock(self, client_session: aiohttp.ClientSession):
        """Test that get_current_gear() returns current gear value."""
        module_udid = "123456789"

        with patch.object(Tech, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {"value": 2}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.get_current_gear(module_udid)

            assert mock_get.called
            assert "menu/MU/ido/1833" in mock_get.call_args[0][0]
            assert result == 2

    @pytest.mark.asyncio
    async def test_get_current_gear_default(self, client_session: aiohttp.ClientSession):
        """Test that get_current_gear() returns 0 when no value in response."""
        module_udid = "123456789"

        with patch.object(Tech, "get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = {}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            result = await instance.get_current_gear(module_udid)
            assert result == 0

    @pytest.mark.asyncio
    async def test_get_current_gear_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that get_current_gear() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.get_current_gear("module")
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_gear_direct_mock(self, client_session: aiohttp.ClientSession):
        """Test that set_gear_direct() sends correct data."""
        module_udid = "123456789"

        with patch.object(Tech, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = {"status": "success"}
            instance = Tech(client_session)
            instance.authenticated = True
            instance.user_id = "user123"

            for gear in range(4):
                await instance.set_gear_direct(module_udid, gear)
                assert "menu/MU/ido/1833" in mock_post.call_args[0][0]
                assert json.loads(mock_post.call_args[0][1]) == {"value": gear}

    @pytest.mark.asyncio
    async def test_set_gear_direct_invalid(self, client_session: aiohttp.ClientSession):
        """Test that set_gear_direct() raises error for invalid gear value."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_gear_direct("module", 5)
        assert exception_info.value.status_code == 400
        assert "Invalid gear value" in exception_info.value.status

    @pytest.mark.asyncio
    async def test_set_gear_direct_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_gear_direct() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_gear_direct("module", 2)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_get_translations_unsupported_language(
        self,
        client_session: aiohttp.ClientSession,
        valid_credentials: dict,
    ):
        """Test that get_translations() falls back to 'en' for unsupported language."""
        tech: Tech = Tech(client_session)

        authenticated = await tech.authenticate(
            valid_credentials["username"], valid_credentials["password"]
        )
        assert authenticated

        # Request unsupported language - should fall back to 'en'
        lang = await tech.get_translations("xyz")
        assert isinstance(lang, dict)
        assert lang["status"] == "success"

    # ==================== Auth failure tests for remaining methods ====================

    @pytest.mark.asyncio
    async def test_set_recuperation_speed_auth_failure(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_recuperation_speed() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_recuperation_speed("module", 1)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_party_mode_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_party_mode() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_party_mode("module", 60)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_fan_mode_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_fan_mode() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_fan_mode("module", 1)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_filter_alarm_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_filter_alarm() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_filter_alarm("module", 90)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_update_filter_data_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that update_filter_data() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.update_filter_data("module")
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_ventilation_room_parameter_auth_failure(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_room_parameter() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_ventilation_room_parameter("module", 50)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_ventilation_bathroom_parameter_auth_failure(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_bathroom_parameter() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_ventilation_bathroom_parameter("module", 50)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_ventilation_bathroom_parameter_invalid(
        self, client_session: aiohttp.ClientSession
    ):
        """Test that set_ventilation_bathroom_parameter() raises error for invalid percent."""
        instance = Tech(client_session)
        instance.authenticated = True
        instance.user_id = "user123"

        with pytest.raises(TechError) as exception_info:
            await instance.set_ventilation_bathroom_parameter("module", 5)
        assert exception_info.value.status_code == 400

    @pytest.mark.asyncio
    async def test_set_co2_threshold_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_co2_threshold() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_co2_threshold("module", 800)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_hysteresis_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_hysteresis() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_hysteresis("module", 7)
        assert exception_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_set_flow_balancing_auth_failure(self, client_session: aiohttp.ClientSession):
        """Test that set_flow_balancing() raises exception when not authenticated."""
        instance = Tech(client_session)
        instance.authenticated = False

        with pytest.raises(TechError) as exception_info:
            await instance.set_flow_balancing("module", True)
        assert exception_info.value.status_code == 401
