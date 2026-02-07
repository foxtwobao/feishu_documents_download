"""HTTP client abstraction for Feishu Open Platform APIs."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import httpx

from ..config import AuthSettings, LarkSyncConfig, RateLimitSettings, RetrySettings
from ..utils.rate_limit import RateLimitRule, RateLimiter
from ..cli_oauth import CLITokenManager

logger = logging.getLogger(__name__)


class FeishuAPIError(RuntimeError):
    """Raised when Feishu API returns an error response."""

    def __init__(self, status_code: int, message: str, payload: Optional[Mapping[str, Any]] = None):
        self.status_code = status_code
        self.message = message
        self.payload = payload
        super().__init__(f"Feishu API error {status_code}: {message}")


class FeishuRetryableError(FeishuAPIError):
    """Retryable variant for rate limit or transient issues."""


@dataclass(slots=True)
class RequestContext:
    """Metadata about a request for logging and retry decisions."""

    method: str
    url: str
    attempt: int


class FeishuAPIClient:
    """Synchronous HTTP client with simple retry logic for Feishu APIs."""

    def __init__(
        self,
        auth: AuthSettings,
        retry: RetrySettings,
        rate_limit: Optional[RateLimitSettings] = None,
        base_url: str = "https://open.feishu.cn",
        timeout: float = 30.0,
        user_agent: str = "larksync/0.1",
        enable_auto_refresh: bool = True,
    ):
        self._auth = auth
        self._retry = retry
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        # 配置连接池限制，避免在大量文件下载时出现 PoolTimeout
        # max_keepalive_connections: 保持活动的连接数
        # max_connections: 最大连接数
        limits = httpx.Limits(
            max_keepalive_connections=100,
            max_connections=200,
            keepalive_expiry=30.0,
        )
        self._client = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers={"User-Agent": user_agent},
            limits=limits,
        )
        self._rate_limiter = self._build_rate_limiter(rate_limit)
        # CLI token 管理器（用于自动刷新）
        self._token_manager: Optional[CLITokenManager] = None
        if enable_auto_refresh:
            try:
                self._token_manager = CLITokenManager(auth)
            except Exception as e:
                logger.debug(f"Token manager initialization skipped: {e}")

    @classmethod
    def from_config(cls, config: LarkSyncConfig) -> "FeishuAPIClient":
        return cls(
            auth=config.auth,
            retry=config.retry,
            rate_limit=config.rate_limit,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FeishuAPIClient":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: D401 - context manager exit signature
        self.close()

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        response = self._request("GET", path, params=params)
        return response.json()

    def post(
        self,
        path: str,
        *,
        json: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
    ) -> Mapping[str, Any]:
        response = self._request("POST", path, json=json, data=data)
        return response.json()

    def download(self, path: str, *, params: Optional[Mapping[str, Any]] = None) -> httpx.Response:
        """Return the raw streaming response for binary downloads."""
        return self._request("GET", path, params=params, stream=True)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Mapping[str, Any]] = None,
        data: Optional[Mapping[str, Any]] = None,
        stream: bool = False,
    ) -> httpx.Response:
        headers = self._build_headers()
        url = path if path.startswith("/") else f"/{path}"

        last_exc: Optional[Exception] = None
        for attempt in range(1, self._retry.max_attempts + 1):
            context = RequestContext(method=method, url=url, attempt=attempt)
            try:
                self._apply_rate_limit(path, method, params, json, data)
                if stream:
                    request = self._client.build_request(
                        method,
                        url,
                        params=params,
                        json=json,
                        data=data,
                        headers=headers,
                    )
                    response = self._client.send(
                        request,
                        stream=True,
                        follow_redirects=True,
                    )
                else:
                    response = self._client.request(
                        method,
                        url,
                        params=params,
                        json=json,
                        data=data,
                        headers=headers,
                        follow_redirects=True,
                        timeout=self._timeout,
                    )
            except httpx.TransportError as exc:
                logger.warning("Transport error when calling Feishu API", extra={"attempt": attempt, "url": url})
                last_exc = exc
                self._sleep(attempt)
                continue

            if self._should_retry(response.status_code):
                logger.info(
                    "Feishu API responded with retryable status",
                    extra={"status_code": response.status_code, "attempt": attempt, "url": url},
                )
                last_exc = FeishuRetryableError(response.status_code, response.text)
                self._sleep(attempt)
                continue

            if self._is_rate_limited_response(response):
                logger.info(
                    "Feishu API hit rate limit",
                    extra={"status_code": response.status_code, "attempt": attempt, "url": url},
                )
                last_exc = FeishuRetryableError(response.status_code, response.text)
                self._sleep(attempt)
                continue

            if response.status_code >= 400:
                self._raise_for_status(response)

            return response

        if last_exc:
            raise last_exc
        raise RuntimeError("Feishu API request failed without exception context")

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
        
        # 尝试获取有效的 user access token（如果启用了 token 管理器）
        user_access_token = self._get_valid_user_token()
        tenant_access_token = self._auth.tenant_access_token

        if user_access_token:
            headers["Authorization"] = f"Bearer {user_access_token}"
        elif tenant_access_token:
            headers["Authorization"] = f"Bearer {tenant_access_token}"
            headers["X-Tenant-Token"] = tenant_access_token

        return headers
    
    def _get_valid_user_token(self) -> Optional[str]:
        """获取有效的 user access token，如果需要会自动刷新"""
        # 如果启用了 token 管理器，使用它来获取有效 token
        if self._token_manager:
            try:
                return self._token_manager.get_valid_token()
            except Exception as e:
                logger.warning(f"Failed to get valid token from manager: {e}")
                # 降级到配置中的 token
                return self._auth.user_access_token
        
        # 否则直接返回配置中的 token
        return self._auth.user_access_token

    def _should_retry(self, status_code: int) -> bool:
        return status_code in {429, 502, 503, 504}

    def _sleep(self, attempt: int) -> None:
        interval = self._retry.initial_interval_seconds * (self._retry.backoff_multiplier ** (attempt - 1))
        time.sleep(interval)

    def _raise_for_status(self, response: httpx.Response) -> None:
        if not response.is_closed:
            try:
                response.read()
            except httpx.HTTPError:
                pass

        try:
            payload = response.json()
            message = payload.get("msg", response.text)
        except ValueError:
            payload = None
            message = response.text

        if response.status_code in {429, 502, 503, 504}:
            raise FeishuRetryableError(response.status_code, message, payload)
        raise FeishuAPIError(response.status_code, message, payload)

    # ------------------------------------------------------------------ rate limit helpers

    def _build_rate_limiter(self, rate_limit: Optional[RateLimitSettings]) -> RateLimiter:
        settings = rate_limit or RateLimitSettings()
        overrides = {
            "docx": RateLimitRule(capacity=settings.docx, interval=1.0),
            "sheet": RateLimitRule(capacity=settings.sheet, interval=1.0),
            "bitable": RateLimitRule(capacity=settings.bitable, interval=1.0),
            "file": RateLimitRule(capacity=settings.file, interval=1.0),
        }
        default_capacity = max(settings.docx, settings.sheet, settings.bitable, settings.file, 1)
        default_rule = RateLimitRule(capacity=default_capacity, interval=1.0)
        return RateLimiter(default=default_rule, overrides=overrides)

    def _apply_rate_limit(
        self,
        path: str,
        method: str,
        params: Optional[Mapping[str, Any]],
        json_payload: Optional[Mapping[str, Any]],
        data: Optional[Mapping[str, Any]],
    ) -> None:
        key = self._resolve_rate_key(path, method, params, json_payload, data)
        if self._rate_limiter:
            self._rate_limiter.acquire(key)

    def _resolve_rate_key(
        self,
        path: str,
        method: str,
        params: Optional[Mapping[str, Any]],
        json_payload: Optional[Mapping[str, Any]],
        data: Optional[Mapping[str, Any]],
    ) -> str:
        if path.startswith("/open-apis/docx/"):
            return "docx"
        if path.startswith("/open-apis/drive/v1/export_tasks"):
            target_type = None
            body = json_payload or data or {}
            if isinstance(body, Mapping):
                candidate = body.get("type") or body.get("doc_type")
                if isinstance(candidate, str):
                    target_type = candidate.lower()
            if target_type in {"sheet", "sheets"}:
                return "sheet"
            if target_type in {"bitable", "base"}:
                return "bitable"
            return "file"
        if path.startswith("/open-apis/drive/v1/files"):
            return "file"
        if path.startswith("/open-apis/drive/v1/medias"):
            return "file"
        if path.startswith("/open-apis/board/"):
            return "file"
        return "default"

    def _is_rate_limited_response(self, response: httpx.Response) -> bool:
        if response.status_code in {429, 503}:
            return True
        if response.status_code != 400:
            return False

        try:
            if not response.is_stream_consumed and not response.is_closed:
                # 流式响应需要先读取内容，否则无法解析 JSON
                response.read()
            payload = response.json()
        except (ValueError, json.JSONDecodeError, httpx.HTTPError):
            return False
        return payload.get("code") == 99991400
