"""User management routes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import User

router = APIRouter(prefix="/users", tags=["users"])


class UserProfileResponse(BaseModel):
    """User profile response."""

    id: int
    feishu_user_id: str
    display_name: Optional[str]
    avatar_url: Optional[str]
    email: Optional[str]
    storage_root: Optional[str]
    created_at: datetime
    last_login_at: Optional[datetime]
    token_status: str
    token_expires_at: Optional[datetime]
    refresh_token_expires_at: Optional[datetime]
    wiki_allowed: bool

    class Config:
        from_attributes = True


class StorageStatsResponse(BaseModel):
    """Storage statistics response."""

    storage_root: Optional[str]
    total_sync_configs: int
    total_sync_runs: int
    # In the future, we can add:
    # total_files: int
    # total_size_bytes: int


def _is_wiki_allowed(request: Request, user: User) -> bool:
    config = request.app.state.config
    raw = config.web.allow_download_wiki_user_ids
    if not raw:
        return False
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return user.feishu_user_id in allowed


def _is_user_allowed(request: Request, user: User) -> bool:
    config = request.app.state.config
    raw = config.web.allow_download_user_ids
    if not raw:
        return False
    if raw.strip() == "*":
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return user.feishu_user_id in allowed


@router.get("/me", response_model=UserProfileResponse)
async def get_my_profile(
    request: Request,
    user: User = Depends(get_current_user),
) -> UserProfileResponse:
    """Get current user's profile."""
    # Determine token status
    if not user.access_token:
        token_status = "missing"
    elif not user.is_token_valid:
        token_status = "expired"
    elif user.is_token_expiring_soon:
        token_status = "expiring_soon"
    else:
        token_status = "valid"

    return UserProfileResponse(
        id=user.id,
        feishu_user_id=user.feishu_user_id,
        display_name=user.display_name,
        avatar_url=user.avatar_url,
        email=user.email,
        storage_root=user.storage_root,
        created_at=user.created_at,
        last_login_at=user.last_login_at,
        token_status=token_status,
        token_expires_at=user.token_expires_at,
        refresh_token_expires_at=user.refresh_token_expires_at,
        wiki_allowed=_is_wiki_allowed(request, user) if _is_user_allowed(request, user) else False,
    )


@router.get("/me/storage-stats", response_model=StorageStatsResponse)
async def get_my_storage_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> StorageStatsResponse:
    """Get storage statistics for current user."""
    from ..models import SyncConfig, SyncRun

    total_configs = db.query(SyncConfig).filter(SyncConfig.user_id == user.id).count()
    total_runs = db.query(SyncRun).filter(SyncRun.user_id == user.id).count()

    return StorageStatsResponse(
        storage_root=user.storage_root,
        total_sync_configs=total_configs,
        total_sync_runs=total_runs,
    )
