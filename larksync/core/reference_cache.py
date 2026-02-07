"""In-memory cache for resolved local paths of downloaded tokens."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Dict, Optional

_cache: Dict[str, Path] = {}
_lock = RLock()


def register_resolved_path(token: str, path: Path) -> None:
    """Register the local path for a downloaded token."""
    if not token:
        return
    with _lock:
        _cache[token] = path


def lookup_resolved_path(token: str) -> Optional[Path]:
    """Retrieve the cached local path for a token, if present."""
    if not token:
        return None
    with _lock:
        return _cache.get(token)


def clear_cache() -> None:
    """Clear all cached entries. Primarily used by tests."""
    with _lock:
        _cache.clear()


__all__ = ["register_resolved_path", "lookup_resolved_path", "clear_cache"]
