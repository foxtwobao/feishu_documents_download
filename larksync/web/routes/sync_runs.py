"""Sync execution record routes with SSE support."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ..database import get_db
from ..deps import get_current_user
from ..models import FileStatus, SyncConfig, SyncFileRecord, SyncRun, SyncRunStatus, User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sync-runs", tags=["sync-runs"])


# ============== Response Models ==============

class SyncRunResponse(BaseModel):
    """Sync run response."""

    id: int
    config_id: int
    config_name: Optional[str] = None
    user_id: int
    status: SyncRunStatus
    total_files: int
    total_folders: int
    downloaded: int
    skipped: int
    errors: int
    current_file: Optional[str]
    current_stage: Optional[str]
    error_message: Optional[str]
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    created_at: datetime
    duration_seconds: Optional[float]
    progress_percent: float
    queue_position: Optional[int] = None

    class Config:
        from_attributes = True


class SyncRunListResponse(BaseModel):
    """Paginated list of sync runs."""

    items: List[SyncRunResponse]
    total: int
    page: int
    page_size: int


def _get_queue_position(db: Session, run: SyncRun) -> Optional[int]:
    if run.status != SyncRunStatus.QUEUED:
        return None
    return (
        db.query(SyncRun)
        .filter(
            SyncRun.status == SyncRunStatus.QUEUED,
            or_(
                SyncRun.created_at < run.created_at,
                and_(SyncRun.created_at == run.created_at, SyncRun.id <= run.id),
            ),
        )
        .count()
    )


class SyncFileRecordResponse(BaseModel):
    """Sync file record response."""

    id: int
    run_id: int
    file_name: str
    file_path: Optional[str]
    file_type: Optional[str]
    token: Optional[str]
    status: FileStatus
    reason: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class SyncFileRecordListResponse(BaseModel):
    """List of sync file records."""

    items: List[SyncFileRecordResponse]
    total: int


# ============== Routes ==============

@router.get("", response_model=SyncRunListResponse)
async def list_sync_runs(
    config_id: Optional[int] = None,
    status_filter: Optional[SyncRunStatus] = None,
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncRunListResponse:
    """
    List sync runs for the current user.
    
    Supports filtering by config_id and status.
    """
    query = db.query(SyncRun).filter(SyncRun.user_id == user.id)

    if config_id:
        query = query.filter(SyncRun.config_id == config_id)
    if status_filter:
        query = query.filter(SyncRun.status == status_filter)

    total = query.count()
    
    runs = (
        query
        .order_by(SyncRun.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    queued_positions = {}
    queued_ids = {run.id for run in runs if run.status == SyncRunStatus.QUEUED}
    if queued_ids:
        ordered = (
            db.query(SyncRun.id)
            .filter(SyncRun.status == SyncRunStatus.QUEUED)
            .order_by(SyncRun.created_at, SyncRun.id)
            .all()
        )
        for index, row in enumerate(ordered, start=1):
            if row.id in queued_ids:
                queued_positions[row.id] = index

    # Get config names
    config_ids = {r.config_id for r in runs}
    configs = db.query(SyncConfig).filter(SyncConfig.id.in_(config_ids)).all()
    config_names = {c.id: c.name for c in configs}

    items = []
    for run in runs:
        response = SyncRunResponse(
            id=run.id,
            config_id=run.config_id,
            config_name=config_names.get(run.config_id),
            user_id=run.user_id,
            status=run.status,
            total_files=run.total_files,
            total_folders=run.total_folders,
            downloaded=run.downloaded,
            skipped=run.skipped,
            errors=run.errors,
            current_file=run.current_file,
            current_stage=run.current_stage,
            error_message=run.error_message,
            started_at=run.started_at,
            finished_at=run.finished_at,
            created_at=run.created_at,
            duration_seconds=run.duration_seconds,
            progress_percent=run.progress_percent,
            queue_position=queued_positions.get(run.id),
        )
        items.append(response)

    return SyncRunListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{run_id}", response_model=SyncRunResponse)
async def get_sync_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncRunResponse:
    """Get a specific sync run."""
    run = (
        db.query(SyncRun)
        .filter(SyncRun.id == run_id, SyncRun.user_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync run not found",
        )

    # Get config name
    config = db.query(SyncConfig).filter(SyncConfig.id == run.config_id).first()
    config_name = config.name if config else None

    return SyncRunResponse(
        id=run.id,
        config_id=run.config_id,
        config_name=config_name,
        user_id=run.user_id,
        status=run.status,
        total_files=run.total_files,
        total_folders=run.total_folders,
        downloaded=run.downloaded,
        skipped=run.skipped,
        errors=run.errors,
        current_file=run.current_file,
        current_stage=run.current_stage,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        duration_seconds=run.duration_seconds,
        progress_percent=run.progress_percent,
        queue_position=_get_queue_position(db, run),
    )


@router.get("/{run_id}/files", response_model=SyncFileRecordListResponse)
async def get_sync_run_files(
    run_id: int,
    status_filter: Optional[FileStatus] = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncFileRecordListResponse:
    """
    Get file records for a specific sync run.
    
    Optionally filter by file status (downloaded, skipped, failed).
    """
    # Verify access
    run = (
        db.query(SyncRun)
        .filter(SyncRun.id == run_id, SyncRun.user_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync run not found",
        )

    # Query file records
    query = db.query(SyncFileRecord).filter(SyncFileRecord.run_id == run_id)
    
    if status_filter:
        query = query.filter(SyncFileRecord.status == status_filter)
    
    # Order by created_at desc
    query = query.order_by(SyncFileRecord.created_at.desc())
    
    records = query.all()
    total = len(records)

    items = [
        SyncFileRecordResponse(
            id=record.id,
            run_id=record.run_id,
            file_name=record.file_name,
            file_path=record.file_path,
            file_type=record.file_type,
            token=record.token,
            status=record.status,
            reason=record.reason,
            created_at=record.created_at,
        )
        for record in records
    ]

    return SyncFileRecordListResponse(items=items, total=total)


@router.get("/{run_id}/stream")
async def stream_sync_progress(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Stream sync progress using Server-Sent Events (SSE).
    
    Events:
    - status: Current run status and progress
    - log: Log messages (if available)
    - complete: Sent when sync finishes
    - error: Error information
    """
    # Verify access
    run = (
        db.query(SyncRun)
        .filter(SyncRun.id == run_id, SyncRun.user_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync run not found",
        )

    async def event_generator():
        """Generate SSE events for sync progress."""
        from ..database import get_session_factory

        session_factory = get_session_factory()
        last_status = None
        last_progress = -1

        try:
            while True:
                # Create a new session for each poll
                session = session_factory()
                try:
                    current_run = session.query(SyncRun).filter(SyncRun.id == run_id).first()
                    
                    if not current_run:
                        yield _format_sse("error", {"message": "Sync run not found"})
                        break

                    # Build status data
                    status_data = {
                        "id": current_run.id,
                        "status": current_run.status.value,
                        "total_files": current_run.total_files,
                        "total_folders": current_run.total_folders,
                        "downloaded": current_run.downloaded,
                        "skipped": current_run.skipped,
                        "errors": current_run.errors,
                        "current_file": current_run.current_file,
                        "current_stage": current_run.current_stage,
                        "progress_percent": current_run.progress_percent,
                        "queue_position": _get_queue_position(session, current_run),
                    }

                    # Only send if changed
                    current_progress = (
                        current_run.status.value,
                        current_run.downloaded,
                        current_run.skipped,
                        current_run.errors,
                        current_run.current_file,
                    )

                    if current_progress != last_progress or current_run.status.value != last_status:
                        yield _format_sse("status", status_data)
                        last_status = current_run.status.value
                        last_progress = current_progress

                    # Check if completed
                    if current_run.status in (
                        SyncRunStatus.COMPLETED,
                        SyncRunStatus.FAILED,
                        SyncRunStatus.AUTH_REQUIRED,
                        SyncRunStatus.CANCELLED,
                    ):
                        complete_data = {
                            "status": current_run.status.value,
                            "total_files": current_run.total_files,
                            "downloaded": current_run.downloaded,
                            "skipped": current_run.skipped,
                            "errors": current_run.errors,
                            "error_message": current_run.error_message,
                            "duration_seconds": current_run.duration_seconds,
                        }
                        yield _format_sse("complete", complete_data)
                        break

                finally:
                    session.close()

                # Poll interval
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            logger.debug(f"SSE stream cancelled for run {run_id}")
        except Exception as e:
            logger.error(f"SSE stream error for run {run_id}: {e}")
            yield _format_sse("error", {"message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


@router.post("/{run_id}/cancel", response_model=SyncRunResponse)
async def cancel_sync_run(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SyncRunResponse:
    """
    Cancel a running sync.
    
    Note: This only marks the run as cancelled. The actual sync process
    may continue until it checks the cancellation flag.
    """
    run = (
        db.query(SyncRun)
        .filter(SyncRun.id == run_id, SyncRun.user_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Sync run not found",
        )

    if run.status not in (SyncRunStatus.QUEUED, SyncRunStatus.PENDING, SyncRunStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel sync in status: {run.status.value}",
        )

    run.status = SyncRunStatus.CANCELLED
    run.finished_at = datetime.now()
    db.commit()
    db.refresh(run)

    # Get config name
    config = db.query(SyncConfig).filter(SyncConfig.id == run.config_id).first()
    config_name = config.name if config else None

    return SyncRunResponse(
        id=run.id,
        config_id=run.config_id,
        config_name=config_name,
        user_id=run.user_id,
        status=run.status,
        total_files=run.total_files,
        total_folders=run.total_folders,
        downloaded=run.downloaded,
        skipped=run.skipped,
        errors=run.errors,
        current_file=run.current_file,
        current_stage=run.current_stage,
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
        created_at=run.created_at,
        duration_seconds=run.duration_seconds,
        progress_percent=run.progress_percent,
    )


def _format_sse(event: str, data: dict) -> str:
    """Format data as an SSE message."""
    json_data = json.dumps(data, ensure_ascii=False, default=str)
    return f"event: {event}\ndata: {json_data}\n\n"
