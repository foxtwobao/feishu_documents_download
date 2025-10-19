"""Placeholder downloaders for unsupported document types."""

from __future__ import annotations

from pathlib import Path

from ...utils.filesystem import sanitize_filename
from ..models import SyncTask
from ..api_client import FeishuAPIError
from .base_downloader import BaseDownloader


class UnsupportedMarkdownDownloader(BaseDownloader):
    """Generate a Markdown placeholder describing unsupported document types."""

    message: str = "This document type is not yet supported."
    file_type: str = "unsupported"

    def download(self, task: SyncTask) -> None:
        link = self._resolve_link(task)
        title = self._resolve_title(task)
        content = self._build_content(task, title, link)
        relative = task.parent_path / sanitize_filename(f"{title}.md")
        path = self.storage.target_path(relative)
        self.storage.write_text(path, content)

    def _resolve_link(self, task: SyncTask) -> str:
        if isinstance(task.extra, dict) and task.extra.get("source_url"):
            return str(task.extra["source_url"])
        return f"https://feishu.cn/{task.file_type}/{task.token}"

    def _resolve_title(self, task: SyncTask) -> str:
        metadata = self._fetch_metadata(task.token, task.file_type)
        if metadata:
            for key in ("name", "title"):
                if metadata.get(key):
                    return str(metadata[key])
        return task.name or task.token

    def _fetch_metadata(self, token: str, doc_type: str):
        try:
            payload = self.drive_adapter.batch_get_metadata([(token, doc_type)])
        except FeishuAPIError:
            return None
        metas = payload.get("data", {}).get("metas") or []
        for meta in metas:
            if meta.get("token") == token:
                return meta
        return metas[0] if metas else None

    def _build_content(self, task: SyncTask, title: str, link: str) -> str:
        lines = [
            f"# {title}",
            "",
            self.message,
            "",
            f"- 类型：`{task.file_type}`",
            f"- 原始链接：{link}",
        ]
        return "\n".join(lines) + "\n"


class SlidesPlaceholderDownloader(UnsupportedMarkdownDownloader):
    file_type = "slides"
    message = "当前版本暂不支持幻灯片下载，请手动访问原始链接。"


class MindnotePlaceholderDownloader(UnsupportedMarkdownDownloader):
    file_type = "mindnote"
    message = "当前版本暂不支持思维笔记下载，请手动访问原始链接。"
