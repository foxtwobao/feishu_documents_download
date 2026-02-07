"""Storage manager to handle local file writes."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from ..config import StorageSettings
from ..utils.filesystem import ensure_directory, safe_add_suffix


class StorageManager:
    """Manage local storage paths and writes."""

    def __init__(self, settings: StorageSettings):
        self._settings = settings
        self._root = settings.root.expanduser()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def target_path(self, relative_path: Path, extension: Optional[str] = None) -> Path:
        """Resolve path relative to storage root and ensure suffix."""

        if extension:
            suffix = extension if extension.startswith(".") else f".{extension}"
            # 使用 safe_add_suffix 避免 .with_suffix() 把 '产品2.0' 变成 '产品2.md'
            resolved = safe_add_suffix(self._root / relative_path, suffix)
        else:
            resolved = self._root / relative_path
        return resolved

    def images_dir(self) -> Path:
        path = self._root / self._settings.images_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def attachments_dir(self) -> Path:
        path = self._root / self._settings.attachments_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def nested_root(self) -> Path:
        path = self._root / self._settings.nested_dir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_document_dir(self, relative_path: Path) -> Path:
        path = self._root / relative_path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def write_bytes(self, path: Path, data: bytes) -> None:
        ensure_directory(path)
        path.write_bytes(data)

    def write_text(self, path: Path, content: str, encoding: str = "utf-8") -> None:
        ensure_directory(path)
        path.write_text(content, encoding=encoding)

    def write_stream(self, path: Path, chunks: Iterable[bytes]) -> None:
        ensure_directory(path)
        with path.open("wb") as handle:
            for chunk in chunks:
                handle.write(chunk)
