"""Core orchestration for running sync tasks."""

from __future__ import annotations

import logging
from typing import Iterable, Sequence

from ..config import LarkSyncConfig
from ..storage import StorageManager
from .adapters.docx_adapter import DocxAdapter
from .adapters.drive_adapter import DriveAdapter
from .api_client import FeishuAPIClient
from .downloaders.base_downloader import DownloaderContext
from .models import SyncTask
from .parsers.docx_parser import DocxMarkdownParser
from .registry import DownloaderRegistry

logger = logging.getLogger(__name__)


class SyncEngine:
    """Coordinate the download pipeline."""

    def __init__(
        self,
        config: LarkSyncConfig,
        client: FeishuAPIClient,
        registry: DownloaderRegistry,
        storage: StorageManager,
    ):
        self._config = config
        self._client = client
        self._registry = registry
        self._storage = storage
        self._docx_adapter = DocxAdapter(client)
        self._drive_adapter = DriveAdapter(client)
        self._docx_parser = DocxMarkdownParser()

    def run(self, tasks: Iterable[SyncTask]) -> None:
        for task in tasks:
            self.process_task(task)

    def process_task(self, task: SyncTask) -> None:
        logger.debug("Processing sync task", extra={"token": task.token, "file_type": task.file_type})
        context = DownloaderContext(
            config=self._config,
            client=self._client,
            storage=self._storage,
            docx_adapter=self._docx_adapter,
            drive_adapter=self._drive_adapter,
            docx_parser=self._docx_parser,
            registry=self._registry,
        )
        downloader = self._registry.build(task.file_type, context)
        downloader.execute(task)

    def close(self) -> None:
        """Release underlying HTTP client resources."""

        self._client.close()

    @property
    def registry(self) -> DownloaderRegistry:
        return self._registry

    @property
    def storage(self) -> StorageManager:
        return self._storage

    @property
    def drive_adapter(self) -> DriveAdapter:
        return self._drive_adapter

    @property
    def config(self) -> LarkSyncConfig:
        return self._config
