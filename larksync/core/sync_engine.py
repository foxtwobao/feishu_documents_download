"""Core orchestration for running sync tasks."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Sequence

from ..config import LarkSyncConfig
from ..storage import StorageManager
from .adapters.docx_adapter import DocxAdapter
from .adapters.drive_adapter import DriveAdapter
from .adapters.wiki_adapter import WikiAdapter
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
        self._wiki_adapter = WikiAdapter(client)
        self._docx_parser = DocxMarkdownParser()

    def run(self, tasks: Iterable[SyncTask], max_workers: int | None = None) -> None:
        """
        执行同步任务，支持并发处理
        
        Args:
            tasks: 要处理的任务列表
            max_workers: 最大工作线程数，None表示使用配置默认值
        """
        tasks_list = list(tasks)
        if not tasks_list:
            return
        
        # 确定最大并发数
        if max_workers is None:
            # 根据文件类型统计，使用最小的并发配置作为保守值
            max_workers = min(
                self._config.concurrency.docx,
                self._config.concurrency.sheet,
                self._config.concurrency.bitable,
                self._config.concurrency.file,
            )
            max_workers = max(1, max_workers)  # 至少1个
        
        # 如果只有少量任务，使用串行执行更高效
        if len(tasks_list) <= 3:
            for task in tasks_list:
                self.process_task(task)
            return
        
        # 并发执行任务
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(self.process_task, task): task
                for task in tasks_list
            }
            
            for future in as_completed(futures):
                task = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    logger.error(
                        "Task failed",
                        extra={"token": task.token, "file_type": task.file_type, "error": str(exc)},
                    )
                    # 继续处理其他任务，不中断

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
    def wiki_adapter(self) -> WikiAdapter:
        return self._wiki_adapter

    @property
    def config(self) -> LarkSyncConfig:
        return self._config
