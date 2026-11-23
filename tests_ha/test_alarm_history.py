"""Validate synthetic archive rows and the client's bounded, read-only transport."""

from __future__ import annotations

from datetime import date
import json
from typing import Any

import pytest

from custom_components.tech.alarm_history import DISPLAY_LIMIT, history_snapshot
from custom_components.tech.const import ALARM_HISTORY_MAX_BYTES, ALARM_HISTORY_TIMEOUT
from custom_components.tech.tech import Tech, TechError


def _row(**overrides: Any) -> dict[str, Any]:
    """Return a synthetic row, never a recording from an account."""
    result = {
        "id": 7,
        "alarmType": "alarm",
        "startAlarm": "2028-02-28T10:00:00+00:00",
        "clearAlarm": None,
        "txtId": 120,
        "value": 0,
        "unit": "°C",
    }
    result.update(overrides)
    return result


def test_empty_is_a_successful_archive_and_not_a_failed_read() -> None:
    """A valid empty array has a known count and no invented latest alarm."""
    assert history_snapshot([]) == {
        "status": "empty",
        "returned_count": 0,
        "displayed_count": 0,
        "truncated": False,
        "chronology_complete": True,
        "ordering": "source",
        "latest": None,
        "events": [],
    }


def test_offsets_determine_latest_and_reused_source_ids_keep_each_event() -> None:
    """Sort actual instants while preserving raw times and every repeated id."""
    rows = [
        _row(startAlarm="2028-02-28T04:00:00+03:00", value="first"),
        _row(
            startAlarm="2028-02-28T02:00:00+00:00",
            clearAlarm="2028-02-28T06:00:00+03:00",
            value="latest",
        ),
        _row(startAlarm="2028-02-28T03:00:00+02:00", value="equal instant"),
    ]
    snapshot = history_snapshot(rows)

    assert snapshot["status"] == "ready"
    assert snapshot["returned_count"] == snapshot["displayed_count"] == 3
    assert snapshot["chronology_complete"] is True
    assert snapshot["ordering"] == "start_descending"
    assert [event["value"] for event in snapshot["events"]] == [
        "latest",
        "first",
        "equal instant",
    ]
    assert snapshot["latest"]["start"] == rows[1]["startAlarm"]
    assert snapshot["latest"]["clear"] == rows[1]["clearAlarm"]
    assert "id" not in snapshot["latest"]
    assert rows[1]["id"] == 7, "normalizing does not mutate the source"


def test_display_is_bounded_and_latest_can_arrive_after_the_display_limit() -> None:
    """The endpoint's source order is not assumed to be chronological."""
    rows = [
        _row(startAlarm=f"2028-02-{day:02d}T10:00:00+00:00", value=day)
        for day in range(1, DISPLAY_LIMIT + 3)
    ]
    snapshot = history_snapshot(rows)

    assert snapshot["returned_count"] == DISPLAY_LIMIT + 2
    assert snapshot["displayed_count"] == DISPLAY_LIMIT
    assert len(snapshot["events"]) == DISPLAY_LIMIT
    assert snapshot["truncated"] is True
    assert snapshot["latest"]["value"] == DISPLAY_LIMIT + 2
    assert [event["value"] for event in snapshot["events"]] == list(
        range(DISPLAY_LIMIT + 2, 2, -1)
    )


