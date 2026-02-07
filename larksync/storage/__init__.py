"""Local storage helpers."""

from .manager import StorageManager
from .metadata_store import MetadataStore
from .sqlite_store import SQLiteMetadataStore
from .strategies import (
    DuplicateCheckStrategy,
    DownloadDecision,
    CloudDocStrategy,
    FileStrategy,
    FolderStrategy,
    get_strategy_for_type,
)

__all__ = [
    "StorageManager",
    "MetadataStore",
    "SQLiteMetadataStore",
    "DuplicateCheckStrategy",
    "DownloadDecision",
    "CloudDocStrategy",
    "FileStrategy",
    "FolderStrategy",
    "get_strategy_for_type",
]
