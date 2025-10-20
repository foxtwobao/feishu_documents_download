"""Task management endpoints."""

from __future__ import annotations

import io
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ..dependencies import db_session, get_current_user
from ..models import SyncTask, TaskArtifact, TaskLog, User
from ..schemas import (
    TaskArtifactResponse,
    TaskCreateRequest,
    TaskDetailResponse,
    TaskListResponse,
    TaskLogResponse,
    TaskParameter,
    TaskPlanSample,
    TaskPlanSummary,
    TaskPreviewRequest,
    TaskPreviewResponse,
    TaskResponse,
)
from ...core.api_client import FeishuAPIError

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/preview", response_model=TaskPreviewResponse)
def preview_task(
    payload: TaskPreviewRequest,
    request: Request,
    user: User = Depends(get_current_user),
) -> TaskPreviewResponse:
    task_manager = request.app.state.task_manager
    try:
        plan_dict = task_manager.preview_task_plan(
            user_id=user.id,
            task_type=payload.task_type,
            payload=dict(payload.payload or {}),
            incremental=payload.incremental,
            limit=payload.limit,
        )
    except FeishuAPIError as exc:
        if exc.status_code == 401:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_required") from exc
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    plan = TaskPlanSummary.model_validate(plan_dict)
    return TaskPreviewResponse(plan=plan)


