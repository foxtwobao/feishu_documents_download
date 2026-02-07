"""APScheduler-based task scheduler for sync jobs."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import or_

from ..config import LarkSyncConfig
from .database import session_scope
from .models import ScheduleType, SyncConfig, SyncRun, SyncRunStatus, User, ensure_utc

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _QueueItem:
    config_id: int
    run_id: int


class SyncScheduler:
    """
    Scheduler for managing sync jobs.
    
    Supports:
    - Cron-based scheduling (e.g., "0 3 * * *" for daily at 3am)
    - Interval-based scheduling (e.g., every 6 hours)
    - Manual triggering
    - Automatic token refresh
    """

    def __init__(
        self,
        config: LarkSyncConfig,
        base_storage_root: Path,
        progress_callback: Optional[Callable[[SyncRun], None]] = None,
    ):
        """
        Initialize the scheduler.
        
        Args:
            config: Application configuration
            base_storage_root: Base storage root for user data
            progress_callback: Optional callback for progress updates
        """
        self.config = config
        self.base_storage_root = base_storage_root
        self.progress_callback = progress_callback
        self.scheduler = AsyncIOScheduler()
        self._running_jobs: Dict[int, bool] = {}  # config_id -> is_running
        self._queued_jobs: Dict[int, bool] = {}  # config_id -> is_queued
        self._queue: Optional[asyncio.Queue[_QueueItem]] = None
        self._queue_task: Optional[asyncio.Task[None]] = None

    def start(self) -> None:
        """Start the scheduler."""
        if not self.scheduler.running:
            if self.config.web.scheduler.force_queue:
                self._queue = asyncio.Queue()
                loop = asyncio.get_event_loop()
                self._queue_task = loop.create_task(self._queue_runner())

            self._cleanup_stale_runs()

            # Add token refresh job
            refresh_interval = self.config.web.scheduler.token_refresh_interval
            self.scheduler.add_job(
                self._refresh_tokens_job,
                IntervalTrigger(seconds=refresh_interval),
                id="token_refresh",
                replace_existing=True,
            )

            # Load existing scheduled jobs from database
            self._load_scheduled_jobs()

            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")
        if self._queue_task:
            self._queue_task.cancel()
            self._queue_task = None
        self._queue = None
        self._queued_jobs.clear()

    def _cleanup_stale_runs(self) -> None:
        """Mark unfinished runs as failed after a restart."""
        try:
            with session_scope() as db:
                stale_runs = (
                    db.query(SyncRun)
                    .filter(SyncRun.status.in_(
                        [
                            SyncRunStatus.QUEUED,
                            SyncRunStatus.PENDING,
                            SyncRunStatus.RUNNING,
                        ]
                    ))
                    .all()
                )
                if not stale_runs:
                    return
                now = datetime.now(timezone.utc)
                for run in stale_runs:
                    run.status = SyncRunStatus.FAILED
                    run.error_message = "Service restarted; previous run was interrupted"
                    run.finished_at = now
                db.commit()
                logger.info("Marked %s stale runs as failed", len(stale_runs))
        except Exception as exc:
            logger.warning("Failed to cleanup stale runs: %s", exc)

    def add_job(self, sync_config: SyncConfig) -> None:
        """
        Add or update a scheduled job for a sync config.
        
        Args:
            sync_config: Sync configuration to schedule
        """
        job_id = f"sync_{sync_config.id}"

        # Remove existing job if any
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        if not sync_config.enabled:
            logger.debug(f"Sync config {sync_config.id} is disabled, skipping schedule")
            return

        if sync_config.schedule_type == ScheduleType.MANUAL:
            logger.debug(f"Sync config {sync_config.id} is manual, skipping schedule")
            return

        trigger = None
        if sync_config.schedule_type == ScheduleType.CRON:
            if sync_config.schedule_cron:
                try:
                    trigger = CronTrigger.from_crontab(sync_config.schedule_cron)
                except Exception as e:
                    logger.error(f"Invalid cron expression for config {sync_config.id}: {e}")
                    return

        elif sync_config.schedule_type == ScheduleType.INTERVAL:
            if sync_config.schedule_interval_hours:
                trigger = IntervalTrigger(hours=sync_config.schedule_interval_hours)

        if trigger:
            self.scheduler.add_job(
                self._execute_sync_job,
                trigger=trigger,
                id=job_id,
                args=[sync_config.id],
                replace_existing=True,
                max_instances=1,  # Prevent overlapping executions
            )
            logger.info(
                f"Scheduled sync job",
                extra={"config_id": sync_config.id, "schedule_type": sync_config.schedule_type.value},
            )

    def remove_job(self, config_id: int) -> None:
        """Remove a scheduled job."""
        job_id = f"sync_{config_id}"
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed sync job {job_id}")
        except Exception:
            pass

    async def trigger_sync(self, config_id: int) -> Optional[SyncRun]:
        """
        Manually trigger a sync job.
        
        Args:
            config_id: Sync configuration ID
            
        Returns:
            Created SyncRun or None if already running
        """
        if self._running_jobs.get(config_id):
            logger.warning(f"Sync job {config_id} is already running")
            return None

        return await self._enqueue_or_execute(config_id)

    def _load_scheduled_jobs(self) -> None:
        """Load all enabled scheduled jobs from database."""
        try:
            with session_scope() as db:
                configs = (
                    db.query(SyncConfig)
                    .filter(SyncConfig.enabled == True)
                    .filter(SyncConfig.schedule_type != ScheduleType.MANUAL)
                    .all()
                )
                for config in configs:
                    self.add_job(config)
                logger.info(f"Loaded {len(configs)} scheduled jobs")
        except Exception as e:
            logger.error(f"Failed to load scheduled jobs: {e}")

    async def _execute_sync_job(self, config_id: int) -> Optional[SyncRun]:
        if self.config.web.scheduler.force_queue:
            return await self._enqueue_or_execute(config_id)
        return await self._execute_sync_job_now(config_id)

    async def _enqueue_or_execute(self, config_id: int) -> Optional[SyncRun]:
        if not self.config.web.scheduler.force_queue:
            return await self._execute_sync_job_now(config_id)
        if self._running_jobs.get(config_id) or self._queued_jobs.get(config_id):
            logger.warning(f"Sync job {config_id} is already running or queued")
            return None
        with session_scope() as db:
            sync_config = (
                db.query(SyncConfig)
                .filter(SyncConfig.id == config_id)
                .first()
            )
            if not sync_config:
                logger.error(f"Sync config {config_id} not found")
                return None

            user = db.query(User).filter(User.id == sync_config.user_id).first()
            if not user:
                logger.error(f"User {sync_config.user_id} not found")
                return None

            token_ok, token_error = await self._ensure_user_access_token(db, user)
            if not token_ok:
                sync_run = SyncRun(
                    config_id=config_id,
                    user_id=user.id,
                    status=SyncRunStatus.AUTH_REQUIRED,
                    error_message=token_error,
                    created_at=datetime.now(timezone.utc),
                )
                db.add(sync_run)
                db.commit()
                db.refresh(sync_run)
                db.expunge(sync_run)
                return sync_run

            sync_run = SyncRun(
                config_id=config_id,
                user_id=user.id,
                status=SyncRunStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
            )
            db.add(sync_run)
            db.commit()
            db.refresh(sync_run)
            db.expunge(sync_run)

        if not self._queue:
            self._queue = asyncio.Queue()
        if not self._queue_task:
            loop = asyncio.get_event_loop()
            self._queue_task = loop.create_task(self._queue_runner())
        self._queued_jobs[config_id] = True
        await self._queue.put(_QueueItem(config_id=config_id, run_id=sync_run.id))
        return sync_run

    async def _queue_runner(self) -> None:
        if not self._queue:
            return
        while True:
            item = await self._queue.get()
            try:
                await self._execute_sync_job_now(item.config_id, run_id=item.run_id)
            finally:
                self._queued_jobs.pop(item.config_id, None)
                self._queue.task_done()

    async def _execute_sync_job_now(self, config_id: int, run_id: Optional[int] = None) -> Optional[SyncRun]:
        """
        Execute a sync job.
        
        Args:
            config_id: Sync configuration ID
            
        Returns:
            Created SyncRun or None on error
        """
        if self._running_jobs.get(config_id):
            logger.warning(f"Sync job {config_id} is already running, skipping")
            return None

        self._running_jobs[config_id] = True

        try:
            with session_scope() as db:
                # Get sync config with user
                sync_config = (
                    db.query(SyncConfig)
                    .filter(SyncConfig.id == config_id)
                    .first()
                )
                if not sync_config:
                    logger.error(f"Sync config {config_id} not found")
                    return None

                user = db.query(User).filter(User.id == sync_config.user_id).first()
                if not user:
                    logger.error(f"User {sync_config.user_id} not found")
                    return None

                token_ok, token_error = await self._ensure_user_access_token(db, user)
                if not token_ok:
                    logger.warning(f"User {user.id} token is invalid or expired")
                    if run_id is not None:
                        sync_run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
                        if sync_run:
                            sync_run.status = SyncRunStatus.AUTH_REQUIRED
                            sync_run.error_message = token_error
                            db.commit()
                            db.refresh(sync_run)
                            db.expunge(sync_run)
                            return sync_run
                    # Create a failed run
                    sync_run = SyncRun(
                        config_id=config_id,
                        user_id=user.id,
                        status=SyncRunStatus.AUTH_REQUIRED,
                        error_message=token_error,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(sync_run)
                    db.commit()
                    db.refresh(sync_run)
                    db.expunge(sync_run)  # Detach from session before returning
                    return sync_run

                if run_id is not None:
                    sync_run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
                    if not sync_run:
                        logger.error(f"Sync run {run_id} not found")
                        return None
                    if sync_run.status == SyncRunStatus.CANCELLED:
                        db.expunge(sync_run)
                        return sync_run
                    if sync_run.status != SyncRunStatus.QUEUED:
                        db.expunge(sync_run)
                        return sync_run
                    sync_run.status = SyncRunStatus.PENDING
                    db.commit()
                    db.refresh(sync_run)
                else:
                    # Create sync run record
                    sync_run = SyncRun(
                        config_id=config_id,
                        user_id=user.id,
                        status=SyncRunStatus.PENDING,
                        created_at=datetime.now(timezone.utc),
                    )
                    db.add(sync_run)
                    db.commit()
                    db.refresh(sync_run)

                # Execute sync in thread pool to avoid blocking
                from .sync_service import UserSyncService

                # Copy necessary data for the thread (avoid passing session)
                run_id = sync_run.id
                user_data = {
                    "id": user.id,
                    "feishu_user_id": user.feishu_user_id,
                    "access_token": user.access_token,
                }
                config_data = {
                    "id": sync_config.id,
                    "sync_type": sync_config.sync_type,
                    "wiki_space_id": sync_config.wiki_space_id,
                    "sync_mode": sync_config.sync_mode,
                    "limit": sync_config.limit,
                }

                # Run sync in thread pool with its own session
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self._run_sync_in_thread,
                    run_id,
                    user_data,
                    config_data,
                )

                db.refresh(sync_run)
                db.expunge(sync_run)  # Detach from session before returning
                return sync_run

        except Exception as e:
            logger.exception(f"Error executing sync job {config_id}")
            return None

        finally:
            self._running_jobs[config_id] = False

    async def _ensure_user_access_token(self, db, user: User) -> tuple[bool, str]:
        now = datetime.now(timezone.utc)
        expires_at = ensure_utc(user.token_expires_at)
        if user.access_token and (not expires_at or expires_at >= now):
            return True, ""

        if not user.refresh_token:
            return False, "Access token is invalid or expired"

        app_id = self.config.web.oauth.app_id
        app_secret = self.config.web.oauth.app_secret
        if not app_id or not app_secret:
            return False, "OAuth app credentials are missing"

        from .auth import FeishuOAuthClient

        oauth_client = FeishuOAuthClient(self.config.web.oauth)
        try:
            (
                new_access_token,
                new_refresh_token,
                expires_in,
                refresh_token_expires_in,
            ) = await oauth_client.refresh_token(user.refresh_token)
        except Exception as exc:
            logger.warning(
                "Failed to refresh expired token before sync run",
                extra={"user_id": user.id, "error": str(exc)},
            )
            return False, "Access token refresh failed"

        user.access_token = new_access_token
        user.refresh_token = new_refresh_token
        user.token_expires_at = now + timedelta(seconds=int(expires_in))
        user.refresh_token_expires_at = now + timedelta(seconds=int(refresh_token_expires_in))
        db.commit()
        return True, ""

    def _run_sync_in_thread(
        self,
        run_id: int,
        user_data: Dict[str, Any],
        config_data: Dict[str, Any],
    ) -> None:
        """
        Execute sync in a separate thread with its own database session.
        
        This is necessary because SQLAlchemy sessions are not thread-safe.
        """
        from .sync_service import UserSyncService

        with session_scope() as db:
            # Reload entities in this thread's session
            sync_run = db.query(SyncRun).filter(SyncRun.id == run_id).first()
            if not sync_run:
                logger.error(f"Sync run {run_id} not found in thread")
                return

            user = db.query(User).filter(User.id == user_data["id"]).first()
            if not user:
                logger.error(f"User {user_data['id']} not found in thread")
                return

            sync_config = db.query(SyncConfig).filter(SyncConfig.id == config_data["id"]).first()
            if not sync_config:
                logger.error(f"Sync config {config_data['id']} not found in thread")
                return

            # Create sync service and execute
            service = UserSyncService(
                user=user,
                sync_config=sync_config,
                base_storage_root=self.base_storage_root,
                app_config=self.config,
            )

            try:
                service.execute(db, sync_run, self.progress_callback)
            except Exception as e:
                logger.exception(f"Error in sync thread for run {run_id}")
                sync_run.status = SyncRunStatus.FAILED
                sync_run.error_message = str(e)
                sync_run.finished_at = datetime.now(timezone.utc)
                db.commit()

    async def _refresh_tokens_job(self) -> None:
        """Background job to refresh expiring tokens."""
        logger.debug("Running token refresh job")

        margin_minutes = self.config.web.oauth.token_refresh_margin_minutes
        threshold = datetime.now(timezone.utc) + timedelta(minutes=margin_minutes)

        try:
            with session_scope() as db:
                active_runs = (
                    db.query(SyncRun)
                    .filter(
                        SyncRun.status.in_(
                            [
                                SyncRunStatus.QUEUED,
                                SyncRunStatus.PENDING,
                                SyncRunStatus.RUNNING,
                            ]
                        )
                    )
                    .count()
                )
                if active_runs > 0:
                    logger.debug(
                        "Skip token refresh while sync runs are active",
                        extra={"active_runs": active_runs},
                    )
                    return

                # Find users with tokens expiring soon
                users = (
                    db.query(User)
                    .filter(User.refresh_token.isnot(None))
                    .filter(
                        or_(
                            User.token_expires_at < threshold,
                            User.refresh_token_expires_at < threshold,
                        )
                    )
                    .all()
                )

                if not users:
                    return

                logger.info(f"Found {len(users)} users with expiring tokens")

                from .auth import FeishuOAuthClient

                oauth_client = FeishuOAuthClient(self.config.web.oauth)

                for user in users:
                    try:
                        locked = (
                            db.query(User)
                            .filter(User.id == user.id)
                            .with_for_update()
                            .one_or_none()
                        )
                        if not locked or not locked.refresh_token:
                            continue
                        token_ok = False
                        if locked.token_expires_at:
                            token_ok = ensure_utc(locked.token_expires_at) >= threshold
                        refresh_ok = False
                        if locked.refresh_token_expires_at:
                            refresh_ok = ensure_utc(locked.refresh_token_expires_at) >= threshold
                        if token_ok and refresh_ok:
                            continue
                        (
                            new_access_token,
                            new_refresh_token,
                            expires_in,
                            refresh_token_expires_in,
                        ) = await oauth_client.refresh_token(locked.refresh_token)

                        locked.access_token = new_access_token
                        locked.refresh_token = new_refresh_token
                        locked.token_expires_at = datetime.now(timezone.utc) + timedelta(
                            seconds=expires_in
                        )
                        if refresh_token_expires_in:
                            locked.refresh_token_expires_at = datetime.now(
                                timezone.utc
                            ) + timedelta(seconds=refresh_token_expires_in)

                        db.commit()
                        logger.info(f"Refreshed token for user {user.id}")

                    except Exception as e:
                        logger.error(f"Failed to refresh token for user {user.id}: {e}")
                        db.rollback()

        except Exception as e:
            logger.exception("Error in token refresh job")


# Global scheduler instance
_scheduler: Optional[SyncScheduler] = None


def get_scheduler() -> Optional[SyncScheduler]:
    """Get the global scheduler instance."""
    return _scheduler


def init_scheduler(
    config: LarkSyncConfig,
    base_storage_root: Path,
    progress_callback: Optional[Callable[[SyncRun], None]] = None,
) -> SyncScheduler:
    """
    Initialize and start the global scheduler.
    
    Args:
        config: Application configuration
        base_storage_root: Base storage root for user data
        progress_callback: Optional callback for progress updates
        
    Returns:
        Initialized scheduler
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()

    _scheduler = SyncScheduler(config, base_storage_root, progress_callback)
    _scheduler.start()
    return _scheduler


def shutdown_scheduler() -> None:
    """Shutdown the global scheduler."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.stop()
        _scheduler = None
