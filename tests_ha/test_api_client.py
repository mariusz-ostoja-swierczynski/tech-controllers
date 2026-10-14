"""Exercise the API client's own transport, and its guards.

Everything else in this suite answers the integration with a stubbed transport,
so the client's HTTP layer -- what it does with a 500 while polling, a 401 on a
token the API no longer accepts, a menu tree this controller does not have --
never runs. These call the client directly, on a session that answers with the
status under test.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from custom_components.tech.tech import Tech, TechError, TechLoginError


@pytest.fixture(autouse=True)
def _client_transport(real_transport: None) -> None:
    """Talk to the client itself here, not to the suite's offline stub."""


class _Answer:
    """A response object the client's ``async with`` can read."""

    def __init__(self, status: int = 200, payload: Any = None, text: str = "") -> None:
        self.status = status
        self._payload = payload
        self._text = text

    async def text(self) -> str:
        """Return the body as text, the way the client reads an error."""
        return self._text or json.dumps(self._payload)

    async def json(self) -> Any:
        """Return the parsed body."""
        return self._payload

    async def __aenter__(self) -> _Answer:
        """Enter the response context."""
        return self

    async def __aexit__(self, *args: Any) -> bool:
        """Leave the response context."""
        return False


class _Session:
    """A client session whose requests answer the way a test asks for."""

    def __init__(self, answer: _Answer, menu_answer: _Answer | None = None) -> None:
        self.answer = answer
        self.menu_answer = menu_answer
        self.calls: list[tuple[str, str]] = []

    def _request(self, method: str, url: str) -> _Answer:
        self.calls.append((method, url))
        if self.menu_answer is not None and "/menu/" in url:
            return self.menu_answer
        return self.answer

    def get(self, url: str, **kwargs: Any) -> _Answer:
        """Answer a GET; the headers and timeout are the client's business."""
        return self._request("GET", url)

    def post(self, url: str, **kwargs: Any) -> _Answer:
        """Answer a POST."""
        return self._request("POST", url)


def _client(
    answer: _Answer,
    *,
    authenticated: bool = True,
    menu_answer: _Answer | None = None,
) -> tuple[Tech, _Session]:
    """Return a client on a session that answers with the given response."""
    session = _Session(answer, menu_answer)
    if authenticated:
        return Tech(session, user_id="42", token="token"), session
    return Tech(session), session


async def test_a_get_that_is_not_ok_carries_its_status() -> None:
    """A failing GET surfaces as TechError with the status, not as a crash."""
    client, _ = _client(_Answer(500, text="boom"))

    with pytest.raises(TechError) as raised:
        await client.get("users/42/modules/abc")

    assert raised.value.status_code == 500
    assert raised.value.status == "boom"


async def test_a_post_that_is_not_ok_carries_its_status() -> None:
    """The write path is read the same way."""
    client, _ = _client(_Answer(503, text="down"))

    with pytest.raises(TechError) as raised:
        await client.post("users/42/modules/abc", json.dumps({"value": 1}))

    assert raised.value.status_code == 503


async def test_logging_in_stores_the_token_and_the_header() -> None:
    """A successful login leaves the client ready for the account's modules."""
    client, _ = _client(
        _Answer(200, {"authenticated": True, "user_id": 240471648, "token": "fresh"}),
        authenticated=False,
    )

    assert await client.authenticate("user", "pass") is True
    assert client.authenticated
    assert client.user_id == "240471648"
    assert client.headers["Authorization"] == "Bearer fresh"


async def test_a_rejected_login_says_so_without_raising() -> None:
    """The API answers a wrong password with 200 and ``authenticated: false``."""
    client, _ = _client(_Answer(200, {"authenticated": False}), authenticated=False)

    assert await client.authenticate("user", "wrong") is False
    assert not client.authenticated


async def test_a_login_that_answers_with_an_error_is_a_login_error() -> None:
    """An error status on the login is reported as a login failure.

    The config flow turns that into "invalid credentials" rather than "cannot
    connect", so it has to keep its own exception.
    """
    client, _ = _client(
        _Answer(401, {"error": {"authenticated": False}}), authenticated=False
    )

    with pytest.raises(TechLoginError):
        await client.authenticate("user", "pass")


async def test_listing_the_modules_reads_the_account() -> None:
    """The module list is what the config flow offers to the user."""
    client, session = _client(_Answer(200, {"data": {"modules": []}}))

    assert await client.list_modules() == {"data": {"modules": []}}
    assert session.calls[-1] == ("GET", "https://emodul.eu/api/v1/users/42/modules")


async def test_an_unsupported_language_falls_back_to_english() -> None:
    """A language the API does not have is asked for as ``en``."""
    client, session = _client(_Answer(200, {"data": {}}))

    await client.get_translations("xx")

    assert session.calls[-1] == ("GET", "https://emodul.eu/api/v1/i18n/en")


async def test_reading_and_writing_before_logging_in_is_refused() -> None:
    """Every call that needs a token refuses without one, and sends nothing."""
    client, session = _client(_Answer(200, {}), authenticated=False)

    calls = (
        client.list_modules,
        lambda: client.get_module_data("abc"),
        lambda: client.get_translations("pl"),
        lambda: client.get_module_menus("abc"),
        lambda: client.get_module_zones("abc"),
        lambda: client.get_module_tiles("abc"),
        lambda: client.get_zone("abc", 1),
        lambda: client.get_tile("abc", 1),
        lambda: client.set_const_temp("abc", 1, 21),
        lambda: client.set_zone("abc", 1, True),
        lambda: client.set_menu_value("abc", "MU", 1, {"value": 1}),
    )

    for call in calls:
        with pytest.raises(TechError):
            await call()

    assert session.calls == []


async def test_a_menu_tree_this_controller_does_not_have_is_skipped() -> None:
    """The four trees are fetched separately; a missing one is not fatal."""
    client, _ = _client(
        _Answer(200, {"tiles": [], "zones": {"elements": []}}),
        menu_answer=_Answer(401, text="not available"),
    )

    data = await client.module_data("abc", force=True)

    assert data["menus"] == {}
    assert data["tiles"] == {}
