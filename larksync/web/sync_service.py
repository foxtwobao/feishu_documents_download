"""Sync service that reuses CLI core modules for multi-user sync."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx
from sqlalchemy.orm import Session

from ..config import (
    AuthSettings,
    LarkSyncConfig,
    RateLimitSettings,
    RetrySettings,
    StorageSettings,
    load_config,
)
from ..core.api_client import FeishuAPIClient, FeishuAPIError
from ..core.adapters.docx_adapter import DocxAdapter
from ..core.adapters.drive_adapter import DriveAdapter
from ..core.adapters.wiki_adapter import WikiAdapter
from ..core.parsers.docx_parser import DocxMarkdownParser
from ..core.registry import DownloaderRegistry
from ..core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from ..core.sync_engine import SyncEngine
from ..core.wiki_sync import WikiSpaceSynchronizer, WikiSyncContext
from ..storage import StorageManager, SQLiteMetadataStore
from ..storage.migration import MetadataStoreAdapter
from .models import (
    FileStatus,
    SyncConfig,
    SyncFileRecord,
    SyncRun,
    SyncRunStatus,
    SyncType,
    User,
    ensure_utc,
)
from .auth import compute_expiry

logger = logging.getLogger(__name__)

_AUTH_ERROR_CODES = {20005, 20006, 99991663, 99991668}


def build_downloader_registry() -> DownloaderRegistry:
    """Build a standard downloader registry."""
    from ..core.downloaders import (
        BitableDownloader,
        DocxDownloader,
        FileDownloader,
        FolderDownloader,
        MindnotePlaceholderDownloader,
        SheetDownloader,
        ShortcutDownloader,
        SlidesPlaceholderDownloader,
        WikiDownloader,
    )

    registry = DownloaderRegistry()
    registry.register("docx", DocxDownloader)
    registry.register("doc", DocxDownloader)
    registry.register("sheet", SheetDownloader)
    registry.register("bitable", BitableDownloader)
    registry.register("file", FileDownloader)
    registry.register("folder", FolderDownloader)
    registry.register("shortcut", ShortcutDownloader)
    registry.register("wiki", WikiDownloader)
    registry.register("slides", SlidesPlaceholderDownloader)
    registry.register("mindnote", MindnotePlaceholderDownloader)
    return registry


class UserAPIClient(FeishuAPIClient):
    """
    FeishuAPIClient that uses a specific user's access token.
    
    This bypasses the CLI token manager and directly uses the provided token.
    """

    def __init__(
        self,
        user_access_token: str,
        retry: RetrySettings,
        rate_limit: Optional[RateLimitSettings] = None,
        base_url: str = "https://open.feishu.cn",
        timeout: float = 30.0,
    ):
        # Create a minimal AuthSettings with the user token
        auth = AuthSettings(user_access_token=user_access_token)
        
        # Initialize parent with auto_refresh disabled (we manage tokens separately)
        super().__init__(
            auth=auth,
            retry=retry,
            rate_limit=rate_limit,
            base_url=base_url,
            timeout=timeout,
            enable_auto_refresh=False,  # Disable CLI token manager
        )
        
        # Store the token directly
        self._user_token = user_access_token

    def _get_valid_user_token(self) -> Optional[str]:
        """Override to return the user's token directly."""
        return self._user_token


