"""HTTP client abstraction for Feishu Open Platform APIs."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

import httpx

from ..config import AuthSettings, LarkSyncConfig, RetrySettings

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
        base_url: str = "https://open.feishu.cn",
        timeout: float = 30.0,
        user_agent: str = "larksync/0.1",
    ):
        self._auth = auth
        self._retry = retry
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout, headers={"User-Agent": user_agent})

    @classmethod
    def from_config(cls, config: LarkSyncConfig) -> "FeishuAPIClient":
        return cls(auth=config.auth, retry=config.retry)

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

            if response.status_code >= 400:
                self._raise_for_status(response)

            return response

        if last_exc:
            raise last_exc
        raise RuntimeError("Feishu API request failed without exception context")

    def _build_headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json; charset=utf-8"}
        user_access_token = self._auth.user_access_token
        tenant_access_token = self._auth.tenant_access_token

        if user_access_token:
            headers["Authorization"] = f"Bearer {user_access_token}"
        elif tenant_access_token:
            headers["Authorization"] = f"Bearer {tenant_access_token}"
            headers["X-Tenant-Token"] = tenant_access_token

        return headers

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
