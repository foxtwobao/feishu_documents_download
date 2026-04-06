from __future__ import annotations

import httpx
import pytest

from larksync.config import RetrySettings
from larksync.core.api_client import FeishuAPIError
from larksync.web.sync_service import UserAPIClient


class _StubHTTPClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def request(self, method, url, params=None, json=None, data=None, headers=None, follow_redirects=True, timeout=None):
        auth = (headers or {}).get("Authorization", "")
        self.calls.append(auth)
        return self._responses.pop(0)


def _response(status_code: int, payload: dict) -> httpx.Response:
    return httpx.Response(
        status_code,
        json=payload,
        request=httpx.Request("GET", "https://open.feishu.cn/open-apis/drive/v1/files"),
    )


def test_user_api_client_refreshes_and_retries_on_auth_expiry():
    refreshed_tokens: list[str] = []

    def refresh_callback() -> str | None:
        refreshed_tokens.append("new-token")
        return "new-token"

    client = UserAPIClient(
        user_access_token="expired-token",
        retry=RetrySettings(max_attempts=1),
        refresh_callback=refresh_callback,
    )
    client._client = _StubHTTPClient(
        [
            _response(401, {"msg": "Authentication token expired. Please request a new one."}),
            _response(200, {"data": {"ok": True}}),
        ]
    )

    payload = client.get("/open-apis/drive/v1/files")

    assert payload == {"data": {"ok": True}}
    assert refreshed_tokens == ["new-token"]
    assert client._client.calls == ["Bearer expired-token", "Bearer new-token"]


def test_user_api_client_raises_when_refresh_cannot_recover_auth():
    client = UserAPIClient(
        user_access_token="expired-token",
        retry=RetrySettings(max_attempts=1),
        refresh_callback=lambda: None,
    )
    client._client = _StubHTTPClient(
        [_response(401, {"msg": "Authentication token expired. Please request a new one."})]
    )

    with pytest.raises(FeishuAPIError):
        client.get("/open-apis/drive/v1/files")
