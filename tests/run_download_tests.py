#!/usr/bin/env python3
"""Run download checks for entries listed in test.md."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

from larksync.config import AuthSettings, StorageSettings, load_config
from larksync.core.api_client import FeishuAPIClient
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
from larksync.utils.filesystem import sanitize_filename

CASE_PATTERN = re.compile(r"-\s*`(?P<type>[^`]+)`.*?:\s*(?P<url>https?://\S+)")
FOLDER_PATTERN = re.compile(r"#\s*文件夹下载\s*\n(?P<url>https?://\S+)")
SUPPORTED_TYPES = {
    "doc",
    "docx",
    "sheet",
    "bitable",
    "file",
    "slides",
    "mindnote",
    "folder",
    "wiki",
}

TEST_OUTPUT_ROOT = Path("output") / "testcase"


@dataclass(frozen=True)
class DownloadCase:
    label: str
    token: str
    file_type: str


def load_cases(test_md_path: Path) -> List[DownloadCase]:
    content = test_md_path.read_text(encoding="utf-8")
    cases: List[DownloadCase] = []

    folder_match = FOLDER_PATTERN.search(content)
    if folder_match:
        cases.append(
            DownloadCase(
                label="folder",
                token=_extract_token(folder_match.group("url")),
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


def _build_engine(storage_root: Path, config_path: Path | None) -> Tuple[SyncEngine, str]:
    config = load_config(config_path)
    user_token = config.auth.user_access_token or os.getenv("LARKSYNC_USER_ACCESS_TOKEN")
    tenant_token = config.auth.tenant_access_token or os.getenv("LARKSYNC_TENANT_ACCESS_TOKEN")
    if not (user_token or tenant_token):
        raise RuntimeError(
            "Missing Feishu token. Configure [auth] in config.toml or export "
            "LARKSYNC_USER_ACCESS_TOKEN/LARKSYNC_TENANT_ACCESS_TOKEN."
        )

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
    engine = SyncEngine(config=config, client=client, registry=registry, storage=storage)
    token_source = "config" if config.auth.user_access_token or config.auth.tenant_access_token else "env"
    return engine, token_source


def run_case(case: DownloadCase, config_path: Path | None) -> Tuple[str, str]:
    if case.file_type not in SUPPORTED_TYPES:
        return "SKIP", f"{case.file_type} not supported"

    task_type = "docx" if case.file_type == "doc" else case.file_type
    safe_label = sanitize_filename(case.label) or case.file_type
    safe_token = sanitize_filename(case.token) or case.token
    storage_root = TEST_OUTPUT_ROOT / f"{safe_label}_{safe_token}"

    if storage_root.exists():
        shutil.rmtree(storage_root)
    storage_root.mkdir(parents=True, exist_ok=True)

    try:
        engine, _ = _build_engine(storage_root, config_path)
    except RuntimeError as exc:
        return "SKIP", str(exc)

    try:
        task = SyncTask(token=case.token, file_type=task_type, name=case.label, parent_path=Path("."))
        engine.process_task(task)
        outputs = [p for p in engine.storage.root.rglob("*") if p.is_file()]
        if not outputs:
            return "FAIL", "No output generated"
        primary = outputs[0].relative_to(engine.storage.root)
        return "OK", str(TEST_OUTPUT_ROOT / storage_root.name / primary)
    except Exception as exc:  # noqa: B902 - best effort reporting
        return "FAIL", str(exc)
    finally:
        engine.close()


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Feishu download checks based on test.md entries.")
    parser.add_argument("--test-md", default="test.md", help="Path to test.md list (default: test.md).")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml (default: config.toml).")
    args = parser.parse_args(list(argv) if argv is not None else None)

    test_md_path = Path(args.test_md).resolve()
    if not test_md_path.exists():
        print(f"[ERROR] test list not found: {test_md_path}", file=sys.stderr)
        return 1

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        config_path = None

    cases = load_cases(test_md_path)
    if not cases:
        print("[WARN] No downloadable entries found in test.md")
        return 0

    print(f"[INFO] Running download checks for {len(cases)} cases...")
    failures = 0
    for case in cases:
        status, message = run_case(case, config_path)
        print(f"[{status:>4}] {case.label:10s} {case.token} -> {message}")
        if status == "FAIL":
            failures += 1

    if failures:
        print(f"[ERROR] {failures} case(s) failed.")
        return 1

    print("[INFO] Download checks completed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
