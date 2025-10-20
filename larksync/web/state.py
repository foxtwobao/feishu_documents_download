"""Helpers for storing short-lived OAuth state tokens."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from secrets import token_urlsafe
from threading import Lock
from typing import Dict


class OAuthStateStore:
    """In-memory store with TTL for OAuth state values."""

    def __init__(self, ttl_seconds: int = 600) -> None:
        self._ttl = timedelta(seconds=ttl_seconds)
        self._values: Dict[str, datetime] = {}
        self._lock = Lock()

    def issue(self) -> str:
        with self._lock:
            self._prune()
            state = token_urlsafe(16)
            self._values[state] = datetime.now(timezone.utc)
            return state

    def consume(self, state: str) -> bool:
        with self._lock:
            self._prune()
            return self._values.pop(state, None) is not None

    def _prune(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [key for key, issued_at in self._values.items() if now - issued_at > self._ttl]
        for key in expired:
            self._values.pop(key, None)