@router.post("/", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
def create_task(
    payload: TaskCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> TaskResponse:
    schedule_at = payload.schedule_at
    raw_payload = dict(payload.payload or {})
    plan_snapshot = raw_payload.get("_plan_summary")
    if plan_snapshot is None:
        try:
            plan_snapshot = request.app.state.task_manager.preview_task_plan(
                user_id=user.id,
                task_type=payload.task_type,
                payload=raw_payload,
                incremental=payload.incremental,
                limit=payload.limit,
            )
        except FeishuAPIError as exc:
            if exc.status_code == 401:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_required") from exc
            logger.warning("Failed to compute plan snapshot: %s", exc)
            plan_snapshot = None
        except Exception:
            plan_snapshot = None
    if plan_snapshot is not None:
        raw_payload["_plan_summary"] = plan_snapshot
    description = raw_payload.get("_description")
    if description is None:
        description = _build_task_description(payload.task_type, raw_payload, incremental=payload.incremental, limit=payload.limit)
        raw_payload["_description"] = description

    task = SyncTask(
        user_id=user.id,
        task_type=payload.task_type,
        payload=json.dumps(raw_payload, ensure_ascii=False),
        incremental=payload.incremental,
        limit=payload.limit,
        status="pending",
        scheduled_for=payload.schedule_at,
    )
    session.add(task)
    session.flush()

    task_manager = request.app.state.task_manager
    task_manager.enqueue_sync(task.id, schedule_at=schedule_at)

    session.refresh(task)
    runtime = task_manager.runtime_snapshot(task.id)
    return _serialize_task(task, runtime)


@router.get("/", response_model=TaskListResponse)
def list_tasks(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> TaskListResponse:
    tasks = (
        session.query(SyncTask)
        .filter_by(user_id=user.id)
        .order_by(SyncTask.created_at.desc())
        .all()
    )
    manager = request.app.state.task_manager
    return TaskListResponse(tasks=[_serialize_task(task, manager.runtime_snapshot(task.id)) for task in tasks])


@router.get("/{task_id}", response_model=TaskDetailResponse)
def get_task(
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> TaskDetailResponse:
    task = _get_task_for_user(session, user, task_id)
    logs = [_serialize_log(entry) for entry in sorted(task.logs, key=lambda item: item.created_at)]
    runtime = request.app.state.task_manager.runtime_snapshot(task.id)
    artifacts = _serialize_artifacts(task.artifacts)
    base = _serialize_task(task, runtime)
    return TaskDetailResponse(**base.model_dump(), logs=logs, artifacts=artifacts)


@router.get("/{task_id}/logs", response_model=List[TaskLogResponse])
def get_task_logs(
    task_id: int,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> list[TaskLogResponse]:
    task = _get_task_for_user(session, user, task_id)
    return [_serialize_log(entry) for entry in sorted(task.logs, key=lambda item: item.created_at)]


@router.get("/{task_id}/download")
def download_task(
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> StreamingResponse:
    task = _get_task_for_user(session, user, task_id)
    if not task.artifacts:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务暂无可下载文件")
    task_manager = request.app.state.task_manager
    storage_root = task_manager.get_storage_root_for_user(user)
    buffer = io.BytesIO()
    seen: set[str] = set()
    added = 0
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for artifact in task.artifacts:
            for absolute, arcname in _iter_artifact_files(storage_root, artifact):
                if arcname in seen:
                    continue
                archive.write(absolute, arcname)
                seen.add(arcname)
                added += 1
    if added == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未找到可下载的文件")
    buffer.seek(0)
    filename = f"task-{task.id}.zip"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


@router.get("/{task_id}/stream")
async def stream_task(
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
):
    task = _get_task_for_user(session, user, task_id)
    task_manager = request.app.state.task_manager

    async def event_stream():
        async for event in task_manager.listen(task.id):
            payload = json.dumps(event.get("data"), ensure_ascii=False)
            event_name = event.get("type") or "message"
            yield f"event: {event_name}\ndata: {payload}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/{task_id}/retry", response_model=TaskResponse)
def retry_task(
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> TaskResponse:
    task = _get_task_for_user(session, user, task_id)
    if task.status == "running":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="任务正在执行")

    task.status = "pending"
    task.progress = 0
    task.error_message = None
    task.started_at = None
    task.completed_at = None
    task.scheduled_for = None
    session.add(task)
    session.flush()

    task_manager = request.app.state.task_manager
    task_manager.clear_runtime(task.id)
    task_manager.enqueue_sync(task.id)
    session.refresh(task)
    runtime = task_manager.runtime_snapshot(task.id)
    return _serialize_task(task, runtime)


@router.post("/{task_id}/cancel", response_model=TaskResponse)
def cancel_task(
    task_id: int,
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(db_session),
) -> TaskResponse:
    task = _get_task_for_user(session, user, task_id)
    if task.status not in {"pending", "queued", "scheduled"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="无法取消当前状态的任务")
    task.status = "cancelled"
    task.completed_at = datetime.now(timezone.utc)
    task.scheduled_for = None
    session.add(task)
    session.flush()
    task_manager = request.app.state.task_manager
    task_manager.clear_runtime(task.id)
    task_manager.publish_status(task.id)
    runtime = task_manager.runtime_snapshot(task.id)
    return _serialize_task(task, runtime)


def _get_task_for_user(session: Session, user: User, task_id: int) -> SyncTask:
    task = session.query(SyncTask).filter_by(id=task_id, user_id=user.id).one_or_none()
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")
    session.refresh(task)
    return task


def _ensure_timezone(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _serialize_task(task: SyncTask, runtime: Optional[Dict[str, object]] = None) -> TaskResponse:
    runtime = runtime or {}
    payload_data = _parse_payload(task)
    description = payload_data.get("_description") or _build_task_description(
        task.task_type, payload_data, incremental=task.incremental, limit=task.limit
    )
    parameters = _build_task_parameters(task, payload_data)
    plan = _extract_plan_summary(payload_data)
    if plan is None:
        plan = _plan_summary_from_artifacts(task.artifacts)
    artifact_count = len(task.artifacts)
    download_ready = artifact_count > 0 and task.completed_at is not None
    return TaskResponse(
        id=task.id,
        task_type=task.task_type,
        status=task.status,
        progress=task.progress,
        incremental=task.incremental,
        limit=task.limit,
        created_at=_ensure_timezone(task.created_at),
        scheduled_for=_ensure_timezone(task.scheduled_for),
        started_at=_ensure_timezone(task.started_at),
        completed_at=_ensure_timezone(task.completed_at),
        result_path=task.result_path,
        error_message=task.error_message,
        description=description,
        parameters=parameters,
        current_item=runtime.get("current_item"),
        current_stage=runtime.get("current_stage"),
        current_detail=runtime.get("current_detail"),
        processed=runtime.get("processed"),
        expected=runtime.get("expected"),
        plan=plan,
        artifact_count=artifact_count,
        download_ready=download_ready,
    )


def _serialize_log(entry: TaskLog) -> TaskLogResponse:
    return TaskLogResponse(
        created_at=_ensure_timezone(entry.created_at),
        level=entry.level,
        message=entry.message,
    )


def _serialize_artifacts(artifacts: Sequence[TaskArtifact]) -> List[TaskArtifactResponse]:
    return [
        TaskArtifactResponse(
            path=artifact.path,
            file_type=artifact.file_type,
            created_at=_ensure_timezone(artifact.created_at),
        )
        for artifact in sorted(artifacts, key=lambda item: item.created_at)
    ]


def _parse_payload(task: SyncTask) -> Dict[str, object]:
    if not task.payload:
        return {}
    try:
        data = json.loads(task.payload)
    except json.JSONDecodeError:
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _build_task_description(
    task_type: str,
    payload: Dict[str, object],
    *,
    incremental: bool,
    limit: Optional[int],
) -> str:
    mode = (task_type or "").lower()
    increment_label = "增量" if incremental else "全量"
    limit_note = f"，最多处理 {limit} 项" if limit else ""
    if mode in {"space", "drive_space", "full"}:
        return f"{increment_label}同步个人空间{limit_note}"
    target_name = str(payload.get("name") or payload.get("token") or "未命名")
    parent_path = str(payload.get("parent_path") or ".")
    return f"{increment_label}下载 {mode.upper()}「{target_name}」到 {parent_path}{limit_note}"


def _build_task_parameters(task: SyncTask, payload: Dict[str, object]) -> List[TaskParameter]:
    params: List[TaskParameter] = []
    if "name" in payload and payload.get("name"):
        params.append(TaskParameter(label="名称", value=str(payload["name"])))
    if "token" in payload and payload.get("token"):
        params.append(TaskParameter(label="Token", value=str(payload["token"])))
    parent = payload.get("parent_path") or "."
    params.append(TaskParameter(label="输出目录", value=str(parent)))
    params.append(TaskParameter(label="增量", value="是" if task.incremental else "否"))
    if task.limit:
        params.append(TaskParameter(label="最大处理数量", value=str(task.limit)))
    schedule = payload.get("schedule_at")
    if schedule:
        params.append(TaskParameter(label="计划执行时间", value=str(schedule)))
    extra = payload.get("extra")
    if isinstance(extra, dict):
        for key, value in extra.items():
            params.append(TaskParameter(label=f"扩展参数：{key}", value=_stringify_value(value)))
    return params


def _stringify_value(value: object) -> str:
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _extract_plan_summary(payload: Dict[str, object]) -> Optional[TaskPlanSummary]:
    plan = payload.get("_plan_summary")
    if isinstance(plan, dict):
        try:
            return TaskPlanSummary.model_validate(plan)
        except Exception:
            return None
    return None


def _plan_summary_from_artifacts(artifacts: Sequence[TaskArtifact]) -> Optional[TaskPlanSummary]:
    if not artifacts:
        return None
    samples = [
        TaskPlanSample(
            name=Path(artifact.path).name,
            file_type=artifact.file_type,
            action="download",
            detail=artifact.path,
        )
        for artifact in list(sorted(artifacts, key=lambda item: item.created_at))[:10]
    ]
    total = len(artifacts)
    return TaskPlanSummary(
        total_files=total,
        will_download=total,
        existing=0,
        skipped=0,
        root=None,
        samples=samples,
    )


def _validate_within_root(root: Path, target: Path) -> None:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if target_resolved == root_resolved:
        return
    if root_resolved not in target_resolved.parents:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="文件路径越界，拒绝访问")


def _iter_artifact_files(storage_root: Path, artifact: TaskArtifact) -> Iterable[Tuple[Path, str]]:
    path_obj = Path(artifact.path)
    if path_obj.is_absolute():
        absolute = path_obj.resolve()
        _validate_within_root(storage_root, absolute)
        try:
            relative = absolute.relative_to(storage_root.resolve())
        except ValueError:
            relative = absolute.name
    else:
        relative = path_obj
        absolute = (storage_root / relative).resolve()
        _validate_within_root(storage_root, absolute)
    if not absolute.exists():
        return []
    if absolute.is_dir():
        for item in absolute.rglob("*"):
            if not item.is_file():
                continue
            _validate_within_root(storage_root, item)
            yield item, item.relative_to(storage_root).as_posix()
        return []
    yield absolute, relative.as_posix()
    if artifact.file_type and artifact.file_type.lower() in {"doc", "docx", "wiki", "slides", "mindnote", "shortcut"}:
        asset_dir = absolute.with_suffix("")
        if asset_dir.exists() and asset_dir.is_dir():
            _validate_within_root(storage_root, asset_dir)
            for item in asset_dir.rglob("*"):
                if not item.is_file():
                    continue
                _validate_within_root(storage_root, item)
                yield item, item.relative_to(storage_root).as_posix()
