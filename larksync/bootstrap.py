"""Application bootstrap helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Tuple

from pydantic import BaseModel

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


def _apply_overrides(config: LarkSyncConfig, overrides: Mapping[str, Any]) -> LarkSyncConfig:
    """Apply nested overrides onto a LarkSync configuration model."""

    update_payload: dict[str, Any] = {}
    for field_name, value in overrides.items():
        current = getattr(config, field_name, None)
        if isinstance(current, BaseModel) and isinstance(value, Mapping):
            update_payload[field_name] = current.model_copy(update=value)
        else:
            update_payload[field_name] = value
    return config.model_copy(update=update_payload)


def build_runtime(
    config_path: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> Tuple[LarkSyncConfig, FeishuAPIClient, StorageManager, DownloaderRegistry]:
    """Instantiate core components needed for running the sync engine."""

    config = load_config(config_path)
    if overrides:
        config = _apply_overrides(config, overrides)
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
