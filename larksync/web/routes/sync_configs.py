"""Sync configuration routes."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user, require_valid_token
from ..models import ScheduleType, SyncConfig, SyncMode, SyncRun, SyncRunStatus, SyncType, User

router = APIRouter(prefix="/sync-configs", tags=["sync-configs"])


def _parse_allowed_wiki_users(request: Request) -> set[str]:
    config = request.app.state.config
    raw = config.web.allow_download_wiki_user_ids
    if not raw:
        return set()
    return {item.strip() for item in raw.split(",") if item.strip()}


def _ensure_wiki_allowed(request: Request, user: User) -> None:
    allowed = _parse_allowed_wiki_users(request)
    if not allowed or user.feishu_user_id not in allowed:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wiki sync is not enabled for this user",
        )


# ============== Request/Response Models ==============

class SyncConfigCreate(BaseModel):
    """Request body for creating a sync config."""

    name: str = Field(..., min_length=1, max_length=255)
    sync_type: SyncType = SyncType.MY_SPACE
    wiki_space_id: Optional[str] = None
    wiki_space_name: Optional[str] = None
    sync_mode: SyncMode = SyncMode.INCREMENTAL
    limit: int = Field(default=0, ge=0)  # 0 = no limit
    schedule_type: ScheduleType = ScheduleType.MANUAL
    schedule_cron: Optional[str] = None
    schedule_interval_hours: Optional[int] = Field(default=None, ge=1)
    enabled: bool = True


class SyncConfigUpdate(BaseModel):
    """Request body for updating a sync config."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    sync_mode: Optional[SyncMode] = None
    limit: Optional[int] = Field(default=None, ge=0)
    schedule_type: Optional[ScheduleType] = None
    schedule_cron: Optional[str] = None
    schedule_interval_hours: Optional[int] = Field(default=None, ge=1)
    enabled: Optional[bool] = None


class SyncConfigResponse(BaseModel):
    """Sync config response."""

    id: int
    user_id: int
    name: str
    sync_type: SyncType
    wiki_space_id: Optional[str]
    wiki_space_name: Optional[str]
    sync_mode: SyncMode
    limit: int
    schedule_type: ScheduleType
    schedule_cron: Optional[str]
    schedule_interval_hours: Optional[int]
    enabled: bool
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WikiSpaceResponse(BaseModel):
    """Wiki space info response."""

    space_id: str
    name: str
    description: Optional[str]


class TriggerSyncResponse(BaseModel):
    """Response for triggering a sync."""

    sync_run_id: int
    status: str
    message: str
    queue_position: Optional[int] = None


# ============== Routes ==============

@router.get("", response_model=List[SyncConfigResponse])
async def list_sync_configs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> List[SyncConfigResponse]:
    """List all sync configs for the current user."""
    configs = (
        db.query(SyncConfig)
        .filter(SyncConfig.user_id == user.id)
        .order_by(SyncConfig.created_at.desc())
        .all()
    )
    return [SyncConfigResponse.model_validate(c) for c in configs]


@router.post("", response_model=SyncConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_sync_config(
    request: Request,
    data: SyncConfigCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncConfigResponse:
    """Create a new sync config."""
    # Validate wiki config
    if data.sync_type == SyncType.WIKI:
        _ensure_wiki_allowed(request, user)
    if data.sync_type == SyncType.WIKI and not data.wiki_space_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="wiki_space_id is required for wiki sync type",
        )

    # Validate schedule config
    if data.schedule_type == ScheduleType.CRON and not data.schedule_cron:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="schedule_cron is required for cron schedule type",
        )
    if data.schedule_type == ScheduleType.INTERVAL and not data.schedule_interval_hours:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="schedule_interval_hours is required for interval schedule type",
        )

    # Create config
    config = SyncConfig(
        user_id=user.id,
        name=data.name,
        sync_type=data.sync_type,
        wiki_space_id=data.wiki_space_id,
        wiki_space_name=data.wiki_space_name,
        sync_mode=data.sync_mode,
        limit=data.limit,
        schedule_type=data.schedule_type,
        schedule_cron=data.schedule_cron,
        schedule_interval_hours=data.schedule_interval_hours,
        enabled=data.enabled,
    )
    db.add(config)
    db.commit()
    db.refresh(config)

    # Add to scheduler if enabled and not manual
    if config.enabled and config.schedule_type != ScheduleType.MANUAL:
        from ..scheduler import get_scheduler
        scheduler = get_scheduler()
        if scheduler:
            scheduler.add_job(config)

    return SyncConfigResponse.model_validate(config)


