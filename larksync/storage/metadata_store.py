"""Simple JSON-backed metadata store for sync information."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping, Optional

from .manager import StorageSettings


class MetadataStore:
    """Persist per-token metadata such as modified timestamps for incremental sync."""

    def __init__(self, root: Path, filename: str = ".metadata.json"):
        self._path = root / filename
        self._data: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(content, Mapping):
            self._data = {str(key): dict(value) for key, value in content.items() if isinstance(value, Mapping)}

    def update(
        self,
        token: str,
        *,
        name: str,
        file_type: str,
        parent_path: Path,
        modified_time: Optional[str],
        source_url: Optional[str] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "name": name,
            "file_type": file_type,
            "parent_path": parent_path.as_posix(),
            "modified_time": modified_time,
        }
        if source_url:
            entry["source_url"] = source_url
        self._data[token] = entry
        self._dirty = True

    def get(self, token: str) -> Optional[Mapping[str, Any]]:
        return self._data.get(token)

    def flush(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._dirty = False
