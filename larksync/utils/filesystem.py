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
