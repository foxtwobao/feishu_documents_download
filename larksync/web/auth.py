"""Feishu OAuth client for Web UI authentication."""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Tuple
from urllib.parse import quote_plus

import httpx

from ..config import WebOAuthSettings

logger = logging.getLogger(__name__)


def compute_expiry(expires_in: int) -> datetime:
    """Compute expiry datetime from seconds."""
    return datetime.now(timezone.utc) + timedelta(seconds=expires_in)


class FeishuOAuthClient:
    """
    Async OAuth client for Feishu authentication.
    
    Handles:
    - Authorization URL generation
    - Code exchange for tokens
    - Token refresh
    - User info retrieval
    """

    def __init__(self, settings: WebOAuthSettings):
        """
        Initialize the OAuth client.
        
        Args:
            settings: OAuth configuration settings
        """
        self.settings = settings
        self.enabled = bool(settings.app_id and settings.app_secret)

    def build_authorization_url(self, state: str) -> str:
        """
        Build the Feishu authorization URL.
        
        Args:
            state: Random state parameter for CSRF protection
            
        Returns:
            Authorization URL
        """
        if not self.settings.callback_url:
            raise ValueError("OAuth callback URL is not configured")

        callback = quote_plus(self.settings.callback_url)
        return (
            "https://passport.feishu.cn/suite/passport/oauth/authorize?"
            f"client_id={self.settings.app_id}&redirect_uri={callback}&response_type=code&state={state}"
        )

    async def exchange_code(
        self, code: str
    ) -> Tuple[str, str, int, int]:
        """
        Exchange authorization code for tokens.
        
        Args:
            code: Authorization code from callback
            
        Returns:
            Tuple of (access_token, refresh_token, expires_in, refresh_token_expires_in)
        """
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.settings.app_id,
            "client_secret": self.settings.app_secret,
            "code": code,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") not in (0, None):
                error_msg = body.get("msg", "Unknown error")
                raise RuntimeError(f"Feishu token exchange failed: {error_msg}")

            data = body.get("data") or body
            access_token = data["access_token"]
            refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 7200))
            refresh_token_expires_in = int(data.get("refresh_token_expires_in", 2592000))

            return access_token, refresh_token, expires_in, refresh_token_expires_in

    async def refresh_token(
        self, refresh_token: str
    ) -> Tuple[str, str, int, int]:
        """
        Refresh the access token.
        
        Args:
            refresh_token: Refresh token
            
        Returns:
            Tuple of (access_token, new_refresh_token, expires_in, refresh_token_expires_in)
        """
        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.settings.app_id,
            "client_secret": self.settings.app_secret,
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") not in (0, None):
                error_msg = body.get("msg", "Unknown error")
                raise RuntimeError(f"Feishu token refresh failed: {error_msg}")

            data = body.get("data") or body
            new_access_token = data["access_token"]
            new_refresh_token = data["refresh_token"]
            expires_in = int(data.get("expires_in", 7200))
            refresh_token_expires_in = int(data.get("refresh_token_expires_in", 2592000))

            return new_access_token, new_refresh_token, expires_in, refresh_token_expires_in

    async def get_user_info(self, access_token: str) -> dict:
        """
        Get user information from Feishu.
        
        Args:
            access_token: User's access token
            
        Returns:
            User info dict with user_id, name, avatar_url, etc.
        """
        url = "https://open.feishu.cn/open-apis/authen/v1/user_info"
        headers = {"Authorization": f"Bearer {access_token}"}

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            body = resp.json()

            if body.get("code") not in (0, None):
                error_msg = body.get("msg", "Unknown error")
                raise RuntimeError(f"Failed to get user info: {error_msg}")

            data = body.get("data", {})
            return {
                "user_id": data.get("user_id"),
                "open_id": data.get("open_id"),
                "union_id": data.get("union_id"),
                "name": data.get("name"),
                "en_name": data.get("en_name"),
                "avatar_url": data.get("avatar_url"),
                "email": data.get("email"),
            }


def generate_state() -> str:
    """Generate a random state parameter for OAuth."""
    return secrets.token_urlsafe(32)
