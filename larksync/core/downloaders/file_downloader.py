"""Downloader for Drive files (non-cloud docs)."""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

import httpx

from ...utils.filesystem import sanitize_filename
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
            filename = self._resolve_filename(response, task.name)
            relative = task.parent_path / sanitize_filename(filename)
            path = self.storage.target_path(relative)
            self.storage.write_stream(path, response.iter_bytes())
        finally:
            response.close()

    def _resolve_filename(self, response: httpx.Response, fallback: str) -> str:
        disposition = response.headers.get("Content-Disposition") or ""
        filename = self._parse_content_disposition(disposition)
        if not filename:
            filename = fallback
        return filename

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
