"""Utilities for syncing the entire personal space."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set

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
        incremental: bool = True,
        force_on_missing: bool = True,
        clean_deleted: bool = False,
        progress_callback: Callable[[int, int, Optional[str], str, Optional[str], Optional[str]], None] | None = None,
        plan_only: bool = False,
    ):
        self._context = context
        self._metadata = metadata_store
        self._visited: set[str] = set()
        self._limit = limit
        self._processed_files = 0
        self._incremental = incremental
        self._force_on_missing = force_on_missing
        self._clean_deleted = clean_deleted
        self._current_tokens: Set[str] = set()
        self._progress_callback = progress_callback
        self._expected_total = 0
        self._plan_only = plan_only
        self._summary: Dict[str, Any] = {
            "root": {},
            "total_files": 0,
            "will_download": 0,
            "existing": 0,
            "skipped": 0,
            "limit": limit,
            "incremental": incremental,
            "samples": [],
        }

    def sync(self) -> None:
        root_meta = self._fetch_root_meta()
        root_token = root_meta["token"]
        root_name = root_meta["name"]
        root_modified = root_meta.get("modified_time")

        relative_root = Path(sanitize_filename(root_name) or root_token)
        self._summary["root"] = {"token": root_token, "name": root_name}
        self._current_tokens = set()
        if not self._plan_only:
            self._context.storage.ensure_document_dir(relative_root)
            self._record_metadata(
                token=root_token,
                name=root_name,
                file_type="folder",
                parent_path=Path("."),
                modified_time=root_modified,
                source_url=None,
                local_path=relative_root,
            )
        self._visited.add(root_token)
        self._current_tokens.add(root_token)
        self._walk_folder(root_token, relative_root)
        if self._incremental and not self._plan_only:
            self._mark_deleted_tokens()
        if not self._plan_only:
            self._metadata.flush()
        self._processed_files = 0

    def summary(self) -> Dict[str, Any]:
        return {
            "root": self._summary.get("root"),
            "total_files": self._summary.get("total_files", 0),
            "will_download": self._summary.get("will_download", 0),
            "existing": self._summary.get("existing", 0),
            "skipped": self._summary.get("skipped", 0),
            "limit": self._summary.get("limit"),
            "incremental": self._summary.get("incremental"),
            "samples": self._summary.get("samples", []),
        }

    # ------------------------------------------------------------------ internals

    def _fetch_root_meta(self) -> Dict[str, Optional[str]]:
        payload = self._context.drive.get_root_folder_meta()
        data = self._ensure_success(payload, "获取根目录信息")
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
            data = self._ensure_success(payload, f"获取文件夹 {folder_token} 列表")
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
        self._current_tokens.add(token)

        name = str(item.get("name") or token)
        modified_time_raw = (
            item.get("latest_modify_time")
            or item.get("update_time")
            or item.get("modify_time")
            or item.get("modified_time")
        )
        modified_time = str(modified_time_raw) if modified_time_raw is not None else None
        source_url = item.get("url")
        if isinstance(source_url, str):
            source_url = source_url
        else:
            source_url = None

        current_meta = {
            "modified_time": modified_time,
            "revision": item.get("revision") or item.get("rev"),
            "checksum": item.get("checksum"),
        }

        if raw_type == "folder":
            folder_name = sanitize_filename(name) or token
            folder_path = parent_path / folder_name
            if not self._plan_only:
                self._context.storage.ensure_document_dir(folder_path)
                self._record_metadata(
                    token=token,
                    name=name,
                    file_type="folder",
                    parent_path=parent_path,
                    modified_time=modified_time,
                    source_url=source_url,
                    local_path=folder_path,
                    revision=current_meta.get("revision"),
                    checksum=current_meta.get("checksum"),
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
                self._current_tokens.add(actual_token)
            else:
                self._plan_file()
                self._emit_progress("skip", name, raw_type, "无法解析快捷方式目标")
                detail_path = self._expected_local_path(token, "shortcut", name, parent_path)
                detail = detail_path.as_posix() if detail_path else None
                if self._plan_only:
                    self._track_item("skip", name, raw_type, detail)
                else:
                    self._record_metadata(
                        token=token,
                        name=name,
                        file_type="shortcut",
                        parent_path=parent_path,
                        modified_time=modified_time,
                        source_url=source_url,
                        local_path=detail_path,
                        revision=current_meta.get("revision"),
                        checksum=current_meta.get("checksum"),
                    )
            self._visited.add(token)
            self._count_file()
            return

        if not file_type:
            self._plan_file()
            self._emit_progress("skip", name, raw_type or "unknown", "未知类型，写入占位")
            detail_path = self._expected_local_path(token, raw_type, name, parent_path)
            detail = detail_path.as_posix() if detail_path else None
            if self._plan_only:
                self._track_item("skip", name, raw_type or "unknown", detail)
            else:
                self._record_metadata(
                    token=token,
                    name=name,
                    file_type=raw_type or "unknown",
                    parent_path=parent_path,
                    modified_time=modified_time,
                    source_url=source_url,
                    local_path=detail_path,
                    revision=current_meta.get("revision"),
                    checksum=current_meta.get("checksum"),
                )
            self._visited.add(token)
            self._count_file()
            return

        if actual_token in self._visited:
            self._plan_file()
            self._emit_progress("skip", name, file_type, "已下载，跳过")
            detail_path = self._expected_local_path(actual_token, file_type, name, parent_path)
            detail = detail_path.as_posix() if detail_path else None
            if self._plan_only:
                self._track_item("existing", name, file_type, detail)
            else:
                self._record_metadata(
                    token=actual_token,
                    name=name,
                    file_type=file_type,
                    parent_path=parent_path,
                    modified_time=modified_time,
                    source_url=source_url,
                    local_path=detail_path,
                    revision=current_meta.get("revision"),
                    checksum=current_meta.get("checksum"),
                )
            self._count_file()
            return

        expected_local_path = self._expected_local_path(actual_token, file_type, name, parent_path)

        if self._reached_limit():
            return

        if not self._metadata.should_download(
            actual_token,
            current_meta=current_meta,
            expected_local_path=expected_local_path,
            incremental=self._incremental,
            force_on_missing=self._force_on_missing,
            parent_path=parent_path,
        ):
            self._plan_file()
            self._emit_progress("skip", name, file_type, "增量策略跳过")
            detail = expected_local_path.as_posix() if expected_local_path else None
            if self._plan_only:
                self._track_item("existing", name, file_type, detail)
            else:
                self._record_metadata(
                    token=actual_token,
                    name=name,
                    file_type=file_type,
                    parent_path=parent_path,
                    modified_time=modified_time,
                    source_url=source_url,
                    local_path=expected_local_path,
                    revision=current_meta.get("revision"),
                    checksum=current_meta.get("checksum"),
                )
            self._visited.add(actual_token)
            if raw_type == "shortcut":
                self._visited.add(token)
            self._count_file()
            return

        self._plan_file(name, file_type, "已下载，跳过")
        if self._plan_only:
            detail = expected_local_path.as_posix() if expected_local_path else None
            self._track_item("download", name, file_type, detail)
            self._visited.add(actual_token)
            if raw_type == "shortcut":
                self._visited.add(token)
            self._count_file()
            return
        task = SyncTask(
            token=actual_token,
            file_type=file_type,
            name=name,
            parent_path=parent_path,
            extra={**extra, **({"source_url": source_url} if source_url else {})},
        )

        self._emit_progress("start", name, file_type)
        try:
            self._context.engine.process_task(task)
        except Exception as exc:  # pragma: no cover - defensive
            self._emit_progress("failed", name, file_type, str(exc))
            self._metadata.mark_missing(
                actual_token,
                error=str(exc),
                current_meta=current_meta,
                parent_path=parent_path,
                source_url=source_url,
            )
            raise
        local_relative = self._finalize_local_path(expected_local_path, file_type, name, parent_path)
        self._record_metadata(
            token=actual_token,
            name=name,
            file_type=file_type,
            parent_path=parent_path,
            modified_time=modified_time,
            source_url=source_url,
            local_path=local_relative,
            revision=current_meta.get("revision"),
            checksum=current_meta.get("checksum"),
        )
        self._emit_progress("success", name, file_type, str(local_relative) if local_relative else None)
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
        local_path: Optional[Path],
        revision: Optional[str] = None,
        checksum: Optional[str] = None,
    ) -> None:
        if self._plan_only:
            return
        self._metadata.mark_synced(
            token,
            name=name,
            file_type=file_type,
            parent_path=parent_path,
            modified_time=modified_time,
            local_path=local_path,
            revision=revision,
            checksum=checksum,
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
        self._emit_progress("progress")

    def _plan_file(
        self,
        name: Optional[str] = None,
        file_type: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        self._expected_total += 1
        if self._progress_callback:
            expected = max(self._expected_total, 1)
            self._progress_callback(self._processed_files, expected, name, "plan", file_type, detail)
        if self._plan_only:
            self._summary["total_files"] = self._summary.get("total_files", 0) + 1

    def _track_item(self, action: str, name: str, file_type: Optional[str], detail: Optional[str]) -> None:
        if not self._plan_only:
            return
        if action == "download":
            self._summary["will_download"] = self._summary.get("will_download", 0) + 1
        elif action == "existing":
            self._summary["existing"] = self._summary.get("existing", 0) + 1
        else:
            self._summary["skipped"] = self._summary.get("skipped", 0) + 1
        samples: List[Dict[str, Any]] = self._summary.setdefault("samples", [])
        if len(samples) < 10:
            samples.append(
                {
                    "name": name,
                    "file_type": file_type,
                    "detail": detail,
                    "action": action,
                }
            )

    def _expected_local_path(self, token: str, file_type: Optional[str], name: str, parent_path: Path) -> Optional[Path]:
        safe_name = sanitize_filename(name) if name else None
        if not safe_name:
            safe_name = token
        base = parent_path / safe_name
        if not file_type:
            return base
        lowered = file_type.lower()
        if lowered in {"doc", "docx", "wiki"}:
            return base.with_suffix(".md")
        if lowered in {"sheet", "sheets", "bitable", "base"}:
            return base.with_suffix(".xlsx")
        if lowered in {"mindnote", "slides", "shortcut"}:
            return base.with_suffix(".md")
        if lowered == "file":
            return base
        if lowered == "folder":
            return base
        return base

    def _emit_progress(
        self,
        stage: str,
        name: Optional[str] = None,
        file_type: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> None:
        if not self._progress_callback:
            return
        expected = self._expected_total
        if expected < self._processed_files:
            expected = self._processed_files
        if expected == 0:
            expected = 1
        self._progress_callback(self._processed_files, expected, name, stage, file_type, detail)

    def _ensure_success(self, payload: Mapping[str, object], context: str) -> Mapping[str, object]:
        code = payload.get("code") if isinstance(payload, Mapping) else None
        if code not in (None, 0):
            msg = payload.get("msg") or payload.get("message") or str(payload)
            raise RuntimeError(f"{context}失败: code={code}, message={msg}")
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if isinstance(data, Mapping):
            return data
        return {}

    def _finalize_local_path(self, expected: Optional[Path], file_type: str, name: str, parent_path: Path) -> Optional[Path]:
        if expected is None:
            return None
        root_base = self._context.storage.root.resolve()
        absolute = (self._context.storage.root / expected).resolve()
        if absolute.exists():
            return expected

        parent_dir = absolute.parent
        safe_name = sanitize_filename(name) if name else expected.stem

        if file_type in {"doc", "docx", "wiki", "slides", "mindnote", "shortcut"}:
            candidate = parent_dir / f"{safe_name}.md"
            if candidate.exists():
                return candidate.relative_to(root_base)

        if file_type in {"sheet", "sheets", "bitable", "base"}:
            candidate = parent_dir / f"{safe_name}.xlsx"
            if candidate.exists():
                return candidate.relative_to(root_base)

        if file_type == "file" and parent_dir.exists():
            candidate = parent_dir / safe_name
            if candidate.exists():
                return candidate.relative_to(root_base)

        if file_type == "folder" and absolute.exists():
            return absolute.relative_to(root_base)

        return expected

    def _mark_deleted_tokens(self) -> None:
        if self._plan_only:
            return
        known_tokens = set(self._metadata.tokens())
        stale_tokens = known_tokens - self._current_tokens
        for token in stale_tokens:
            entry = self._metadata.get(token)
            if not entry:
                continue
            if self._clean_deleted:
                path = self._metadata.resolve_path(entry)
                try:
                    if path.exists():
                        if path.is_dir():
                            shutil.rmtree(path)
                        else:
                            path.unlink()
                except OSError:
                    pass
                self._metadata.remove(token)
            else:
                self._metadata.mark_deleted(token)
