"""Simple JSON-backed metadata store for sync information."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional


class MetadataStore:
    """Persist per-token metadata such as modified timestamps for incremental sync."""

    def __init__(self, root: Path, filename: str = ".metadata.json"):
        self._root = root
        self._path = root / filename
        self._data: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._load()

    # ------------------------------------------------------------------ persistence

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            content = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        if isinstance(content, Mapping):
            self._data = {str(key): dict(value) for key, value in content.items() if isinstance(value, Mapping)}

    def flush(self) -> None:
        if not self._dirty:
            return
        self._write()

    def clear(self) -> None:
        self._data.clear()
        self._dirty = True
        self._write()

    # ------------------------------------------------------------------ access helpers

    def get(self, token: str) -> Optional[Mapping[str, Any]]:
        return self._data.get(token)

    def tokens(self) -> Iterable[str]:
        return self._data.keys()

    def resolve_path(self, entry: Mapping[str, Any]) -> Path:
        local = entry.get("local_path")
        if isinstance(local, str) and local:
            return (self._root / local).resolve()
        parent = entry.get("parent_path")
        if isinstance(parent, str) and parent:
            return (self._root / parent).resolve()
        return self._root

    def remove(self, token: str) -> None:
        if token in self._data:
            del self._data[token]
            self._dirty = True

    # ------------------------------------------------------------------ decision helpers

    def should_download(
        self,
        token: str,
        *,
        current_meta: Mapping[str, Any],
        expected_local_path: Optional[Path],
        incremental: bool,
        force_on_missing: bool,
        parent_path: Path,
    ) -> bool:
        if not incremental:
            return True

        entry = self._data.get(token)
        if entry is None:
            return True

        if entry.get("status") == "deleted":
            return True

        if entry.get("status") == "missing":
            return True

        if entry.get("parent_path") != parent_path.as_posix():
            return True

        if force_on_missing and not self._path_exists(entry, expected_local_path):
            return True

        modified_time = current_meta.get("modified_time")
        if modified_time and entry.get("modified_time") != modified_time:
            return True

        revision = current_meta.get("revision")
        if revision and entry.get("revision") != revision:
            return True

        checksum = current_meta.get("checksum")
        if checksum and entry.get("checksum") != checksum:
            return True

        return False

    def mark_synced(
        self,
        token: str,
        *,
        name: str,
        file_type: str,
        parent_path: Path,
        modified_time: Optional[str],
        local_path: Optional[Path],
        revision: Optional[str] = None,
        checksum: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> None:
        entry: Dict[str, Any] = {
            "name": name,
            "file_type": file_type,
            "parent_path": parent_path.as_posix(),
            "modified_time": modified_time,
            "status": "ok",
            "last_synced": datetime.utcnow().isoformat(),
        }
        if revision:
            entry["revision"] = revision
        if checksum:
            entry["checksum"] = checksum
        if source_url:
            entry["source_url"] = source_url
        if local_path is not None:
            entry["local_path"] = local_path.as_posix()
        else:
            existing = self._data.get(token, {}).get("local_path")
            if existing:
                entry["local_path"] = existing
        self._data[token] = entry
        self._dirty = True
        self._write()

    def mark_missing(
        self,
        token: str,
        *,
        error: str,
        current_meta: Mapping[str, Any],
        parent_path: Path,
        source_url: Optional[str] = None,
    ) -> None:
        entry = dict(self._data.get(token, {}))
        entry.update(
            {
                "status": "missing",
                "last_error": error,
                "parent_path": parent_path.as_posix(),
                "modified_time": current_meta.get("modified_time"),
            }
        )
        if current_meta.get("revision"):
            entry["revision"] = current_meta.get("revision")
        if source_url:
            entry["source_url"] = source_url
        self._data[token] = entry
        self._dirty = True
        self._write()

    def mark_deleted(self, token: str) -> None:
        entry = dict(self._data.get(token, {}))
        entry["status"] = "deleted"
        entry.pop("last_error", None)
        self._data[token] = entry
        self._dirty = True
        self._write()

    # ------------------------------------------------------------------ helpers

    def _path_exists(self, entry: Mapping[str, Any], expected_local_path: Optional[Path]) -> bool:
        path = None
        local = entry.get("local_path")
        if isinstance(local, str) and local:
            path = (self._root / local).resolve()
        elif expected_local_path is not None:
            path = (self._root / expected_local_path).resolve()
        else:
            path = self.resolve_path(entry)
        return path.exists()

    def _write(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._path)
        self._dirty = False
