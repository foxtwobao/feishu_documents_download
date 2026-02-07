"""Downloaders for folder-like resources (folder, shortcut, wiki)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

from ...utils.filesystem import sanitize_filename
from ..api_client import FeishuAPIError
from ..models import SyncTask
from .base_downloader import BaseDownloader


@dataclass(slots=True)
class FolderEntry:
    name: str
    token: str
    file_type: str
    url: Optional[str]
    shortcut_target_token: Optional[str] = None
    shortcut_target_type: Optional[str] = None


class FolderDownloader(BaseDownloader):
    """Produce a manifest for folder contents."""

    file_type = "folder"

    def download(self, task: SyncTask) -> None:
        display_name = self._resolve_display_name(task)
        folder_dir = self._ensure_folder_dir(task, display_name)
        entries = self._collect_entries(task.token)
        results: List[Tuple[FolderEntry, bool, Optional[str]]] = []
        for entry in entries:
            success, note = self._download_entry(task, folder_dir, entry)
            results.append((entry, success, note))
        content = self._render_manifest(task.token, display_name, results)
        self.storage.write_text(folder_dir / "index.md", content)

    def _resolve_display_name(self, task: SyncTask) -> str:
        metadata = self._fetch_metadata(task.token, self.file_type)
        if metadata:
            for key in ("name", "title"):
                if metadata.get(key):
                    return str(metadata[key])
        return task.name or task.token

    def _ensure_folder_dir(self, task: SyncTask, display_name: str) -> Path:
        safe_name = sanitize_filename(display_name) or task.token
        folder_name = f"{safe_name}_{task.token}" if not safe_name.endswith(f"_{task.token}") else safe_name
        relative = Path(task.parent_path) / folder_name
        folder_dir = self.storage.root / relative
        folder_dir.mkdir(parents=True, exist_ok=True)
        return folder_dir

    def _collect_entries(self, folder_token: str) -> List[FolderEntry]:
        entries: List[FolderEntry] = []
        page_token: Optional[str] = None
        while True:
            payload = self.drive_adapter.list_folder_children(folder_token, page_token=page_token)
            data = payload.get("data") or {}
            for item in data.get("files", []):
                entries.append(
                    FolderEntry(
                        name=item.get("name") or item.get("token") or "(untitled)",
                        token=item.get("token") or "",
                        file_type=item.get("type") or "unknown",
                        url=item.get("url"),
                        shortcut_target_token=(item.get("shortcut_info") or {}).get("target_token"),
                        shortcut_target_type=(item.get("shortcut_info") or {}).get("target_type"),
                    )
                )
            if not data.get("has_more"):
                break
            page_token = data.get("next_page_token")
            if not page_token:
                break
        return entries

    def _render_manifest(
        self,
        token: str,
        name: str,
        results: Iterable[Tuple[FolderEntry, bool, Optional[str]]],
    ) -> str:
        lines: List[str] = [f"# {name}", "", f"- 文件夹 token：`{token}`", ""]
        results = list(results)
        if not results:
            lines.append("该文件夹为空。")
            return "\n".join(lines) + "\n"

        lines.append("## 子文件")
        lines.append("")
        for entry, success, note in results:
            link = entry.url or self._build_url(entry.file_type, entry.token)
            detail = f"`{entry.file_type}` token `{entry.token}`"
            if entry.file_type == "shortcut" and entry.shortcut_target_token:
                detail += (
                    f" → 指向 `{entry.shortcut_target_type}` token "
                    f"`{entry.shortcut_target_token}`"
                )
            status = "✅ 已下载" if success else "⚠️ 未下载"
            if note:
                status += f"（{note}）"
            lines.append(f"- [{entry.name}]({link}) — {detail} — {status}")

        lines.append("")
        lines.append(
            "> 系统已尝试下载上述条目；如需重新下载或处理失败项，请使用 `larksync download --type <type> <token>` 手动执行。"
        )
        return "\n".join(lines) + "\n"

    def _build_url(self, file_type: str, token: str) -> str:
        return f"https://feishu.cn/{file_type}/{token}"

    def _fetch_metadata(self, token: str, doc_type: str) -> Optional[Mapping[str, Any]]:
        try:
            payload = self.drive_adapter.batch_get_metadata([(token, doc_type)])
        except FeishuAPIError:
            return None
        metas = payload.get("data", {}).get("metas") or []
        for meta in metas:
            if meta.get("doc_token") == token or meta.get("token") == token:
                return meta
        return metas[0] if metas else None

    def _download_entry(
        self,
        task: SyncTask,
        folder_dir: Path,
        entry: FolderEntry,
    ) -> Tuple[bool, Optional[str]]:
        original_type = entry.file_type.lower()
        entry_type = "docx" if original_type == "doc" else original_type
        entry_token = entry.token
        entry_name = entry.name
        entry_url = entry.url

        if entry_type == "shortcut" and entry.shortcut_target_token and entry.shortcut_target_type:
            mapped_type = self._normalize_shortcut_target(entry.shortcut_target_type)
            if mapped_type and entry.shortcut_target_token:
                entry_type = mapped_type
                entry_token = entry.shortcut_target_token
                if not entry_url:
                    entry_url = f"https://feishu.cn/{entry.shortcut_target_type}/{entry.shortcut_target_token}"

        try:
            registry = self.registry
        except RuntimeError:
            return False, "缺少注册表"

        if not registry.is_registered(entry_type):
            return False, f"类型 `{entry_type}` 未注册"

        parent_relative = folder_dir.relative_to(self.storage.root)
        extra = {"source_url": entry_url} if entry_url else {}
        extra["entry_root"] = parent_relative.as_posix()
        if original_type == "shortcut":
            extra["shortcut_token"] = entry.token
        subtask = SyncTask(
            token=entry_token,
            file_type=entry_type,
            name=entry_name,
            parent_path=parent_relative,
            extra=extra,
        )

        try:
            downloader = registry.build(entry_type, self._context)
            downloader.execute(subtask)
            return True, None
        except FeishuAPIError as exc:
            self._logger.warning(
                "Failed downloading folder entry",
                extra={
                    "folder": task.token,
                    "entry_token": entry.token,
                    "file_type": entry_type,
                    "status_code": exc.status_code,
                    "error_message": exc.message,
                },
            )
            return False, f"API {exc.status_code}"
        except KeyError:
            self._logger.warning(
                "No downloader available for folder entry",
                extra={
                    "folder": task.token,
                    "entry_token": entry.token,
                    "file_type": entry_type,
                },
            )
            return False, "未找到下载器"

    def _normalize_shortcut_target(self, value: str) -> Optional[str]:
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
            "wiki": "wiki",
        }
        return mapping.get(value.lower())


class ShortcutDownloader(BaseDownloader):
    """Describe shortcut target information."""

    file_type = "shortcut"

    def download(self, task: SyncTask) -> None:
        meta = self._fetch_metadata(task.token)
        title = meta.get("name") if meta else task.name or task.token
        shortcut_info = meta.get("shortcut_info") if meta else None
        target_token = shortcut_info.get("target_token") if isinstance(shortcut_info, Mapping) else None
        target_type = shortcut_info.get("target_type") if isinstance(shortcut_info, Mapping) else None
        target_url = meta.get("url") if meta else None
        if not target_url and target_token and target_type:
            target_url = f"https://feishu.cn/{target_type}/{target_token}"

        placeholder_path = self.storage.target_path(
            Path(task.parent_path) / sanitize_filename(title), extension="md"
        )

        if target_token and target_type:
            normalized = self._normalize_target_type(target_type)
            if normalized and self._try_download_target(normalized, target_token, task, target_url):
                if placeholder_path.exists():
                    placeholder_path.unlink()
                return

        lines = [f"# {title}", "", "这是一个快捷方式。", ""]
        lines.append(f"- 快捷方式 token：`{task.token}`")
        if target_type and target_token:
            lines.append(f"- 指向类型：`{target_type}`")
            lines.append(f"- 指向 token：`{target_token}`")
        if target_url:
            lines.append(f"- 原始链接：{target_url}")

        self.storage.write_text(placeholder_path, "\n".join(lines) + "\n")

    def _fetch_metadata(self, token: str) -> Mapping[str, Any] | None:
        try:
            payload = self.drive_adapter.batch_get_metadata([(token, "shortcut")])
        except FeishuAPIError:
            return None
        metas = payload.get("data", {}).get("metas") or []
        for meta in metas:
            if meta.get("doc_token") == token or meta.get("token") == token:
                return meta
        return metas[0] if metas else None

    def _normalize_target_type(self, value: str) -> Optional[str]:
        mapping = {
            "doc": "docx",
            "docx": "docx",
            "sheet": "sheet",
            "sheets": "sheet",
            "base": "bitable",
            "bitable": "bitable",
            "file": "file",
            "slides": "slides",
            "mindnote": "mindnote",
            "wiki": "wiki",
        }
        key = value.lower()
        return mapping.get(key)

    def _try_download_target(
        self,
        target_type: str,
        target_token: str,
        task: SyncTask,
        target_url: Optional[str],
    ) -> bool:
        try:
            registry = self.registry
        except RuntimeError:
            return False

        if not registry.is_registered(target_type):
            return False

        parent_dir = self.storage.root / task.parent_path
        parent_dir.mkdir(parents=True, exist_ok=True)
        pre_snapshot = {path for path in parent_dir.rglob("*") if path.is_file()}

        extra: Dict[str, object] = {"source_url": target_url} if target_url else {}
        subtask = SyncTask(
            token=target_token,
            file_type=target_type,
            name=target_token,
            parent_path=task.parent_path,
            extra=extra,
        )

        try:
            downloader = registry.build(target_type, self._context)
            downloader.execute(subtask)
        except Exception:  # pragma: no cover - defensive
            return False

        post_snapshot = {path for path in parent_dir.rglob("*") if path.is_file()}
        if post_snapshot == pre_snapshot:
            return False
        return True


class WikiDownloader(BaseDownloader):
    """Fetch wiki node details and record underlying document mapping."""

    file_type = "wiki"

    def download(self, task: SyncTask) -> None:
        cache = self._load_cache()
        try:
            node = self._get_node(task.token)
        except FeishuAPIError as exc:
            self._logger.warning(
                "Failed to fetch wiki node",
                extra={
                    "token": task.token,
                    "status_code": exc.status_code,
                    "error_message": exc.message,
                },
            )
            self._write_placeholder(task, error=f"API {exc.status_code}: {exc.message}")
            return

        title = node.get("title") or task.name or task.token
        obj_type = node.get("obj_type")
        obj_token = node.get("obj_token")
        obj_url = self._build_url(obj_type, obj_token) if obj_type and obj_token else None
        safe_title = sanitize_filename(title) or sanitize_filename(task.token) or "wiki_node"
        placeholder_path = self.storage.target_path(Path(task.parent_path) / f"{safe_title}.md")

        cached_relative = cache.get(task.token)
        if cached_relative:
            existing = self.storage.root / cached_relative
            if existing.exists():
                self._write_existing_placeholder(
                    task,
                    title=title,
                    placeholder_path=placeholder_path,
                    target_path=existing,
                    source_url=obj_url,
                )
                return
            cache.pop(task.token, None)
            self._save_cache(cache)

        resource_type = self._normalize_resource_type(obj_type)
        if not resource_type or not obj_token:
            self._write_placeholder(task, error="未能识别知识库节点对应的资源类型或 token")
            return

        try:
            registry = self.registry
        except RuntimeError:
            self._write_placeholder(task, error="缺少下载器注册表，无法处理知识库节点")
            return

        if not registry.is_registered(resource_type):
            self._write_placeholder(
                task,
                error=f"类型 `{resource_type}` 未注册，请手动下载",
                title=title,
                source_url=obj_url,
            )
            return

        resource_name = self._resolve_resource_name(resource_type, obj_token)
        safe_resource_name = sanitize_filename(resource_name) or obj_token
        parent_dir = self.storage.root / task.parent_path
        parent_dir.mkdir(parents=True, exist_ok=True)

        pre_snapshot = self._snapshot_files(parent_dir)

        extra: Dict[str, object] = {"source_url": obj_url} if obj_url else {}
        subtask = SyncTask(
            token=obj_token,
            file_type=resource_type,
            name=safe_resource_name,
            parent_path=task.parent_path,
            extra=extra,
        )

        try:
            downloader = registry.build(resource_type, self._context)
            downloader.execute(subtask)
        except FeishuAPIError as exc:
            self._write_placeholder(
                task,
                error=f"API {exc.status_code}: {exc.message}",
                title=title,
                source_url=obj_url,
            )
            return
        except Exception as exc:  # pragma: no cover - defensive
            self._write_placeholder(task, error=str(exc), title=title, source_url=obj_url)
            return

        post_snapshot = self._snapshot_files(parent_dir)
        primary = self._select_primary_output(resource_type, safe_resource_name, pre_snapshot, post_snapshot)
        if primary is None:
            self._write_placeholder(
                task,
                error="未找到下载文件，请检查对应资源输出",
                title=title,
                source_url=obj_url,
            )
            return

        relative = primary.relative_to(self.storage.root).as_posix()
        cache[task.token] = relative
        self._save_cache(cache)

        if placeholder_path.exists():
            placeholder_path.unlink()
        return

    def _get_node(self, token: str) -> Mapping[str, Any]:
        response = self.client.get("/open-apis/wiki/v2/spaces/get_node", params={"token": token})
        return (response.get("data") or {}).get("node", {})

    def _build_url(self, obj_type: Optional[str], obj_token: Optional[str]) -> Optional[str]:
        if not obj_type or not obj_token:
            return None
        return f"https://feishu.cn/{obj_type}/{obj_token}"

    def _write_placeholder(
        self,
        task: SyncTask,
        *,
        error: str,
        title: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> None:
        title = title or task.name or task.token
        lines = [f"# {title}", "", "无法获取知识库节点信息。", "", f"- 节点 token：`{task.token}`"]
        url = source_url
        if url is None and isinstance(task.extra, dict):
            url = task.extra.get("source_url")
        if url:
            lines.append(f"- 原始链接：{url}")
        lines.append(f"- 错误信息：{error}")
        lines.append("")
        lines.append("> 请确认应用/账号拥有访问该节点的权限后重试。")
        relative = Path(task.parent_path) / sanitize_filename(title)
        path = self.storage.target_path(relative, extension="md")
        self.storage.write_text(path, "\n".join(lines) + "\n")

    def _write_existing_placeholder(
        self,
        task: SyncTask,
        *,
        title: str,
        placeholder_path: Path,
        target_path: Path,
        source_url: Optional[str],
    ) -> None:
        relative_link = Path(os.path.relpath(target_path, start=placeholder_path.parent)).as_posix()
        lines = [
            f"# {title}",
            "",
            "该知识库节点对应的资源已下载至本地，以下为访问路径：",
            "",
            f"- 节点 token：`{task.token}`",
            f"- 本地路径：[{target_path.name}]({relative_link})",
        ]
        if source_url:
            lines.append(f"- 原始链接：{source_url}")
        self.storage.write_text(placeholder_path, "\n".join(lines) + "\n")

    def _normalize_resource_type(self, obj_type: Optional[str]) -> Optional[str]:
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
        value = obj_type.lower()
        return mapping.get(value, value if value in mapping.values() else None)

    def _resolve_resource_name(self, resource_type: str, token: str) -> str:
        try:
            payload = self.drive_adapter.batch_get_metadata([(token, resource_type)])
        except FeishuAPIError:
            return token
        metas = payload.get("data", {}).get("metas") or []
        for meta in metas:
            if meta.get("doc_token") == token or meta.get("token") == token:
                for key in ("name", "title"):
                    if meta.get(key):
                        return str(meta[key])
        return token

    def _snapshot_files(self, base_dir: Path) -> Set[Path]:
        return {path for path in base_dir.rglob("*") if path.is_file()}

    def _select_primary_output(
        self,
        resource_type: str,
        safe_name: str,
        pre_snapshot: Set[Path],
        post_snapshot: Set[Path],
    ) -> Optional[Path]:
        new_files = list(post_snapshot - pre_snapshot)
        if not new_files:
            return None
        priority = [".md", ".xlsx", ".pdf", ".pptx", ".docx", ".txt"]

        def sort_key(path: Path) -> Tuple[int, float]:
            suffix = path.suffix.lower()
            try:
                index = priority.index(suffix)
            except ValueError:
                index = len(priority)
            return (index, -path.stat().st_mtime)

        new_files.sort(key=sort_key)
        if resource_type == "docx":
            for candidate in new_files:
                if candidate.name == f"{safe_name}.md":
                    return candidate
        return new_files[0]

    def _cache_path(self) -> Path:
        return self.storage.root / ".wiki_cache.json"

    def _load_cache(self) -> Dict[str, str]:
        path = self._cache_path()
        if not path.exists():
            return {}
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
        if isinstance(content, dict):
            return {str(k): str(v) for k, v in content.items()}
        return {}

    def _save_cache(self, cache: Dict[str, str]) -> None:
        path = self._cache_path()
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
