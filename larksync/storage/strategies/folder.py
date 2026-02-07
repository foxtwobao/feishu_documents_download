"""Duplicate check strategy for folders."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from .base import DuplicateCheckStrategy, DownloadDecision


class FolderStrategy(DuplicateCheckStrategy):
    """
    Strategy for folders.
    
    Folders don't need actual download - just directory creation.
    This strategy is mainly for metadata tracking purposes.
    
    Decision priority:
    1. Directory doesn't exist locally -> create
    2. Parent path changed (folder moved) -> update metadata
    3. Skip (folder exists)
    """
    
    @property
    def file_types(self) -> tuple[str, ...]:
        return ("folder",)
    
    def should_download(
        self,
        stored: Optional[Mapping[str, Any]],
        current: Mapping[str, Any],
        local_path: Optional[Path],
        *,
        incremental: bool = True,
        force_on_missing: bool = True,
    ) -> DownloadDecision:
        # Non-incremental mode: always process
        if not incremental:
            return DownloadDecision(True, "non_incremental_mode", priority=100)
        
        # No stored metadata: new folder
        if stored is None:
            return DownloadDecision(True, "new_folder", priority=90)
        
        # Check if local directory exists
        if local_path and not local_path.exists():
            return DownloadDecision(True, "directory_missing", priority=80)
        
        # Check parent path change (folder moved)
        current_parent = current.get("parent_path")
        stored_parent = stored.get("parent_path")
        if current_parent and stored_parent and current_parent != stored_parent:
            return DownloadDecision(True, "parent_path_changed", priority=70)
        
        # Folder exists and metadata is current
        return DownloadDecision(False, "folder_exists", priority=0)
