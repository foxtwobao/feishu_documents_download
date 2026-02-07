"""API adapters translating Feishu endpoints into domain operations."""

from .docx_adapter import DocxAdapter
from .drive_adapter import DriveAdapter
from .wiki_adapter import WikiAdapter

__all__ = ["DocxAdapter", "DriveAdapter", "WikiAdapter"]
