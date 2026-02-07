"""Tests for the shared CLI OAuth callback service."""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from larksync.cli_oauth import CLIOAuthClient
from larksync.web.routes.cli_auth import router as cli_auth_router
from larksync.web.state import CLIOAuthSessionStore


class StubOAuthClient:
    """Stub implementation of FeishuOAuthClient for tests."""

    def __init__(self) -> None:
        self.enabled = True
        self._exchanged_codes: list[str] = []

    def build_authorization_url(self, state: str) -> str:
        return f"https://auth.example.com/authorize?state={state}"

    async def exchange_code(self, code: str) -> tuple[str, str, int, int]:
        if code != "valid-code":
            raise RuntimeError("invalid code")
        self._exchanged_codes.append(code)
        return "access-token", "refresh-token", 3600, 2592000


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(cli_auth_router)
    app.state.oauth_client = StubOAuthClient()
    app.state.cli_session_store = CLIOAuthSessionStore(ttl_seconds=30)
    return app


def test_cli_shared_callback_flow_success():
    app = _make_app()
    client = TestClient(app)

    resp = client.post("/cli/oauth/session")
    assert resp.status_code == 200
    payload = resp.json()
    session_id = payload["session_id"]
    authorization_url = payload["authorization_url"]

    parsed = urlparse(authorization_url)
    state = parse_qs(parsed.query)["state"][0]

    status_resp = client.get(f"/cli/oauth/session/{session_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["status"] == "pending"

    callback_resp = client.get("/cli/oauth/callback", params={"code": "valid-code", "state": state})
    assert callback_resp.status_code == 200

    final_resp = client.get(f"/cli/oauth/session/{session_id}")
    final_payload = final_resp.json()
    assert final_payload["status"] == "authorized"
    assert final_payload["access_token"] == "access-token"
    assert final_payload["refresh_token"] == "refresh-token"
    assert final_payload["expires_in"] == 3600


def test_cli_shared_callback_unknown_state():
    app = _make_app()
    client = TestClient(app)

    resp = client.get("/cli/oauth/callback", params={"code": "valid-code", "state": "non-existent"})
    assert resp.status_code == 400


class _DummyResponse:
    def __init__(self, data: dict, status_code: int = 200) -> None:
        self._data = data
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://example.com")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self) -> dict:
        return self._data


class _DummyClient:
    def __init__(self, *, post_payload: dict | None = None, get_payloads: list[dict] | None = None) -> None:
        self._post_payload = post_payload
        self._get_iter = iter(get_payloads or [])

    def __enter__(self) -> "_DummyClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url: str, json: dict | None = None) -> _DummyResponse:
        if self._post_payload is None:
            raise AssertionError("Unexpected POST call")
        return _DummyResponse(self._post_payload)

    def get(self, url: str) -> _DummyResponse:
        try:
            payload = next(self._get_iter)
        except StopIteration as exc:
            raise AssertionError("Unexpected GET call") from exc
        return _DummyResponse(payload)


def test_cli_oauth_client_remote_flow(monkeypatch):
    client = CLIOAuthClient(
        app_id="mock-app",
        app_secret="mock-secret",
        callback_url="https://oauth.example.com/cli/oauth/callback",
        service_base_url="https://oauth.example.com",
    )
    client.token_cache.save = lambda *args, **kwargs: None  # avoid filesystem writes

    session_payload = {
        "session_id": "sess-1",
        "authorization_url": "https://auth.example.com/authorize?state=sess",
        "expires_in": 30,
        "poll_interval_seconds": 1,
    }
    poll_payloads = [
        {"status": "pending"},
        {"status": "authorized", "access_token": "access-token", "refresh_token": "refresh-token", "expires_in": 3600},
    ]

    def fake_client_factory(*args, **kwargs):
        timeout = kwargs.get("timeout")
        if timeout == 30.0:
            return _DummyClient(post_payload=session_payload)
        return _DummyClient(get_payloads=poll_payloads)

    monkeypatch.setattr(httpx, "Client", fake_client_factory)
    monkeypatch.setattr("larksync.cli_oauth.webbrowser.open", lambda url: True)
    monkeypatch.setattr("larksync.cli_oauth.time.sleep", lambda *_args, **_kwargs: None)

    access_token, refresh_token, expires_in = client._authorize_via_remote()
    assert access_token == "access-token"
    assert refresh_token == "refresh-token"
    assert expires_in == 3600
