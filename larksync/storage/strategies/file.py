"""Duplicate check strategy for regular files (non-cloud documents)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from .base import DuplicateCheckStrategy, DownloadDecision


class FileStrategy(DuplicateCheckStrategy):
    """
    Strategy for regular files that don't have revision numbers.
    
    Supported types: file
    
    Key limitation: Feishu API only returns modified_time for file type,
    no revision or checksum available.
    
    Decision priority:
    1. Check common conditions (new file, deleted, missing, etc.)
    2. Parent path changed (file moved)
    3. Modified time changed
    4. Local file size changed (extra check since no checksum)
    5. Skip download (no changes detected)
    """
    
    @property
    def file_types(self) -> tuple[str, ...]:
        return ("file",)
    
    def should_download(
        self,
        stored: Optional[Mapping[str, Any]],
        current: Mapping[str, Any],
        local_path: Optional[Path],
        *,
        incremental: bool = True,
        force_on_missing: bool = True,
    ) -> DownloadDecision:
        # Check common conditions first
        common_decision = self._check_common_conditions(
            stored, local_path,
            incremental=incremental,
            force_on_missing=force_on_missing,
        )
        if common_decision is not None:
            return common_decision
        
        assert stored is not None  # Guaranteed by common checks
        
        # Check parent path change (file moved)
        current_parent = current.get("parent_path")
        stored_parent = stored.get("parent_path")
        if current_parent and stored_parent and current_parent != stored_parent:
            return DownloadDecision(True, "parent_path_changed", priority=70)
        
        # Check modified time (primary indicator for files)
        if self._compare_timestamps(
            stored.get("modified_time"),
            current.get("modified_time"),
        ):
            return DownloadDecision(True, "modified_time_changed", priority=60)
        
        # Check checksum if available (API may provide in future)
        current_checksum = current.get("checksum")
        stored_checksum = stored.get("checksum")
        if current_checksum is not None:
            if stored_checksum is None or current_checksum != stored_checksum:
                return DownloadDecision(True, "checksum_changed", priority=55)
        
        # Extra check: local file size changed (defensive)
        # This helps catch cases where API metadata didn't update
        if local_path and local_path.exists():
            stored_size = stored.get("local_file_size")
            if stored_size is not None:
                try:
                    current_size = local_path.stat().st_size
                    if current_size != stored_size:
                        return DownloadDecision(True, "local_size_mismatch", priority=40)
                except OSError:
                    pass
        
        # No changes detected
        return DownloadDecision(False, "no_changes", priority=0)
