"""Constrained transport for the pinned upstream portal parser.

Only this adapter is used by the integration. No credentials or response bodies
are included in exceptions. Requests remain serial and never follow redirects.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import aiohttp
from eac_dso_portal import EacApiError, EacAuthError
from eac_dso_portal import EacClient as UpstreamClient
from eac_dso_portal.exceptions import EacRateLimitError

from .const import DEFAULT_BASE_URL

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30, connect=10, sock_read=20)


def validate_base_url(value: str) -> str:
    """Prevent sending the portal password to a custom HTTP server or origin."""
    if value.rstrip("/") != DEFAULT_BASE_URL:
        raise ValueError("Only the official HTTPS EAC portal is supported")
    return DEFAULT_BASE_URL


class EacClient(UpstreamClient):
    """Keep upstream models/endpoints, harden all network and login operations."""

    def __init__(
        self, email: str, password: str, *, session, base_url=DEFAULT_BASE_URL
    ):
        super().__init__(
            email, password, session=session, base_url=validate_base_url(base_url)
        )
        self._request_lock = asyncio.Lock()
        self._retry_after = 0.0

    async def _exchange(
        self,
        method: str,
        path: str,
        *,
        authenticated=False,
        json_body=None,
        params=None,
    ):
        if time.monotonic() < self._retry_after:
            raise EacRateLimitError(429, "Portal rate limit; try later")
        headers = {"Authorization": f"Bearer {self._jwt}"} if authenticated else {}
        async with self._session.request(
            method,
            f"{self._base}{path}",
            json=json_body,
            params=params,
            headers=headers,
            allow_redirects=False,
            timeout=REQUEST_TIMEOUT,
        ) as response:
            status = response.status
            if status == 429:
                delay = 60.0
                retry = response.headers.get("Retry-After", "")
                try:
                    delay = float(retry)
                except ValueError:
                    try:
                        delay = (
                            parsedate_to_datetime(retry) - datetime.now(UTC)
                        ).total_seconds()
                    except (ValueError, TypeError, OverflowError):
                        delay = 60.0
                # NaN must not silently disable cooldown.
                delay = delay if math.isfinite(delay) else 60.0
                self._retry_after = time.monotonic() + max(60.0, min(delay, 86400.0))
                raise EacRateLimitError(429, "Portal rate limit; try later")
            if status != 200:
                # Do not read or log an error body (it can contain account data).
                return status, None
            body = bytearray()
            async for chunk in response.content.iter_chunked(65536):
                body.extend(chunk)
                if len(body) > MAX_RESPONSE_BYTES:
                    raise EacApiError(200, "Portal response exceeds size limit")
            try:
                return status, json.loads(body)
            except (ValueError, UnicodeError):
                raise EacApiError(200, "Invalid portal JSON response") from None

    async def _login_unlocked(self):
        status, data = await self._exchange(
            "POST",
            "/api/portal/login",
            json_body={
                "email": self._email,
                "password": self._password,
            },
        )
        if status in (401, 403):
            self._jwt = None
            raise EacAuthError("Portal rejected credentials")
        if status != 200:
            raise EacApiError(status, "Portal login failed")
        token = data.get("jwt") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16384:
            raise EacAuthError("Invalid portal login response")
        self._jwt = token

    async def login(self):
        async with self._request_lock:
            await self._login_unlocked()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params=None,
        _retried=False,
    ):
        async with self._request_lock:
            if self._jwt is None:
                await self._login_unlocked()
            for attempt in range(2):
                status, data = await self._exchange(
                    method,
                    path,
                    authenticated=True,
                    json_body=json_body,
                    params=params,
                )
                if status == 200:
                    return data
                if status == 401 and attempt == 0:
                    self._jwt = None
                    await self._login_unlocked()
                    continue
                if status in (401, 403):
                    self._jwt = None
                    raise EacAuthError("Portal authorization failed")
                raise EacApiError(status, "Portal request failed")
        raise EacAuthError("Portal authorization failed")

    async def get_readings(self, sp_id, start, end, mc_id=None, chunk_days=14):
        if not 1 <= chunk_days <= 14:
            raise ValueError("chunk_days must be between 1 and 14")
        return await super().get_readings(sp_id, start, end, mc_id, chunk_days)
