"""Tests for SQLite metadata store."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from larksync.storage import SQLiteMetadataStore
from larksync.storage.strategies import (
    CloudDocStrategy,
    FileStrategy,
    FolderStrategy,
    DownloadDecision,
    get_strategy_for_type,
)


class TestSQLiteMetadataStore:
    """Test SQLiteMetadataStore functionality."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def store(self, temp_dir: Path) -> SQLiteMetadataStore:
        """Create a SQLiteMetadataStore instance."""
        db_path = temp_dir / ".sync.db"
        return SQLiteMetadataStore(db_path, temp_dir)
    
    def test_init_creates_schema(self, store: SQLiteMetadataStore):
        """Test that initialization creates the database schema."""
        assert store._db_path.exists()
        
        # Check tables exist
        conn = store._get_connection()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        tables = {row["name"] for row in cursor}
        
        assert "sync_metadata" in tables
        assert "shortcut_mappings" in tables
        assert "sync_history" in tables
        assert "schema_meta" in tables
    
    def test_mark_synced_and_get(self, store: SQLiteMetadataStore, temp_dir: Path):
        """Test marking a document as synced and retrieving it."""
        # Create a test file
        test_file = temp_dir / "test.md"
        test_file.write_text("# Test")
        
        store.mark_synced(
            "token123",
            name="测试文档",
            file_type="docx",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00+00:00",
            local_path=Path("test.md"),
            revision="rev001",
        )
        
        entry = store.get("token123")
        assert entry is not None
        assert entry["token"] == "token123"
        assert entry["name"] == "测试文档"
        assert entry["file_type"] == "docx"
        assert entry["revision"] == "rev001"
        assert entry["status"] == "ok"
    
    def test_mark_missing(self, store: SQLiteMetadataStore):
        """Test marking a document as missing."""
        store.mark_missing(
            "token_missing",
            error="下载失败：权限不足",
            current_meta={"file_type": "file", "name": "私密文档.pdf"},
            parent_path=Path("folder"),
        )
        
        entry = store.get("token_missing")
        assert entry is not None
        assert entry["status"] == "missing"
        assert "权限不足" in entry["last_error"]
    
    def test_mark_deleted(self, store: SQLiteMetadataStore):
        """Test marking a document as deleted."""
        # First sync the document
        store.mark_synced(
            "token_to_delete",
            name="待删除文档",
            file_type="docx",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00+00:00",
            local_path=None,
        )
        
        # Mark as deleted
        store.mark_deleted("token_to_delete")
        
        entry = store.get("token_to_delete")
        assert entry is not None
        assert entry["status"] == "deleted"
    
    def test_tokens_iteration(self, store: SQLiteMetadataStore):
        """Test iterating over all tokens."""
        for i in range(5):
            store.mark_synced(
                f"token_{i}",
                name=f"文档 {i}",
                file_type="docx",
                parent_path=Path("."),
                modified_time=None,
                local_path=None,
            )
        
        tokens = list(store.tokens())
        assert len(tokens) == 5
        assert "token_0" in tokens
        assert "token_4" in tokens
    
    def test_count(self, store: SQLiteMetadataStore):
        """Test counting entries."""
        # Add some entries with different statuses
        store.mark_synced(
            "ok_1", name="OK 1", file_type="docx",
            parent_path=Path("."), modified_time=None, local_path=None,
        )
        store.mark_synced(
            "ok_2", name="OK 2", file_type="docx",
            parent_path=Path("."), modified_time=None, local_path=None,
        )
        store.mark_missing(
            "missing_1", error="Error",
            current_meta={"file_type": "file"},
            parent_path=Path("."),
        )
        
        assert store.count() == 3
        assert store.count(status="ok") == 2
        assert store.count(status="missing") == 1
    
    def test_stats(self, store: SQLiteMetadataStore):
        """Test getting statistics."""
        store.mark_synced(
            "doc_1", name="文档 1", file_type="docx",
            parent_path=Path("."), modified_time=None, local_path=None,
        )
        store.mark_synced(
            "file_1", name="文件 1", file_type="file",
            parent_path=Path("."), modified_time=None, local_path=None,
        )
        store.mark_deleted("doc_1")
        
        stats = store.stats()
        assert stats["total"] == 2
        assert stats["by_status"]["deleted"] == 1
        assert stats["by_status"]["ok"] == 1
        assert "docx" in stats["by_type"]
        assert "file" in stats["by_type"]


