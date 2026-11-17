"""Regression tests for safe TECH API error diagnostics."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.tech.tech import (
    Tech,
    TechError,
    _safe_api_endpoint,
    _safe_response_kind,
)


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("authentication", "authentication"),
        ("i18n/en", "i18n/{language}"),
        ("users/123/modules", "users/{user_id}/modules"),
        (
            "users/123/modules/secret-module",
            "users/{user_id}/modules/{module_id}",
        ),
        (
            "users/123/modules/secret-module/zones",
            "users/{user_id}/modules/{module_id}/zones",
        ),
        (
            "users/123/modules/secret-module/menu/MS/0:topsecretpin",
            "users/{user_id}/modules/{module_id}/menu/MS/{item}",
        ),
        (
            "users/123/modules/secret-module/menu/MS/ido/45",
            "users/{user_id}/modules/{module_id}/menu/MS/ido/{item_id}",
        ),
        ("users/123/modules?token=topsecret", "users/{user_id}/modules"),
        ("unrecognized/topsecret", "<unknown endpoint>"),
    ],
)
def test_safe_api_endpoint(path: str, expected: str) -> None:
    """Only route templates, never user-supplied identifiers, are logged."""
    assert _safe_api_endpoint(path) == expected


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", "empty response"),
        ("<html>topsecret</html>", "non-JSON response"),
        ('{"error":"topsecret"}', "JSON error response"),
        ('{"message":"topsecret"}', "JSON response"),
        ('["topsecret"]', "JSON response"),
    ],
)
def test_safe_response_kind(body: str, expected: str) -> None:
    """Response content is classified but never included in the description."""
    assert _safe_response_kind(body) == expected
    assert "topsecret" not in _safe_response_kind(body)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
@pytest.mark.parametrize(
    ("path", "body", "kind"),
    [
        (
            "users/secret-user/modules/secret-module/menu/MS/0:secret-pin",
            '{"error":"secret-token"}',
            "JSON error response",
        ),
        (
            "users/secret-user/modules/secret-module",
            "<html>secret-token</html>",
            "non-JSON response",
        ),
    ],
)
async def test_http_error_logging_redacts_and_preserves_exception(
    method: str, path: str, body: str, kind: str, caplog: pytest.LogCaptureFixture
) -> None:
    """GET and POST include safe context without changing the TechError payload."""
    response = MagicMock()
    response.status = 400
    response.text = AsyncMock(return_value=body)
    session = MagicMock()
    request = getattr(session, method)
    request.return_value.__aenter__.return_value = response
    client = Tech(session, user_id="secret-user", token="secret-token")

    with caplog.at_level(logging.DEBUG, logger="custom_components.tech.tech"):
        with pytest.raises(TechError) as exc:
            if method == "get":
                await client.get(path)
            else:
                await client.post(path, '{"pin":"secret-pin"}')

    assert exc.value.status_code == 400
    assert exc.value.status == body
    response.text.assert_awaited_once()
    messages = "\n".join(record.getMessage() for record in caplog.records)
    assert f"Tech API {method.upper()}" in messages
    assert "HTTP 400" in messages
    assert kind in messages
    assert "secret-user" not in messages
    assert "secret-module" not in messages
    assert "secret-pin" not in messages
    assert "secret-token" not in messages
    assert body not in messages


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["get", "post"])
async def test_successful_request_unchanged(method: str) -> None:
    """Successful GET and POST still parse and return JSON."""
    response = MagicMock()
    response.status = 200
    response.json = AsyncMock(return_value={"status": "success"})
    session = MagicMock()
    getattr(session, method).return_value.__aenter__.return_value = response
    client = Tech(session)

    result = (
        await client.get("authentication")
        if method == "get"
        else await client.post("authentication", "{}")
    )
    assert result == {"status": "success"}
    response.json.assert_awaited_once()
