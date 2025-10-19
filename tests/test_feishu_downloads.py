"""Integration tests that exercise downloads defined in test.md."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List

import pytest

from larksync.config import AuthSettings, StorageSettings, load_config
from larksync.core.api_client import FeishuAPIClient, FeishuAPIError
from larksync.core.downloaders import (
    BitableDownloader,
    DocxDownloader,
    FileDownloader,
    FolderDownloader,
    MindnotePlaceholderDownloader,
    SheetDownloader,
    ShortcutDownloader,
    SlidesPlaceholderDownloader,
    WikiDownloader,
)
from larksync.core.models import SyncTask
from larksync.core.registry import DownloaderRegistry
from larksync.core.sync_engine import SyncEngine
from larksync.storage import StorageManager

CASE_PATTERN = re.compile(r"-\s*`(?P<type>[^`]+)`.*?:\s*(?P<url>https?://\S+)")
FOLDER_PATTERN = re.compile(r"#\s*文件夹下载\s*\n(?P<url>https?://\S+)")


@dataclass(frozen=True)
class DownloadCase:
    """Represents a download case pulled from test.md."""

    label: str
    token: str
    file_type: str


def _load_cases() -> List[DownloadCase]:
    test_md = Path(__file__).resolve().parent.parent / "test.md"
    content = test_md.read_text(encoding="utf-8")
    cases: List[DownloadCase] = []

    folder_match = FOLDER_PATTERN.search(content)
    if folder_match:
        folder_url = folder_match.group("url")
        cases.append(
            DownloadCase(
                label="folder",
                token=_extract_token(folder_url),
                file_type="folder",
            )
        )

    for match in CASE_PATTERN.finditer(content):
        entry_type = match.group("type").strip().lower()
        url = match.group("url").strip()
        cases.append(
            DownloadCase(
                label=entry_type,
                token=_extract_token(url),
                file_type=_normalize_file_type(entry_type),
            )
        )

    return cases


def _extract_token(url: str) -> str:
    token = url.rstrip("/").split("/")[-1]
    token = token.split("?")[0]
    token = token.split("#")[0]
    return token


def _normalize_file_type(label: str) -> str:
    normalized = label.strip().lower()
    if normalized in {"doc", "docx"}:
        return normalized
    return normalized


def _build_engine_for_case(case: DownloadCase, tmp_path: Path, config_path: Path | None = None) -> SyncEngine:
    config = load_config(config_path)
    user_token = config.auth.user_access_token or os.getenv("LARKSYNC_USER_ACCESS_TOKEN")
    tenant_token = config.auth.tenant_access_token or os.getenv("LARKSYNC_TENANT_ACCESS_TOKEN")
    if not (user_token or tenant_token):
        pytest.skip("Access token missing: set in config.toml [auth] or export LARKSYNC_USER_ACCESS_TOKEN/LARKSYNC_TENANT_ACCESS_TOKEN")

    storage_root = tmp_path / "output"
    config = config.model_copy(
        update={
            "auth": AuthSettings(user_access_token=user_token, tenant_access_token=tenant_token),
            "storage": StorageSettings(
                root=storage_root,
                nested_dir=config.storage.nested_dir,
                images_dir=config.storage.images_dir,
                attachments_dir=config.storage.attachments_dir,
                preserve_remote_structure=config.storage.preserve_remote_structure,
            ),
        }
    )

    client = FeishuAPIClient.from_config(config)
    storage = StorageManager(config.storage)
    registry = DownloaderRegistry()
    registry.register("docx", DocxDownloader)
    registry.register("doc", DocxDownloader)
    registry.register("sheet", SheetDownloader)
    registry.register("bitable", BitableDownloader)
    registry.register("file", FileDownloader)
    registry.register("slides", SlidesPlaceholderDownloader)
    registry.register("mindnote", MindnotePlaceholderDownloader)
    registry.register("folder", FolderDownloader)
    registry.register("shortcut", ShortcutDownloader)
    registry.register("wiki", WikiDownloader)

    return SyncEngine(config=config, client=client, registry=registry, storage=storage)


@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case.label)
def test_download_cases(case: DownloadCase, tmp_path: Path) -> None:
    """Attempt to download each case defined in test.md."""

    config_path = Path("config.toml") if Path("config.toml").exists() else None
    engine = _build_engine_for_case(case, tmp_path, config_path)
    try:
        supported_types = set(engine.registry.available_types())
        if case.file_type not in supported_types:
            pytest.xfail(f"Downloader for file type '{case.file_type}' not yet implemented")

        task_type = "docx" if case.file_type == "doc" else case.file_type
        task = SyncTask(token=case.token, file_type=task_type, name=case.label, parent_path=Path("."))
        try:
            engine.process_task(task)
        except FeishuAPIError as exc:
            if exc.status_code == 401:
                pytest.xfail("Access token invalid or expired")
            raise

        outputs = [p for p in engine.storage.root.rglob("*") if p.is_file()]
        assert outputs, f"No output produced for {case.label}"
    finally:
        engine.close()
