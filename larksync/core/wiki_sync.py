"""Utilities for syncing wiki spaces."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Set, Tuple

from ..storage import MetadataStore, StorageManager
from ..utils.filesystem import sanitize_filename
from ..utils.time import normalize_timestamp
from .adapters.drive_adapter import DriveAdapter
from .adapters.wiki_adapter import WikiAdapter
from .models import SyncTask
from .registry import DownloaderRegistry
from .sync_engine import SyncEngine

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class WikiSyncContext:
    """Context object holding dependencies for wiki sync operations."""

    engine: SyncEngine
    wiki: WikiAdapter
    drive: DriveAdapter
    registry: DownloaderRegistry
    storage: StorageManager


@dataclass(slots=True)
class PlannedWikiNode:
    """Represents a wiki node planned for download."""

    node_token: str
    obj_token: Optional[str]
    obj_type: Optional[str]
    title: str
    parent_path: Path
    edit_time: Optional[str]
    source_url: Optional[str]
    has_child: bool
    space_id: str
    # 快捷方式支持：记录原始类型和目标信息
    is_shortcut: bool = False
    original_obj_type: Optional[str] = None  # 原始类型（shortcut）
    shortcut_target_token: Optional[str] = None  # 目标文档 token
    shortcut_target_type: Optional[str] = None  # 目标文档类型
    expected_local_path: Optional[Path] = None


class DiscoveryLimitReached(RuntimeError):
    """Raised internally when discovery should stop due to reaching the limit."""


class WikiSpaceSynchronizer:
    """Traverse a wiki space and download every node's underlying document."""

    def __init__(
        self,
        context: WikiSyncContext,
        metadata_store: MetadataStore,
        *,
        limit: Optional[int] = None,
        incremental: bool = True,
        force_on_missing: bool = True,
        progress_callback: Optional[
            Callable[[int, int, Optional[str], str, Optional[str], Optional[str]], None]
        ] = None,
        progress_tracker: Any = None,
        plan_only: bool = False,
    ):
        self._context = context
        self._metadata = metadata_store
        self._visited: Set[str] = set()
        # 跨知识库访问记录，防止 shortcut 循环引用导致无限递归
        self._visited_origins: Set[Tuple[str, str]] = set()  # (space_id, node_token)
        self._limit = limit
        self._incremental = incremental
        self._force_on_missing = force_on_missing
        self._progress_callback = progress_callback
        self._progress_tracker = progress_tracker
        self._plan_only = plan_only

        self._processed_files = 0
        self._processed_folders = 0
        self._skip_count = 0
        self._error_count = 0
        self._total_discovered = 0
        self._download_total = 0
        self._expected_total = 0
        self._discovery_truncated = False

        self._download_candidates: List[PlannedWikiNode] = []
        self._current_tokens: Set[str] = set()
        self._entry_root: Optional[Path] = None
        self._resolved_obj_paths: Dict[str, Path] = {}

        self._summary: Dict[str, Any] = {
            "root": {},
            "total_files": 0,
            "total_folders": 0,
            "will_download": 0,
            "existing": 0,
            "skipped": 0,
            "limit": limit,
            "incremental": incremental,
            "samples": [],
            "discovery_truncated": False,
        }

    def list_spaces(self) -> List[Dict[str, Any]]:
        """获取用户可访问的知识库列表。

        Returns:
            知识库列表，每个元素包含 space_id, name, description 等信息
        """
        spaces: List[Dict[str, Any]] = []
        page_token: Optional[str] = None

        while True:
            response = self._context.wiki.list_spaces(page_token=page_token)
            data = self._ensure_success(response, "获取知识库列表")
            items = data.get("items") or []
            for item in items:
                spaces.append({
                    "space_id": item.get("space_id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                    "wiki_url": item.get("wiki_url"),
                })
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

        return spaces

    def sync(self, space_id: str) -> None:
        """同步指定的知识库。

        Args:
            space_id: 知识库 ID
        """
        # 重置状态
        self._visited = set()
        self._visited_origins = set()
        self._current_tokens = set()
        self._download_candidates = []
        self._skip_count = 0
        self._total_discovered = 0
        self._download_total = 0
        self._processed_files = 0
        self._processed_folders = 0
        self._expected_total = 0
        self._discovery_truncated = False
        self._error_count = 0
        self._resolved_obj_paths = {}

        # 获取知识库信息
        space_info = self._fetch_space_info(space_id)
        space_name = space_info.get("name") or space_id
        safe_space_name = sanitize_filename(space_name) or space_id

        # 使用知识库名作为根目录
        relative_root = Path(f"wiki_{safe_space_name}_{space_id[:8]}")
        self._entry_root = relative_root

        self._summary = {
            "root": {"space_id": space_id, "name": space_name},
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
                token=space_id,
                name=space_name,
                file_type="wiki_space",
                parent_path=Path("."),
                modified_time=None,
                source_url=space_info.get("wiki_url"),
                local_path=relative_root,
            )

        self._current_tokens.add(space_id)

        # 发现阶段：遍历知识库节点
        try:
            self._discover_nodes(space_id, None, relative_root)
        except DiscoveryLimitReached:
            self._discovery_truncated = True

        # 准备下载队列
        if self._limit is not None and self._limit > 0:
            download_queue = self._download_candidates[: self._limit]
        else:
            download_queue = list(self._download_candidates)

        self._resolved_obj_paths = self._build_resolved_obj_paths(download_queue)

        self._download_total = len(download_queue)
        self._summary["total_files"] = self._total_discovered
        self._summary["total_folders"] = self._processed_folders
        self._summary["will_download"] = self._download_total
        self._summary["existing"] = self._skip_count
        self._summary["skipped"] = self._skip_count
        self._summary["discovery_truncated"] = self._discovery_truncated

        # 通知进度追踪器发现阶段结束
        if self._progress_tracker and hasattr(self._progress_tracker, "announce_plan"):
            pending_limit = len(self._download_candidates) - self._download_total
            self._progress_tracker.announce_plan(
                total_found=self._total_discovered,
                to_download=self._download_total,
                skipped=self._skip_count,
                pending_limit=pending_limit,
                truncated=self._discovery_truncated,
            )

        if self._plan_only or self._download_total == 0:
            if not self._plan_only:
                self._metadata.flush()
            return

        # 下载阶段
        self._expected_total = self._download_total
        self._perform_downloads(download_queue)
        self._metadata.flush()

    def summary(self) -> Dict[str, Any]:
        """返回同步统计信息。"""
        return {
            "root": self._summary.get("root"),
            "total_files": self._summary.get("total_files", 0),
            "total_folders": self._processed_folders,
            "will_download": self._summary.get("will_download", 0),
            "existing": self._summary.get("existing", 0),
            "skipped": self._summary.get("skipped", 0),
            "errors": self._error_count,
            "limit": self._summary.get("limit"),
            "incremental": self._summary.get("incremental"),
            "samples": self._summary.get("samples", []),
            "discovery_truncated": self._summary.get("discovery_truncated", False),
        }

    # ------------------------------------------------------------------ internals

    def _fetch_space_info(self, space_id: str) -> Dict[str, Any]:
        """获取知识库详情。"""
        response = self._context.wiki.get_space(space_id)
        data = self._ensure_success(response, f"获取知识库 {space_id} 信息")
        space = data.get("space") or {}
        return {
            "space_id": space.get("space_id") or space_id,
            "name": space.get("name"),
            "description": space.get("description"),
            "wiki_url": space.get("wiki_url"),
        }

    def _discover_nodes(
        self,
        space_id: str,
        parent_node_token: Optional[str],
        parent_path: Path,
    ) -> None:
        """递归发现知识库节点。"""
        page_token: Optional[str] = None

        while True:
            response = self._context.wiki.list_space_nodes(
                space_id,
                parent_node_token=parent_node_token,
                page_token=page_token,
            )
            data = self._ensure_success(response, f"获取节点列表 {space_id}")
            items = data.get("items") or []

            for item in items:
                self._process_node(item, space_id, parent_path)

            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

    def _process_node(
        self,
        item: Mapping[str, Any],
        space_id: str,
        parent_path: Path,
    ) -> None:
        """处理单个节点。"""
        node_token = item.get("node_token")
        if not node_token:
            return

        if node_token in self._visited:
            return

        title = item.get("title") or node_token
        obj_type = item.get("obj_type")
        obj_token = item.get("obj_token")
        has_child = item.get("has_child", False)
        edit_time_raw = item.get("obj_edit_time") or item.get("node_create_time")
        edit_time = normalize_timestamp(edit_time_raw)
        origin_url = item.get("origin_url")

        # 标记已访问
        self._visited.add(node_token)
        self._current_tokens.add(node_token)

        # 获取节点详情以检测 shortcut 类型
        # list_space_nodes 返回的 obj_type 是底层文档类型，不是节点类型
        # 只有 get_node 返回的 node_type 才能判断是否是 shortcut
        node_detail = self._get_node_detail(node_token)
        node_type = node_detail.get("node_type") if node_detail else None
        is_shortcut_node = node_type == "shortcut"

        # 对于 shortcut 节点，检查是否有原始位置的子节点需要遍历
        origin_space_id = None
        origin_node_token = None
        if is_shortcut_node and node_detail:
            origin_space_id = node_detail.get("origin_space_id")
            origin_node_token = node_detail.get("origin_node_token")

        # 确定是否有子节点需要遍历
        # 对于 shortcut 节点：has_child 可能为 False（当前知识库无子节点），
        # 但原始位置可能有子节点
        should_traverse_children = has_child
        traverse_space_id = space_id
        traverse_parent_token = node_token

        if is_shortcut_node and origin_space_id and origin_node_token:
            # 检查是否已经访问过这个原始位置，防止循环引用
            origin_key = (origin_space_id, origin_node_token)
            if origin_key not in self._visited_origins:
                self._visited_origins.add(origin_key)
                # 使用原始位置遍历子节点
                should_traverse_children = True
                traverse_space_id = origin_space_id
                traverse_parent_token = origin_node_token
                logger.debug(
                    f"Shortcut {node_token} -> origin {origin_space_id}/{origin_node_token}"
                )
            else:
                logger.debug(
                    f"Shortcut {node_token} 的原始位置已访问，跳过子节点遍历"
                )

        # 如果有子节点，创建文件夹并递归
        if should_traverse_children:
            safe_title = sanitize_filename(title) or node_token
            folder_name = self._append_token_suffix(safe_title, node_token, treat_as_file=False)
            folder_path = parent_path / folder_name

            if not self._plan_only:
                self._context.storage.ensure_document_dir(folder_path)
                self._record_metadata(
                    token=node_token,
                    name=title,
                    file_type="wiki_folder",
                    parent_path=parent_path,
                    modified_time=edit_time,
                    source_url=origin_url,
                    local_path=folder_path,
                )

            self._processed_folders += 1

            # 递归获取子节点（可能是原始知识库的子节点）
            self._discover_nodes(traverse_space_id, traverse_parent_token, folder_path)

        # 如果节点有关联的文档，添加到下载候选列表
        if obj_type and obj_token:
            # 处理快捷方式：解析目标文档信息
            is_shortcut = False
            original_obj_type = None
            shortcut_target_token = None
            shortcut_target_type = None
            actual_obj_type = obj_type
            actual_obj_token = obj_token

            # 使用已获取的 node_detail 来判断是否是 shortcut
            if is_shortcut_node or (obj_type and obj_type.lower() == "shortcut"):
                is_shortcut = True
                original_obj_type = obj_type
                # 使用已获取的 node_detail 或重新获取
                try:
                    shortcut_info = self._resolve_shortcut_from_detail(node_detail) if node_detail else self._resolve_shortcut(node_token)
                    if shortcut_info:
                        shortcut_target_token = shortcut_info.get("target_token")
                        shortcut_target_type = shortcut_info.get("target_type")
                        if shortcut_target_token and shortcut_target_type:
                            # 使用目标类型和 token
                            actual_obj_type = shortcut_target_type
                            actual_obj_token = shortcut_target_token
                            logger.debug(
                                f"Shortcut {node_token} -> {shortcut_target_type}/{shortcut_target_token}"
                            )
                        else:
                            logger.warning(
                                f"Shortcut {node_token} 没有有效的目标信息，跳过"
                            )
                            self._skip_count += 1
                            return
                    else:
                        logger.warning(
                            f"无法解析快捷方式 {node_token} 的目标信息，跳过"
                        )
                        self._skip_count += 1
                        return
                except Exception as e:
                    logger.warning(f"获取快捷方式 {node_token} 详情失败: {e}")
                    self._skip_count += 1
                    return

            self._total_discovered += 1
            self._notify_discovery(title, actual_obj_type)

            # 检查是否需要下载（增量同步）
            # 使用 node_token 作为增量判断的 key，这样同一目标的不同快捷方式可以独立同步
            resource_type = self._normalize_type(actual_obj_type)
            current_meta: Dict[str, Any] = {"modified_time": edit_time}
            if resource_type:
                current_meta["file_type"] = resource_type

            expected_local_path = self._expected_local_path(
                resource_type, title, parent_path, node_token
            )

            should_download = self._metadata.should_download(
                node_token,
                current_meta=current_meta,
                expected_local_path=expected_local_path,
                incremental=self._incremental,
                force_on_missing=self._force_on_missing,
                parent_path=parent_path,
            )

            if should_download:
                planned = PlannedWikiNode(
                    node_token=node_token,
                    obj_token=actual_obj_token,
                    obj_type=actual_obj_type,
                    title=title,
                    parent_path=parent_path,
                    edit_time=edit_time,
                    source_url=origin_url,
                    has_child=has_child,
                    space_id=space_id,
                    is_shortcut=is_shortcut,
                    original_obj_type=original_obj_type,
                    shortcut_target_token=shortcut_target_token,
                    shortcut_target_type=shortcut_target_type,
                    expected_local_path=expected_local_path,
                )
                self._download_candidates.append(planned)

                # 检查是否达到限制
                if self._limit_reached():
                    raise DiscoveryLimitReached()
            else:
                self._skip_count += 1

    def _get_node_detail(self, node_token: str) -> Optional[Dict[str, Any]]:
        """获取节点详情，用于检测 shortcut 类型和获取原始位置信息。

        Args:
            node_token: 节点 token

        Returns:
            节点详情字典，或 None
        """
        try:
            response = self._context.wiki.get_node(node_token)
            data = self._ensure_success(response, f"获取节点详情 {node_token}")
            return data.get("node") or {}
        except Exception as e:
            logger.warning(f"获取节点详情失败 {node_token}: {e}")
            return None

    def _resolve_shortcut(self, node_token: str) -> Optional[Dict[str, Any]]:
        """解析快捷方式，获取目标文档信息。

        Args:
            node_token: 快捷方式节点的 token

        Returns:
            包含 target_token 和 target_type 的字典，或 None
        """
        node_detail = self._get_node_detail(node_token)
        if node_detail:
            return self._resolve_shortcut_from_detail(node_detail)
        return None

    def _resolve_shortcut_from_detail(
        self, node_info: Mapping[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """从已获取的节点详情中解析快捷方式目标信息。

        Args:
            node_info: 节点详情（get_node 返回的 node 对象）

        Returns:
            包含 target_token 和 target_type 的字典，或 None
        """
        try:
            # 尝试从 shortcut_info 获取目标信息
            shortcut_info = node_info.get("shortcut_info")
            if isinstance(shortcut_info, Mapping):
                target_token = shortcut_info.get("target_token")
                target_type = shortcut_info.get("target_type")
                if target_token and target_type:
                    return {
                        "target_token": target_token,
                        "target_type": target_type,
                    }

            # 备选：直接从 node_info 获取 obj_token 和 obj_type（某些 API 版本）
            obj_token = node_info.get("obj_token")
            obj_type = node_info.get("obj_type")
            if obj_token and obj_type and obj_type.lower() != "shortcut":
                return {
                    "target_token": obj_token,
                    "target_type": obj_type,
                }

            return None
        except Exception as e:
            logger.warning(f"解析快捷方式详情失败: {e}")
            return None

    def _notify_discovery(self, name: Optional[str], file_type: Optional[str]) -> None:
        """通知发现进度。"""
        total = max(self._total_discovered, 1)
        if self._progress_tracker and hasattr(self._progress_tracker, "show_discovery"):
            self._progress_tracker.show_discovery(self._total_discovered, name)
        elif self._progress_callback:
            self._progress_callback(
                self._total_discovered, total, name, "discover", file_type, None
            )

    def _perform_downloads(self, queue: List[PlannedWikiNode]) -> None:
        """执行下载队列。"""
        serialized_paths = self._serialize_resolved_paths(self._resolved_obj_paths)

        for index, item in enumerate(queue, start=1):
            processed_before = index - 1
            self._notify_download_progress("start", item, processed_before, None)

            # 构建下载任务
            resource_type = self._normalize_type(item.obj_type)
            if not resource_type:
                self._error_count += 1
                self._notify_download_progress(
                    "failed", item, index, f"未知类型: {item.obj_type}"
                )
                continue

            safe_title = sanitize_filename(item.title) or item.node_token
            extra: Dict[str, Any] = {
                "source_url": item.source_url,
                "wiki_node_token": item.node_token,
                "wiki_space_id": item.space_id,
            }
            if self._entry_root is not None:
                extra["entry_root"] = self._entry_root.as_posix()
            if serialized_paths:
                extra["_resolved_paths"] = serialized_paths

            # 快捷方式：记录额外信息
            if item.is_shortcut:
                extra["is_shortcut"] = True
                extra["original_obj_type"] = item.original_obj_type
                extra["shortcut_target_token"] = item.shortcut_target_token
                extra["shortcut_target_type"] = item.shortcut_target_type

            output_filename = item.expected_local_path.name if item.expected_local_path else None

            task = SyncTask(
                token=item.obj_token or item.node_token,
                file_type=resource_type,
                name=safe_title,
                parent_path=item.parent_path,
                extra=extra,
                output_filename=output_filename,
            )

            parent_dir = self._context.storage.root / item.parent_path
            parent_dir.mkdir(parents=True, exist_ok=True)
            pre_snapshot = self._snapshot_files(parent_dir)

            try:
                self._context.engine.process_task(task)
            except Exception as exc:
                self._error_count += 1
                self._notify_download_progress("failed", item, index, str(exc))
                logger.warning(
                    "Failed to download wiki node",
                    extra={
                        "node_token": item.node_token,
                        "obj_token": item.obj_token,
                        "is_shortcut": item.is_shortcut,
                        "error": str(exc),
                    },
                )
                continue

            post_snapshot = self._snapshot_files(parent_dir)
            local_path = self._resolve_local_path(
                item,
                resource_type,
                pre_snapshot,
                post_snapshot,
            )

            # 记录元数据
            self._record_metadata(
                token=item.node_token,
                name=item.title,
                file_type=resource_type,
                parent_path=item.parent_path,
                modified_time=item.edit_time,
                source_url=item.source_url,
                local_path=local_path,
            )

            self._notify_download_progress("success", item, index, None)
            self._current_tokens.add(item.node_token)
            if item.obj_token:
                self._current_tokens.add(item.obj_token)
            # 快捷方式：也记录目标 token
            if item.is_shortcut and item.shortcut_target_token:
                self._current_tokens.add(item.shortcut_target_token)

    def _notify_download_progress(
        self,
        stage: str,
        item: PlannedWikiNode,
        processed: int,
        detail: Optional[str],
    ) -> None:
        """通知下载进度。"""
        total = max(self._download_total, 1)
        if self._progress_tracker:
            self._progress_tracker.update(
                processed, total, item.title, stage, item.obj_type, detail
            )
        elif self._progress_callback:
            self._progress_callback(
                processed, total, item.title, stage, item.obj_type, detail
            )

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
    ) -> None:
        """记录元数据。"""
        if self._plan_only:
            return
        self._metadata.mark_synced(
            token,
            name=name,
            file_type=file_type,
            parent_path=parent_path,
            modified_time=modified_time,
            local_path=local_path,
            source_url=source_url,
        )

    def _limit_reached(self) -> bool:
        """检查是否达到下载限制。"""
        return (
            self._limit is not None
            and self._limit > 0
            and len(self._download_candidates) >= self._limit
        )

    @staticmethod
    def _normalize_type(obj_type: Optional[str]) -> Optional[str]:
        """将 Wiki 节点类型转换为下载器类型。"""
        if not obj_type:
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
        }
        lower = obj_type.lower()
        return mapping.get(lower, lower if lower in mapping.values() else None)

    @staticmethod
    def _expected_local_path(
        file_type: Optional[str],
        title: str,
        parent_path: Path,
        fallback_token: str,
    ) -> Optional[Path]:
        """推断 Wiki 节点的本地路径（用于增量判断）。"""
        safe_title = sanitize_filename(title) or fallback_token
        if not file_type:
            return None
        if file_type in {"docx", "doc", "wiki", "slides", "mindnote"}:
            filename = WikiSpaceSynchronizer._append_token_suffix(
                f"{safe_title}.md",
                fallback_token,
                treat_as_file=True,
            )
            return parent_path / filename
        if file_type in {"sheet", "bitable"}:
            filename = WikiSpaceSynchronizer._append_token_suffix(
                f"{safe_title}.xlsx",
                fallback_token,
                treat_as_file=True,
            )
            return parent_path / filename
        # 文件类无法可靠预测文件名，留空避免误判
        return None

    @staticmethod
    def _append_token_suffix(name: str, token: str, *, treat_as_file: bool) -> str:
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

    def _build_resolved_obj_paths(self, queue: List[PlannedWikiNode]) -> Dict[str, Path]:
        path_sets: Dict[str, Set[Path]] = {}
        for item in queue:
            if not item.obj_token or item.expected_local_path is None:
                continue
            path_sets.setdefault(item.obj_token, set()).add(item.expected_local_path)

        resolved: Dict[str, Path] = {}
        for token, paths in path_sets.items():
            if len(paths) == 1:
                resolved[token] = next(iter(paths))
        return resolved

    def _serialize_resolved_paths(self, mapping: Mapping[str, Path]) -> Dict[str, str]:
        serialized: Dict[str, str] = {}
        for token, path in mapping.items():
            serialized[token] = path.as_posix()
        return serialized

    def _snapshot_files(self, base_dir: Path) -> Set[Path]:
        if not base_dir.exists():
            return set()
        return {path for path in base_dir.rglob("*") if path.is_file()}

    def _resolve_local_path(
        self,
        item: PlannedWikiNode,
        resource_type: str,
        pre_snapshot: Set[Path],
        post_snapshot: Set[Path],
    ) -> Optional[Path]:
        expected = item.expected_local_path
        if expected is not None:
            expected_abs = self._context.storage.root / expected
            if expected_abs.exists():
                return expected

        new_files = [path for path in (post_snapshot - pre_snapshot) if path.is_file()]
        if not new_files:
            return expected

        priority = {
            "docx": [".md"],
            "wiki": [".md"],
            "slides": [".md"],
            "mindnote": [".md"],
            "sheet": [".xlsx", ".csv"],
            "bitable": [".xlsx", ".csv"],
            "file": [],
        }
        preferred = priority.get(resource_type, [])

        def sort_key(path: Path) -> tuple[int, float]:
            suffix = path.suffix.lower()
            if suffix in preferred:
                suffix_rank = preferred.index(suffix)
            else:
                suffix_rank = len(preferred) + 1
            return (suffix_rank, -path.stat().st_mtime)

        new_files.sort(key=sort_key)
        chosen = new_files[0]
        try:
            return chosen.relative_to(self._context.storage.root)
        except ValueError:
            return expected

    @staticmethod
    def _ensure_success(
        payload: Mapping[str, Any], context: str
    ) -> Mapping[str, Any]:
        """确保 API 响应成功。"""
        code = payload.get("code") if isinstance(payload, Mapping) else None
        if code not in (None, 0):
            msg = payload.get("msg") or payload.get("message") or str(payload)
            raise RuntimeError(f"{context}失败: code={code}, message={msg}")
        data = payload.get("data") if isinstance(payload, Mapping) else None
        if isinstance(data, Mapping):
            return data
        return {}
