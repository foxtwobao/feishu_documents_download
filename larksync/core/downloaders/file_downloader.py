"""Downloader for Drive files (non-cloud docs)."""

from __future__ import annotations

import re
import mimetypes
from pathlib import Path
from urllib.parse import unquote

import httpx

from ...utils.filesystem import sanitize_filename
from ..reference_cache import lookup_resolved_path, register_resolved_path
from ..api_client import FeishuAPIError
from ..models import SyncTask
from .base_downloader import BaseDownloader


class FileDownloader(BaseDownloader):
    """Download regular Drive files using the files API."""

    file_type = "file"

    def download(self, task: SyncTask) -> None:
        response: httpx.Response | None = None
        try:
            response = self.drive_adapter.download_file(task.token)
        except FeishuAPIError as exc:
            self._logger.warning(
                "Failed to download file via drive API",
                extra={"token": task.token, "status_code": exc.status_code, "error": exc.message},
            )
            raise

        assert response is not None
        try:
            if isinstance(task.extra, dict) and task.extra.get("force_original_name"):
                filename = self._resolve_reference_filename(response, task)
            elif task.output_filename:
                filename = task.output_filename
            else:
                filename = self._resolve_filename(response, task.name)
            relative = task.parent_path / sanitize_filename(filename)
            path = self.storage.target_path(relative)
            self.storage.write_stream(path, response.iter_bytes())
            self._cleanup_stale_refer_copy(task.token, path)
            register_resolved_path(task.token, path)
        finally:
            response.close()

    def _resolve_filename(self, response: httpx.Response, fallback: str) -> str:
        disposition = response.headers.get("Content-Disposition") or ""
        filename = self._parse_content_disposition(disposition)
        if not filename:
            filename = fallback
        return filename

    def _resolve_reference_filename(self, response: httpx.Response, task: SyncTask) -> str:
        filename = self._resolve_filename(response, "")
        if filename:
            return filename

        base_name = sanitize_filename(task.name) or task.token or "file"
        stem = Path(base_name).stem or task.token or "file"
        token_suffix = f"_{task.token}" if task.token and not stem.endswith(f"_{task.token}") else ""
        suffix = Path(filename).suffix
        if not suffix:
            mime_type = response.headers.get("Content-Type") or ""
            ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) if mime_type else None
            suffix = ext or ".bin"
        return f"{stem}{token_suffix}{suffix}"

    def _cleanup_stale_refer_copy(self, token: str, canonical_path: Path) -> None:
        existing = lookup_resolved_path(token)
        if existing is None or existing == canonical_path or not existing.exists():
            return
        try:
            existing.relative_to(self.storage.root / "refer")
        except ValueError:
            return
        if existing.is_file():
            existing.unlink(missing_ok=True)

    @staticmethod
    def _parse_content_disposition(value: str) -> str | None:
        if not value:
            return None
        filename_star_match = re.search(r'filename\*\s*=\s*[^\'"]*\'\'([^;]+)', value)
        if filename_star_match:
            return unquote(filename_star_match.group(1))
        filename_match = re.search(r'filename="([^"]+)"', value)
        if filename_match:
            return unquote(filename_match.group(1))
        return None