@pytest.mark.parametrize(
    "uncertain", ["2028-02-28 10:00:00", "unknown time", "99999-01-01"]
)
def test_one_uncertain_timestamp_preserves_source_order_without_claiming_latest(
    uncertain: str,
) -> None:
    """Even uncertainty outside the displayed prefix prevents a latest claim."""
    rows = [_row(value=index) for index in range(DISPLAY_LIMIT + 1)]
    rows[-1]["startAlarm"] = uncertain
    snapshot = history_snapshot(rows)

    assert snapshot["ordering"] == "source"
    assert snapshot["chronology_complete"] is False
    assert snapshot["latest"] is None
    assert [event["value"] for event in snapshot["events"]] == list(
        range(DISPLAY_LIMIT)
    )


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": []}, {"error": "unavailable"}, "[]", 0, [None], [[]]],
)
def test_envelopes_errors_and_non_rows_do_not_masquerade_as_empty(payload: Any) -> None:
    """Only the endpoint's array response represents a successful read."""
    with pytest.raises(TypeError):
        history_snapshot(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("alarmType", None),
        ("alarmType", ""),
        ("alarmType", "x" * 65),
        ("startAlarm", None),
        ("startAlarm", " "),
        ("startAlarm", "x" * 129),
        ("clearAlarm", 3),
        ("clearAlarm", "x" * 129),
        ("txtId", True),
        ("txtId", -1),
        ("txtId", 2**63),
        ("txtId", "120"),
        ("value", True),
        ("value", 2**65),
        ("value", float("nan")),
        ("value", float("inf")),
        ("value", "x" * 257),
        ("value", {}),
        ("unit", "x" * 65),
        ("unit", []),
    ],
)
def test_invalid_rows_in_the_undisplayed_tail_reject_the_entire_response(
    field: str, value: Any
) -> None:
    """A display cap is not permission to skip validating later rows."""
    rows = [_row() for _ in range(DISPLAY_LIMIT)]
    rows.append(_row(**{field: value}))
    with pytest.raises(ValueError):
        history_snapshot(rows)


@pytest.mark.parametrize("value", [None, "", "text", 0, -1, 1.5])
def test_display_scalars_preserve_zero_none_and_numeric_units(value: Any) -> None:
    """Bounded scalar values are displayed without unit or value conversion."""
    event = history_snapshot([_row(value=value, unit=value)])["events"][0]
    assert event["value"] == value
    assert event["unit"] == value


def test_new_alarm_categories_are_preserved_without_a_current_alarm_claim() -> None:
    """The archive may acquire a category the integration has never seen."""
    event = history_snapshot([_row(alarmType="future_kind")])["latest"]
    assert event["alarm_type"] == "future_kind"


@pytest.mark.parametrize("text_id", [0, 2**63 - 1])
def test_text_identifiers_accept_the_valid_boundary_values(text_id: int) -> None:
    """Both the missing-title id and the largest accepted id survive parsing."""
    assert history_snapshot([_row(txtId=text_id)])["latest"]["txt_id"] == text_id


class _Body:
    """Model a chunked response whose reads can be shorter than requested."""

    def __init__(self, body: bytes, chunk_size: int = 65536) -> None:
        self.body = body
        self.chunk_size = chunk_size
        self.offset = 0
        self.read_sizes: list[int] = []

    async def read(self, size: int) -> bytes:
        """Return at most one chunk and record the client's actual byte budget."""
        self.read_sizes.append(size)
        chunk = self.body[self.offset : self.offset + min(size, self.chunk_size)]
        self.offset += len(chunk)
        return chunk


class _Response:
    """A response the real Tech transport can consume without any sockets."""

    def __init__(
        self, body: bytes, *, status: int = 200, chunk_size: int = 65536
    ) -> None:
        self.status = status
        self.content = _Body(body, chunk_size)
        self.json_reads = 0
        self.text_reads = 0

    async def __aenter__(self) -> _Response:
        return self

    async def __aexit__(self, *args: Any) -> bool:
        return False

    async def json(self) -> Any:
        self.json_reads += 1
        return json.loads(self.content.body)

    async def text(self) -> str:
        self.text_reads += 1
        return self.content.body.decode()


