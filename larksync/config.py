"""Configuration helpers for LarkSync."""

from __future__ import annotations

__all__ = [
    "AuthSettings",
    "LarkSyncConfig",
    "WebOAuthSettings",
    "WebSchedulerSettings",
    "WebSettings",
    "load_config",
]

import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, MutableMapping, Optional

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover - fallback for <3.11
    import tomli as tomllib  # type: ignore

from pydantic import BaseModel, ConfigDict, Field


class AuthSettings(BaseModel):
    """Authentication options for Feishu Open API."""

    model_config = ConfigDict(extra="ignore")

    app_id: Optional[str] = Field(default=None, description="App ID for tenant token flow")
    app_secret: Optional[str] = Field(default=None, description="App secret for tenant token flow")
    tenant_access_token: Optional[str] = Field(
        default=None, description="Tenant access token; overrides app_id/app_secret if provided"
    )
    user_access_token: Optional[str] = Field(
        default=None, description="User access token for personal space operations"
    )
    oauth_callback_url: Optional[str] = Field(
        default=None, description="OAuth callback URL for CLI authorization flow (e.g. reverse proxy URL)"
    )
    cli_oauth_listen_port: int = Field(
        default=8899, description="Local port for CLI OAuth callback server to listen on"
    )


class StorageSettings(BaseModel):
    """Local storage layout."""

    model_config = ConfigDict(extra="ignore")

    download_root: Optional[Path] = Field(
        default=Path("/download"),
        description="Unified download root for CLI/Web; overrides root and web.user_storage_base if set",
    )
    root: Path = Field(default=Path("./data/sync"), description="Root directory for synced files")
    nested_dir: str = Field(default="nested_docs", description="Directory to store nested documents")
    images_dir: str = Field(default="images", description="Directory to store downloaded images")
    attachments_dir: str = Field(default="attachments", description="Directory to store attachments")
    preserve_remote_structure: bool = Field(
        default=True, description="Whether to mirror the remote folder hierarchy locally"
    )
    # Metadata storage backend configuration
    metadata_backend: str = Field(
        default="json",
        description="Metadata storage backend: 'json' (legacy) or 'sqlite' (recommended)"
    )
    metadata_json_file: str = Field(
        default=".metadata.json",
        description="Filename for JSON metadata store"
    )
    metadata_sqlite_file: str = Field(
        default=".sync.db",
        description="Filename for SQLite metadata store"
    )
    metadata_enable_history: bool = Field(
        default=False,
        description="Enable sync history recording (SQLite only)"
    )
    metadata_auto_migrate: bool = Field(
        default=True,
        description="Auto-migrate JSON to SQLite when switching backends"
    )


class ConcurrencySettings(BaseModel):
    """Concurrency hints per file type."""

    model_config = ConfigDict(extra="allow")

    docx: int = 3
    sheet: int = 2
    bitable: int = 2
    file: int = 4


class RateLimitSettings(BaseModel):
    """Simple rate limit hints (requests per minute)."""

    model_config = ConfigDict(extra="allow")

    docx: int = 5
    sheet: int = 3
    bitable: int = 3
    file: int = 20


class FeatureFlags(BaseModel):
    """Feature toggles."""

    model_config = ConfigDict(extra="allow")

    slides_placeholder: bool = True
    mindnote_placeholder: bool = True
    wiki_support: bool = False


class RetrySettings(BaseModel):
    """Retry policy configuration."""

    model_config = ConfigDict(extra="ignore")

    max_attempts: int = 4
    initial_interval_seconds: float = 0.5
    backoff_multiplier: float = 2.0


class SyncSettings(BaseModel):
    """High level sync behaviour toggles."""

    model_config = ConfigDict(extra="ignore")

    max_nested_depth: int = 3
    enable_incremental: bool = True
    enable_preview: bool = False
    clean_deleted: bool = False
    force_download_missing: bool = True


class LoggingSettings(BaseModel):
    """Logging configuration."""

    model_config = ConfigDict(extra="ignore")

    level: str = "INFO"
    structured: bool = True


class WebOAuthSettings(BaseModel):
    """OAuth settings for Web UI."""

    model_config = ConfigDict(extra="ignore")

    app_id: Optional[str] = Field(default=None, description="Feishu app ID for OAuth")
    app_secret: Optional[str] = Field(default=None, description="Feishu app secret for OAuth")
    callback_url: Optional[str] = Field(
        default=None, description="OAuth callback URL (e.g. https://your-domain.com/auth/callback)"
    )
    base_url: Optional[str] = Field(
        default=None, description="Base URL for OAuth service (optional, for remote callback)"
    )
    token_refresh_margin_minutes: int = Field(
        default=10, description="Minutes before expiry to refresh token"
    )


class WebSchedulerSettings(BaseModel):
    """Scheduler settings for Web sync jobs."""

    model_config = ConfigDict(extra="ignore")

    check_interval: int = Field(default=60, description="Scheduler check interval in seconds")
    token_refresh_interval: int = Field(
        default=300, description="Token refresh interval in seconds"
    )
    force_queue: bool = Field(
        default=True,
        description="Force sync jobs to run sequentially in FIFO order",
    )
    max_concurrent_jobs: int = Field(default=3, description="Maximum concurrent sync jobs")


