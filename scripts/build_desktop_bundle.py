#!/usr/bin/env python3
"""Build standalone desktop bundles for the LarkSync GUI using PyInstaller."""

from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
from pathlib import Path


def _ensure_pyinstaller_available() -> None:
    try:
        import PyInstaller  # noqa: F401  # pragma: no cover - availability check
    except ModuleNotFoundError as exc:  # pragma: no cover - runtime feedback
        message = (
            "PyInstaller 未安装。请先运行 `pip install pyinstaller` 再执行本脚本，"
            "即可在当前平台生成免安装的可执行程序。"
        )
        raise SystemExit(message) from exc


def build_desktop_bundle(name: str, mode: str, windowed: bool) -> Path:
    """Invoke PyInstaller and return the directory containing the artifacts."""

    root_dir = Path(__file__).resolve().parents[1]
    app_entry = root_dir / "larksync" / "local_app" / "__main__.py"
    if not app_entry.exists():  # pragma: no cover - defensive
        raise SystemExit(f"无法找到桌面程序入口：{app_entry}")

    dist_root = root_dir / "dist" / "desktop"
    work_root = root_dir / "build" / "desktop"
    platform_key = platform.system().lower()
    dist_dir = dist_root / platform_key
    work_dir = work_root / platform_key

    dist_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--clean",
        "--noconfirm",
        "--name",
        name,
        "--workpath",
        str(work_dir / "work"),
        "--specpath",
        str(work_dir / "spec"),
        "--distpath",
        str(dist_dir),
    ]

    if windowed:
        command.append("--windowed")
    if mode == "onefile":
        command.append("--onefile")

    command.append(str(app_entry))

    subprocess.run(command, check=True)
    return dist_dir


def _zip_artifacts(dist_dir: Path, name: str) -> Path:
    """Create a zip archive for easy distribution."""

    if not dist_dir.exists():  # pragma: no cover - defensive
        raise SystemExit(f"未找到打包输出目录：{dist_dir}")

    platform_key = platform.system().lower()
    archive_root = dist_dir.parent
    archive_root.mkdir(parents=True, exist_ok=True)

    archive_name = f"{name}-{platform_key}"
    archive_path = shutil.make_archive(str(archive_root / archive_name), "zip", root_dir=dist_dir)
    return Path(archive_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 LarkSync 桌面版的免安装包。")
    parser.add_argument("--name", default="LarkSyncDesktop", help="输出程序名称（默认：LarkSyncDesktop）")
    parser.add_argument(
        "--mode",
        choices=["onefile", "onedir"],
        default="onefile",
        help="PyInstaller 打包模式：onefile 生成单文件，onedir 生成目录。",
    )
    parser.add_argument(
        "--no-windowed",
        action="store_true",
        help="禁用窗口模式（调试命令行输出时可使用）。",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="跳过 zip 压缩，仅保留 PyInstaller 输出。",
    )
    args = parser.parse_args()

    _ensure_pyinstaller_available()
    dist_dir = build_desktop_bundle(args.name, args.mode, not args.no_windowed)

    print(f"PyInstaller 输出目录：{dist_dir}")

    if args.no_zip:
        return

    archive_path = _zip_artifacts(dist_dir, args.name)
    print(f"已生成压缩包：{archive_path}")


if __name__ == "__main__":  # pragma: no cover - script entry point
    main()
