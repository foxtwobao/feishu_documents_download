"""Command line interface for LarkSync."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer

from .bootstrap import build_runtime, build_metadata_store
from .cli_oauth import CLITokenManager  # type: ignore[attr-defined]
from .config import LarkSyncConfig, load_config
from .core.api_client import FeishuAPIError
from .core.models import SyncTask
from .core.sync_engine import SyncEngine
from .core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from .core.wiki_sync import WikiSpaceSynchronizer, WikiSyncContext
from .logging_utils import configure_logging
from .storage import MetadataStore, SQLiteMetadataStore

app = typer.Typer(help="Sync Feishu personal documents to local storage.")


def _build_engine(config_path: Path | None) -> tuple[LarkSyncConfig, SyncEngine]:
    config, client, storage, registry = build_runtime(config_path)
    configure_logging(config.logging)
    engine = SyncEngine(config=config, client=client, registry=registry, storage=storage)
    return config, engine


def _build_token_manager(config: LarkSyncConfig) -> CLITokenManager:
    return CLITokenManager(config.auth)


@app.command("download")
def download(
    token: str = typer.Argument(..., help="Feishu document token or full URL"),
    file_type: str = typer.Option("docx", "--type", "-t", help="Document file type, e.g. docx, doc"),
    name: str | None = typer.Option(None, "--name", "-n", help="Override output filename (without extension)"),
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """Download a single document and convert/store locally."""

    file_type = file_type.lower()
    source_url: str | None = None
    parsed_token = token
    if "://" in token:
        source_url = token.strip()
        parsed_token = token.rstrip("/").split("/")[-1]
        parsed_token = parsed_token.split("?")[0].split("#")[0]
    else:
        parsed_token = token.split("?")[0].split("#")[0]

    config, engine = _build_engine(config_path)
    task_name = name or parsed_token
    task = SyncTask(
        token=parsed_token,
        file_type=file_type,
        name=task_name,
        parent_path=Path("."),
        extra={"source_url": source_url} if source_url else {},
    )
    success = False
    try:
        engine.process_task(task)
        success = True
    except KeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except FeishuAPIError as exc:
        payload = exc.payload or {}
        if exc.status_code == 400 and payload.get("code") == 1770003:
            typer.secho("目标资源已在飞书端删除，跳过下载。", fg=typer.colors.YELLOW)
            return
        raise
    finally:
        engine.close()
    if success:
        typer.echo(f"Downloaded {file_type} {token} → {config.storage.root}")


@app.command("download-docx")
def download_docx(
    token: str = typer.Argument(..., help="Feishu docx document token"),
    name: str | None = typer.Option(None, "--name", "-n", help="Override output filename (without extension)"),
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """Download a single DocX document and convert it to Markdown."""

    download(token=token, file_type="docx", name=name, config_path=config_path)  # type: ignore[arg-type]


@app.command("sync-space")
def sync_space(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
    limit: int = typer.Option(10, "--limit", help="Maximum number of files to download (default: 10; 0 for no limit)"),
    incremental: Optional[bool] = typer.Option(
        None,
        "--incremental/--no-incremental",
        help="Enable or disable incremental sync for this run (overrides config)",
    ),
    full: bool = typer.Option(False, "--full", help="Perform a full sync regardless of metadata"),
    reset_metadata: bool = typer.Option(False, "--reset-metadata", help="Clear cached metadata before syncing"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Quiet mode: only show progress, suppress logs"),
) -> None:
    """Traverse personal space and download every accessible document."""

    config, engine = _build_engine(config_path)
    
    # 安静模式：设置日志级别为 ERROR
    if quiet:
        import logging
        logging.getLogger().setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.ERROR)
        logging.getLogger("larksync").setLevel(logging.ERROR)
    
    # 根据配置创建 metadata store（支持 JSON 或 SQLite）
    metadata_store = build_metadata_store(config, engine.storage.root)
    if reset_metadata:
        metadata_store.clear()
        metadata_store.flush()

    effective_incremental = config.sync.enable_incremental
    if incremental is not None:
        effective_incremental = incremental
    if full:
        effective_incremental = False

    limit_value = None if limit <= 0 else limit
    context = SpaceSyncContext(
        engine=engine,
        drive=engine.drive_adapter,
        registry=engine.registry,
        storage=engine.storage,
    )

    # 创建进度追踪器
    from larksync.cli_progress import TerminalProgressTracker
    progress_tracker = TerminalProgressTracker(limit=limit_value)
    
    synchronizer = DriveSpaceSynchronizer(
        context,
        metadata_store,
        limit=limit_value,
        incremental=effective_incremental,
        force_on_missing=config.sync.force_download_missing,
        clean_deleted=config.sync.clean_deleted,
        progress_callback=progress_tracker.update,
        progress_tracker=progress_tracker,
    )
    
    try:
        progress_tracker.start()
        synchronizer.sync()
        summary = synchronizer.summary()  # 获取统计信息
        progress_tracker.finish(config.storage.root, summary)  # 传递summary
    finally:
        engine.close()


@app.command("sync-wiki")
def sync_wiki(
    space_id: Optional[str] = typer.Option(
        None, "--space-id", "-s", help="Wiki space ID to sync"
    ),
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help="Path to config.toml"
    ),
    limit: int = typer.Option(
        0, "--limit", help="Maximum number of files to download (default: no limit; 0 for no limit)"
    ),
    incremental: Optional[bool] = typer.Option(
        None,
        "--incremental/--no-incremental",
        help="Enable or disable incremental sync for this run (overrides config)",
    ),
    full: bool = typer.Option(
        False, "--full", help="Perform a full sync regardless of metadata"
    ),
    reset_metadata: bool = typer.Option(
        False, "--reset-metadata", help="Clear cached metadata before syncing"
    ),
    list_spaces: bool = typer.Option(
        False, "--list", "-l", help="List available wiki spaces and exit"
    ),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="Quiet mode: only show progress, suppress logs"
    ),
) -> None:
    """同步飞书知识库到本地。

    示例:
        larksync sync-wiki --list              # 列出可访问的知识库
        larksync sync-wiki -s <space_id>       # 同步指定知识库（默认完整遍历）
        larksync sync-wiki -s <space_id> --limit 0  # 完整同步（无限制）
    """
    config, engine = _build_engine(config_path)

    # 安静模式：设置日志级别为 ERROR
    if quiet:
        import logging
        logging.getLogger().setLevel(logging.ERROR)
        logging.getLogger("httpx").setLevel(logging.ERROR)
        logging.getLogger("larksync").setLevel(logging.ERROR)

    # 创建 metadata store
    metadata_store = build_metadata_store(config, engine.storage.root)
    if reset_metadata:
        metadata_store.clear()
        metadata_store.flush()

    # 确定增量同步模式
    effective_incremental = config.sync.enable_incremental
    if incremental is not None:
        effective_incremental = incremental
    if full:
        effective_incremental = False

    limit_value = None if limit <= 0 else limit

    # 创建 Wiki 同步上下文
    context = WikiSyncContext(
        engine=engine,
        wiki=engine.wiki_adapter,
        drive=engine.drive_adapter,
        registry=engine.registry,
        storage=engine.storage,
    )

    # 创建进度追踪器
    from larksync.cli_progress import TerminalProgressTracker
    progress_tracker = TerminalProgressTracker(limit=limit_value, sync_type="wiki")

    synchronizer = WikiSpaceSynchronizer(
        context,
        metadata_store,
        limit=limit_value,
        incremental=effective_incremental,
        force_on_missing=config.sync.force_download_missing,
        progress_callback=progress_tracker.update,
        progress_tracker=progress_tracker,
    )

    try:
        # 如果是列出知识库模式
        if list_spaces:
            typer.echo()
            typer.secho("🔍 正在获取知识库列表...", fg=typer.colors.CYAN)
            spaces = synchronizer.list_spaces()
            if not spaces:
                typer.secho("⚠️  未找到可访问的知识库", fg=typer.colors.YELLOW)
                typer.echo("请确认您的应用已获得知识库读取权限 (wiki:wiki:readonly)")
                return

            typer.echo()
            typer.secho(f"📚 找到 {len(spaces)} 个知识库:", fg=typer.colors.GREEN)
            typer.echo("━" * 60)
            for space in spaces:
                space_id_str = space.get("space_id", "N/A")
                name = space.get("name", "未命名")
                description = space.get("description", "")
                typer.echo(f"  ID: {space_id_str}")
                typer.secho(f"  名称: {name}", fg=typer.colors.CYAN, bold=True)
                if description:
                    typer.echo(f"  描述: {description[:50]}...")
                typer.echo("  " + "-" * 40)
            typer.echo()
            typer.echo("使用方法: larksync sync-wiki --space-id <SPACE_ID>")
            return

        # 检查是否指定了 space_id
        if not space_id:
            typer.secho("❌ 错误：请指定知识库 ID", fg=typer.colors.RED)
            typer.echo("使用 --list 查看可用的知识库")
            typer.echo("使用 --space-id <ID> 指定要同步的知识库")
            raise typer.Exit(code=1)

        # 执行同步
        progress_tracker.start()
        synchronizer.sync(space_id)
        summary = synchronizer.summary()
        progress_tracker.finish(config.storage.root, summary)

    except FeishuAPIError as exc:
        typer.secho(f"❌ API 错误: {exc.message}", fg=typer.colors.RED)
        if exc.status_code == 403:
            typer.echo("请确认应用已获得知识库相关权限")
        raise typer.Exit(code=1) from exc
    finally:
        engine.close()


@app.command("login")
def login(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """通过浏览器进行飞书 OAuth 授权。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    if not config.auth.app_id or not config.auth.app_secret:
        typer.secho(
            "错误：未配置 app_id 和 app_secret",
            fg=typer.colors.RED,
        )
        typer.echo("请在 config.toml 中配置：")
        typer.echo("""[auth]
app_id = "your_app_id"
app_secret = "your_app_secret"
""")
        raise typer.Exit(code=1)
    
    token_manager = _build_token_manager(config)
    
    try:
        access_token = token_manager._authorize_and_get_token()
        typer.secho("✅ 授权成功！", fg=typer.colors.GREEN)
        typer.echo(f"Access Token: {access_token[:20]}...")
        typer.echo(f"✨ Token 已保存到 {token_manager.token_cache.cache_path}")
    except Exception as e:
        typer.secho(f"❌ 授权失败：{e}", fg=typer.colors.RED)
        raise typer.Exit(code=1)


