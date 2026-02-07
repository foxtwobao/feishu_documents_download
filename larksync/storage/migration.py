"""Migration utilities for metadata storage backends."""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional

from .metadata_store import MetadataStore
from .sqlite_store import SQLiteMetadataStore

logger = logging.getLogger(__name__)


def migrate_json_to_sqlite(
    storage_root: Path,
    *,
    json_filename: str = ".metadata.json",
    sqlite_filename: str = ".sync.db",
    backup: bool = True,
) -> int:
    """
    Migrate metadata from JSON file to SQLite database.
    
    Args:
        storage_root: Root directory of the storage
        json_filename: Name of the JSON metadata file
        sqlite_filename: Name of the SQLite database file
        backup: Whether to backup the JSON file after migration
        
    Returns:
        Number of entries migrated
    """
    json_path = storage_root / json_filename
    sqlite_path = storage_root / sqlite_filename
    
    if not json_path.exists():
        logger.info(
            "No JSON metadata file found, nothing to migrate",
            extra={"path": str(json_path)},
        )
        return 0
    
    if sqlite_path.exists():
        logger.warning(
            "SQLite database already exists, migration will add new entries only",
            extra={"path": str(sqlite_path)},
        )
    
    # Create SQLite store and migrate
    sqlite_store = SQLiteMetadataStore(sqlite_path, storage_root)
    count = sqlite_store.migrate_from_json(json_path)
    
    # Backup JSON file
    if backup and count > 0:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = json_path.with_suffix(f".json.backup.{timestamp}")
        try:
            shutil.copy2(json_path, backup_path)
            logger.info(
                "JSON file backed up",
                extra={"original": str(json_path), "backup": str(backup_path)},
            )
        except OSError as e:
            logger.warning(
                "Failed to backup JSON file",
                extra={"path": str(json_path), "error": str(e)},
            )
    
    sqlite_store.close()
    return count


def create_metadata_store(
    storage_root: Path,
    *,
    backend: str = "sqlite",
    json_filename: str = ".metadata.json",
    sqlite_filename: str = ".sync.db",
    auto_migrate: bool = True,
    enable_history: bool = False,
) -> MetadataStore | SQLiteMetadataStore:
    """
    Factory function to create the appropriate metadata store.
    
    Args:
        storage_root: Root directory of the storage
        backend: Backend type ("sqlite" or "json")
        json_filename: Name of the JSON metadata file
        sqlite_filename: Name of the SQLite database file
        auto_migrate: Automatically migrate JSON to SQLite if switching backends
        enable_history: Enable sync history recording (SQLite only)
        
    Returns:
        Configured metadata store instance
    """
    if backend == "json":
        return MetadataStore(storage_root, filename=json_filename)
    
    sqlite_path = storage_root / sqlite_filename
    json_path = storage_root / json_filename
    
    # Auto-migrate if JSON exists but SQLite doesn't
    if auto_migrate and json_path.exists() and not sqlite_path.exists():
        logger.info("Auto-migrating JSON metadata to SQLite")
        migrate_json_to_sqlite(
            storage_root,
            json_filename=json_filename,
            sqlite_filename=sqlite_filename,
            backup=True,
        )
    
    return SQLiteMetadataStore(
        sqlite_path,
        storage_root,
        enable_history=enable_history,
    )


class MetadataStoreAdapter:
    """
    Adapter that wraps SQLiteMetadataStore to provide MetadataStore interface.
    
    This allows gradual migration without changing existing code.
    """
    
    def __init__(self, sqlite_store: SQLiteMetadataStore):
        self._store = sqlite_store
    
    def get(self, token: str):
        return self._store.get(token)
    
    def tokens(self):
        return self._store.tokens()
    
    def should_download(
        self,
        token: str,
        *,
        current_meta,
        expected_local_path,
        incremental: bool,
        force_on_missing: bool,
        parent_path,
    ) -> bool:
        """Compatibility wrapper for old interface."""
        return self._store.should_download_compat(
            token,
            current_meta=current_meta,
            expected_local_path=expected_local_path,
            incremental=incremental,
            force_on_missing=force_on_missing,
            parent_path=parent_path,
        )
    
    def mark_synced(self, token: str, **kwargs):
        return self._store.mark_synced(token, **kwargs)
    
    def mark_missing(self, token: str, **kwargs):
        return self._store.mark_missing(token, **kwargs)
    
    def mark_deleted(self, token: str):
        return self._store.mark_deleted(token)
    
    def remove(self, token: str):
        return self._store.remove(token)
    
    def resolve_path(self, entry):
        return self._store.resolve_path(entry)
    
    def flush(self):
        return self._store.flush()
    
    def clear(self):
        return self._store.clear()
