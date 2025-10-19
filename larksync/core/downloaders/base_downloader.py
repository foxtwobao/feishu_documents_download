"""Downloader base classes."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from typing import TYPE_CHECKING

from ...config import LarkSyncConfig
from ...storage import StorageManager
from ..adapters.docx_adapter import DocxAdapter
from ..adapters.drive_adapter import DriveAdapter
from ..api_client import FeishuAPIClient
from ..models import SyncTask
from ..parsers.docx_parser import DocxMarkdownParser

if TYPE_CHECKING:  # pragma: no cover
    from ..registry import DownloaderRegistry


@dataclass(slots=True)
class DownloaderContext:
    """Context object shared across downloaders."""

    config: LarkSyncConfig
    client: FeishuAPIClient
    storage: StorageManager
    docx_adapter: DocxAdapter | None = None
    drive_adapter: DriveAdapter | None = None
    docx_parser: DocxMarkdownParser | None = None
    registry: "DownloaderRegistry" | None = None


class BaseDownloader(ABC):
    """Abstract downloader contract."""

    file_type: str

    def __init__(self, context: DownloaderContext):
        self._context = context
        self._logger = logging.getLogger(self.__class__.__name__)

    @property
    def storage(self) -> StorageManager:
        return self._context.storage

    @property
    def config(self) -> LarkSyncConfig:
        return self._context.config

    @property
    def client(self) -> FeishuAPIClient:
        return self._context.client

    @property
    def docx_adapter(self) -> DocxAdapter:
        if self._context.docx_adapter is None:
            raise RuntimeError("DocxAdapter not configured for this downloader")
        return self._context.docx_adapter

    @property
    def docx_parser(self) -> DocxMarkdownParser:
        if self._context.docx_parser is None:
            raise RuntimeError("Docx parser not configured for this downloader")
        return self._context.docx_parser

    @property
    def drive_adapter(self) -> DriveAdapter:
        if self._context.drive_adapter is None:
            raise RuntimeError("DriveAdapter not configured for this downloader")
        return self._context.drive_adapter

    @property
    def registry(self) -> "DownloaderRegistry":
        if self._context.registry is None:
            raise RuntimeError("Registry not configured for this downloader")
        return self._context.registry

    def execute(self, task: SyncTask) -> None:
        """Entry point invoked by the sync engine."""

        self._logger.info("Processing task", extra={"token": task.token, "file_type": task.file_type})
        self.download(task)

    @abstractmethod
    def download(self, task: SyncTask) -> None:
        """Perform file-specific download/parse/save logic."""
