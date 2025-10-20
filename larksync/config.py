"""Configuration helpers for LarkSync."""

from __future__ import annotations

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


class StorageSettings(BaseModel):
    """Local storage layout."""

    model_config = ConfigDict(extra="ignore")

    root: Path = Field(default=Path("./output"), description="Root directory for synced files")
    nested_dir: str = Field(default="nested_docs", description="Directory to store nested documents")
    images_dir: str = Field(default="images", description="Directory to store downloaded images")
    attachments_dir: str = Field(default="attachments", description="Directory to store attachments")
    preserve_remote_structure: bool = Field(
        default=True, description="Whether to mirror the remote folder hierarchy locally"
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


def load_config(path: Optional[Path] = None) -> LarkSyncConfig:
    """Load configuration from a TOML file merged with environment overrides."""

    raw_config: Dict[str, Any] = {}
    config_path = _resolve_config_path(path)
    if config_path and config_path.exists():
        raw_config = _read_toml(config_path)

    raw_config = _apply_env_overrides(raw_config)
    return LarkSyncConfig.model_validate(raw_config)


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
