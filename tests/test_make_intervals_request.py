"""
Unit tests for the make_intervals_request function in intervals_mcp_server.server.

These tests focus on error handling, particularly the scenario where the API returns invalid JSON.
Mock classes are used to simulate httpx responses and client behavior.
"""

import asyncio
import logging
import os
import pathlib
import sys
from json import JSONDecodeError

import httpx
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("API_KEY", "test")
os.environ.setdefault("ATHLETE_ID", "i1")

from intervals_mcp_server import server  # pylint: disable=wrong-import-position
from intervals_mcp_server.api import client as api_client  # pylint: disable=wrong-import-position
from intervals_mcp_server.config import Config  # pylint: disable=wrong-import-position


class MockBadJSONResponse:
    """
    Simulates an httpx response object that returns invalid JSON content.
    Used to test error handling for JSONDecodeError in make_intervals_request.
    """

    def __init__(self):
        self.content = b"bad"
        self.status_code = 200

    def raise_for_status(self):
        """Mock raise_for_status that does nothing."""
        return None

    def json(self):
        """Raise JSONDecodeError to simulate invalid JSON."""
        raise JSONDecodeError("Expecting value", "bad", 0)


class MockAsyncClient:
    """
    Simulates an httpx.AsyncClient for use in monkeypatching.
    Always returns a MockBadJSONResponse from get().
    """

    def __init__(self, *_args, **_kwargs):
        # Accept any arguments to match httpx.AsyncClient's interface
        self.is_closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def get(self, _url, **_kwargs):
        """Mock get method that returns MockBadJSONResponse."""
        return MockBadJSONResponse()

    async def request(self, *_args, **_kwargs):
        """Mock request method that returns MockBadJSONResponse."""
        return MockBadJSONResponse()

    async def aclose(self):
        """Simulate closing the AsyncClient."""
        self.is_closed = True


def test_make_intervals_request_bad_json(monkeypatch, caplog):
    """
    Test that make_intervals_request returns an error dict when the response contains invalid JSON.
    Ensures proper logging and error message content.
    """
    monkeypatch.setenv("API_KEY", "test")
    monkeypatch.setenv("ATHLETE_ID", "i1")
    # Reset the singleton so config picks up the monkeypatched env vars
    monkeypatch.setattr("intervals_mcp_server.config._config_instance", None)
    monkeypatch.setattr(server, "httpx_client", MockAsyncClient())
    monkeypatch.setattr(
        api_client,
        "get_config",
        lambda: Config(
            api_key="test",
            athlete_id="i1",
            intervals_api_base_url="https://intervals.icu/api/v1",
            user_agent="test-agent",
        ),
    )

    # Ensure the config singleton has an API key, regardless of test execution order
    from intervals_mcp_server.config import get_config  # pylint: disable=import-outside-toplevel

    monkeypatch.setattr(get_config(), "api_key", "test")

    with caplog.at_level(logging.ERROR):
        result = asyncio.run(server.make_intervals_request("/bad"))

    assert result["error"] is True
    assert "Invalid JSON in response" in result["message"]


async def _no_network():
    raise AssertionError("a request was about to be sent")


@pytest.mark.parametrize(
    "url",
    [
        "/athlete/i1/events/../../../activity/i150000001",  # DELETE would delete an activity
        "/athlete/i1/events/116000003?others=true",  # would also delete the sibling events
        "/activity/../athlete/i1/events?x=/messages",
        "/athlete/i1/events/1 2",
        "",
    ],
)
def test_make_intervals_request_rejects_paths_that_would_reroute(monkeypatch, url):
    """Ids are interpolated into the path: one that reaches another endpoint sends nothing."""
    monkeypatch.setattr(api_client, "_get_httpx_client", _no_network)
    result = asyncio.run(server.make_intervals_request(url, method="DELETE"))
    assert result["error"] is True
    assert "Invalid identifier" in result["message"]


def test_delete_event_cannot_delete_an_activity(monkeypatch):
    """Regression: delete_event("../../../activity/i1") sent DELETE /activity/i1 and answered
    "Successfully deleted"."""
    monkeypatch.setattr(api_client, "_get_httpx_client", _no_network)
    result = asyncio.run(server.delete_event("../../../activity/i150000001", athlete_id="i1"))
    assert result.startswith("Error deleting event: Invalid identifier")


def _authorization(auth):
    """The Authorization header an httpx auth object puts on a request."""
    return next(auth.auth_flow(httpx.Request("GET", "https://intervals.icu"))).headers[
        "Authorization"
    ]


def test_server_api_key_wins_over_a_caller_supplied_key(monkeypatch):
    """Regression: a caller-supplied api_key replaced the server's, so a tool call could write to
    another account; an empty string made the call fail instead of using the server's key."""

    def config(api_key):
        return lambda: Config(
            api_key=api_key,
            athlete_id="i1",
            intervals_api_base_url="https://intervals.icu/api/v1",
            user_agent="test-agent",
        )

    monkeypatch.setattr(api_client, "get_config", config("server-key"))
    for caller_key in ("someone-else", "", None):
        _url, auth, _headers, error = api_client._prepare_request_config("/x", caller_key, "GET")  # pylint: disable=protected-access
        assert error is None
        assert _authorization(auth) == _authorization(httpx.BasicAuth("API_KEY", "server-key"))

    # A server started without API_KEY still accepts the caller's key.
    monkeypatch.setattr(api_client, "get_config", config(""))
    _url, auth, _headers, error = api_client._prepare_request_config("/x", "caller-key", "GET")  # pylint: disable=protected-access
    assert error is None
    assert _authorization(auth) == _authorization(httpx.BasicAuth("API_KEY", "caller-key"))


def test_parse_response_keeps_http_status_for_non_json_error_body():
    """A 503 with an HTML body is an HTTP error (status kept), not "Invalid JSON"."""
    response = httpx.Response(
        503, content=b"<html>down</html>", request=httpx.Request("GET", "https://intervals.icu")
    )
    with pytest.raises(httpx.HTTPStatusError):
        api_client._parse_response(response, "https://intervals.icu")  # pylint: disable=protected-access