class _Session:
    """Capture GET requests; attempting any write immediately fails a test."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _Response:
        self.calls.append((url, kwargs))
        return self.response

    def post(self, *args: Any, **kwargs: Any) -> None:
        raise AssertionError("An archive read must never write to the controller")


def _client(
    response: _Response, *, authenticated: bool = True
) -> tuple[Tech, _Session]:
    session = _Session(response)
    return (
        Tech(
            session,
            user_id="synthetic/account" if authenticated else None,
            token="synthetic-token" if authenticated else None,
            base_url="https://synthetic.invalid/",
        ),
        session,
    )


async def test_archive_uses_one_fixed_get_with_encoded_ids_and_explicit_dates() -> None:
    """The read shares Tech's authenticated session and never assembles a query."""
    response = _Response(json.dumps([_row()]).encode(), chunk_size=3)
    client, session = _client(response)

    result = await client.get_module_alarm_history(
        "synthetic/module?query", date(2027, 3, 1), date(2028, 2, 29)
    )

    assert result == [_row()]
    assert len(session.calls) == 1
    url, kwargs = session.calls[0]
    assert url == (
        "https://synthetic.invalid/users/synthetic%2Faccount/"
        "modules/synthetic%2Fmodule%3Fquery/alarm_history/"
        "from/2027-03-01/to/2028-02-29/type/all"
    )
    assert kwargs["timeout"].total == ALARM_HISTORY_TIMEOUT
    assert kwargs["headers"]["Authorization"] == "Bearer synthetic-token"
    assert response.content.offset == len(response.content.body)
    assert response.json_reads == response.text_reads == 0


async def test_an_unauthenticated_archive_read_sends_nothing() -> None:
    """Refuse a read before login without opening a request."""
    client, session = _client(_Response(b"[]"), authenticated=False)
    with pytest.raises(TechError) as raised:
        await client.get_module_alarm_history(
            "synthetic", date(2028, 1, 1), date(2028, 2, 1)
        )
    assert raised.value.status_code == 401
    assert session.calls == []


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
async def test_http_errors_keep_status_without_reading_or_logging_response_bodies(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    """A rejected optional endpoint exposes only its status code."""
    response = _Response(b"synthetic-private-response-fragment", status=status)
    client, _ = _client(response)
    with pytest.raises(TechError) as raised:
        await client.get_module_alarm_history(
            "synthetic", date(2028, 1, 1), date(2028, 2, 1)
        )
    assert raised.value.status_code == status
    assert response.content.offset == response.json_reads == response.text_reads == 0
    assert "synthetic-private-response-fragment" not in caplog.text
    assert "synthetic-private-response-fragment" not in str(raised.value)


async def test_a_body_exactly_at_the_limit_is_read_to_eof() -> None:
    """A legal body at the boundary remains distinct from an oversized body."""
    response = _Response(b"[]" + b" " * (ALARM_HISTORY_MAX_BYTES - 2), chunk_size=511)
    client, _ = _client(response)
    assert (
        await client.get_module_alarm_history(
            "synthetic", date(2028, 1, 1), date(2028, 2, 1)
        )
        == []
    )
    assert response.content.offset == ALARM_HISTORY_MAX_BYTES


async def test_chunked_body_overflow_stops_after_one_byte_beyond_the_limit() -> None:
    """Neither missing Content-Length nor short reads bypass the byte budget."""
    response = _Response(b" " * (ALARM_HISTORY_MAX_BYTES + 200000), chunk_size=511)
    client, _ = _client(response)
    with pytest.raises(ValueError, match="byte limit"):
        await client.get_module_alarm_history(
            "synthetic", date(2028, 1, 1), date(2028, 2, 1)
        )
    assert response.content.offset == ALARM_HISTORY_MAX_BYTES + 1
    assert response.json_reads == response.text_reads == 0
    assert all(0 < size <= 65536 for size in response.content.read_sizes)


@pytest.mark.parametrize("body", [b"", b"<html>failure</html>", b"[", b"\xff"])
async def test_non_json_and_invalid_encoding_are_failed_reads(body: bytes) -> None:
    """An unparseable body never becomes an apparently empty history."""
    client, _ = _client(_Response(body, chunk_size=1))
    with pytest.raises(ValueError):
        await client.get_module_alarm_history(
            "synthetic", date(2028, 1, 1), date(2028, 2, 1)
        )
