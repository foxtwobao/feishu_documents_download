"""Simple JSON-backed metadata store for sync information."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional

from ..utils.time import normalize_timestamp

logger = logging.getLogger(__name__)


class MetadataStore:
    """Persist per-token metadata such as modified timestamps for incremental sync."""

    def __init__(self, root: Path, filename: str = ".metadata.json", flush_interval: int = 50):
        self._root = root
        self._path = root / filename
        self._data: Dict[str, Dict[str, Any]] = {}
        self._dirty = False
        self._flush_interval = flush_interval
        self._updates_since_flush = 0
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
            logger.debug("Incremental download forced (no metadata entry)", extra={"doc_token": token})
            return True

        if entry.get("status") == "deleted":
            logger.debug("Incremental download forced (marked deleted)", extra={"doc_token": token})
            return True

        if entry.get("status") == "missing":
            logger.debug("Incremental download forced (previously missing)", extra={"doc_token": token})
            return True

        parent_posix = parent_path.as_posix()
        if entry.get("parent_path") != parent_posix:
            logger.debug(
                "Incremental download forced (parent path changed)",
                extra={"doc_token": token, "stored_parent": entry.get("parent_path"), "current_parent": parent_posix},
            )
            return True

        if force_on_missing and not self._path_exists(entry, expected_local_path):
            logger.debug(
                "Incremental download forced (local path missing) stored=%s expected=%s",
                entry.get("local_path"),
                expected_local_path.as_posix() if expected_local_path else None,
                extra={"doc_token": token},
            )
            return True

        stored_modified = normalize_timestamp(entry.get("modified_time"))
        incoming_modified = normalize_timestamp(current_meta.get("modified_time"))
        if incoming_modified and stored_modified != incoming_modified:
            logger.debug(
                "Incremental download forced (modified timestamp change)",
                extra={"doc_token": token, "stored_modified": stored_modified, "incoming_modified": incoming_modified},
            )
            return True

        revision = current_meta.get("revision")
        if revision and entry.get("revision") != revision:
            logger.debug(
                "Incremental download forced (revision change)",
                extra={"doc_token": token, "stored_revision": entry.get("revision"), "incoming_revision": revision},
            )
            return True

        checksum = current_meta.get("checksum")
        if checksum and entry.get("checksum") != checksum:
            logger.debug(
                "Incremental download forced (checksum change)",
                extra={"doc_token": token, "stored_checksum": entry.get("checksum"), "incoming_checksum": checksum},
            )
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
            "modified_time": normalize_timestamp(modified_time),
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
        self._updates_since_flush += 1
        
        # 批量刷盘：每 N 个文件刷盘一次
        if self._updates_since_flush >= self._flush_interval:
            self._write()
            self._updates_since_flush = 0

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
                "modified_time": normalize_timestamp(current_meta.get("modified_time")),
            }
        )
        if current_meta.get("revision"):
            entry["revision"] = current_meta.get("revision")
        if source_url:
            entry["source_url"] = source_url
        self._data[token] = entry
        self._dirty = True
        self._updates_since_flush += 1
        
        # 批量刷盘
        if self._updates_since_flush >= self._flush_interval:
            self._write()
            self._updates_since_flush = 0

    def mark_deleted(self, token: str) -> None:
        entry = dict(self._data.get(token, {}))
        entry["status"] = "deleted"
        entry.pop("last_error", None)
        self._data[token] = entry
        self._dirty = True
        self._updates_since_flush += 1
        
        # 批量刷盘
        if self._updates_since_flush >= self._flush_interval:
            self._write()
            self._updates_since_flush = 0

    # ------------------------------------------------------------------ helpers

    def _path_exists(self, entry: Mapping[str, Any], expected_local_path: Optional[Path]) -> bool:
        local = entry.get("local_path")
        if isinstance(local, str) and local:
            stored_path = (self._root / local).resolve()
            if stored_path.exists():
                return True
            if expected_local_path is not None:
                fallback = (self._root / expected_local_path).resolve()
                if fallback.exists():
                    return True
        elif expected_local_path is not None:
            fallback = (self._root / expected_local_path).resolve()
            if fallback.exists():
                return True
        else:
            stored_path = self.resolve_path(entry)
            if stored_path.exists():
                return True
        return False

    def _write(self) -> None:
        if not self._dirty:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        
        # 准备 JSON 数据
        json_data = json.dumps(self._data, ensure_ascii=False, indent=2)
        
        # 尝试使用临时文件方式（原子操作，更安全）
        try:
            tmp_path = self._path.with_suffix(self._path.suffix + ".tmp")
            tmp_path.write_text(json_data, encoding="utf-8")
            tmp_path.replace(self._path)
        except (OSError, IOError) as e:
            # 如果临时文件方式失败（比如 CIFS/SMB 文件系统），直接写入
            # 这种方式不是原子操作，但在网络文件系统上更兼容
            try:
                self._path.write_text(json_data, encoding="utf-8")
            except Exception as write_error:
                # 如果直接写入也失败，记录错误但不中断程序
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Failed to write metadata to {self._path}: {write_error}")
                # 不抛出异常，避免中断下载流程
                return
        
        self._dirty = False
        self._updates_since_flush = 0
