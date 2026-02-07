"""Base class for duplicate check strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True, slots=True)
class DownloadDecision:
    """Result of a duplicate check decision."""
    
    should_download: bool
    reason: str
    priority: int = 0  # Higher priority reasons override lower ones
    
    def __bool__(self) -> bool:
        return self.should_download


class DuplicateCheckStrategy(ABC):
    """
    Abstract base class for duplicate check strategies.
    
    Different file types in Feishu have different metadata available:
    - Cloud docs (docx, sheet, bitable): Have revision numbers
    - Regular files: Only have modified_time
    - Folders: Only need existence check
    
    Each strategy encapsulates the logic for its file type.
    """
    
    @property
    @abstractmethod
    def file_types(self) -> tuple[str, ...]:
        """File types this strategy handles."""
    
    @abstractmethod
    def should_download(
        self,
        stored: Optional[Mapping[str, Any]],
        current: Mapping[str, Any],
        local_path: Optional[Path],
        *,
        incremental: bool = True,
        force_on_missing: bool = True,
    ) -> DownloadDecision:
        """
        Determine whether a file should be downloaded.
        
        Args:
            stored: Previously stored metadata (None if new file)
            current: Current metadata from Feishu API
            local_path: Expected local file path (None if unknown)
            incremental: Whether incremental sync is enabled
            force_on_missing: Re-download if local file is missing
            
        Returns:
            DownloadDecision with should_download flag and reason
        """
    
    def _check_common_conditions(
        self,
        stored: Optional[Mapping[str, Any]],
        local_path: Optional[Path],
        *,
        incremental: bool,
        force_on_missing: bool,
    ) -> Optional[DownloadDecision]:
        """
        Check conditions common to all strategies.
        
        Returns:
            DownloadDecision if a common condition triggers download,
            None if type-specific checks should continue.
        """
        # Non-incremental mode: always download
        if not incremental:
            return DownloadDecision(True, "non_incremental_mode", priority=100)
        
        # No stored metadata: new file
        if stored is None:
            return DownloadDecision(True, "new_file", priority=90)
        
        # Previously marked as deleted or missing
        status = stored.get("status")
        if status == "deleted":
            return DownloadDecision(True, "previously_deleted", priority=85)
        if status == "missing":
            return DownloadDecision(True, "previously_missing", priority=85)
        if status == "error":
            return DownloadDecision(True, "previous_error", priority=85)
        
        # Local file missing check
        if force_on_missing and local_path:
            if not self._path_exists(stored, local_path):
                return DownloadDecision(True, "local_file_missing", priority=80)
        
        return None
    
    def _path_exists(self, stored: Mapping[str, Any], expected_path: Optional[Path]) -> bool:
        """Check if the local file exists."""
        stored_path = stored.get("local_path")
        
        # Check stored path
        if stored_path:
            stored_path_obj = Path(stored_path)
            if stored_path_obj.exists():
                return True
        
        # Check expected path
        if expected_path and expected_path.exists():
            return True
        
        return False
    
    def _compare_timestamps(
        self,
        stored_time: Optional[str],
        current_time: Optional[str],
    ) -> bool:
        """
        Compare two timestamps for equality.
        
        Returns:
            True if timestamps are different (need update),
            False if same or both None.
        """
        if current_time is None:
            return False
        if stored_time is None:
            return True
        return stored_time != current_time
