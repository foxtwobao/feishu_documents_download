"""Duplicate check strategies for different file types."""

from .base import DuplicateCheckStrategy, DownloadDecision
from .cloud_doc import CloudDocStrategy
from .file import FileStrategy
from .folder import FolderStrategy

__all__ = [
    "DuplicateCheckStrategy",
    "DownloadDecision",
    "CloudDocStrategy",
    "FileStrategy",
    "FolderStrategy",
    "get_strategy_for_type",
]


# Strategy registry
_STRATEGY_MAP: dict[str, type[DuplicateCheckStrategy]] = {
    # Cloud documents with revision support
    "docx": CloudDocStrategy,
    "doc": CloudDocStrategy,
    "sheet": CloudDocStrategy,
    "bitable": CloudDocStrategy,
    "wiki": CloudDocStrategy,
    "slides": CloudDocStrategy,
    "mindnote": CloudDocStrategy,
    # Regular files
    "file": FileStrategy,
    # Folders
    "folder": FolderStrategy,
}


def get_strategy_for_type(file_type: str) -> DuplicateCheckStrategy:
    """Get the appropriate duplicate check strategy for a file type."""
    strategy_cls = _STRATEGY_MAP.get(file_type.lower(), FileStrategy)
    return strategy_cls()
