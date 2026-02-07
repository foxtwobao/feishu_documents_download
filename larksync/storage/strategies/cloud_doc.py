"""Duplicate check strategy for cloud documents (docx, sheet, bitable, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

from .base import DuplicateCheckStrategy, DownloadDecision


class CloudDocStrategy(DuplicateCheckStrategy):
    """
    Strategy for cloud documents that have revision numbers.
    
    Supported types: docx, doc, sheet, bitable, wiki, slides, mindnote
    
    Decision priority:
    1. Check common conditions (new file, deleted, missing, etc.)
    2. Parent path changed (file moved)
    3. Revision changed (most reliable indicator)
    4. Modified time changed (fallback if no revision)
    5. Skip download (no changes detected)
    """
    
    @property
    def file_types(self) -> tuple[str, ...]:
        return ("docx", "doc", "sheet", "bitable", "wiki", "slides", "mindnote")
    
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
        
        # Check revision change (most reliable for cloud docs)
        current_revision = current.get("revision")
        stored_revision = stored.get("revision")
        if current_revision is not None:
            if stored_revision is None or current_revision != stored_revision:
                return DownloadDecision(True, "revision_changed", priority=60)
        
        # Fallback: check modified time
        if self._compare_timestamps(
            stored.get("modified_time"),
            current.get("modified_time"),
        ):
            return DownloadDecision(True, "modified_time_changed", priority=50)
        
        # No changes detected
        return DownloadDecision(False, "no_changes", priority=0)