class TestDuplicateCheckStrategies:
    """Test duplicate check strategies."""
    
    def test_get_strategy_for_type(self):
        """Test strategy selection by file type."""
        assert isinstance(get_strategy_for_type("docx"), CloudDocStrategy)
        assert isinstance(get_strategy_for_type("sheet"), CloudDocStrategy)
        assert isinstance(get_strategy_for_type("file"), FileStrategy)
        assert isinstance(get_strategy_for_type("folder"), FolderStrategy)
        # Unknown types fall back to FileStrategy
        assert isinstance(get_strategy_for_type("unknown"), FileStrategy)
    
    def test_cloud_doc_new_file(self):
        """Test CloudDocStrategy for new files."""
        strategy = CloudDocStrategy()
        decision = strategy.should_download(
            stored=None,
            current={"modified_time": "2024-01-01T10:00:00+00:00"},
            local_path=None,
        )
        assert decision.should_download is True
        assert decision.reason == "new_file"
    
    def test_cloud_doc_revision_changed(self):
        """Test CloudDocStrategy when revision changes."""
        strategy = CloudDocStrategy()
        # 测试时禁用 force_on_missing，专注测试 revision 变化
        decision = strategy.should_download(
            stored={
                "revision": "rev001",
                "modified_time": "2024-01-01T10:00:00+00:00",
                "status": "ok",
            },
            current={
                "revision": "rev002",
                "modified_time": "2024-01-01T10:00:00+00:00",
            },
            local_path=Path("/tmp/test.md"),
            force_on_missing=False,  # 禁用本地文件检查
        )
        assert decision.should_download is True
        assert decision.reason == "revision_changed"
    
    def test_cloud_doc_no_changes(self):
        """Test CloudDocStrategy when nothing changed."""
        strategy = CloudDocStrategy()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as f:
            f.write(b"# Test")
            local_path = Path(f.name)
        
        try:
            decision = strategy.should_download(
                stored={
                    "revision": "rev001",
                    "modified_time": "2024-01-01T10:00:00+00:00",
                    "status": "ok",
                    "local_path": str(local_path),
                },
                current={
                    "revision": "rev001",
                    "modified_time": "2024-01-01T10:00:00+00:00",
                },
                local_path=local_path,
            )
            assert decision.should_download is False
            assert decision.reason == "no_changes"
        finally:
            local_path.unlink()
    
    def test_file_strategy_modified_time_changed(self):
        """Test FileStrategy when modified time changes."""
        strategy = FileStrategy()
        # 测试时禁用 force_on_missing，专注测试时间戳变化
        decision = strategy.should_download(
            stored={
                "modified_time": "2024-01-01T10:00:00+00:00",
                "status": "ok",
            },
            current={
                "modified_time": "2024-01-02T10:00:00+00:00",
            },
            local_path=Path("/tmp/test.pdf"),
            force_on_missing=False,  # 禁用本地文件检查
        )
        assert decision.should_download is True
        assert decision.reason == "modified_time_changed"
    
    def test_folder_strategy_directory_missing(self):
        """Test FolderStrategy when directory is missing."""
        strategy = FolderStrategy()
        decision = strategy.should_download(
            stored={
                "status": "ok",
            },
            current={},
            local_path=Path("/nonexistent/folder"),
        )
        assert decision.should_download is True
        assert decision.reason == "directory_missing"
    
    def test_non_incremental_mode(self):
        """Test that non-incremental mode always downloads."""
        strategy = CloudDocStrategy()
        decision = strategy.should_download(
            stored={
                "revision": "rev001",
                "modified_time": "2024-01-01T10:00:00+00:00",
                "status": "ok",
            },
            current={
                "revision": "rev001",
                "modified_time": "2024-01-01T10:00:00+00:00",
            },
            local_path=None,
            incremental=False,
        )
        assert decision.should_download is True
        assert decision.reason == "non_incremental_mode"


