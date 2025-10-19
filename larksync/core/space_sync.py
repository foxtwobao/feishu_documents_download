"""Utilities for syncing the entire personal space."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Mapping, Optional

from ..storage import MetadataStore, StorageManager
from ..utils.filesystem import sanitize_filename
from .adapters.drive_adapter import DriveAdapter
from .models import SyncTask
from .registry import DownloaderRegistry
from .sync_engine import SyncEngine


@dataclass(slots=True)
class SpaceSyncContext:
    engine: SyncEngine
    drive: DriveAdapter
    registry: DownloaderRegistry
    storage: StorageManager


class DriveSpaceSynchronizer:
    """Traverse the personal space root folder and download every entry."""

    def __init__(
        self,
        context: SpaceSyncContext,
        metadata_store: MetadataStore,
        *,
        limit: Optional[int] = None,
    ):
        self._context = context
        self._metadata = metadata_store
        self._visited: set[str] = set()
        self._limit = limit
        self._processed_files = 0

    def sync(self) -> None:
        root_meta = self._fetch_root_meta()
        root_token = root_meta["token"]
        root_name = root_meta["name"]
        root_modified = root_meta.get("modified_time")

        relative_root = Path(sanitize_filename(root_name) or root_token)
        self._context.storage.ensure_document_dir(relative_root)
        self._record_metadata(
            token=root_token,
            name=root_name,
            file_type="folder",
            parent_path=Path("."),
            modified_time=root_modified,
            source_url=None,
        )
        self._visited.add(root_token)
        self._walk_folder(root_token, relative_root)
        self._metadata.flush()
        self._processed_files = 0

    # ------------------------------------------------------------------ internals

    def _fetch_root_meta(self) -> Dict[str, Optional[str]]:
        payload = self._context.drive.get_root_folder_meta()
        data = payload.get("data") or {}
        token = data.get("token") or data.get("folder_token")
        if not token:
            raise RuntimeError("Failed to resolve root folder token")
        name = data.get("name") or token
        modified = data.get("update_time") or data.get("latest_modify_time") or data.get("modify_time")
        return {"token": str(token), "name": str(name), "modified_time": modified}

    def _walk_folder(self, folder_token: str, relative_path: Path) -> None:
        page_token: Optional[str] = None
        while True:
            payload = self._context.drive.list_folder_children(folder_token, page_token=page_token)
            data = payload.get("data") or {}
            files = data.get("files") or []
            for item in files:
                self._handle_entry(item, relative_path)
                if self._reached_limit():
                    return
            if not data.get("has_more") or self._reached_limit():
                break
            page_token = data.get("next_page_token")
            if not page_token:
                break

    def _handle_entry(self, item: Mapping[str, object], parent_path: Path) -> None:
        raw_type = str(item.get("type") or "").lower()
        token = self._extract_token(item)
        if not token:
            return
        if token in self._visited:
            return

        name = str(item.get("name") or token)
        modified_time = (
            item.get("latest_modify_time")
            or item.get("update_time")
            or item.get("modify_time")
            or item.get("modified_time")
        )
        source_url = item.get("url")
        if isinstance(source_url, str):
            source_url = source_url
        else:
            source_url = None

        if raw_type == "folder":
            folder_name = sanitize_filename(name) or token
            folder_path = parent_path / folder_name
            self._context.storage.ensure_document_dir(folder_path)
            self._record_metadata(
                token=token,
                name=name,
                file_type="folder",
                parent_path=parent_path,
                modified_time=modified_time if isinstance(modified_time, str) else None,
                source_url=source_url,
            )
            self._visited.add(token)
            if not self._reached_limit():
                self._walk_folder(token, folder_path)
            return

        actual_token = token
        file_type = self._normalize_type(raw_type)
        extra: Dict[str, object] = {}

        if raw_type == "shortcut":
            shortcut_info = item.get("shortcut_info") if isinstance(item.get("shortcut_info"), Mapping) else {}
            target_token = shortcut_info.get("target_token")
            target_type = shortcut_info.get("target_type")
            normalized = self._normalize_type(str(target_type)) if target_type else None
            if normalized and isinstance(target_token, str):
                file_type = normalized
                actual_token = target_token
                extra["shortcut_token"] = token
            else:
                self._record_metadata(
                    token=token,
                    name=name,
                    file_type="shortcut",
                    parent_path=parent_path,
                    modified_time=modified_time if isinstance(modified_time, str) else None,
                    source_url=source_url,
                )
                self._visited.add(token)
                self._count_file()
                return

        if not file_type:
            self._record_metadata(
                token=token,
                name=name,
                file_type=raw_type or "unknown",
                parent_path=parent_path,
                modified_time=modified_time if isinstance(modified_time, str) else None,
                source_url=source_url,
            )
            self._visited.add(token)
            self._count_file()
            return

        if actual_token in self._visited:
            self._record_metadata(
                token=actual_token,
                name=name,
                file_type=file_type,
                parent_path=parent_path,
                modified_time=modified_time if isinstance(modified_time, str) else None,
                source_url=source_url,
            )
            self._count_file()
            return

        if self._reached_limit():
            return

        task = SyncTask(
            token=actual_token,
            file_type=file_type,
            name=name,
            parent_path=parent_path,
            extra={**extra, **({"source_url": source_url} if source_url else {})},
        )

        try:
            self._context.engine.process_task(task)
        except Exception as exc:  # pragma: no cover - defensive
            self._record_metadata(
                token=actual_token,
                name=name,
                file_type=file_type,
                parent_path=parent_path,
                modified_time=modified_time if isinstance(modified_time, str) else None,
                source_url=source_url,
            )
            raise

        self._record_metadata(
            token=actual_token,
            name=name,
            file_type=file_type,
            parent_path=parent_path,
            modified_time=modified_time if isinstance(modified_time, str) else None,
            source_url=source_url,
        )
        self._visited.add(actual_token)
        if raw_type == "shortcut":
            self._visited.add(token)
        self._count_file()

    def _record_metadata(
        self,
        *,
        token: str,
        name: str,
        file_type: str,
        parent_path: Path,
        modified_time: Optional[str],
        source_url: Optional[str],
    ) -> None:
        self._metadata.update(
            token,
            name=name,
            file_type=file_type,
            parent_path=parent_path,
            modified_time=modified_time,
            source_url=source_url,
        )

    @staticmethod
    def _extract_token(item: Mapping[str, object]) -> Optional[str]:
        for key in ("token", "file_token", "folder_token"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value
        return None

    @staticmethod
    def _normalize_type(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        mapping = {
            "doc": "docx",
            "docx": "docx",
            "sheet": "sheet",
            "sheets": "sheet",
            "bitable": "bitable",
            "base": "bitable",
            "file": "file",
            "slides": "slides",
            "mindnote": "mindnote",
            "folder": "folder",
            "wiki": "wiki",
        }
        lower = value.lower()
        return mapping.get(lower, lower)

    def _reached_limit(self) -> bool:
        if self._limit is None:
            return False
        return self._processed_files >= self._limit

    def _count_file(self) -> None:
        self._processed_files += 1
