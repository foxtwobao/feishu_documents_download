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
    # 输出文件名（可能带 token 后缀以避免同名文件冲突）
    output_filename: Optional[str] = None

    @property
    def target_path(self) -> Path:
        # 优先使用指定的输出文件名（可能带 token 后缀）
        if self.output_filename:
            return self.parent_path / self.output_filename
        safe_name = sanitize_filename(self.name)
        return self.parent_path / safe_name