class TestMigration:
    """Test JSON to SQLite migration."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    def test_migrate_from_json(self, temp_dir: Path):
        """Test migrating data from JSON file."""
        # Create a JSON metadata file
        json_path = temp_dir / ".metadata.json"
        json_data = {
            "token_1": {
                "name": "文档 1",
                "file_type": "docx",
                "parent_path": ".",
                "modified_time": "2024-01-01T10:00:00+00:00",
                "revision": "rev001",
                "status": "ok",
            },
            "token_2": {
                "name": "文件 2",
                "file_type": "file",
                "parent_path": "folder",
                "modified_time": "2024-01-02T10:00:00+00:00",
                "status": "ok",
            },
        }
        json_path.write_text(json.dumps(json_data), encoding="utf-8")
        
        # Create SQLite store and migrate
        db_path = temp_dir / ".sync.db"
        store = SQLiteMetadataStore(db_path, temp_dir)
        count = store.migrate_from_json(json_path)
        
        assert count == 2
        
        # Verify data
        entry1 = store.get("token_1")
        assert entry1 is not None
        assert entry1["name"] == "文档 1"
        assert entry1["file_type"] == "docx"
        assert entry1["revision"] == "rev001"
        
        entry2 = store.get("token_2")
        assert entry2 is not None
        assert entry2["name"] == "文件 2"
        assert entry2["file_type"] == "file"
    
    def test_migrate_empty_json(self, temp_dir: Path):
        """Test migrating from non-existent JSON file."""
        db_path = temp_dir / ".sync.db"
        store = SQLiteMetadataStore(db_path, temp_dir)
        count = store.migrate_from_json(temp_dir / "nonexistent.json")
        
        assert count == 0


class TestShouldDownloadIntegration:
    """Integration tests for should_download with SQLiteMetadataStore."""
    
    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)
    
    @pytest.fixture
    def store(self, temp_dir: Path) -> SQLiteMetadataStore:
        """Create a SQLiteMetadataStore instance."""
        db_path = temp_dir / ".sync.db"
        return SQLiteMetadataStore(db_path, temp_dir)
    
    def test_new_docx_should_download(self, store: SQLiteMetadataStore):
        """Test that new docx files should be downloaded."""
        decision = store.should_download(
            "new_token",
            file_type="docx",
            current_meta={
                "modified_time": "2024-01-01T10:00:00+00:00",
                "revision": "rev001",
            },
            expected_local_path=None,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("."),
        )
        assert decision.should_download is True
        assert decision.reason == "new_file"
    
    def test_unchanged_docx_should_skip(self, store: SQLiteMetadataStore, temp_dir: Path):
        """Test that unchanged docx files should be skipped."""
        # Create local file
        local_file = temp_dir / "test.md"
        local_file.write_text("# Test")
        
        # Mark as synced
        store.mark_synced(
            "existing_token",
            name="测试文档",
            file_type="docx",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00+00:00",
            local_path=Path("test.md"),
            revision="rev001",
        )
        
        # Check if should download
        decision = store.should_download(
            "existing_token",
            file_type="docx",
            current_meta={
                "modified_time": "2024-01-01T10:00:00+00:00",
                "revision": "rev001",
            },
            expected_local_path=local_file,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("."),
        )
        assert decision.should_download is False
        assert decision.reason == "no_changes"
    
    def test_file_with_time_change_should_download(
        self, store: SQLiteMetadataStore, temp_dir: Path
    ):
        """Test that file with modified_time change should download."""
        # Create local file
        local_file = temp_dir / "test.pdf"
        local_file.write_bytes(b"PDF content")
        
        # Mark as synced with old time
        store.mark_synced(
            "file_token",
            name="测试文件.pdf",
            file_type="file",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00+00:00",
            local_path=Path("test.pdf"),
        )
        
        # Check with new time
        decision = store.should_download(
            "file_token",
            file_type="file",
            current_meta={
                "modified_time": "2024-01-02T10:00:00+00:00",  # Changed!
            },
            expected_local_path=local_file,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("."),
        )
        assert decision.should_download is True
        assert decision.reason == "modified_time_changed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