@app.command("token-status")
def token_status(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """查看当前 token 状态。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    token_manager = _build_token_manager(config)
    status = token_manager.get_token_status()
    
    typer.echo("\n" + "="*60)
    typer.echo("Token 状态")
    typer.echo("="*60)
    
    status_colors = {
        "valid": typer.colors.GREEN,
        "expiring_soon": typer.colors.YELLOW,
        "expired": typer.colors.RED,
        "no_cache": typer.colors.YELLOW,
        "invalid_cache": typer.colors.RED,
    }
    
    color = status_colors.get(status["status"], typer.colors.WHITE)
    typer.secho(f"状态: {status['message']}", fg=color)
    
    if "expires_at" in status:
        typer.echo(f"过期时间: {status['expires_at']}")
    if "updated_at" in status:
        typer.echo(f"更新时间: {status['updated_at']}")
    
    typer.echo(f"缓存位置: {token_manager.token_cache.cache_path}")
    typer.echo("="*60 + "\n")
    
    if status["status"] in ["expired", "no_cache"]:
        typer.echo("提示：请运行 'larksync login' 进行授权")


@app.command("refresh-token")
def refresh_token_cmd(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """手动刷新 access token。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    token_manager = _build_token_manager(config)
    
    # 加载缓存
    cached = token_manager.token_cache.load()
    if not cached:
        typer.secho("错误：没有缓存的 token", fg=typer.colors.RED)
        typer.echo("请先运行 'larksync login' 进行授权")
        raise typer.Exit(code=1)
    
    try:
        typer.echo("🔄 正在刷新 token...")
        new_access_token, new_refresh_token, expires_in = token_manager._refresh_cached_token(cached)
        typer.secho("✅ Token 刷新成功！", fg=typer.colors.GREEN)
        typer.echo(f"Access Token: {new_access_token[:20]}...")
        typer.echo(f"有效期: {expires_in} 秒 ({expires_in // 3600} 小时)")
    except Exception as e:
        typer.secho(f"❌ 刷新失败：{e}", fg=typer.colors.RED)
        typer.echo("请运行 'larksync login' 重新授权")
        raise typer.Exit(code=1)


@app.command("logout")
def logout(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """清除本地缓存的 token。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    token_manager = _build_token_manager(config)
    token_manager.clear_cache()
    
    typer.secho("✅ 已清除本地 token 缓存", fg=typer.colors.GREEN)


@app.command("migrate-metadata")
def migrate_metadata(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
    backup: bool = typer.Option(True, "--backup/--no-backup", help="Backup JSON file after migration"),
) -> None:
    """将 metadata 从 JSON 迁移到 SQLite 存储。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    from .storage.migration import migrate_json_to_sqlite
    
    storage_root = config.storage.root.expanduser()
    
    typer.echo("🔄 正在迁移 metadata...")
    typer.echo(f"   存储目录: {storage_root}")
    typer.echo(f"   JSON 文件: {config.storage.metadata_json_file}")
    typer.echo(f"   SQLite 数据库: {config.storage.metadata_sqlite_file}")
    
    count = migrate_json_to_sqlite(
        storage_root,
        json_filename=config.storage.metadata_json_file,
        sqlite_filename=config.storage.metadata_sqlite_file,
        backup=backup,
    )
    
    if count > 0:
        typer.secho(f"✅ 迁移完成！共迁移 {count} 条记录", fg=typer.colors.GREEN)
        if backup:
            typer.echo("   原 JSON 文件已备份")
    else:
        typer.secho("⚠️  没有数据需要迁移", fg=typer.colors.YELLOW)


@app.command("metadata-stats")
def metadata_stats(
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
    backend: str = typer.Option("auto", "--backend", "-b", help="Backend to check: auto, json, sqlite"),
) -> None:
    """显示 metadata 存储统计信息。"""
    config = load_config(config_path)
    configure_logging(config.logging)
    
    storage_root = config.storage.root.expanduser()
    
    typer.echo("\n" + "=" * 60)
    typer.echo("Metadata 存储统计")
    typer.echo("=" * 60)
    typer.echo(f"存储目录: {storage_root}")
    
    # 检查 JSON
    json_path = storage_root / config.storage.metadata_json_file
    if json_path.exists():
        import json
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            typer.echo(f"\n📄 JSON 存储 ({config.storage.metadata_json_file}):")
            typer.echo(f"   文件大小: {json_path.stat().st_size / 1024:.1f} KB")
            typer.echo(f"   记录数: {len(data)}")
        except (json.JSONDecodeError, OSError) as e:
            typer.echo(f"\n📄 JSON 存储: 读取失败 ({e})")
    else:
        typer.echo(f"\n📄 JSON 存储: 不存在")
    
    # 检查 SQLite
    sqlite_path = storage_root / config.storage.metadata_sqlite_file
    if sqlite_path.exists():
        from .storage import SQLiteMetadataStore
        try:
            store = SQLiteMetadataStore(sqlite_path, storage_root)
            stats = store.stats()
            store.close()
            
            typer.echo(f"\n🗄️  SQLite 存储 ({config.storage.metadata_sqlite_file}):")
            typer.echo(f"   文件大小: {sqlite_path.stat().st_size / 1024:.1f} KB")
            typer.echo(f"   总记录数: {stats['total']}")
            
            if stats['by_status']:
                typer.echo("   按状态统计:")
                for status, cnt in sorted(stats['by_status'].items()):
                    typer.echo(f"     - {status}: {cnt}")
            
            if stats['by_type']:
                typer.echo("   按类型统计:")
                for ftype, cnt in sorted(stats['by_type'].items()):
                    typer.echo(f"     - {ftype}: {cnt}")
            
            if stats['shortcuts'] > 0:
                typer.echo(f"   快捷方式映射: {stats['shortcuts']}")
            if stats['history_entries'] > 0:
                typer.echo(f"   历史记录: {stats['history_entries']}")
        except Exception as e:
            typer.echo(f"\n🗄️  SQLite 存储: 读取失败 ({e})")
    else:
        typer.echo(f"\n🗄️  SQLite 存储: 不存在")
    
    typer.echo("\n" + "=" * 60)
    typer.echo(f"当前配置的后端: {config.storage.metadata_backend}")
    typer.echo("=" * 60 + "\n")
