"""Application bootstrap helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple, Union

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
from .storage import StorageManager, MetadataStore, SQLiteMetadataStore
from .storage.migration import MetadataStoreAdapter


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


def build_metadata_store(
    config: LarkSyncConfig,
    storage_root: Path,
) -> Union[MetadataStore, MetadataStoreAdapter]:
    """
    Create the appropriate metadata store based on configuration.
    
    Args:
        config: Application configuration
        storage_root: Root directory for storage
        
    Returns:
        MetadataStore (JSON backend) or MetadataStoreAdapter (SQLite backend)
    """
    backend = config.storage.metadata_backend.lower()
    
    if backend == "sqlite":
        from .storage.migration import migrate_json_to_sqlite
        
        sqlite_path = storage_root / config.storage.metadata_sqlite_file
        json_path = storage_root / config.storage.metadata_json_file
        
        # Auto-migrate if JSON exists but SQLite doesn't
        if config.storage.metadata_auto_migrate and json_path.exists() and not sqlite_path.exists():
            migrate_json_to_sqlite(
                storage_root,
                json_filename=config.storage.metadata_json_file,
                sqlite_filename=config.storage.metadata_sqlite_file,
                backup=True,
            )
        
        sqlite_store = SQLiteMetadataStore(
            sqlite_path,
            storage_root,
            enable_history=config.storage.metadata_enable_history,
        )
        # Return adapter for backward compatibility with existing code
        return MetadataStoreAdapter(sqlite_store)
    
    # Default: JSON backend
    return MetadataStore(storage_root, filename=config.storage.metadata_json_file)