@router.get("/wiki-spaces", response_model=List[WikiSpaceResponse])
async def list_wiki_spaces(
    request: Request,
    user: User = Depends(require_valid_token),
) -> List[WikiSpaceResponse]:
    """List wiki spaces accessible to the current user."""
    _ensure_wiki_allowed(request, user)
    from ..sync_service import get_user_wiki_spaces

    spaces = get_user_wiki_spaces(user)
    return [
        WikiSpaceResponse(
            space_id=s["space_id"],
            name=s["name"],
            description=s.get("description"),
        )
        for s in spaces
    ]


@router.get("/{config_id}", response_model=SyncConfigResponse)
async def get_sync_config(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncConfigResponse:
    """Get a specific sync config."""
    config = (
        db.query(SyncConfig)
        .filter(SyncConfig.id == config_id, SyncConfig.user_id == user.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync config not found",
        )
    return SyncConfigResponse.model_validate(config)


@router.put("/{config_id}", response_model=SyncConfigResponse)
async def update_sync_config(
    config_id: int,
    data: SyncConfigUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncConfigResponse:
    """Update a sync config."""
    config = (
        db.query(SyncConfig)
        .filter(SyncConfig.id == config_id, SyncConfig.user_id == user.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync config not found",
        )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(config, key, value)

    db.commit()
    db.refresh(config)

    # Update scheduler
    from ..scheduler import get_scheduler
    scheduler = get_scheduler()
    if scheduler:
        if config.enabled and config.schedule_type != ScheduleType.MANUAL:
            scheduler.add_job(config)
        else:
            scheduler.remove_job(config.id)

    return SyncConfigResponse.model_validate(config)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sync_config(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Delete a sync config."""
    config = (
        db.query(SyncConfig)
        .filter(SyncConfig.id == config_id, SyncConfig.user_id == user.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync config not found",
        )

    # Remove from scheduler
    from ..scheduler import get_scheduler
    scheduler = get_scheduler()
    if scheduler:
        scheduler.remove_job(config.id)

    db.delete(config)
    db.commit()


@router.post("/{config_id}/run", response_model=TriggerSyncResponse)
async def trigger_sync(
    config_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TriggerSyncResponse:
    """Manually trigger a sync for this config."""
    config = (
        db.query(SyncConfig)
        .filter(SyncConfig.id == config_id, SyncConfig.user_id == user.id)
        .first()
    )
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync config not found",
        )

    # Check for running sync
    active = (
        db.query(SyncRun)
        .filter(
            SyncRun.config_id == config_id,
            SyncRun.status.in_(
                [
                    SyncRunStatus.QUEUED,
                    SyncRunStatus.PENDING,
                    SyncRunStatus.RUNNING,
                ]
            ),
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A sync is already queued or running for this config",
        )

    # Trigger via scheduler
    from ..scheduler import get_scheduler
    scheduler = get_scheduler()
    if not scheduler:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler is not available",
        )

    sync_run = await scheduler.trigger_sync(config_id)

    if not sync_run:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to trigger sync",
        )

    queue_position = None
    if sync_run.status == SyncRunStatus.QUEUED:
        queue_position = (
            db.query(SyncRun)
            .filter(
                SyncRun.status == SyncRunStatus.QUEUED,
                or_(
                    SyncRun.created_at < sync_run.created_at,
                    and_(
                        SyncRun.created_at == sync_run.created_at,
                        SyncRun.id <= sync_run.id,
                    ),
                ),
            )
            .count()
        )

    message = "Sync queued successfully" if sync_run.status == SyncRunStatus.QUEUED else "Sync triggered successfully"

    return TriggerSyncResponse(
        sync_run_id=sync_run.id,
        status=sync_run.status.value,
        message=message,
        queue_position=queue_position,
    )
