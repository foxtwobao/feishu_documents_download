"""In-memory cache for resolved local paths of downloaded tokens."""

from __future__ import annotations

from pathlib import Path
from threading import RLock
from typing import Dict, Optional, Tuple, Union

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


# wiki 节点解析结果：node_token -> (下载器类型, obj_token, 标题) 或 None（解析失败）
WikiNodeInfo = Tuple[str, str, Optional[str]]
MISSING = object()
_wiki_nodes: Dict[str, Optional[WikiNodeInfo]] = {}
_wiki_titles: Dict[str, str] = {}


def register_wiki_node(node_token: str, info: Optional[WikiNodeInfo]) -> None:
    """Cache the resolution of a wiki node token (``None`` marks a failure)."""
    if not node_token:
        return
    with _lock:
        _wiki_nodes[node_token] = info
        if info is not None and info[2]:
            _wiki_titles[info[1]] = info[2]


def lookup_wiki_node(node_token: str) -> Union[Optional[WikiNodeInfo], object]:
    """Return the cached resolution, ``None`` for a cached failure, or ``MISSING``."""
    with _lock:
        return _wiki_nodes.get(node_token, MISSING)


def lookup_wiki_title(obj_token: str) -> Optional[str]:
    """Return the wiki node title recorded for an underlying object token."""
    with _lock:
        return _wiki_titles.get(obj_token)


def clear_cache() -> None:
    """Clear all cached entries. Primarily used by tests."""
    with _lock:
        _cache.clear()
        _wiki_nodes.clear()
        _wiki_titles.clear()


__all__ = [
    "MISSING",
    "register_resolved_path",
    "lookup_resolved_path",
    "register_wiki_node",
    "lookup_wiki_node",
    "lookup_wiki_title",
    "clear_cache",
]
