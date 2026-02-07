"""Simple rate limiter utilities."""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional


@dataclass(slots=True)
class RateLimitRule:
    """Rate limit rule defined by a capacity within a fixed interval."""

    capacity: int
    interval: float  # seconds


class RateLimiter:
    """Enforce per-key rate limits using a simple sliding window with per-key locks."""

    def __init__(self, *, default: RateLimitRule, overrides: Optional[Dict[str, RateLimitRule]] = None):
        self._default = default
        self._overrides = overrides or {}
        self._timestamps: Dict[str, Deque[float]] = {}
        self._locks: Dict[str, threading.Lock] = {}  # 每个 key 独立的锁
        self._locks_guard = threading.Lock()  # 序列化锁对象的创建，避免竞态

    def acquire(self, key: Optional[str]) -> None:
        """Block until the caller is allowed to proceed for the given key."""

        rule = self._overrides.get(key or "", self._default)
        if rule.capacity <= 0:
            return

        bucket_key = key or "default"

        # 获取该 key 专属的锁（不阻塞其他 key）
        with self._locks_guard:
            lock = self._locks.get(bucket_key)
            if lock is None:
                lock = threading.Lock()
                self._locks[bucket_key] = lock
        
        with lock:
            bucket = self._timestamps.setdefault(bucket_key, deque())
            while True:
                now = time.monotonic()
                cutoff = now - rule.interval
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if len(bucket) < rule.capacity:
                    bucket.append(now)
                    return

                wait = rule.interval - (now - bucket[0])
                if wait > 0:
                    time.sleep(wait)
                else:
                    bucket.popleft()
