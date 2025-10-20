"""Feishu OAuth helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote_plus

import httpx

from ..config import WebOAuthSettings


class FeishuOAuthClient:
    def __init__(self, settings: WebOAuthSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self._settings.app_id and self._settings.app_secret and self._settings.callback_url)

    def build_authorization_url(self, state: str) -> str:
        if not self.enabled:
            raise RuntimeError("Feishu OAuth 未启用")

        callback = quote_plus(self._settings.callback_url)
        return (
            "https://passport.feishu.cn/suite/passport/oauth/authorize?"
            f"client_id={self._settings.app_id}&redirect_uri={callback}&response_type=code&state={state}"
        )

    async def exchange_code(self, code: str) -> tuple[str, str, int]:
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self._settings.app_id,
            "client_secret": self._settings.app_secret,
            "code": code,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") not in (0, None) and not all(
                key in body for key in ("access_token", "refresh_token")
            ):
                raise RuntimeError(f"Feishu token exchange failed: {body}")
            data = body.get("data") or body
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 3600))
            return access_token, refresh_token, expires_in

    async def refresh_token(self, refresh_token: str) -> tuple[str, str, int]:
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self._settings.app_id,
            "client_secret": self._settings.app_secret,
            "refresh_token": refresh_token,
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()
            if body.get("code") not in (0, None) and not all(
                key in body for key in ("access_token", "refresh_token")
            ):
                raise RuntimeError(f"Feishu token refresh failed: {body}")
            data = body.get("data") or body
            access_token = data["access_token"]
            new_refresh = data["refresh_token"]
            expires_in = int(data.get("expires_in", 3600))
            return access_token, new_refresh, expires_in

    async def fetch_user_info(self, access_token: str) -> dict[str, Any]:
        """Retrieve Feishu user profile using the access token."""

        url = "https://open.feishu.cn/open-apis/authen/v1/user_info"
        headers = {"Authorization": f"Bearer {access_token}"}
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data") or {}
            return {str(key): value for key, value in data.items()}


def compute_expiry(expires_in: int) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)
