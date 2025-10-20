"""Background task helpers for token refresh and sync execution."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional, Set

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

from ..config import LarkSyncConfig
from ..core.api_client import FeishuAPIError
from ..core.models import SyncTask as CoreSyncTask
from ..core.sync_engine import SyncEngine
from ..core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from ..storage import MetadataStore
from ..utils.filesystem import sanitize_filename
from .auth import FeishuOAuthClient, compute_expiry
from .database import session_scope
from .models import SyncTask, TaskArtifact, TaskLog, User

logger = logging.getLogger(__name__)


class TaskManager:
    """Coordinate background execution of sync jobs triggered via the Web UI."""

    def __init__(self, config: LarkSyncConfig, oauth_client: FeishuOAuthClient | None = None) -> None:
        self._config = config
        self._scheduler = BackgroundScheduler()
        self._oauth_client = oauth_client
        self._listeners: Dict[int, Set[asyncio.Queue[Dict[str, Any]]]] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._runtime_state: Dict[int, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ scheduler lifecycle

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            if self._oauth_client and self._oauth_client.enabled:
                interval = max(self._config.web.scheduler_interval_seconds, 60)
                self._scheduler.add_job(
                    self._refresh_tokens_job,
                    trigger="interval",
                    seconds=interval,
                    id="token-refresh",
                    replace_existing=True,
                )

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown()

    # ------------------------------------------------------------------ public API

    def enqueue_sync(self, task_id: int, schedule_at: datetime | None = None) -> None:
        run_date = self._normalize_schedule(schedule_at)
        now = datetime.now(timezone.utc)
        immediate = schedule_at is None or run_date <= now
        trigger_time = now + timedelta(milliseconds=100) if immediate else run_date
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task is None:
                return
            task.status = "queued" if immediate else "scheduled"
            task.progress = 0
            task.error_message = None
            task.scheduled_for = None if immediate else run_date
            session.add(task)

        trigger = DateTrigger(run_date=trigger_time)
        self._scheduler.add_job(
            self._run_sync_job,
            trigger=trigger,
            args=(task_id,),
            id=f"sync-{task_id}",
            replace_existing=True,
        )
        self._notify_task_status(task_id)

    async def listen(self, task_id: int) -> AsyncGenerator[Dict[str, Any], None]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self._loop = loop
        listeners = self._listeners.setdefault(task_id, set())
        listeners.add(queue)
        try:
            snapshot = self._snapshot(task_id)
            if snapshot:
                await queue.put({"type": "status", "data": snapshot})
            for record in self._fetch_logs(task_id):
                await queue.put({"type": "log", "data": record})
            while True:
                payload = await queue.get()
                yield payload
        finally:
            listeners = self._listeners.get(task_id)
            if listeners and queue in listeners:
                listeners.remove(queue)
                if not listeners:
                    self._listeners.pop(task_id, None)

    def publish_status(self, task_id: int) -> None:
        self._notify_task_status(task_id)

    def get_storage_root_for_user(self, user: User) -> Path:
        config, engine, metadata_store = self._build_engine_for_user(user)
        try:
            return engine.storage.root
        finally:
            engine.close()
    def preview_task_plan(
        self,
        *,
        user_id: int,
        task_type: str,
        payload: Dict[str, Any],
        incremental: bool,
        limit: Optional[int],
    ) -> Dict[str, Any]:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user is None:
                raise RuntimeError("用户不存在")

        mode = (task_type or "").lower()
        config, engine, metadata_store = self._build_engine_for_user(user)
        try:
            if mode in {"space", "drive_space", "full"}:
                synchronizer = DriveSpaceSynchronizer(
                    SpaceSyncContext(
                        engine=engine,
                        drive=engine.drive_adapter,
                        registry=engine.registry,
                        storage=engine.storage,
                    ),
                    metadata_store,
                    limit=limit,
                    incremental=incremental,
                    force_on_missing=config.sync.force_download_missing,
                    clean_deleted=config.sync.clean_deleted,
                    plan_only=True,
                )
                try:
                    synchronizer.sync()
                except FeishuAPIError as exc:
                    if exc.status_code == 401:
                        self._expire_user_credentials(user.id)
                    raise
                summary = synchronizer.summary()
                return dict(summary)

            token = payload.get("token")
            name = payload.get("name") or token or task_type
            parent_path = Path(payload.get("parent_path") or ".")
            expected_path = self._expected_single_output_path(mode, str(name), parent_path)
            resolved = self._finalize_single_output(engine.storage.root, expected_path, mode, str(name))
            detail = resolved.as_posix() if resolved else expected_path.as_posix()
            return {
                "mode": mode,
                "total_files": 1,
                "will_download": 1,
                "existing": 0,
                "skipped": 0,
                "limit": limit,
                "incremental": incremental,
                "root": {"token": token, "name": name},
                "samples": [
                    {
                        "name": name,
                        "file_type": mode,
                        "detail": detail,
                        "action": "download",
                    }
                ],
            }
        except FeishuAPIError as exc:
            if exc.status_code == 401:
                self._expire_user_credentials(user.id)
            raise
        finally:
            engine.close()

    # ------------------------------------------------------------------ internal helpers

    def _normalize_schedule(self, schedule_at: datetime | None) -> datetime:
        if schedule_at is None:
            return datetime.now(timezone.utc)
        if schedule_at.tzinfo is not None:
            schedule_at = schedule_at.astimezone(timezone.utc)
        else:
            schedule_at = schedule_at.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return schedule_at if schedule_at > now else now

    def _refresh_tokens_job(self) -> None:
        if not self._oauth_client or not self._oauth_client.enabled:
            return
        margin = timedelta(minutes=self._config.web.oauth.token_refresh_margin_minutes)
        now = datetime.now(timezone.utc)
        with session_scope() as session:
            users = (
                session.query(User)
                .filter(User.token_expires_at.isnot(None))
                .filter(User.token_expires_at < now + margin)
                .all()
            )
            for user in users:
                if not user.refresh_token:
                    continue
                try:
                    logger.info("Refreshing token for user %s", user.feishu_user_id)
                    access_token, refresh_token, expires_in = asyncio.run(
                        self._oauth_client.refresh_token(user.refresh_token)
                    )
                except Exception as exc:  # pragma: no cover - network failure path
                    logger.warning("Failed to refresh token for user %s: %s", user.feishu_user_id, exc)
                    continue

                user.access_token = access_token
                user.refresh_token = refresh_token
                user.token_expires_at = compute_expiry(expires_in)
                session.add(user)

    def _run_sync_job(self, task_id: int) -> None:
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task is None:
                return
            if task.status == "cancelled":
                return
            session.query(TaskArtifact).filter(TaskArtifact.task_id == task_id).delete(synchronize_session=False)
            task.status = "running"
            task.started_at = datetime.now(timezone.utc)
            task.scheduled_for = None
            task.result_path = None
            session.add(task)
        self._notify_task_status(task_id)
        self._append_log(task_id, "INFO", "任务开始执行")

        try:
            self._execute_sync(task_id)
        except FeishuAPIError as exc:
            logger.error("Feishu API error for task %s: %s", task_id, exc)
            self._handle_feishu_error(task_id, exc)
        except Exception as exc:  # pragma: no cover - runtime failure path
            logger.exception("Sync task %s failed", task_id)
            self._append_log(task_id, "ERROR", f"任务失败：{exc}")
            with session_scope() as session:
                task = session.get(SyncTask, task_id)
                if task:
                    task.status = "failed"
                    task.error_message = str(exc)
                    task.completed_at = datetime.now(timezone.utc)
                    task.progress = min(task.progress or 0, 99)
                    task.result_path = None
                    task.scheduled_for = None
                    session.add(task)
            self._runtime_state.pop(task_id, None)
            self._notify_task_status(task_id)
        else:
            self._append_log(task_id, "INFO", "任务成功完成")
            with session_scope() as session:
                task = session.get(SyncTask, task_id)
                if task:
                    task.status = "completed"
                    task.progress = 100
                    task.completed_at = datetime.now(timezone.utc)
                    task.scheduled_for = None
                    session.add(task)
            self._runtime_state.pop(task_id, None)
            self._notify_task_status(task_id)

    def _execute_sync(self, task_id: int) -> None:
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task is None:
                return
            user = session.get(User, task.user_id)
            payload: Dict[str, Any] = {}
            if task.payload:
                try:
                    payload = json.loads(task.payload)
                except json.JSONDecodeError:
                    logger.warning("Invalid payload for task %s; fallback to empty payload", task_id)
            plan_total = _extract_planned_total(payload)
            if plan_total:
                runtime = self._runtime_state.setdefault(task_id, {})
                runtime["planned_total"] = plan_total
        if user is None:
            raise RuntimeError("User not found for task")

        config, engine, metadata_store = self._build_engine_for_user(user)
        try:
            mode = (task.task_type or "").lower()
            if mode in {"space", "drive_space", "full"}:
                self._run_space_sync(task, engine, metadata_store, config)
            else:
                self._run_single_resource(task, engine, payload)
        finally:
            engine.close()

    def _handle_feishu_error(self, task_id: int, exc: FeishuAPIError) -> None:
        user_id: Optional[int] = None
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task:
                user_id = task.user_id

        if exc.status_code == 401 and user_id is not None:
            self._append_log(task_id, "ERROR", "授权已过期，请重新登录授权后重试")
            self._expire_user_credentials(user_id)
            with session_scope() as session:
                task = session.get(SyncTask, task_id)
                if task:
                    task.status = "auth_required"
                    task.error_message = "授权已过期，请重新登录"
                    task.completed_at = datetime.now(timezone.utc)
                    task.progress = min(task.progress or 0, 99)
                    task.result_path = None
                    session.add(task)
            self._runtime_state.pop(task_id, None)
            self._notify_task_status(task_id)
            return

        self._append_log(task_id, "ERROR", f"任务失败：{exc.message}")
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task:
                task.status = "failed"
                task.error_message = exc.message
                task.completed_at = datetime.now(timezone.utc)
                task.progress = min(task.progress or 0, 99)
                task.result_path = None
                session.add(task)
        self._runtime_state.pop(task_id, None)
        self._notify_task_status(task_id)

    def _expire_user_credentials(self, user_id: int) -> None:
        with session_scope() as session:
            user = session.get(User, user_id)
            if user:
                user.access_token = None
                user.refresh_token = None
                user.token_expires_at = None
                session.add(user)

    def _run_space_sync(self, task: SyncTask, engine: SyncEngine, metadata_store: MetadataStore, config: LarkSyncConfig) -> None:
        def progress_callback(processed: int, expected: int, name: Optional[str], stage: str, file_type: Optional[str], detail: Optional[str]) -> None:
            self._handle_progress(task.id, processed, expected, name, stage, file_type, detail)

        synchronizer = DriveSpaceSynchronizer(
            SpaceSyncContext(
                engine=engine,
                drive=engine.drive_adapter,
                registry=engine.registry,
                storage=engine.storage,
            ),
            metadata_store,
            limit=task.limit,
            incremental=task.incremental,
            force_on_missing=config.sync.force_download_missing,
            clean_deleted=config.sync.clean_deleted,
            progress_callback=progress_callback,
        )
        synchronizer.sync()

    def _run_single_resource(self, task: SyncTask, engine: SyncEngine, payload: Dict[str, Any]) -> None:
        token = payload.get("token")
        if not token:
            raise ValueError("任务缺少 token 参数")
        file_type = (payload.get("file_type") or task.task_type or "docx").lower()
        name = payload.get("name") or token
        parent_path_value = payload.get("parent_path") or "."
        parent_path = Path(parent_path_value)
        extra = payload.get("extra") if isinstance(payload.get("extra"), dict) else {}

        expected_relative = self._expected_single_output_path(file_type, str(name), parent_path)
        core_task = CoreSyncTask(
            token=str(token),
            file_type=str(file_type),
            name=str(name),
            parent_path=parent_path,
            extra=extra,
        )
        engine.process_task(core_task)
        resolved = self._finalize_single_output(engine.storage.root, expected_relative, file_type, str(name))
        detail = resolved.as_posix() if resolved else (expected_relative.as_posix() if expected_relative else None)
        self._handle_progress(task.id, 1, 1, str(name), "success", file_type, detail)

    def _append_log(self, task_id: int, level: str, message: str) -> None:
        with session_scope() as session:
            entry = TaskLog(task_id=task_id, level=level, message=message)
            session.add(entry)
            session.flush()
            payload = self._serialize_log_entry(entry)
        self._notify_listeners(task_id, {"type": "log", "data": payload})

    def _record_artifact(self, task_id: int, file_type: Optional[str], path: Optional[str]) -> None:
        if not path:
            return
        with session_scope() as session:
            existing = (
                session.query(TaskArtifact)
                .filter(TaskArtifact.task_id == task_id)
                .filter(TaskArtifact.path == path)
                .one_or_none()
            )
            if existing:
                if file_type and existing.file_type != file_type:
                    existing.file_type = file_type
                    session.add(existing)
                return
            entry = TaskArtifact(task_id=task_id, path=path, file_type=file_type)
            session.add(entry)

    def _build_engine_for_user(self, user: User) -> tuple[LarkSyncConfig, SyncEngine, MetadataStore]:
        from ..bootstrap import build_runtime

        config, client, storage, registry = build_runtime(Path("config.toml"))
        if user.access_token:
            auth = config.auth.model_copy(update={"user_access_token": user.access_token})
            config = config.model_copy(update={"auth": auth})
            client._auth = auth  # type: ignore[attr-defined]

        engine = SyncEngine(config=config, client=client, registry=registry, storage=storage)
        metadata_store = MetadataStore(storage.root)
        return config, engine, metadata_store

    # ------------------------------------------------------------------ serialization helpers

    def _handle_progress(
        self,
        task_id: int,
        processed: int,
        expected: int,
        name: Optional[str],
        stage: str,
        file_type: Optional[str],
        detail: Optional[str],
    ) -> None:
        if expected <= 0:
            expected = max(processed, 1)
        runtime = self._runtime_state.setdefault(task_id, {})
        planned_total = runtime.get("planned_total")
        expected_for_progress = planned_total or expected
        if not expected_for_progress or expected_for_progress <= 0:
            expected_for_progress = max(expected, processed, 1)
        else:
            expected_for_progress = max(expected_for_progress, processed, expected or 0)
        progress_pct = min(int((processed / expected_for_progress) * 100), 100)

        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task is None:
                return
            if progress_pct > task.progress:
                task.progress = progress_pct
                session.add(task)
            runtime["processed"] = processed
            runtime["expected"] = expected_for_progress
            runtime["current_stage"] = stage
            if name:
                runtime["current_item"] = name
            if detail:
                runtime["current_detail"] = detail
                if stage == "success" and not task.result_path:
                    task.result_path = detail
                    session.add(task)
            elif "current_detail" in runtime and stage in {"success", "start"}:
                runtime.pop("current_detail", None)

        self._notify_task_status(task_id)

        if not name:
            return
        label = f"{name}"
        suffix = f"（{file_type}）" if file_type else ""
        detail_note = f" -> {detail}" if detail else ""
        if stage == "success":
            self._record_artifact(task_id, file_type, detail)
            self._append_log(task_id, "INFO", f"完成 {label}{suffix}{detail_note}")
        elif stage == "failed":
            desc = detail or "执行失败"
            self._append_log(task_id, "ERROR", f"处理 {label}{suffix} 失败：{desc}")
        elif stage == "skip":
            desc = detail or "已跳过"
            self._append_log(task_id, "INFO", f"跳过 {label}{suffix} - {desc}")

    def _snapshot(self, task_id: int) -> Optional[Dict[str, Any]]:
        with session_scope() as session:
            task = session.get(SyncTask, task_id)
            if task is None:
                return None
            return self._serialize_task(task)

    def _fetch_logs(self, task_id: int) -> List[Dict[str, Any]]:
        with session_scope() as session:
            entries = (
                session.query(TaskLog)
                .filter(TaskLog.task_id == task_id)
                .order_by(TaskLog.created_at.asc())
                .all()
            )
            return [self._serialize_log_entry(entry) for entry in entries]

    def _serialize_task(self, task: SyncTask) -> Dict[str, Any]:
        payload = {
            "id": task.id,
            "task_type": task.task_type,
            "status": task.status,
            "progress": task.progress,
            "incremental": task.incremental,
            "limit": task.limit,
            "created_at": self._to_iso(task.created_at),
            "scheduled_for": self._to_iso(task.scheduled_for),
            "started_at": self._to_iso(task.started_at),
            "completed_at": self._to_iso(task.completed_at),
            "result_path": task.result_path,
            "error_message": task.error_message,
        }
        runtime = self._runtime_state.get(task.id)
        if runtime:
            payload.update(runtime)
        return payload

    def runtime_snapshot(self, task_id: int) -> Dict[str, Any]:
        return dict(self._runtime_state.get(task_id, {}))

    def clear_runtime(self, task_id: int) -> None:
        self._runtime_state.pop(task_id, None)

    def _serialize_log_entry(self, entry: TaskLog) -> Dict[str, Any]:
        return {
            "id": entry.id,
            "task_id": entry.task_id,
            "level": entry.level,
            "message": entry.message,
            "created_at": self._to_iso(entry.created_at),
        }

    def _notify_task_status(self, task_id: int) -> None:
        snapshot = self._snapshot(task_id)
        if snapshot:
            self._notify_listeners(task_id, {"type": "status", "data": snapshot})

    def _notify_listeners(self, task_id: int, payload: Dict[str, Any]) -> None:
        listeners = self._listeners.get(task_id)
        if not listeners:
            return
        loop = self._loop
        if loop is None or not loop.is_running():
            return
        for queue in list(listeners):
            loop.call_soon_threadsafe(self._safe_queue_put, queue, payload)

    @staticmethod
    def _expected_single_output_path(file_type: Optional[str], name: str, parent_path: Path) -> Path:
        safe_name = sanitize_filename(name) or "output"
        base = parent_path / safe_name
        lowered = (file_type or "").lower()
        if lowered in {"doc", "docx", "wiki", "slides", "mindnote", "shortcut"}:
            return base.with_suffix(".md")
        if lowered in {"sheet", "sheets", "bitable", "base"}:
            return base.with_suffix(".xlsx")
        return base

    @staticmethod
    def _finalize_single_output(storage_root: Path, expected: Path, file_type: Optional[str], name: str) -> Optional[Path]:
        absolute = (storage_root / expected).resolve()
        root_base = storage_root.resolve()
        if absolute.exists():
            try:
                return absolute.relative_to(root_base)
            except ValueError:
                return expected

        parent_dir = absolute.parent
        safe_name = sanitize_filename(name) or expected.stem
        lowered = (file_type or "").lower()

        if lowered in {"doc", "docx", "wiki", "slides", "mindnote", "shortcut"}:
            candidate = parent_dir / f"{safe_name}.md"
            if candidate.exists():
                try:
                    return candidate.relative_to(root_base)
                except ValueError:
                    return expected

        if lowered in {"sheet", "sheets", "bitable", "base"}:
            candidate = parent_dir / f"{safe_name}.xlsx"
            if candidate.exists():
                try:
                    return candidate.relative_to(root_base)
                except ValueError:
                    return expected

        if lowered == "file":
            candidate = parent_dir / safe_name
            if candidate.exists():
                try:
                    return candidate.relative_to(root_base)
                except ValueError:
                    return expected

        if lowered == "folder" and absolute.exists():
            try:
                return absolute.relative_to(root_base)
            except ValueError:
                return expected

        return expected

    @staticmethod
    def _safe_queue_put(queue: asyncio.Queue[Dict[str, Any]], payload: Dict[str, Any]) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:  # pragma: no cover - defensive
            pass

    @staticmethod
    def _to_iso(value: Optional[datetime]) -> Optional[str]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).isoformat()
        return value.isoformat()


def _extract_planned_total(payload: Dict[str, Any]) -> Optional[int]:
    if not payload:
        return None
    plan = payload.get("_plan_summary")
    if isinstance(plan, str):
        try:
            plan = json.loads(plan)
        except json.JSONDecodeError:
            return None
    if not isinstance(plan, dict):
        return None
    for key in ("will_download", "total_files"):
        value = plan.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            return int(value)
    return None
