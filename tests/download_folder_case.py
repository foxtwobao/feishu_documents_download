#!/usr/bin/env python3
"""Download a specific Feishu folder for manual verification."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from larksync.core.models import SyncTask
from larksync.utils.filesystem import sanitize_filename

from tests.run_download_tests import _build_engine, _extract_token

DEFAULT_URL = "https://ccpg1987.feishu.cn/drive/folder/CMaWfvvkXlmgFEdieIfcKkSAnLc?from=from_copylink"
MANUAL_OUTPUT_ROOT = Path("output") / "manual_tests"


def run_download(url: str, config_path: Path | None) -> Path:
    token = _extract_token(url)
    safe_token = sanitize_filename(token) or token
    target_dir = MANUAL_OUTPUT_ROOT / safe_token
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)

    engine, _ = _build_engine(target_dir, config_path)
    try:
        task = SyncTask(token=token, file_type="folder", name="manual_folder", parent_path=Path("."))
        engine.process_task(task)
        return target_dir
    finally:
        engine.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Download a Feishu folder for manual inspection.")
    parser.add_argument("--url", default=DEFAULT_URL, help="Folder share link to download.")
    parser.add_argument("--config", default="config.toml", help="Path to config.toml (default: config.toml).")
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    if not config_path.exists():
        config_path = None

    output_dir = run_download(args.url, config_path)
    print(f"[INFO] Folder downloaded to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
