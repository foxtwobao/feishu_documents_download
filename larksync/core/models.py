"""Core domain models used across the sync pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from ..utils.filesystem import sanitize_filename


@dataclass(slots=True)
class SyncTask:
    """Represents a single remote file that needs to be processed."""

    token: str
    file_type: str
    name: str
    parent_path: Path
    revision: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def target_path(self) -> Path:
        safe_name = sanitize_filename(self.name)
        return self.parent_path / safe_name