class WebProgressTracker:
    """Progress tracker that updates SyncRun in database."""

    def __init__(
        self,
        sync_run: SyncRun,
        db: Session,
        callback: Optional[Callable[[SyncRun], None]] = None,
    ):
        self.sync_run = sync_run
        self.db = db
        self.callback = callback
        self._last_update = 0
        self._pending_records: list[SyncFileRecord] = []  # Batch insert for efficiency

    def update(
        self,
        processed: int,
        total: int,
        name: Optional[str],
        stage: str,
        file_type: Optional[str],
        detail: Optional[str],
    ) -> None:
        """Update progress in the database."""
        import time
        now = time.time()
        
        # Always process success/failed immediately for accurate counts
        # Throttle other updates to reduce DB writes (every 1 second)
        should_commit = stage in ("success", "failed", "finish")
        if not should_commit and now - self._last_update < 1.0:
            # Still update in-memory state for discovery
            if stage == "discover":
                self.sync_run.total_files = total
            elif stage == "start":
                self.sync_run.current_file = name
            return
        
        self._last_update = now

        # Update sync run state
        if stage == "discover":
            self.sync_run.current_stage = "discovering"
            self.sync_run.total_files = total
        elif stage == "start":
            self.sync_run.current_stage = "downloading"
            self.sync_run.current_file = name
        elif stage == "success":
            self.sync_run.downloaded += 1
            self.sync_run.current_file = name
            self.sync_run.current_stage = "downloading"
            # Record downloaded file
            self._record_file(
                file_name=name or "unknown",
                file_path=detail,  # detail contains local path for success
                file_type=file_type,
                status=FileStatus.DOWNLOADED,
                reason=None,
            )
        elif stage == "failed":
            self.sync_run.errors += 1
            self.sync_run.current_file = name
            # Record failed file with reason
            self._record_file(
                file_name=name or "unknown",
                file_path=None,
                file_type=file_type,
                status=FileStatus.FAILED,
                reason=detail,  # detail contains error message for failed
            )

        try:
            self.db.commit()
            if self.callback:
                self.callback(self.sync_run)
        except Exception as e:
            logger.warning(f"Failed to update sync run progress: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass  # Ignore rollback errors

    def _record_file(
        self,
        file_name: str,
        file_path: Optional[str],
        file_type: Optional[str],
        status: FileStatus,
        reason: Optional[str],
        token: Optional[str] = None,
    ) -> None:
        """Record a file's sync status."""
        record = SyncFileRecord(
            run_id=self.sync_run.id,
            file_name=file_name,
            file_path=file_path,
            file_type=file_type,
            token=token,
            status=status,
            reason=reason,
        )
        try:
            self.db.add(record)
        except Exception as e:
            logger.warning(f"Failed to record file {file_name}: {e}")

    def announce_plan(
        self,
        total_found: int,
        to_download: int,
        skipped: int,
        pending_limit: int,
        truncated: bool,
    ) -> None:
        """Update with discovery plan summary."""
        self.sync_run.total_files = total_found
        self.sync_run.skipped = skipped
        self.sync_run.current_stage = "planned"
        try:
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update sync run plan: {e}")
            self.db.rollback()

    def show_discovery(self, count: int, name: Optional[str]) -> None:
        """Show discovery progress."""
        import time
        now = time.time()
        
        # Update in-memory state
        self.sync_run.total_files = count
        self.sync_run.current_stage = "discovering"
        self.sync_run.current_file = name
        
        # Throttle commits to every 1 second during discovery
        if now - self._last_update < 1.0:
            return
        self._last_update = now
        
        try:
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update discovery progress: {e}")
            try:
                self.db.rollback()
            except Exception:
                pass

    def start(self) -> None:
        """Mark sync as started."""
        self.sync_run.status = SyncRunStatus.RUNNING
        self.sync_run.started_at = datetime.now(timezone.utc)
        self.sync_run.current_stage = "starting"
        try:
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update sync run start: {e}")
            self.db.rollback()

    def finish(self, storage_root: Path, summary: Dict[str, Any]) -> None:
        """Mark sync as finished."""
        self.sync_run.status = SyncRunStatus.COMPLETED
        self.sync_run.finished_at = datetime.now(timezone.utc)
        self.sync_run.total_files = summary.get("total_files", 0)
        self.sync_run.total_folders = summary.get("total_folders", 0)
        self.sync_run.downloaded = summary.get("will_download", 0) - summary.get("errors", 0)
        self.sync_run.skipped = summary.get("skipped", 0)
        self.sync_run.errors = summary.get("errors", 0)
        self.sync_run.current_stage = "completed"
        self.sync_run.current_file = None
        try:
            self.db.commit()
        except Exception as e:
            logger.warning(f"Failed to update sync run finish: {e}")
            self.db.rollback()


class UserSyncService:
    """
    Service for executing sync tasks for a specific user.
    
    Reuses CLI core modules (SyncEngine, DriveSpaceSynchronizer, WikiSpaceSynchronizer)
    with user-specific storage and metadata isolation.
    """

    def __init__(
        self,
        user: User,
        sync_config: SyncConfig,
        base_storage_root: Path,
        app_config: Optional[LarkSyncConfig] = None,
    ):
        """
        Initialize the sync service.
        
        Args:
            user: User model with access token
            sync_config: Sync configuration
            base_storage_root: Base storage root directory
            app_config: Optional application config (loaded from config.toml if not provided)
        """
        self.user = user
        self.sync_config = sync_config
        self.app_config = app_config or load_config()
        
        # User-specific storage root: {base_storage_root}/{feishu_user_id}/
        self.user_storage_root = base_storage_root / user.feishu_user_id
        self.user_storage_root.mkdir(parents=True, exist_ok=True)
        
        # Store for user
        user.storage_root = str(self.user_storage_root)

    def execute(
        self,
        db: Session,
        sync_run: SyncRun,
        progress_callback: Optional[Callable[[SyncRun], None]] = None,
    ) -> Dict[str, Any]:
        """
        Execute the sync task.
        
        Args:
            db: Database session for updating progress
            sync_run: SyncRun record to update
            progress_callback: Optional callback for progress updates
            
        Returns:
            Summary dict with sync results
        """
        if not self.user.access_token:
            sync_run.status = SyncRunStatus.AUTH_REQUIRED
            sync_run.error_message = "User access token is missing"
            db.commit()
            return {"error": "auth_required", "message": "User access token is missing"}

        # Create progress tracker
        progress_tracker = WebProgressTracker(sync_run, db, progress_callback)

        try:
            if self._should_refresh_before_start():
                refreshed = self._refresh_user_token(db)
                if not refreshed:
                    return self._mark_auth_required(sync_run, db, "Access token expired and refresh failed")

            progress_tracker.start()
            api_client = self._build_api_client()
            summary = self._run_sync(api_client, progress_tracker)
            progress_tracker.finish(self.user_storage_root, summary)

            # Update last run time
            self.sync_config.last_run_at = datetime.now(timezone.utc)
            db.commit()

            return summary

        except FeishuAPIError as e:
            if self._is_auth_related_exception(e):
                refreshed = self._refresh_user_token(db)
                if refreshed:
                    return self._retry_after_refresh(db, sync_run, progress_tracker)
                return self._mark_auth_required(sync_run, db, "Access token expired or invalid")

            logger.error(
                "Feishu API error during sync",
                extra={"user_id": self.user.id, "status_code": e.status_code, "message": e.message},
            )
            return self._mark_failed(sync_run, db, e)

        except Exception as e:
            if self._is_auth_related_exception(e):
                refreshed = self._refresh_user_token(db)
                if refreshed:
                    return self._retry_after_refresh(db, sync_run, progress_tracker)
                return self._mark_auth_required(sync_run, db, "Access token expired or invalid")

            logger.exception(
                "Unexpected error during sync",
                extra={"user_id": self.user.id, "config_id": self.sync_config.id},
            )
            return self._mark_failed(sync_run, db, e)

        finally:
            pass

    def _build_api_client(self) -> UserAPIClient:
        """Build API client with user's access token."""
        return UserAPIClient(
            user_access_token=self.user.access_token,
            retry=self.app_config.retry,
            rate_limit=self.app_config.rate_limit,
        )

    def _build_storage_manager(self) -> StorageManager:
        """Build storage manager for user's storage root."""
        storage_settings = StorageSettings(
            root=self.user_storage_root,
            nested_dir=self.app_config.storage.nested_dir,
            images_dir=self.app_config.storage.images_dir,
            attachments_dir=self.app_config.storage.attachments_dir,
            preserve_remote_structure=self.app_config.storage.preserve_remote_structure,
        )
        return StorageManager(storage_settings)

    def _build_metadata_store(self) -> MetadataStoreAdapter:
        """Build metadata store for user's storage root."""
        sqlite_path = self.user_storage_root / self.app_config.storage.metadata_sqlite_file
        sqlite_store = SQLiteMetadataStore(
            sqlite_path,
            self.user_storage_root,
            enable_history=self.app_config.storage.metadata_enable_history,
        )
        return MetadataStoreAdapter(sqlite_store)

    def _run_sync(
        self,
        api_client: UserAPIClient,
        progress_tracker: WebProgressTracker,
    ) -> Dict[str, Any]:
        storage = self._build_storage_manager()
        metadata_store = self._build_metadata_store()
        registry = build_downloader_registry()

        engine = SyncEngine(
            config=self.app_config,
            client=api_client,
            registry=registry,
            storage=storage,
        )

        try:
            if self.sync_config.sync_type == SyncType.MY_SPACE:
                summary = self._sync_my_space(engine, metadata_store, progress_tracker)
            else:
                summary = self._sync_wiki(engine, metadata_store, progress_tracker)
            return summary
        finally:
            engine.close()
            metadata_store.flush()

    def _is_invalid_access_token_error(self, error: FeishuAPIError) -> bool:
        message = (error.message or "").lower()
        payload = error.payload or {}
        payload_msg = str(payload.get("msg") or "").lower()
        payload_code = self._extract_payload_error_code(payload)
        combined = f"{message} {payload_msg}"
        if payload_code in _AUTH_ERROR_CODES:
            return True
        if error.status_code == 400:
            return self._contains_auth_error_markers(combined)
        if error.status_code == 401:
            if self._contains_auth_error_markers(combined):
                return True
        return False

    def _is_auth_related_exception(self, error: Exception) -> bool:
        if isinstance(error, FeishuAPIError):
            return self._is_invalid_access_token_error(error)

        message = str(error or "")
        lowered = message.lower()
        extracted_code = self._extract_error_code_from_message(message)
        if extracted_code in _AUTH_ERROR_CODES:
            return True
        return self._contains_auth_error_markers(lowered)

    @staticmethod
    def _contains_auth_error_markers(text: str) -> bool:
        markers = (
            "invalid access token",
            "access token invalid",
            "access token expired",
            "token expired",
            "token is expired",
            "token has expired",
            "access token is invalid",
            "invalid tenant access token",
            "access token无效",
            "access token 过期",
            "token无效",
            "token过期",
        )
        return any(marker in text for marker in markers)

    @staticmethod
    def _extract_payload_error_code(payload: object) -> Optional[int]:
        if not isinstance(payload, dict):
            return None
        value = payload.get("code")
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _extract_error_code_from_message(message: str) -> Optional[int]:
        match = re.search(r"code\s*=\s*(\d+)", message)
        if not match:
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None

    def _mark_auth_required(self, sync_run: SyncRun, db: Session, message: str) -> Dict[str, Any]:
        sync_run.status = SyncRunStatus.AUTH_REQUIRED
        sync_run.error_message = message
        sync_run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"error": "auth_required", "message": message}

    def _mark_failed(self, sync_run: SyncRun, db: Session, error: Exception) -> Dict[str, Any]:
        sync_run.status = SyncRunStatus.FAILED
        if isinstance(error, FeishuAPIError):
            sync_run.error_message = f"Feishu API error: {error.message}"
            message = str(error)
            error_key = "api_error"
        else:
            sync_run.error_message = str(error)
            message = str(error)
            error_key = "unexpected_error"
        sync_run.finished_at = datetime.now(timezone.utc)
        db.commit()
        return {"error": error_key, "message": message}

    def _retry_after_refresh(
        self,
        db: Session,
        sync_run: SyncRun,
        progress_tracker: WebProgressTracker,
    ) -> Dict[str, Any]:
        self._reset_run_for_retry(sync_run, db, progress_tracker)
        try:
            api_client = self._build_api_client()
            summary = self._run_sync(api_client, progress_tracker)
            progress_tracker.finish(self.user_storage_root, summary)
            self.sync_config.last_run_at = datetime.now(timezone.utc)
            db.commit()
            return summary
        except Exception as retry_error:
            if self._is_auth_related_exception(retry_error):
                return self._mark_auth_required(sync_run, db, "Access token invalid after refresh")
            logger.error(
                "Sync retry after refresh failed",
                extra={"user_id": self.user.id, "error": str(retry_error)},
            )
            return self._mark_failed(sync_run, db, retry_error)

    def _refresh_user_token(self, db: Session) -> bool:
        if not self.user.refresh_token:
            logger.warning("Refresh token missing; cannot refresh access token")
            return False
        if not self.app_config.web.oauth.app_id or not self.app_config.web.oauth.app_secret:
            logger.warning("OAuth app credentials missing; cannot refresh access token")
            return False

        url = "https://passport.feishu.cn/suite/passport/oauth/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.app_config.web.oauth.app_id,
            "client_secret": self.app_config.web.oauth.app_secret,
            "refresh_token": self.user.refresh_token,
        }

        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except Exception as exc:
            logger.error("Failed to refresh token", extra={"user_id": self.user.id, "error": str(exc)})
            return False

        if body.get("code") not in (0, None):
            logger.error("Token refresh rejected", extra={"user_id": self.user.id, "message": body.get("msg")})
            return False

        data = body.get("data") or body
        self.user.access_token = data["access_token"]
        self.user.refresh_token = data["refresh_token"]
        expires_in = int(data.get("expires_in", 7200))
        refresh_expires_in = int(data.get("refresh_token_expires_in", 2592000))
        self.user.token_expires_at = compute_expiry(expires_in)
        self.user.refresh_token_expires_at = compute_expiry(refresh_expires_in)
        db.commit()
        logger.info("Refreshed access token for user", extra={"user_id": self.user.id})
        return True

    def _should_refresh_before_start(self) -> bool:
        if not self.user.refresh_token or not self.user.token_expires_at:
            return False
        expires_at = ensure_utc(self.user.token_expires_at)
        margin_minutes = max(0, int(self.app_config.web.oauth.token_refresh_margin_minutes))
        threshold = datetime.now(timezone.utc) + timedelta(minutes=margin_minutes)
        return expires_at <= threshold

    def _reset_run_for_retry(
        self,
        sync_run: SyncRun,
        db: Session,
        progress_tracker: WebProgressTracker,
    ) -> None:
        sync_run.total_files = 0
        sync_run.total_folders = 0
        sync_run.downloaded = 0
        sync_run.skipped = 0
        sync_run.errors = 0
        sync_run.current_stage = "retrying"
        sync_run.current_file = None
        progress_tracker._last_update = 0
        try:
            db.commit()
        except Exception as exc:
            logger.warning("Failed to reset sync run for retry", extra={"error": str(exc)})
            db.rollback()

    def _sync_my_space(
        self,
        engine: SyncEngine,
        metadata_store: MetadataStoreAdapter,
        progress_tracker: WebProgressTracker,
    ) -> Dict[str, Any]:
        """Sync user's personal space."""
        from ..core.space_sync import SpaceSyncContext

        context = SpaceSyncContext(
            engine=engine,
            drive=engine.drive_adapter,
            registry=engine.registry,
            storage=engine.storage,
        )

        # Determine limit and incremental mode
        limit = self.sync_config.limit if self.sync_config.limit > 0 else None
        incremental = self.sync_config.sync_mode.value == "incremental"

        synchronizer = DriveSpaceSynchronizer(
            context,
            metadata_store,
            limit=limit,
            incremental=incremental,
            force_on_missing=self.app_config.sync.force_download_missing,
            clean_deleted=self.app_config.sync.clean_deleted,
            progress_callback=progress_tracker.update,
            progress_tracker=progress_tracker,
        )

        synchronizer.sync()
        return synchronizer.summary()

    def _sync_wiki(
        self,
        engine: SyncEngine,
        metadata_store: MetadataStoreAdapter,
        progress_tracker: WebProgressTracker,
    ) -> Dict[str, Any]:
        """Sync a wiki space."""
        from ..core.wiki_sync import WikiSyncContext

        if not self.sync_config.wiki_space_id:
            raise ValueError("Wiki space ID is required for wiki sync")

        context = WikiSyncContext(
            engine=engine,
            wiki=engine.wiki_adapter,
            drive=engine.drive_adapter,
            registry=engine.registry,
            storage=engine.storage,
        )

        # Determine limit and incremental mode
        limit = self.sync_config.limit if self.sync_config.limit > 0 else None
        incremental = self.sync_config.sync_mode.value == "incremental"

        synchronizer = WikiSpaceSynchronizer(
            context,
            metadata_store,
            limit=limit,
            incremental=incremental,
            force_on_missing=self.app_config.sync.force_download_missing,
            progress_callback=progress_tracker.update,
            progress_tracker=progress_tracker,
        )

        synchronizer.sync(self.sync_config.wiki_space_id)
        return synchronizer.summary()


def get_user_wiki_spaces(user: User, app_config: Optional[LarkSyncConfig] = None) -> list:
    """
    Get list of wiki spaces accessible to a user.
    
    Args:
        user: User with valid access token
        app_config: Optional application config
        
    Returns:
        List of wiki space dicts with space_id, name, description
    """
    if not user.access_token:
        return []

    config = app_config or load_config()
    api_client = UserAPIClient(
        user_access_token=user.access_token,
        retry=config.retry,
        rate_limit=config.rate_limit,
    )

    try:
        wiki_adapter = WikiAdapter(api_client)
        spaces = []
        page_token = None

        while True:
            response = wiki_adapter.list_spaces(page_token=page_token)
            data = response.get("data", {})
            items = data.get("items") or []
            for item in items:
                spaces.append({
                    "space_id": item.get("space_id"),
                    "name": item.get("name"),
                    "description": item.get("description"),
                })
            if not data.get("has_more"):
                break
            page_token = data.get("page_token")
            if not page_token:
                break

        return spaces

    except Exception as e:
        logger.error(f"Failed to get wiki spaces: {e}")
        return []

    finally:
        api_client.close()
