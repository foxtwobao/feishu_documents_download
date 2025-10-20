"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from pydantic import BaseModel, Field


class OAuthRedirectResponse(BaseModel):
    authorization_url: str
    state: str


class OAuthCallbackRequest(BaseModel):
    code: str
    state: str


class OAuthTokenResponse(BaseModel):
    success: bool
    message: Optional[str]
    user_id: Optional[int]
    display_name: Optional[str]
    avatar_url: Optional[str]


class TaskCreateRequest(BaseModel):
    task_type: str = Field(..., description="sync mode, e.g. docx, folder, space")
    payload: dict = Field(default_factory=dict)
    incremental: bool = True
    limit: Optional[int] = None
    schedule_at: Optional[datetime] = Field(
        default=None,
        description="Optional ISO timestamp to schedule execution time",
    )

class TaskPreviewRequest(BaseModel):
    task_type: str
    payload: dict = Field(default_factory=dict)
    incremental: bool = True
    limit: Optional[int] = None


class TaskPlanSample(BaseModel):
    name: Optional[str]
    file_type: Optional[str]
    action: str
    detail: Optional[str]


class TaskPlanSummary(BaseModel):
    total_files: int
    will_download: int
    existing: int
    skipped: int
    root: Optional[Dict[str, Optional[str]]] = None
    samples: list[TaskPlanSample] = Field(default_factory=list)


class TaskParameter(BaseModel):
    label: str
    value: str


class TaskResponse(BaseModel):
    id: int
    task_type: str
    status: str
    progress: int
    incremental: bool
    limit: Optional[int]
    created_at: datetime
    scheduled_for: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result_path: Optional[str]
    error_message: Optional[str]
    description: Optional[str] = None
    parameters: list[TaskParameter] = Field(default_factory=list)
    current_item: Optional[str] = None
    current_stage: Optional[str] = None
    current_detail: Optional[str] = None
    processed: Optional[int] = None
    expected: Optional[int] = None
    plan: Optional[TaskPlanSummary] = None
    artifact_count: int = 0
    download_ready: bool = False


class TaskLogResponse(BaseModel):
    created_at: datetime
    level: str
    message: str


class TaskArtifactResponse(BaseModel):
    path: str
    file_type: Optional[str]
    created_at: datetime


class TaskDetailResponse(TaskResponse):
    logs: list[TaskLogResponse]
    artifacts: list[TaskArtifactResponse] = Field(default_factory=list)


class TaskListResponse(BaseModel):
    tasks: list[TaskResponse]


class UserInfoResponse(BaseModel):
    id: int
    feishu_user_id: str
    display_name: Optional[str]
    avatar_url: Optional[str]


class TaskPreviewResponse(BaseModel):
    plan: TaskPlanSummary
