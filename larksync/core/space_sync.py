"""Utilities for syncing the entire personal space."""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Set

from ..storage import MetadataStore, StorageManager
from ..utils.filesystem import sanitize_filename
from ..utils.time import normalize_timestamp
from .adapters.drive_adapter import DriveAdapter
from .models import SyncTask
from .registry import DownloaderRegistry
from .sync_engine import SyncEngine

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class SpaceSyncContext:
    engine: SyncEngine
    drive: DriveAdapter
    registry: DownloaderRegistry
    storage: StorageManager




@dataclass(slots=True)
class PlannedFile:
    token: str
    actual_token: str
    raw_type: str
    file_type: str
    name: str
    parent_path: Path
    modified_time: Optional[str]
    source_url: Optional[str]
    expected_local_path: Optional[Path]
    current_meta: Mapping[str, Any]
    extra: Dict[str, Any]


class DiscoveryLimitReached(RuntimeError):
    """Raised internally when discovery should stop due to reaching the limit."""


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
        progress_tracker: Any | None = None,
        plan_only: bool = False,
    ):
        self._context = context
        self._metadata = metadata_store
        self._visited: set[str] = set()
        self._limit = limit
        self._processed_files = 0
        self._processed_folders = 0  # 新增：统计文件夹数量
        self._incremental = incremental
        self._force_on_missing = force_on_missing
        self._clean_deleted = clean_deleted
        self._current_tokens: Set[str] = set()
        self._progress_callback = progress_callback
        self._progress_tracker = progress_tracker
        self._expected_total = 0
        self._plan_only = plan_only
        self._download_candidates: List[PlannedFile] = []
        self._pending_limit: List[PlannedFile] = []
        self._skip_count = 0
        self._error_count = 0  # 新增：错误计数
        self._total_discovered = 0
        self._download_total = 0
        # 路径注册表：跟踪每个父目录下已使用的文件名，防止同名文件覆盖
        # 格式: {parent_path_posix: {filename: token, ...}, ...}
        self._path_registry: Dict[str, Dict[str, str]] = {}
        self._entry_root: Optional[Path] = None
        self._resolved_obj_paths: Dict[str, Path] = {}
        self._summary: Dict[str, Any] = {
            "root": {},
            "total_files": 0,
            "total_folders": 0,  # 新增：文件夹统计
            "will_download": 0,
            "existing": 0,
            "skipped": 0,
            "limit": limit,
            "incremental": incremental,
            "samples": [],
            "discovery_truncated": False,
        }
        self._discovery_truncated = False
        self._user_identity: Optional[Dict[str, str]] = None

    def sync(self) -> None:
        # 重置本次运行的状态
        self._visited = set()
        self._current_tokens = set()
        self._download_candidates = []
        self._pending_limit = []
        self._skip_count = 0
        self._total_discovered = 0
        self._download_total = 0
        self._processed_files = 0
        self._processed_folders = 0
        self._expected_total = 0
        self._discovery_truncated = False
        self._user_identity = self._fetch_user_identity()
        self._resolved_obj_paths = {}
        # 从 metadata 加载已有的路径注册表，保持已有文件的路径不变
        self._path_registry = self._load_existing_path_registry()

        root_meta = self._fetch_root_meta()
        root_token = root_meta["token"]
        root_name = root_meta["name"]
        root_modified = root_meta.get("modified_time")

        base_title, include_token = self._resolve_root_title(root_name, root_token)
        if include_token:
            relative_root = Path(self._append_token_suffix(base_title, root_token, treat_as_file=False))
        else:
            relative_root = Path(base_title)
        self._entry_root = relative_root
        self._summary = {
            "root": {"token": root_token, "name": root_name},
            "total_files": 0,
            "total_folders": 0,
            "will_download": 0,
            "existing": 0,
            "skipped": 0,
            "limit": self._limit,
            "incremental": self._incremental,
            "samples": [],
            "discovery_truncated": False,
        }

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

        try:
            self._discover_folder(root_token, relative_root)
        except DiscoveryLimitReached:
            self._discovery_truncated = True

        if self._limit is not None and self._limit > 0:
            download_queue = self._download_candidates[: self._limit]
            self._pending_limit = self._download_candidates[self._limit :]
        else:
            download_queue = list(self._download_candidates)
            self._pending_limit = []

        self._download_total = len(download_queue)
        self._resolved_obj_paths = self._build_resolved_obj_paths(download_queue)
        self._summary["total_files"] = self._total_discovered
        self._summary["total_folders"] = self._processed_folders
        self._summary["will_download"] = self._download_total
        self._summary["existing"] = self._skip_count
        self._summary["skipped"] = self._skip_count
        self._summary["discovery_truncated"] = self._discovery_truncated

        if self._progress_tracker and hasattr(self._progress_tracker, "announce_plan"):
            self._progress_tracker.announce_plan(
                total_found=self._total_discovered,
                to_download=self._download_total,
                skipped=self._skip_count,
                pending_limit=len(self._pending_limit),
                truncated=self._discovery_truncated,
            )

        if self._plan_only or self._download_total == 0:
            if not self._plan_only:
                if self._incremental:
                    self._mark_deleted_tokens()
                self._metadata.flush()
            self._processed_files = 0
            return

        self._expected_total = self._download_total
        self._perform_downloads(download_queue)

        if self._incremental:
            self._mark_deleted_tokens()
        self._metadata.flush()
        self._processed_files = 0

    def summary(self) -> Dict[str, Any]:
        return {
            "root": self._summary.get("root"),
            "total_files": self._summary.get("total_files", 0),
            "total_folders": self._processed_folders,  # 返回文件夹统计
            "will_download": self._summary.get("will_download", 0),
            "existing": self._summary.get("existing", 0),
            "skipped": self._summary.get("skipped", 0),
            "errors": self._error_count,  # 新增：错误统计
            "limit": self._summary.get("limit"),
            "incremental": self._summary.get("incremental"),
            "samples": self._summary.get("samples", []),
            "discovery_truncated": self._summary.get("discovery_truncated", False),
        }

    # ------------------------------------------------------------------ internals

    def _fetch_root_meta(self) -> Dict[str, Optional[str]]:
        payload = self._context.drive.get_root_folder_meta()
        data = self._ensure_success(payload, "获取根目录信息")
        token = data.get("token") or data.get("folder_token")
        if not token:
            raise RuntimeError("Failed to resolve root folder token")
        name = data.get("name") or token
        modified = (
            data.get("update_time") or data.get("latest_modify_time") or data.get("modify_time") or data.get("modified_time")
        )
        return {
            "token": str(token),
            "name": str(name),
            "modified_time": normalize_timestamp(modified),
        }

    def _fetch_user_identity(self) -> Optional[Dict[str, str]]:
        identity = self._fetch_user_identity_from_auth()
        if identity:
            logger.info(
                "Resolved user identity via auth API",
                extra={"user_id": identity.get("user_id"), "user_name": identity.get("user_name")},
            )
            return identity
        identity = self._fetch_user_identity_from_contact()
        if identity:
            logger.info(
                "Resolved user identity via contact API",
                extra={"user_id": identity.get("user_id"), "user_name": identity.get("user_name")},
            )
        else:
            logger.warning("Unable to resolve user identity; fallback to root name/token")
        return identity

    def _fetch_user_identity_from_auth(self) -> Optional[Dict[str, str]]:
        try:
            payload = self._context.drive.get_user_info()
        except Exception:
            return None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if not isinstance(data, Mapping):
            return None
        user_id = data.get("user_id")
        user_name = data.get("name") or data.get("en_name")
        if not user_id:
            logger.debug("Auth user_info missing user_id", extra={"has_name": bool(user_name)})
            return None
        return {
            "user_id": str(user_id),
            "user_name": str(user_name) if user_name else "",
        }

    def _fetch_user_identity_from_contact(self) -> Optional[Dict[str, str]]:
        try:
            payload = self._context.drive.get_current_user()
        except Exception:
            return None
        data = payload.get("data") if isinstance(payload, Mapping) else None
        user = data.get("user") if isinstance(data, Mapping) else None
        if not isinstance(user, Mapping):
            return None
        user_id = user.get("user_id")
        user_name = user.get("name") or user.get("user_name") or user.get("display_name")
        if not user_id:
            logger.debug("Contact users/me missing user_id", extra={"has_name": bool(user_name)})
            return None
        return {
            "user_id": str(user_id),
            "user_name": str(user_name) if user_name else "",
        }

    def _resolve_root_title(self, root_name: str, root_token: str) -> tuple[str, bool]:
        identity = self._user_identity or {}
        user_id = identity.get("user_id") or ""
        user_name = identity.get("user_name") or ""
        if user_id:
            display = f"{user_name}_{user_id}".strip("_")
            safe_display = sanitize_filename(display)
            if safe_display:
                return safe_display, False
        return sanitize_filename(root_name) or root_token, True

    def _discover_folder(self, folder_token: str, relative_path: Path) -> None:
        page_token: Optional[str] = None
        while True:
            payload = self._context.drive.list_folder_children(folder_token, page_token=page_token)
            data = self._ensure_success(payload, f"获取文件夹 {folder_token} 列表")
            files = data.get("files") or []
            for item in files:
                self._process_entry(item, relative_path)
            if not data.get("has_more"):
                break
            page_token = data.get("next_page_token")
            if not page_token:
                break

    def _process_entry(
        self,
        item: Mapping[str, object],
        parent_path: Path,
    ) -> None:
        raw_type = str(item.get("type") or "").lower()
        token = self._extract_token(item)
        if not token:
            return

        name = str(item.get("name") or token)
        modified_time_raw = (
            item.get("latest_modify_time")
            or item.get("update_time")
            or item.get("modify_time")
            or item.get("modified_time")
        )
        modified_time = normalize_timestamp(modified_time_raw)
        source_url = item.get("url") if isinstance(item.get("url"), str) else None

        current_meta: Dict[str, Any] = {
            "modified_time": modified_time,
            "revision": item.get("revision") or item.get("rev"),
            "checksum": item.get("checksum"),
        }

        if raw_type == "folder":
            safe_name = sanitize_filename(name) or token
            folder_name = self._append_token_suffix(safe_name, token, treat_as_file=False)
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
            self._current_tokens.add(token)
            self._processed_folders += 1
            self._discover_folder(token, folder_path)
            return

        self._total_discovered += 1
        self._notify_discovery(name, raw_type or None)

        file_type = self._normalize_type(raw_type)
        actual_token = token
        extra: Dict[str, Any] = {}
        if source_url:
            extra["source_url"] = source_url
        if self._entry_root is not None:
            extra["entry_root"] = self._entry_root.as_posix()

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
                expected_local_path = self._expected_local_path(token, "shortcut", name, parent_path)
                self._register_skip(
                    token=token,
                    actual_token=token,
                    raw_type=raw_type,
                    file_type="shortcut",
                    name=name,
                    parent_path=parent_path,
                    modified_time=modified_time,
                    source_url=source_url,
                    expected_local_path=expected_local_path,
                    current_meta=current_meta,
                )
                return

        if not file_type:
            expected_local_path = self._expected_local_path(token, raw_type, name, parent_path)
            self._register_skip(
                token=token,
                actual_token=actual_token,
                raw_type=raw_type,
                file_type=raw_type or "unknown",
                name=name,
                parent_path=parent_path,
                modified_time=modified_time,
                source_url=source_url,
                expected_local_path=expected_local_path,
                current_meta=current_meta,
            )
            return

        if actual_token in self._visited:
            expected_local_path = self._expected_local_path(actual_token, file_type, name, parent_path)
            self._register_skip(
                token=token,
                actual_token=actual_token,
                raw_type=raw_type,
                file_type=file_type,
                name=name,
                parent_path=parent_path,
                modified_time=modified_time,
                source_url=source_url,
                expected_local_path=expected_local_path,
                current_meta=current_meta,
            )
            return

        expected_local_path = self._expected_local_path(actual_token, file_type, name, parent_path)

        should_download = self._metadata.should_download(
            actual_token,
            current_meta=current_meta,
            expected_local_path=expected_local_path,
            incremental=self._incremental,
            force_on_missing=self._force_on_missing,
            parent_path=parent_path,
        )

        if should_download:
            planned = PlannedFile(
                token=token,
                actual_token=actual_token,
                raw_type=raw_type,
                file_type=file_type,
                name=name,
                parent_path=parent_path,
                modified_time=modified_time,
                source_url=source_url,
                expected_local_path=expected_local_path,
                current_meta=current_meta,
                extra=extra,
            )
            self._download_candidates.append(planned)
            if self._plan_only:
                detail = expected_local_path.as_posix() if expected_local_path else None
                self._track_item("download", name, file_type, detail)
        else:
            self._register_skip(
                token=token,
                actual_token=actual_token,
                raw_type=raw_type,
                file_type=file_type,
                name=name,
                parent_path=parent_path,
                modified_time=modified_time,
                source_url=source_url,
                expected_local_path=expected_local_path,
                current_meta=current_meta,
            )
            return

        self._visited.add(actual_token)
        self._current_tokens.add(actual_token)
        if raw_type == "shortcut":
            self._visited.add(token)
            self._current_tokens.add(token)

        if self._limit_reached():
            raise DiscoveryLimitReached()

    def _notify_discovery(self, name: Optional[str], file_type: Optional[str]) -> None:
        total = max(self._total_discovered, 1)
        if self._progress_tracker and hasattr(self._progress_tracker, "show_discovery"):
            self._progress_tracker.show_discovery(self._total_discovered, name)
        elif self._progress_callback:
            self._progress_callback(self._total_discovered, total, name, "discover", file_type, None)

    def _register_skip(
        self,
        *,
        token: str,
        actual_token: str,
        raw_type: str,
        file_type: Optional[str],
        name: str,
        parent_path: Path,
        modified_time: Optional[str],
        source_url: Optional[str],
        expected_local_path: Optional[Path],
        current_meta: Mapping[str, Any],
    ) -> None:
        effective_type = file_type or raw_type or "unknown"
        detail = expected_local_path.as_posix() if expected_local_path else None
        self._skip_count += 1
        if self._plan_only:
            self._track_item("existing", name, effective_type, detail)
        if not self._plan_only:
            self._record_metadata(
                token=actual_token,
                name=name,
                file_type=effective_type,
                parent_path=parent_path,
                modified_time=modified_time,
                source_url=source_url,
                local_path=expected_local_path,
                revision=current_meta.get("revision"),
                checksum=current_meta.get("checksum"),
            )
        self._visited.add(actual_token)
        self._current_tokens.add(actual_token)
        if raw_type == "shortcut":
            self._visited.add(token)
            self._current_tokens.add(token)
            # 注册快捷方式映射关系（即使跳过下载也要记录）
            self._register_shortcut_mapping(token, actual_token, effective_type)

    def _perform_downloads(self, queue: List[PlannedFile]) -> None:
        serialized_paths = self._serialize_resolved_paths(self._resolved_obj_paths)
        for index, item in enumerate(queue, start=1):
            processed_before = index - 1
            self._notify_download_progress("start", item, processed_before, None)
            # 从 expected_local_path 提取输出文件名（可能带 token 后缀）
            output_filename = item.expected_local_path.name if item.expected_local_path else None
            extra = dict(item.extra) if item.extra else {}
            if serialized_paths:
                extra["_resolved_paths"] = serialized_paths
            task = SyncTask(
                token=item.actual_token,
                file_type=item.file_type,
                name=item.name,
                parent_path=item.parent_path,
                extra=extra,
                output_filename=output_filename,
            )
            try:
                self._context.engine.process_task(task)
            except Exception as exc:  # pragma: no cover - defensive
                # 记录错误并继续处理下一个文件，不中断整个同步过程
                self._error_count += 1
                self._notify_download_progress("failed", item, index, str(exc))
                self._metadata.mark_missing(
                    item.actual_token,
                    error=str(exc),
                    current_meta=item.current_meta,
                    parent_path=item.parent_path,
                    source_url=item.source_url,
                )
                # 记录当前 token 以便后续处理
                self._current_tokens.add(item.actual_token)
                if item.raw_type == "shortcut":
                    self._current_tokens.add(item.token)
                continue  # 继续处理下一个文件
            local_relative = self._finalize_local_path(item.expected_local_path, item.file_type, item.name, item.parent_path)
            self._record_metadata(
                token=item.actual_token,
                name=item.name,
                file_type=item.file_type,
                parent_path=item.parent_path,
                modified_time=item.modified_time,
                source_url=item.source_url,
                local_path=local_relative,
                revision=item.current_meta.get("revision"),
                checksum=item.current_meta.get("checksum"),
            )
            detail = str(local_relative) if local_relative else None
            self._notify_download_progress("success", item, index, detail)
            self._current_tokens.add(item.actual_token)
            if item.raw_type == "shortcut":
                self._current_tokens.add(item.token)
                # 注册快捷方式映射关系
                self._register_shortcut_mapping(item.token, item.actual_token, item.file_type)

    def _build_resolved_obj_paths(self, queue: List[PlannedFile]) -> Dict[str, Path]:
        path_sets: Dict[str, Set[Path]] = {}
        for item in queue:
            if item.actual_token and item.expected_local_path is not None:
                path_sets.setdefault(item.actual_token, set()).add(item.expected_local_path)

        resolved: Dict[str, Path] = {}
        for token, paths in path_sets.items():
            if len(paths) == 1:
                resolved[token] = next(iter(paths))
        return resolved

    @staticmethod
    def _serialize_resolved_paths(mapping: Mapping[str, Path]) -> Dict[str, str]:
        return {token: path.as_posix() for token, path in mapping.items()}

    def _notify_download_progress(
        self,
        stage: str,
        item: PlannedFile,
        processed: int,
        detail: Optional[str],
    ) -> None:
        total = max(self._download_total, 1)
        if self._progress_tracker:
            self._progress_tracker.update(processed, total, item.name, stage, item.file_type, detail)
        elif self._progress_callback:
            self._progress_callback(processed, total, item.name, stage, item.file_type, detail)

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
    
    def _register_shortcut_mapping(
        self,
        shortcut_token: str,
        target_token: str,
        target_type: str,
    ) -> None:
        """
        注册快捷方式与目标文件的映射关系。
        
        Args:
            shortcut_token: 快捷方式的 token
            target_token: 目标文件的 token
            target_type: 目标文件的类型
        """
        if self._plan_only:
            return
        # 检查 metadata 存储是否支持 register_shortcut 方法
        if hasattr(self._metadata, "register_shortcut"):
            self._metadata.register_shortcut(shortcut_token, target_token, target_type)
    
    def _load_existing_path_registry(self) -> Dict[str, Dict[str, str]]:
        """
        从 metadata 加载已有的路径注册表。
        
        这确保增量同步时，已有文件的路径保持不变，
        只有新的同名文件才会使用带 token 后缀的路径。
        
        Returns:
            路径注册表: {parent_path: {filename: token, ...}, ...}
        """
        registry: Dict[str, Dict[str, str]] = {}
        
        # 遍历所有已有的 metadata 记录
        for token in self._metadata.tokens():
            entry = self._metadata.get(token)
            if not entry:
                continue
            
            local_path = entry.get("local_path")
            if not local_path:
                continue
            
            # 解析路径，提取父目录和文件名
            path = Path(local_path)
            parent_key = path.parent.as_posix()
            filename = path.name
            
            # 注册到路径表
            if parent_key not in registry:
                registry[parent_key] = {}
            
            # 如果该文件名尚未被注册，或者当前 token 更早（保持稳定性）
            if filename not in registry[parent_key]:
                registry[parent_key][filename] = token
        
        return registry

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

    @staticmethod
    def _apply_suffix(name: str, desired: str, known_suffixes: tuple[str, ...]) -> str:
        lower_name = name.lower()
        desired_lower = desired.lower()
        if lower_name.endswith(desired_lower):
            return name
        for suffix in known_suffixes:
            if lower_name.endswith(suffix):
                return name[: -len(suffix)] + desired
        return f"{name}{desired}"

    def _append_token_suffix(self, name: str, token: str, *, treat_as_file: bool) -> str:
        if not token:
            return name
        if treat_as_file:
            path = Path(name)
            stem = path.stem
            suffix = path.suffix
            if stem.endswith(f"_{token}"):
                return name
            return f"{stem}_{token}{suffix}"
        if name.endswith(f"_{token}"):
            return name
        return f"{name}_{token}"

    def _expected_local_path(self, token: str, file_type: Optional[str], name: str, parent_path: Path) -> Optional[Path]:
        """
        计算文件的预期本地路径，并处理同名文件冲突。
        
        当同一父目录下存在多个同名文件（不同token）时，会在文件名后添加token后缀来避免覆盖。
        """
        safe_name = sanitize_filename(name) if name else None
        if not safe_name:
            safe_name = token
        
        # 根据文件类型确定基础文件名
        base_filename = safe_name
        lowered = (file_type or "").lower()
        if lowered in {"doc", "docx", "wiki"}:
            base_filename = self._apply_suffix(safe_name, ".md", (".docx", ".doc", ".md"))
        elif lowered in {"sheet", "sheets", "bitable", "base"}:
            base_filename = self._apply_suffix(safe_name, ".xlsx", (".xlsx", ".xls"))
        elif lowered in {"mindnote", "slides", "shortcut"}:
            base_filename = self._apply_suffix(safe_name, ".md", (".md",))
        
        # 所有 Entry Tree 文件名强制追加 token 后缀
        base_filename = self._append_token_suffix(base_filename, token, treat_as_file=True)

        # 检查同名文件冲突
        final_filename = self._register_and_resolve_path(parent_path, base_filename, token, lowered)
        
        return parent_path / final_filename
    
    def _register_and_resolve_path(
        self,
        parent_path: Path,
        base_filename: str,
        token: str,
        file_type: str,
    ) -> str:
        """
        注册路径并解决同名文件冲突。
        
        Args:
            parent_path: 父目录路径
            base_filename: 基础文件名（带扩展名）
            token: 文件的唯一标识
            file_type: 文件类型
            
        Returns:
            最终的文件名（可能带有token后缀）
        """
        parent_key = parent_path.as_posix()
        
        # 初始化该目录的注册表
        if parent_key not in self._path_registry:
            self._path_registry[parent_key] = {}
        
        registry = self._path_registry[parent_key]
        
        # 如果该文件名已被同一个token使用，直接返回
        if base_filename in registry and registry[base_filename] == token:
            return base_filename
        
        # 如果该文件名未被使用，注册并返回
        if base_filename not in registry:
            registry[base_filename] = token
            return base_filename
        
        # 文件名冲突：需要添加token后缀
        # 分离文件名和扩展名
        if "." in base_filename:
            name_part, ext_part = base_filename.rsplit(".", 1)
            # 使用token的前8位作为后缀，避免文件名过长
            token_suffix = token[:8] if len(token) > 8 else token
            new_filename = f"{name_part}_{token_suffix}.{ext_part}"
        else:
            token_suffix = token[:8] if len(token) > 8 else token
            new_filename = f"{base_filename}_{token_suffix}"
        
        # 注册新的文件名
        registry[new_filename] = token
        
        return new_filename

    def _limit_reached(self) -> bool:
        return self._limit is not None and self._limit > 0 and len(self._download_candidates) >= self._limit

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

        # 如果 expected 路径包含 token 后缀（表示有同名文件冲突），
        # 直接返回 expected，不要尝试查找原始文件名
        safe_name = sanitize_filename(name) if name else expected.stem
        expected_stem = expected.stem
        if expected_stem != safe_name and "_" in expected_stem:
            # expected 可能带有 token 后缀，直接返回
            return expected

        parent_dir = absolute.parent

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
