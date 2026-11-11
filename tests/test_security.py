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


@pytest.mark.parametrize("body", [b'{"jwt": NaN}', b"[" * 2000 + b"0" + b"]" * 2000])
async def test_nonstandard_or_deep_json_fails_safely(body):
    client, _ = client_with(Response(200, body=body))
    with pytest.raises(EacApiError, match="Invalid portal JSON"):
        await client.login()


@pytest.mark.parametrize(
    "token", ["bad\r\nInjected: value", "bad token", "bad\x00token", "秘密"]
)
async def test_invalid_token_cannot_be_forwarded_as_header(token):
    client, session = client_with(Response(200, {"jwt": token}))
    with pytest.raises(EacAuthError, match="Invalid portal login"):
        await client.get_user_details()
    assert session.request.call_count == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/portal/servicePoints/../login",
        "/api/portal/servicePoints/x?secret=1",
        "//evil.example",
        "/api/admin",
    ],
)
async def test_nonallowlisted_endpoint_rejected_before_network(path):
    client, session = client_with()
    with pytest.raises(EacApiError, match="Unsupported portal endpoint"):
        await client._exchange("GET", path)
    session.request.assert_not_called()


@pytest.mark.parametrize(
    "method,args,data",
    [
        ("get_user_details", (), None),
        ("list_service_points", (), ["PRIVATE_ACCOUNT_DATA"]),
        ("get_meter_configs", ("123",), [{"installDate": "PRIVATE_ACCOUNT_DATA"}]),
    ],
)
async def test_upstream_parse_errors_are_redacted(method, args, data):
    client, _ = client_with(Response(200, {"jwt": "TOKEN"}), Response(200, data))
    with pytest.raises(EacApiError) as error:
        await getattr(client, method)(*args)
    assert "PRIVATE_ACCOUNT_DATA" not in str(error.value)
    assert error.value.__suppress_context__


async def test_bad_reading_number_is_redacted():
    from datetime import UTC, datetime, timedelta

    start = datetime(2026, 1, 1, tzinfo=UTC)
    client, _ = client_with(
        Response(200, {"jwt": "TOKEN"}),
        Response(
            200,
            [
                {
                    "id": "123",
                    "readings": [{"dt": "2026-01-01", "value": "PRIVATE_ACCOUNT_DATA"}],
                }
            ],
        ),
    )
    with pytest.raises(EacApiError, match="Invalid portal readings") as error:
        await client.get_readings("123", start, start + timedelta(days=1))
    assert "PRIVATE_ACCOUNT_DATA" not in str(error.value)


async def test_cancelled_request_releases_transport_lock():
    client, session = client_with()
    entered = asyncio.Event()
    never = asyncio.Event()

    async def exchange(*args, **kwargs):
        entered.set()
        await never.wait()

    with patch.object(client, "_exchange", side_effect=exchange):
        task = asyncio.create_task(client.login())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert not client._request_lock.locked()
    session.request.side_effect = [Response(200, {"jwt": "TOKEN"})]
    await client.login()
