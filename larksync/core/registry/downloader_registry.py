"""Downloader registry."""

from __future__ import annotations

from typing import Dict, Iterable, Optional, Type

from ..downloaders.base_downloader import BaseDownloader, DownloaderContext


class DownloaderRegistry:
    """Maps file types to downloader classes."""

    def __init__(self):
        self._registry: Dict[str, Type[BaseDownloader]] = {}
        self._disabled: set[str] = set()

    def register(self, file_type: str, downloader_cls: Type[BaseDownloader]) -> None:
        self._registry[file_type] = downloader_cls

    def disable(self, file_type: str) -> None:
        self._disabled.add(file_type)

    def is_registered(self, file_type: str) -> bool:
        return file_type in self._registry

    def available_types(self) -> Iterable[str]:
        return (file_type for file_type in self._registry if file_type not in self._disabled)

    def build(self, file_type: str, context: DownloaderContext) -> BaseDownloader:
        if file_type in self._disabled:
            raise KeyError(f"Downloader for {file_type} is disabled")
        try:
            downloader_cls = self._registry[file_type]
        except KeyError as exc:
            raise KeyError(f"No downloader registered for file type {file_type}") from exc
        return downloader_cls(context)
