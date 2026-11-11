"""Exercise the real adapter against controlled HTTP responses, without secrets."""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest
from eac_dso_portal import EacApiError, EacAuthError
from eac_dso_portal.exceptions import EacRateLimitError

from custom_components.eac_cyprus.client import (
    MAX_RESPONSE_BYTES,
    REQUEST_TIMEOUT,
    EacClient,
    validate_base_url,
)
from custom_components.eac_cyprus.const import DEFAULT_BASE_URL


class Response:
    def __init__(self, status, data=None, *, body=None, headers=None):
        self.status = status
        self.body = json.dumps(data).encode() if body is None else body
        self.headers = headers or {}
        self.content = self
        self.closed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.closed = True

    async def iter_chunked(self, size):
        for start in range(0, len(self.body), size):
            yield self.body[start : start + size]


def client_with(*responses):
    session = MagicMock()
    session.request.side_effect = responses
    return EacClient("test@example.com", "PRIVATE_PASSWORD", session=session), session


@pytest.mark.parametrize(
    "url",
    [
        "http://meterreading-dso.eac.com.cy",
        "https://evil.example",
        "https://meterreading-dso.eac.com.cy.evil.example",
        "https://meterreading-dso.eac.com.cy@evil.example",
        "https://meterreading-dso.eac.com.cy:443",
        "http://127.0.0.1",
        "https://meterreading-dso.eac.com.cy/path",
    ],
)
def test_credentials_cannot_be_redirected_by_config(url):
    with pytest.raises(ValueError):
        validate_base_url(url)


async def test_transport_sets_timeout_tls_and_no_redirects():
    client, session = client_with(
        Response(200, {"jwt": "TOKEN"}), Response(200, {"name": "Test"})
    )
    await client.get_user_details()
    for call in session.request.call_args_list:
        assert call.args[1].startswith(DEFAULT_BASE_URL + "/api/portal/")
        assert call.kwargs["allow_redirects"] is False
        assert call.kwargs["timeout"] == REQUEST_TIMEOUT
        assert call.kwargs.get("ssl") is not False
    assert session.request.call_args_list[0].kwargs["headers"] == {}
    assert session.request.call_args_list[1].kwargs["headers"] == {
        "Authorization": "Bearer TOKEN"
    }


@pytest.mark.parametrize("status", [301, 302, 307, 308, 500])
async def test_login_redirect_and_error_bodies_are_not_exposed(status):
    client, session = client_with(
        Response(status, body=b"PRIVATE_PASSWORD ACCOUNT DETAILS")
    )
    with pytest.raises(EacApiError) as err:
        await client.login()
    assert "PRIVATE" not in str(err.value)
    assert "ACCOUNT" not in str(err.value)
    assert session.request.call_count == 1


async def test_response_size_limit():
    client, _ = client_with(Response(200, body=b" " * (MAX_RESPONSE_BYTES + 1)))
    with pytest.raises(EacApiError, match="size limit"):
        await client.login()


async def test_invalid_json_is_redacted():
    client, _ = client_with(Response(200, body=b"PRIVATE_PASSWORD invalid JSON"))
    with pytest.raises(EacApiError) as err:
        await client.login()
    assert "PRIVATE_PASSWORD" not in str(err.value)


async def test_401_refresh_is_bounded_and_releases_response():
    rejected = Response(401)
    client, session = client_with(
        Response(200, {"jwt": "old"}),
        rejected,
        Response(200, {"jwt": "new"}),
        Response(401),
    )
    with pytest.raises(EacAuthError):
        await client.get_user_details()
    assert session.request.call_count == 4
    assert rejected.closed


async def test_concurrent_requests_share_one_login():
    client, session = client_with(
        Response(200, {"jwt": "token"}),
        Response(200, {"name": "Test"}),
        Response(200, {"name": "Test"}),
    )
    await asyncio.gather(client.get_user_details(), client.get_user_details())
    assert session.request.call_count == 3


async def test_rate_limit_cooldown_avoids_repeated_requests():
    client, session = client_with(Response(429, headers={"Retry-After": "120"}))
    with patch("custom_components.eac_cyprus.client.time.monotonic", return_value=100):
        for _ in range(2):
            with pytest.raises(EacRateLimitError):
                await client.login()
    assert session.request.call_count == 1
    assert client._retry_after == 220


async def test_network_timeout_propagates_without_response_data():
    client, session = client_with()
    session.request.side_effect = TimeoutError()
    with pytest.raises(TimeoutError):
        await client.login()


@pytest.mark.parametrize("days", [0, -1, 15])
async def test_invalid_chunk_size_cannot_loop_forever(days):
    client, session = client_with()
    with pytest.raises(ValueError):
        await client.get_readings("1", None, None, chunk_days=days)
    session.request.assert_not_called()
