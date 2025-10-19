"""Command line interface for LarkSync."""

from __future__ import annotations

from pathlib import Path

import typer

from .bootstrap import build_runtime
from .config import LarkSyncConfig
from .core.models import SyncTask
from .core.sync_engine import SyncEngine
from .core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from .logging_utils import configure_logging
from .storage import MetadataStore

app = typer.Typer(help="Sync Feishu personal documents to local storage.")


def _build_engine(config_path: Path | None) -> tuple[LarkSyncConfig, SyncEngine]:
    config, client, storage, registry = build_runtime(config_path)
    configure_logging(config.logging)
    engine = SyncEngine(config=config, client=client, registry=registry, storage=storage)
    return config, engine


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
    try:
        engine.process_task(task)
    except KeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    finally:
        engine.close()
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
    limit: int = typer.Option(10, "--limit", help="Maximum number of files to download (default: 10)"),
) -> None:
    """Traverse personal space and download every accessible document."""

    config, engine = _build_engine(config_path)
    metadata_store = MetadataStore(engine.storage.root)
    context = SpaceSyncContext(
        engine=engine,
        drive=engine.drive_adapter,
        registry=engine.registry,
        storage=engine.storage,
    )

    synchronizer = DriveSpaceSynchronizer(context, metadata_store, limit=limit if limit > 0 else None)
    try:
        synchronizer.sync()
    finally:
        engine.close()
    typer.echo(f"Synced space to {config.storage.root}")


if __name__ == "__main__":
    app()
