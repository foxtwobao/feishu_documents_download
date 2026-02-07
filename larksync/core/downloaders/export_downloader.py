"""Shared helpers for downloaders that rely on Drive export tasks."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Iterable, Optional, Tuple

from ...utils.filesystem import sanitize_filename
from ..reference_cache import register_resolved_path
from ..api_client import FeishuAPIError
from ..models import SyncTask
from .base_downloader import BaseDownloader


class ExportTaskDownloader(BaseDownloader):
    """Base downloader for cloud documents that require drive export."""

    export_type: str
    file_extension: str
    poll_interval_seconds: float = 1.0
    max_attempts: int = 30

    def download(self, task: SyncTask) -> None:
        display_name = self._resolve_display_name(task)
        file_token, file_name = self._export_document(task, sub_id=self._resolve_sub_id(task), display_name=display_name)
        response = self.drive_adapter.download_export_file(file_token)
        try:
            # 优先使用指定的输出文件名（可能带 token 后缀以避免同名文件冲突）
            if task.output_filename:
                base_name = Path(task.output_filename).stem
            else:
                base_name = sanitize_filename(Path(file_name or display_name).stem or display_name or task.token)
            relative = task.parent_path / base_name
            path = self.storage.target_path(relative, extension=self.file_extension)
            self.storage.write_stream(path, response.iter_bytes())
            register_resolved_path(task.token, path)
        finally:
            response.close()

    def _resolve_sub_id(self, task: SyncTask) -> Optional[str]:
        return task.extra.get("sub_id") if isinstance(task.extra, dict) else None

    def _resolve_display_name(self, task: SyncTask) -> str:
        metadata = self._fetch_metadata(task.token)
        if metadata:
            for key in ("name", "title"):
                if metadata.get(key):
                    return str(metadata[key])
        if task.name:
            return task.name
        return task.token

    def _fetch_metadata(self, token: str) -> Optional[dict]:
        try:
            payload = self.drive_adapter.batch_get_metadata([(token, self.export_type)])
        except FeishuAPIError:
            return None
        metas = payload.get("data", {}).get("metas") or []
        for meta in metas:
            if meta.get("token") == token:
                return meta
        return metas[0] if metas else None

    def _export_document(self, task: SyncTask, *, sub_id: Optional[str], display_name: str) -> Tuple[str, str]:
        ticket = self.drive_adapter.create_export_task(
            token=task.token,
            doc_type=self.export_type,
            file_extension=self.file_extension,
            sub_id=sub_id,
        )

        for attempt in range(self.max_attempts):
            payload = self.drive_adapter.get_export_task(ticket, task.token)
            result = payload.get("data", {}).get("result") or {}
            status = result.get("job_status")
            if status in (0, "success"):
                file_token = result.get("file_token")
                if not file_token:
                    raise RuntimeError("Export task succeeded but file token missing")
                file_name = result.get("file_name") or display_name
                suffix = f".{self.file_extension}"
                if not file_name.lower().endswith(suffix):
                    file_name = f"{file_name}{suffix}"
                return file_token, file_name
            if status in (1, 2, "init", "initializing", "processing", "pending", None):
                time.sleep(self.poll_interval_seconds)
                continue
            error_msg = result.get("job_error_msg") or f"Unexpected export status {status}"
            status_code = int(status) if isinstance(status, int) else -1
            raise FeishuAPIError(status_code, str(error_msg))

        raise TimeoutError("Timed out waiting for export task to complete")


class SheetDownloader(ExportTaskDownloader):
    """Export Feishu sheets as XLSX."""

    file_type = "sheet"
    export_type = "sheet"
    file_extension = "xlsx"


class BitableDownloader(ExportTaskDownloader):
    """Export Feishu bitable as XLSX."""

    file_type = "bitable"
    export_type = "bitable"
    file_extension = "xlsx"
