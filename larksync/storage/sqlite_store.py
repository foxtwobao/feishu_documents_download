"""SQLite-backed metadata store for sync information."""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Generator, Iterable, Mapping, Optional

from ..utils.time import normalize_timestamp
from .strategies import DownloadDecision, get_strategy_for_type

logger = logging.getLogger(__name__)


class SQLiteMetadataStore:
    """
    SQLite-backed persistent metadata store for incremental sync.
    
    Advantages over JSON:
    - Atomic writes with transactions
    - Indexed queries for large datasets
    - Concurrent access support
    - No need to load entire dataset into memory
    """
    
    # Schema version for migrations
    SCHEMA_VERSION = 1
    
    def __init__(
        self,
        db_path: Path,
        root: Path,
        *,
        enable_history: bool = False,
    ):
        """
        Initialize the SQLite metadata store.
        
        Args:
            db_path: Path to the SQLite database file
            root: Storage root directory (for resolving relative paths)
            enable_history: Whether to record sync history
        """
        self._db_path = db_path
        self._root = root
        self._enable_history = enable_history
        self._local = threading.local()
        
        # Initialize database
        self._init_db()
    
    # ------------------------------------------------------------------ Connection management
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                isolation_level=None,  # Autocommit by default
            )
            self._local.conn.row_factory = sqlite3.Row
            # Enable foreign keys
            self._local.conn.execute("PRAGMA foreign_keys = ON")
            # WAL mode for better concurrent access
            self._local.conn.execute("PRAGMA journal_mode = WAL")
        return self._local.conn
    
    @contextmanager
    def _transaction(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database transactions."""
        conn = self._get_connection()
        conn.execute("BEGIN")
        try:
            yield conn
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    
    def close(self) -> None:
        """Close the database connection."""
        if hasattr(self._local, "conn") and self._local.conn is not None:
            self._local.conn.close()
            self._local.conn = None
    
    # ------------------------------------------------------------------ Schema initialization
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        
        conn = self._get_connection()
        
        # Check schema version
        try:
            cursor = conn.execute(
                "SELECT value FROM schema_meta WHERE key = 'version'"
            )
            row = cursor.fetchone()
            current_version = int(row["value"]) if row else 0
        except sqlite3.OperationalError:
            current_version = 0
        
        if current_version < self.SCHEMA_VERSION:
            self._create_schema(conn)
    
    def _create_schema(self, conn: sqlite3.Connection) -> None:
        """Create or upgrade database schema."""
        # Schema metadata table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        
        # Main metadata table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                file_type TEXT NOT NULL,
                name TEXT,
                parent_path TEXT,
                local_path TEXT,
                modified_time TEXT,
                revision TEXT,
                checksum TEXT,
                local_file_size INTEGER,
                status TEXT DEFAULT 'ok',
                last_error TEXT,
                last_synced_at TEXT,
                source_url TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Indexes
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_file_type ON sync_metadata(file_type)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_status ON sync_metadata(status)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_parent_path ON sync_metadata(parent_path)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_metadata_modified_time ON sync_metadata(modified_time)"
        )
        
        # Shortcut mappings table
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shortcut_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shortcut_token TEXT NOT NULL UNIQUE,
                target_token TEXT NOT NULL,
                target_type TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Sync history table (optional)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL,
                action TEXT NOT NULL,
                file_type TEXT,
                reason TEXT,
                old_revision TEXT,
                new_revision TEXT,
                old_modified_time TEXT,
                new_modified_time TEXT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_token ON sync_history(token)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_timestamp ON sync_history(timestamp)"
        )
        
        # Update schema version
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('version', ?)",
            (str(self.SCHEMA_VERSION),),
        )
    
    # ------------------------------------------------------------------ Access methods
    
    def get(self, token: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a token."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT * FROM sync_metadata WHERE token = ?",
            (token,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return dict(row)
    
    def tokens(self) -> Iterable[str]:
        """Get all recorded tokens."""
        conn = self._get_connection()
        cursor = conn.execute("SELECT token FROM sync_metadata")
        return (row["token"] for row in cursor)
    
    def count(self, *, status: Optional[str] = None) -> int:
        """Count metadata entries, optionally filtered by status."""
        conn = self._get_connection()
        if status:
            cursor = conn.execute(
                "SELECT COUNT(*) as cnt FROM sync_metadata WHERE status = ?",
                (status,),
            )
        else:
            cursor = conn.execute("SELECT COUNT(*) as cnt FROM sync_metadata")
        return cursor.fetchone()["cnt"]
    
    def resolve_path(self, entry: Mapping[str, Any]) -> Path:
        """Resolve the local path for an entry."""
        local = entry.get("local_path")
        if isinstance(local, str) and local:
            return (self._root / local).resolve()
        parent = entry.get("parent_path")
        if isinstance(parent, str) and parent:
            return (self._root / parent).resolve()
        return self._root
    
    # ------------------------------------------------------------------ Decision methods
    
    def should_download(
        self,
        token: str,
        *,
        file_type: str,
        current_meta: Mapping[str, Any],
        expected_local_path: Optional[Path],
        incremental: bool,
        force_on_missing: bool,
        parent_path: Path,
    ) -> DownloadDecision:
        """
        Determine whether a file should be downloaded.
        
        Uses type-specific strategies for the decision.
        
        Args:
            token: Document token
            file_type: Type of document (docx, sheet, file, etc.)
            current_meta: Current metadata from API
            expected_local_path: Expected local file path
            incremental: Whether incremental sync is enabled
            force_on_missing: Re-download if local file missing
            parent_path: Parent directory path
            
        Returns:
            DownloadDecision with should_download flag and reason
        """
        stored = self.get(token)
        
        # Build current metadata dict with parent_path
        current = dict(current_meta)
        current["parent_path"] = parent_path.as_posix()
        
        # Normalize timestamps
        if "modified_time" in current:
            current["modified_time"] = normalize_timestamp(current["modified_time"])
        
        # Resolve local path for existence check
        if expected_local_path and not expected_local_path.is_absolute():
            resolved_path = self._root / expected_local_path
        else:
            resolved_path = expected_local_path
        
        # Get strategy and make decision
        strategy = get_strategy_for_type(file_type)
        decision = strategy.should_download(
            stored,
            current,
            resolved_path,
            incremental=incremental,
            force_on_missing=force_on_missing,
        )
        
        logger.debug(
            "Download decision",
            extra={
                "token": token,
                "file_type": file_type,
                "decision": decision.should_download,
                "reason": decision.reason,
            },
        )
        
        return decision
    
    # Compatibility wrapper for old interface
    def should_download_compat(
        self,
        token: str,
        *,
        current_meta: Mapping[str, Any],
        expected_local_path: Optional[Path],
        incremental: bool,
        force_on_missing: bool,
        parent_path: Path,
    ) -> bool:
        """
        Compatibility wrapper matching the old MetadataStore interface.
        
        This method exists for backward compatibility during migration.
        """
        file_type = current_meta.get("file_type", "file")
        if isinstance(file_type, str):
            file_type = file_type.lower()
        else:
            file_type = "file"
        
        decision = self.should_download(
            token,
            file_type=file_type,
            current_meta=current_meta,
            expected_local_path=expected_local_path,
            incremental=incremental,
            force_on_missing=force_on_missing,
            parent_path=parent_path,
        )
        return decision.should_download
    
    # ------------------------------------------------------------------ Update methods
    
    def mark_synced(
        self,
        token: str,
        *,
        name: str,
        file_type: str,
        parent_path: Path,
        modified_time: Optional[str],
        local_path: Optional[Path],
        revision: Optional[str] = None,
        checksum: Optional[str] = None,
        source_url: Optional[str] = None,
    ) -> None:
        """Mark a document as successfully synced."""
        now = datetime.now(timezone.utc).isoformat()
        normalized_time = normalize_timestamp(modified_time)
        
        # Get local file size if available
        local_file_size: Optional[int] = None
        if local_path:
            resolved = self._root / local_path if not local_path.is_absolute() else local_path
            if resolved.exists() and resolved.is_file():
                try:
                    local_file_size = resolved.stat().st_size
                except OSError:
                    pass
        
        conn = self._get_connection()
        
        # Record history if enabled
        if self._enable_history:
            old = self.get(token)
            self._record_history(
                conn, token, "sync", file_type,
                reason="download_complete",
                old_revision=old.get("revision") if old else None,
                new_revision=revision,
                old_modified_time=old.get("modified_time") if old else None,
                new_modified_time=normalized_time,
            )
        
        # Upsert metadata
        conn.execute("""
            INSERT INTO sync_metadata (
                token, file_type, name, parent_path, local_path,
                modified_time, revision, checksum, local_file_size,
                status, last_error, last_synced_at, source_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ok', NULL, ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                file_type = excluded.file_type,
                name = excluded.name,
                parent_path = excluded.parent_path,
                local_path = COALESCE(excluded.local_path, local_path),
                modified_time = excluded.modified_time,
                revision = excluded.revision,
                checksum = excluded.checksum,
                local_file_size = excluded.local_file_size,
                status = 'ok',
                last_error = NULL,
                last_synced_at = excluded.last_synced_at,
                source_url = COALESCE(excluded.source_url, source_url),
                updated_at = excluded.updated_at
        """, (
            token,
            file_type,
            name,
            parent_path.as_posix(),
            local_path.as_posix() if local_path else None,
            normalized_time,
            revision,
            checksum,
            local_file_size,
            now,
            source_url,
            now,
        ))
    
    def mark_missing(
        self,
        token: str,
        *,
        error: str,
        current_meta: Mapping[str, Any],
        parent_path: Path,
        source_url: Optional[str] = None,
    ) -> None:
        """Mark a document as failed to download."""
        now = datetime.now(timezone.utc).isoformat()
        normalized_time = normalize_timestamp(current_meta.get("modified_time"))
        revision = current_meta.get("revision")
        file_type = current_meta.get("file_type", "unknown")
        name = current_meta.get("name", token)
        
        conn = self._get_connection()
        
        if self._enable_history:
            self._record_history(
                conn, token, "error", file_type,
                reason=error,
            )
        
        conn.execute("""
            INSERT INTO sync_metadata (
                token, file_type, name, parent_path, modified_time,
                revision, status, last_error, source_url, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'missing', ?, ?, ?)
            ON CONFLICT(token) DO UPDATE SET
                parent_path = excluded.parent_path,
                modified_time = excluded.modified_time,
                revision = COALESCE(excluded.revision, revision),
                status = 'missing',
                last_error = excluded.last_error,
                source_url = COALESCE(excluded.source_url, source_url),
                updated_at = excluded.updated_at
        """, (
            token,
            file_type,
            name,
            parent_path.as_posix(),
            normalized_time,
            revision,
            error,
            source_url,
            now,
        ))
    
    def mark_deleted(self, token: str) -> None:
        """Mark a document as deleted from remote."""
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        
        if self._enable_history:
            old = self.get(token)
            if old:
                self._record_history(
                    conn, token, "delete", old.get("file_type"),
                    reason="remote_deleted",
                )
        
        conn.execute("""
            UPDATE sync_metadata
            SET status = 'deleted', last_error = NULL, updated_at = ?
            WHERE token = ?
        """, (now, token))
    
    def remove(self, token: str) -> None:
        """Remove a token from the metadata store."""
        conn = self._get_connection()
        conn.execute("DELETE FROM sync_metadata WHERE token = ?", (token,))
    
    # ------------------------------------------------------------------ Shortcut methods
    
    def register_shortcut(
        self,
        shortcut_token: str,
        target_token: str,
        target_type: str,
    ) -> None:
        """Register a shortcut mapping."""
        conn = self._get_connection()
        conn.execute("""
            INSERT OR REPLACE INTO shortcut_mappings
            (shortcut_token, target_token, target_type)
            VALUES (?, ?, ?)
        """, (shortcut_token, target_token, target_type))
    
    def get_shortcut_target(self, shortcut_token: str) -> Optional[Dict[str, str]]:
        """Get the target of a shortcut."""
        conn = self._get_connection()
        cursor = conn.execute(
            "SELECT target_token, target_type FROM shortcut_mappings WHERE shortcut_token = ?",
            (shortcut_token,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {"target_token": row["target_token"], "target_type": row["target_type"]}
    
    # ------------------------------------------------------------------ History methods
    
    def _record_history(
        self,
        conn: sqlite3.Connection,
        token: str,
        action: str,
        file_type: Optional[str],
        *,
        reason: Optional[str] = None,
        old_revision: Optional[str] = None,
        new_revision: Optional[str] = None,
        old_modified_time: Optional[str] = None,
        new_modified_time: Optional[str] = None,
    ) -> None:
        """Record an entry in sync history."""
        if not self._enable_history:
            return
        
        conn.execute("""
            INSERT INTO sync_history
            (token, action, file_type, reason, old_revision, new_revision,
             old_modified_time, new_modified_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            token, action, file_type, reason,
            old_revision, new_revision,
            old_modified_time, new_modified_time,
        ))
    
    def get_history(
        self,
        token: Optional[str] = None,
        *,
        limit: int = 100,
    ) -> list[Dict[str, Any]]:
        """Get sync history entries."""
        conn = self._get_connection()
        if token:
            cursor = conn.execute(
                "SELECT * FROM sync_history WHERE token = ? ORDER BY timestamp DESC LIMIT ?",
                (token, limit),
            )
        else:
            cursor = conn.execute(
                "SELECT * FROM sync_history ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            )
        return [dict(row) for row in cursor]
    
    # ------------------------------------------------------------------ Migration methods
    
    def migrate_from_json(self, json_path: Path) -> int:
        """
        Migrate data from a JSON metadata file.
        
        Args:
            json_path: Path to the JSON metadata file
            
        Returns:
            Number of entries migrated
        """
        if not json_path.exists():
            logger.info("No JSON file to migrate", extra={"path": str(json_path)})
            return 0
        
        try:
            content = json.loads(json_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to read JSON file", extra={"path": str(json_path), "error": str(e)})
            return 0
        
        if not isinstance(content, dict):
            logger.warning("Invalid JSON structure", extra={"path": str(json_path)})
            return 0
        
        count = 0
        with self._transaction() as conn:
            for token, entry in content.items():
                if not isinstance(entry, dict):
                    continue
                
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO sync_metadata (
                            token, file_type, name, parent_path, local_path,
                            modified_time, revision, checksum, status,
                            last_error, last_synced_at, source_url
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        token,
                        entry.get("file_type", "unknown"),
                        entry.get("name"),
                        entry.get("parent_path"),
                        entry.get("local_path"),
                        entry.get("modified_time"),
                        entry.get("revision"),
                        entry.get("checksum"),
                        entry.get("status", "ok"),
                        entry.get("last_error"),
                        entry.get("last_synced"),
                        entry.get("source_url"),
                    ))
                    count += 1
                except sqlite3.Error as e:
                    logger.warning(
                        "Failed to migrate entry",
                        extra={"token": token, "error": str(e)},
                    )
        
        logger.info(
            "Migration complete",
            extra={"migrated": count, "total": len(content)},
        )
        return count
    
    # ------------------------------------------------------------------ Utility methods
    
    def flush(self) -> None:
        """Flush pending changes (no-op for SQLite with autocommit)."""
        pass
    
    def clear(self) -> None:
        """Clear all metadata."""
        conn = self._get_connection()
        conn.execute("DELETE FROM sync_metadata")
        conn.execute("DELETE FROM shortcut_mappings")
        if self._enable_history:
            conn.execute("DELETE FROM sync_history")
    
    def vacuum(self) -> None:
        """Reclaim space from deleted entries."""
        conn = self._get_connection()
        conn.execute("VACUUM")
    
    def stats(self) -> Dict[str, Any]:
        """Get statistics about the metadata store."""
        conn = self._get_connection()
        
        total = conn.execute("SELECT COUNT(*) as cnt FROM sync_metadata").fetchone()["cnt"]
        by_status = {}
        for row in conn.execute(
            "SELECT status, COUNT(*) as cnt FROM sync_metadata GROUP BY status"
        ):
            by_status[row["status"]] = row["cnt"]
        
        by_type = {}
        for row in conn.execute(
            "SELECT file_type, COUNT(*) as cnt FROM sync_metadata GROUP BY file_type"
        ):
            by_type[row["file_type"]] = row["cnt"]
        
        return {
            "total": total,
            "by_status": by_status,
            "by_type": by_type,
            "shortcuts": conn.execute(
                "SELECT COUNT(*) as cnt FROM shortcut_mappings"
            ).fetchone()["cnt"],
            "history_entries": conn.execute(
                "SELECT COUNT(*) as cnt FROM sync_history"
            ).fetchone()["cnt"] if self._enable_history else 0,
        }