class WebSettings(BaseModel):
    """Web UI configuration."""

    model_config = ConfigDict(extra="ignore")

    enabled: bool = Field(default=True, description="Enable web UI")
    database_url: str = Field(
        default="sqlite:////data/web/larksync.db", description="SQLAlchemy database URL"
    )
    user_storage_base: Optional[str] = Field(
        default="./data/web/users", description="Base directory for user storage"
    )
    allow_download_user_ids: Optional[str] = Field(
        default=None,
        description="Comma-separated Feishu user IDs allowed to use the web system; '*' allows all",
    )
    allow_download_wiki_user_ids: Optional[str] = Field(
        default=None,
        description="Comma-separated Feishu user IDs allowed to create wiki sync configs",
    )
    secret_key: Optional[str] = Field(
        default=None, description="Secret key for session signing"
    )
    scheduler_interval_seconds: int = Field(
        default=300, description="Deprecated: use scheduler.token_refresh_interval instead"
    )
    oauth: WebOAuthSettings = Field(default_factory=WebOAuthSettings)
    scheduler: WebSchedulerSettings = Field(default_factory=WebSchedulerSettings)


class LarkSyncConfig(BaseModel):
    """Root configuration model."""

    model_config = ConfigDict(extra="ignore")

    auth: AuthSettings = Field(default_factory=AuthSettings)
    storage: StorageSettings = Field(default_factory=StorageSettings)
    concurrency: ConcurrencySettings = Field(default_factory=ConcurrencySettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    features: FeatureFlags = Field(default_factory=FeatureFlags)
    retry: RetrySettings = Field(default_factory=RetrySettings)
    sync: SyncSettings = Field(default_factory=SyncSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    web: WebSettings = Field(default_factory=WebSettings)


def load_config(path: Optional[Path] = None) -> LarkSyncConfig:
    """Load configuration from a TOML file merged with environment overrides."""

    raw_config: Dict[str, Any] = {}
    config_path = _resolve_config_path(path)
    if config_path and config_path.exists():
        raw_config = _read_toml(config_path)

    raw_config = _apply_env_overrides(raw_config)
    config = LarkSyncConfig.model_validate(raw_config)

    # Optional unified download root for CLI + Web.
    download_root = config.storage.download_root
    if download_root:
        config.storage.root = download_root / "cli"
        web_raw = raw_config.get("web", {})
        user_storage_explicit = isinstance(web_raw, Mapping) and "user_storage_base" in web_raw
        if not user_storage_explicit:
            config.web.user_storage_base = str(download_root / "web")

    return config


def _resolve_config_path(path: Optional[Path]) -> Optional[Path]:
    if path:
        return path.expanduser().resolve()
    env_path = os.environ.get("LARKSYNC_CONFIG")
    if env_path:
        return Path(env_path).expanduser().resolve()
    default_path = Path("config.toml")
    return default_path.resolve() if default_path.exists() else None


def _read_toml(path: Path) -> Dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _apply_env_overrides(raw: Dict[str, Any]) -> Dict[str, Any]:
    # Backwards-compatible single-variable overrides
    env_map: Dict[tuple[str, ...], str] = {
        ("auth", "app_id"): "LARKSYNC_APP_ID",
        ("auth", "app_secret"): "LARKSYNC_APP_SECRET",
        ("auth", "tenant_access_token"): "LARKSYNC_TENANT_ACCESS_TOKEN",
        ("auth", "user_access_token"): "LARKSYNC_USER_ACCESS_TOKEN",
        ("storage", "download_root"): "LARKSYNC_DOWNLOAD_ROOT",
        ("storage", "root"): "LARKSYNC_STORAGE_ROOT",
        ("logging", "level"): "LARKSYNC_LOG_LEVEL",
        ("logging", "structured"): "LARKSYNC_LOG_STRUCTURED",
    }

    updated = dict(raw)
    for key_path, env_var in env_map.items():
        value = os.environ.get(env_var)
        if value is None:
            continue
        _set_nested_value(updated, key_path, value)

    for key_path, value in _collect_prefixed_env("LARKSYNC").items():
        _set_nested_value(updated, key_path, value)

    return updated


def _collect_prefixed_env(prefix: str) -> Dict[tuple[str, ...], str]:
    overrides: Dict[tuple[str, ...], str] = {}
    marker = f"{prefix}__"

    for env_key, env_value in os.environ.items():
        if not env_key.startswith(marker):
            continue

        raw_segments = env_key[len(marker) :].split("__")
        segments = tuple(_normalise_env_segment(segment) for segment in raw_segments if segment)
        if not segments:
            continue

        overrides[segments] = env_value
    return overrides


def _normalise_env_segment(segment: str) -> str:
    """Convert environment variable chunks into configuration keys."""

    return segment.strip().lower()


def _set_nested_value(data: MutableMapping[str, Any], path: Iterable[str], value: Any) -> None:
    segments = list(path)
    cursor: MutableMapping[str, Any] = data
    for segment in segments[:-1]:
        next_value = cursor.get(segment)
        if not isinstance(next_value, Mapping):
            next_value = {}
            cursor[segment] = next_value
        cursor = next_value  # type: ignore[assignment]
    cursor[segments[-1]] = value
