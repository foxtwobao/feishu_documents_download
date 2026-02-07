"""Filesystem utilities."""

from __future__ import annotations

import re
from pathlib import Path


INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def sanitize_filename(name: str, replacement: str = "_") -> str:
    """Sanitize a filename by replacing disallowed characters."""

    sanitized = INVALID_FILENAME_CHARS.sub(replacement, name).strip()
    return sanitized or "untitled"


def ensure_directory(path: Path) -> None:
    """Ensure the parent directory of ``path`` exists."""

    path.parent.mkdir(parents=True, exist_ok=True)


def safe_add_suffix(path: Path, suffix: str) -> Path:
    """
    安全地为路径添加后缀，不会替换文件名中的 .数字 部分。
    
    Path.with_suffix() 会把 '产品2.0' 变成 '产品2.md'，因为 .0 被当作扩展名。
    此函数直接追加后缀，保持原始文件名完整。
    
    Args:
        path: 原始路径
        suffix: 要添加的后缀（如 '.md'）
        
    Returns:
        添加后缀后的新路径
        
    Examples:
        >>> safe_add_suffix(Path('产品2.0'), '.md')
        Path('产品2.0.md')
        >>> safe_add_suffix(Path('parent/产品2.0'), '.md')
        Path('parent/产品2.0.md')
    """
    if not suffix.startswith('.'):
        suffix = '.' + suffix
    return path.parent / (path.name + suffix)
