"""SQLAlchemy models for LarkSync Web multi-user system."""

from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .database import Base


class SyncType(str, enum.Enum):
    """Type of sync task."""
    MY_SPACE = "my_space"
    WIKI = "wiki"


class SyncMode(str, enum.Enum):
    """Sync mode."""
    INCREMENTAL = "incremental"
    FULL = "full"


class ScheduleType(str, enum.Enum):
    """Schedule type for sync tasks."""
    MANUAL = "manual"
    CRON = "cron"
    INTERVAL = "interval"


class SyncRunStatus(str, enum.Enum):
    """Status of a sync run."""
    QUEUED = "queued"
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    AUTH_REQUIRED = "auth_required"
    CANCELLED = "cancelled"


class FileStatus(str, enum.Enum):
    """Status of a synced file."""
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"
    FAILED = "failed"


def utcnow() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Ensure datetime is timezone-aware (UTC). SQLite may return naive datetime."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class User(Base):
    """User model for multi-user sync system."""
    
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    feishu_user_id = Column(String(64), unique=True, nullable=False, index=True)
    display_name = Column(String(255), nullable=True)
    avatar_url = Column(String(1024), nullable=True)
    email = Column(String(255), nullable=True)
    
    # OAuth tokens
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expires_at = Column(DateTime(timezone=True), nullable=True)
    refresh_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    
    # Storage configuration
    storage_root = Column(String(1024), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)
    
    # Relationships
    sync_configs = relationship("SyncConfig", back_populates="user", cascade="all, delete-orphan")
    sync_runs = relationship("SyncRun", back_populates="user", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<User(id={self.id}, feishu_user_id={self.feishu_user_id}, display_name={self.display_name})>"
    
    @property
    def is_token_valid(self) -> bool:
        """Check if the access token is still valid."""
        if not self.access_token or not self.token_expires_at:
            return False
        expires_at = ensure_utc(self.token_expires_at)
        return expires_at > utcnow()
    
    @property
    def is_token_expiring_soon(self) -> bool:
        """Check if the access token is expiring within the refresh margin."""
        if not self.token_expires_at:
            return True
        from datetime import timedelta
        expires_at = ensure_utc(self.token_expires_at)
        margin = timedelta(minutes=10)
        return expires_at < (utcnow() + margin)


class SyncConfig(Base):
    """Sync task configuration model."""
    
    __tablename__ = "sync_configs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Configuration details
    name = Column(String(255), nullable=False)
    sync_type = Column(Enum(SyncType), nullable=False, default=SyncType.MY_SPACE)
    
    # Wiki-specific fields
    wiki_space_id = Column(String(64), nullable=True)
    wiki_space_name = Column(String(255), nullable=True)
    
    # Sync options
    sync_mode = Column(Enum(SyncMode), nullable=False, default=SyncMode.INCREMENTAL)
    limit = Column(Integer, nullable=False, default=0)  # 0 = no limit
    
    # Schedule configuration
    schedule_type = Column(Enum(ScheduleType), nullable=False, default=ScheduleType.MANUAL)
    schedule_cron = Column(String(100), nullable=True)  # e.g., "0 3 * * *"
    schedule_interval_hours = Column(Integer, nullable=True)  # e.g., 6
    
    # Status
    enabled = Column(Boolean, nullable=False, default=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    
    # Relationships
    user = relationship("User", back_populates="sync_configs")
    sync_runs = relationship("SyncRun", back_populates="config", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<SyncConfig(id={self.id}, name={self.name}, sync_type={self.sync_type})>"


class SyncRun(Base):
    """Sync execution record model."""
    
    __tablename__ = "sync_runs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    config_id = Column(Integer, ForeignKey("sync_configs.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Status
    status = Column(Enum(SyncRunStatus), nullable=False, default=SyncRunStatus.PENDING)
    
    # Progress counters
    total_files = Column(Integer, nullable=False, default=0)
    total_folders = Column(Integer, nullable=False, default=0)
    downloaded = Column(Integer, nullable=False, default=0)
    skipped = Column(Integer, nullable=False, default=0)
    errors = Column(Integer, nullable=False, default=0)
    
    # Current progress info (for live updates)
    current_file = Column(String(255), nullable=True)
    current_stage = Column(String(50), nullable=True)  # discover, download, etc.
    
    # Error info
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    
    # Relationships
    config = relationship("SyncConfig", back_populates="sync_runs")
    user = relationship("User", back_populates="sync_runs")
    file_records = relationship("SyncFileRecord", back_populates="sync_run", cascade="all, delete-orphan")
    
    def __repr__(self) -> str:
        return f"<SyncRun(id={self.id}, config_id={self.config_id}, status={self.status})>"
    
    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate the duration of the sync run in seconds."""
        if not self.started_at:
            return None
        started = ensure_utc(self.started_at)
        end_time = ensure_utc(self.finished_at) if self.finished_at else utcnow()
        return (end_time - started).total_seconds()
    
    @property
    def progress_percent(self) -> float:
        """Calculate progress percentage."""
        if self.total_files == 0:
            return 0.0
        completed = self.downloaded + self.skipped + self.errors
        return min(100.0, (completed / self.total_files) * 100)


class SyncFileRecord(Base):
    """Record of individual file sync status."""
    
    __tablename__ = "sync_file_records"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(Integer, ForeignKey("sync_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # File info
    file_name = Column(String(500), nullable=False)
    file_path = Column(String(1000), nullable=True)  # Local path after download
    file_type = Column(String(50), nullable=True)  # docx, sheet, file, etc.
    token = Column(String(100), nullable=True)  # Feishu document token
    
    # Status
    status = Column(Enum(FileStatus), nullable=False)
    reason = Column(Text, nullable=True)  # Reason for skip/failure
    
    # Timestamps
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    
    # Relationships
    sync_run = relationship("SyncRun", back_populates="file_records")
    
    def __repr__(self) -> str:
        return f"<SyncFileRecord(id={self.id}, run_id={self.run_id}, file_name={self.file_name}, status={self.status})>"
