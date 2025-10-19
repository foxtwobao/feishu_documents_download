"""API adapters translating Feishu endpoints into domain operations."""

from .docx_adapter import DocxAdapter
from .drive_adapter import DriveAdapter

__all__ = ["DocxAdapter", "DriveAdapter"]
