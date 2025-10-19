"""Application bootstrap helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple

from .config import LarkSyncConfig, load_config
from .core.api_client import FeishuAPIClient
from .core.registry import DownloaderRegistry
from .core.downloaders import (
    BitableDownloader,
    DocxDownloader,
    FileDownloader,
    FolderDownloader,
    MindnotePlaceholderDownloader,
    SheetDownloader,
    ShortcutDownloader,
    SlidesPlaceholderDownloader,
    WikiDownloader,
)
from .storage import StorageManager


def build_runtime(config_path: Path | None = None) -> Tuple[LarkSyncConfig, FeishuAPIClient, StorageManager, DownloaderRegistry]:
    """Instantiate core components needed for running the sync engine."""

    config = load_config(config_path)
    client = FeishuAPIClient.from_config(config)
    storage = StorageManager(config.storage)
    registry = DownloaderRegistry()
    registry.register("docx", DocxDownloader)
    registry.register("doc", DocxDownloader)
    registry.register("sheet", SheetDownloader)
    registry.register("bitable", BitableDownloader)
    registry.register("file", FileDownloader)
    registry.register("folder", FolderDownloader)
    registry.register("shortcut", ShortcutDownloader)
    registry.register("wiki", WikiDownloader)
    registry.register("slides", SlidesPlaceholderDownloader)
    registry.register("mindnote", MindnotePlaceholderDownloader)
    return config, client, storage, registry
