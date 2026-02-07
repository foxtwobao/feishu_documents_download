"""Tests for Wiki sync functionality."""

from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
from unittest.mock import MagicMock, patch

import pytest

from larksync.core.adapters.wiki_adapter import WikiAdapter
from larksync.core.wiki_sync import (
    WikiSpaceSynchronizer,
    WikiSyncContext,
    PlannedWikiNode,
)


class MockFeishuAPIClient:
    """Mock Feishu API client for testing."""

    def __init__(self, responses: Optional[Dict[str, Any]] = None):
        self._responses = responses or {}

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        """Return mocked response based on path."""
        if path in self._responses:
            return self._responses[path]
        # Default empty response
        return {"code": 0, "data": {}}


class TestWikiAdapter:
    """Tests for WikiAdapter."""

    def test_list_spaces_returns_spaces(self):
        """Test that list_spaces returns available wiki spaces."""
        mock_response = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "space_id": "space123",
                        "name": "测试知识库",
                        "description": "用于测试的知识库",
                    }
                ],
                "has_more": False,
            },
        }
        client = MockFeishuAPIClient({"/open-apis/wiki/v2/spaces": mock_response})
        adapter = WikiAdapter(client)

        result = adapter.list_spaces()

        assert result["code"] == 0
        assert "data" in result
        assert len(result["data"]["items"]) == 1
        assert result["data"]["items"][0]["space_id"] == "space123"

    def test_get_space_returns_details(self):
        """Test that get_space returns space details."""
        mock_response = {
            "code": 0,
            "data": {
                "space": {
                    "space_id": "space123",
                    "name": "测试知识库",
                    "wiki_url": "https://example.feishu.cn/wiki/space/space123",
                }
            },
        }
        client = MockFeishuAPIClient({"/open-apis/wiki/v2/spaces/space123": mock_response})
        adapter = WikiAdapter(client)

        result = adapter.get_space("space123")

        assert result["code"] == 0
        assert result["data"]["space"]["name"] == "测试知识库"

    def test_list_space_nodes_returns_nodes(self):
        """Test that list_space_nodes returns wiki nodes."""
        mock_response = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "node_token": "node123",
                        "title": "测试文档",
                        "obj_type": "docx",
                        "obj_token": "docx123",
                        "has_child": False,
                    }
                ],
                "has_more": False,
            },
        }
        client = MockFeishuAPIClient(
            {"/open-apis/wiki/v2/spaces/space123/nodes": mock_response}
        )
        adapter = WikiAdapter(client)

        result = adapter.list_space_nodes("space123")

        assert result["code"] == 0
        assert len(result["data"]["items"]) == 1
        assert result["data"]["items"][0]["node_token"] == "node123"

    def test_get_node_returns_node_details(self):
        """Test that get_node returns node details."""
        mock_response = {
            "code": 0,
            "data": {
                "node": {
                    "node_token": "node123",
                    "title": "测试文档",
                    "obj_type": "docx",
                    "obj_token": "docx123",
                }
            },
        }
        client = MockFeishuAPIClient(
            {"/open-apis/wiki/v2/spaces/get_node": mock_response}
        )
        adapter = WikiAdapter(client)

        result = adapter.get_node("node123")

        assert result["code"] == 0
        assert result["data"]["node"]["title"] == "测试文档"


class TestWikiSpaceSynchronizer:
    """Tests for WikiSpaceSynchronizer."""

    def _create_mock_context(self) -> WikiSyncContext:
        """Create a mock WikiSyncContext for testing."""
        engine = MagicMock()
        wiki = MagicMock()
        drive = MagicMock()
        registry = MagicMock()
        storage = MagicMock()
        storage.root = Path("/tmp/test_output")
        storage.ensure_document_dir = MagicMock()

        return WikiSyncContext(
            engine=engine,
            wiki=wiki,
            drive=drive,
            registry=registry,
            storage=storage,
        )

    def _create_mock_metadata_store(self) -> MagicMock:
        """Create a mock MetadataStore."""
        store = MagicMock()
        store.should_download = MagicMock(return_value=True)
        store.mark_synced = MagicMock()
        store.flush = MagicMock()
        store.clear = MagicMock()
        return store

    def test_list_spaces_returns_space_list(self):
        """Test that list_spaces returns formatted space list."""
        context = self._create_mock_context()
        context.wiki.list_spaces.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "space_id": "space1",
                        "name": "知识库1",
                        "description": "描述1",
                        "wiki_url": "https://example.com/wiki/space1",
                    },
                    {
                        "space_id": "space2",
                        "name": "知识库2",
                        "description": "描述2",
                        "wiki_url": "https://example.com/wiki/space2",
                    },
                ],
                "has_more": False,
            },
        }

        metadata_store = self._create_mock_metadata_store()
        synchronizer = WikiSpaceSynchronizer(context, metadata_store)

        spaces = synchronizer.list_spaces()

        assert len(spaces) == 2
        assert spaces[0]["space_id"] == "space1"
        assert spaces[0]["name"] == "知识库1"
        assert spaces[1]["space_id"] == "space2"

    def test_normalize_type_maps_correctly(self):
        """Test that _normalize_type maps types correctly."""
        assert WikiSpaceSynchronizer._normalize_type("doc") == "docx"
        assert WikiSpaceSynchronizer._normalize_type("docx") == "docx"
        assert WikiSpaceSynchronizer._normalize_type("sheet") == "sheet"
        assert WikiSpaceSynchronizer._normalize_type("sheets") == "sheet"
        assert WikiSpaceSynchronizer._normalize_type("bitable") == "bitable"
        assert WikiSpaceSynchronizer._normalize_type("base") == "bitable"
        assert WikiSpaceSynchronizer._normalize_type("file") == "file"
        assert WikiSpaceSynchronizer._normalize_type("slides") == "slides"
        assert WikiSpaceSynchronizer._normalize_type("mindnote") == "mindnote"
        assert WikiSpaceSynchronizer._normalize_type(None) is None
        assert WikiSpaceSynchronizer._normalize_type("unknown_type") is None

    def test_ensure_success_raises_on_error(self):
        """Test that _ensure_success raises RuntimeError on API error."""
        error_response = {"code": 99991, "msg": "Permission denied"}

        with pytest.raises(RuntimeError) as exc_info:
            WikiSpaceSynchronizer._ensure_success(error_response, "获取知识库")

        assert "code=99991" in str(exc_info.value)
        assert "Permission denied" in str(exc_info.value)

    def test_ensure_success_returns_data_on_success(self):
        """Test that _ensure_success returns data on success."""
        success_response = {
            "code": 0,
            "data": {"items": [{"id": "1"}]},
        }

        result = WikiSpaceSynchronizer._ensure_success(success_response, "获取知识库")

        assert result == {"items": [{"id": "1"}]}

    def test_summary_returns_correct_structure(self):
        """Test that summary returns correct structure."""
        context = self._create_mock_context()
        metadata_store = self._create_mock_metadata_store()
        synchronizer = WikiSpaceSynchronizer(
            context, metadata_store, limit=10, incremental=True
        )

        summary = synchronizer.summary()

        assert "root" in summary
        assert "total_files" in summary
        assert "total_folders" in summary
        assert "will_download" in summary
        assert "existing" in summary
        assert "skipped" in summary
        assert "errors" in summary
        assert "limit" in summary
        assert "incremental" in summary
        assert summary["limit"] == 10
        assert summary["incremental"] is True


class TestPlannedWikiNode:
    """Tests for PlannedWikiNode dataclass."""

    def test_planned_wiki_node_creation(self):
        """Test that PlannedWikiNode can be created correctly."""
        node = PlannedWikiNode(
            node_token="node123",
            obj_token="docx456",
            obj_type="docx",
            title="测试文档",
            parent_path=Path("wiki_test"),
            edit_time="2024-01-01T00:00:00Z",
            source_url="https://example.com/wiki/node123",
            has_child=False,
            space_id="space789",
        )

        assert node.node_token == "node123"
        assert node.obj_token == "docx456"
        assert node.obj_type == "docx"
        assert node.title == "测试文档"
        assert node.parent_path == Path("wiki_test")
        assert node.edit_time == "2024-01-01T00:00:00Z"
        assert node.source_url == "https://example.com/wiki/node123"
        assert node.has_child is False
        assert node.space_id == "space789"
        # 默认值测试
        assert node.is_shortcut is False
        assert node.original_obj_type is None
        assert node.shortcut_target_token is None
        assert node.shortcut_target_type is None

    def test_planned_wiki_node_shortcut_creation(self):
        """Test that PlannedWikiNode can be created with shortcut fields."""
        node = PlannedWikiNode(
            node_token="shortcut_node",
            obj_token="docx_target",
            obj_type="docx",  # 已解析后的目标类型
            title="快捷方式文档",
            parent_path=Path("wiki_test"),
            edit_time="2024-01-01T00:00:00Z",
            source_url="https://example.com/wiki/shortcut_node",
            has_child=False,
            space_id="space789",
            is_shortcut=True,
            original_obj_type="shortcut",
            shortcut_target_token="docx_target",
            shortcut_target_type="docx",
        )

        assert node.node_token == "shortcut_node"
        assert node.obj_token == "docx_target"
        assert node.obj_type == "docx"
        assert node.is_shortcut is True
        assert node.original_obj_type == "shortcut"
        assert node.shortcut_target_token == "docx_target"
        assert node.shortcut_target_type == "docx"


class TestWikiSyncIntegration:
    """Integration tests for Wiki sync (requires mocked API)."""

    def _create_full_mock_context(self) -> WikiSyncContext:
        """Create a fully mocked context for integration testing."""
        engine = MagicMock()
        engine.process_task = MagicMock()

        wiki = MagicMock()
        wiki.get_space.return_value = {
            "code": 0,
            "data": {
                "space": {
                    "space_id": "test_space",
                    "name": "测试知识库",
                    "wiki_url": "https://example.com/wiki/test_space",
                }
            },
        }
        wiki.list_space_nodes.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "node_token": "node1",
                        "title": "文档1",
                        "obj_type": "docx",
                        "obj_token": "docx1",
                        "has_child": False,
                        "obj_edit_time": "1704067200",
                    }
                ],
                "has_more": False,
            },
        }

        drive = MagicMock()
        registry = MagicMock()
        storage = MagicMock()
        storage.root = Path("/tmp/test_wiki_output")
        storage.ensure_document_dir = MagicMock()

        return WikiSyncContext(
            engine=engine,
            wiki=wiki,
            drive=drive,
            registry=registry,
            storage=storage,
        )

    def test_sync_discovers_nodes(self):
        """Test that sync discovers wiki nodes correctly."""
        context = self._create_full_mock_context()
        metadata_store = MagicMock()
        metadata_store.should_download = MagicMock(return_value=True)
        metadata_store.mark_synced = MagicMock()
        metadata_store.flush = MagicMock()

        synchronizer = WikiSpaceSynchronizer(
            context, metadata_store, limit=10, incremental=True
        )

        synchronizer.sync("test_space")

        # Verify that wiki.list_space_nodes was called
        context.wiki.list_space_nodes.assert_called()

        # Verify summary
        summary = synchronizer.summary()
        assert summary["root"]["space_id"] == "test_space"
        assert summary["total_files"] == 1

    def test_sync_handles_shortcut_nodes(self):
        """Test that sync correctly handles shortcut nodes."""
        engine = MagicMock()
        engine.process_task = MagicMock()

        wiki = MagicMock()
        wiki.get_space.return_value = {
            "code": 0,
            "data": {
                "space": {
                    "space_id": "test_space",
                    "name": "测试知识库",
                    "wiki_url": "https://example.com/wiki/test_space",
                }
            },
        }
        # 返回包含快捷方式的节点列表
        wiki.list_space_nodes.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "node_token": "shortcut_node1",
                        "title": "快捷方式文档",
                        "obj_type": "shortcut",  # 快捷方式类型
                        "obj_token": "shortcut_obj",
                        "has_child": False,
                        "obj_edit_time": "1704067200",
                    },
                    {
                        "node_token": "normal_node1",
                        "title": "普通文档",
                        "obj_type": "docx",
                        "obj_token": "docx1",
                        "has_child": False,
                        "obj_edit_time": "1704067200",
                    }
                ],
                "has_more": False,
            },
        }
        # 模拟 get_node 返回不同节点的详情
        # 现在会为每个节点调用 get_node 来检测 shortcut 类型
        def mock_get_node(node_token):
            if node_token == "shortcut_node1":
                return {
                    "code": 0,
                    "data": {
                        "node": {
                            "node_token": "shortcut_node1",
                            "title": "快捷方式文档",
                            "node_type": "shortcut",  # node_type 才是判断 shortcut 的依据
                            "obj_type": "docx",
                            "shortcut_info": {
                                "target_token": "real_docx_token",
                                "target_type": "docx",
                            }
                        }
                    },
                }
            else:  # normal_node1
                return {
                    "code": 0,
                    "data": {
                        "node": {
                            "node_token": "normal_node1",
                            "title": "普通文档",
                            "node_type": "origin",  # 非 shortcut 类型
                            "obj_type": "docx",
                        }
                    },
                }
        wiki.get_node.side_effect = mock_get_node

        drive = MagicMock()
        registry = MagicMock()
        storage = MagicMock()
        storage.root = Path("/tmp/test_wiki_output")
        storage.ensure_document_dir = MagicMock()

        context = WikiSyncContext(
            engine=engine,
            wiki=wiki,
            drive=drive,
            registry=registry,
            storage=storage,
        )

        metadata_store = MagicMock()
        metadata_store.should_download = MagicMock(return_value=True)
        metadata_store.mark_synced = MagicMock()
        metadata_store.flush = MagicMock()

        synchronizer = WikiSpaceSynchronizer(
            context, metadata_store, limit=10, incremental=True
        )

        synchronizer.sync("test_space")

        # 验证 get_node 被调用来检测每个节点的类型
        # 现在会为所有节点调用 get_node 来检测是否是 shortcut
        assert wiki.get_node.call_count == 2
        wiki.get_node.assert_any_call("shortcut_node1")
        wiki.get_node.assert_any_call("normal_node1")

        # 验证 summary
        summary = synchronizer.summary()
        assert summary["root"]["space_id"] == "test_space"
        assert summary["total_files"] == 2  # 1 shortcut + 1 normal

        # 验证 engine.process_task 被调用两次（快捷方式解析为目标后也会下载）
        assert engine.process_task.call_count == 2

    def test_sync_skips_invalid_shortcut(self):
        """Test that sync skips shortcuts without valid target info."""
        engine = MagicMock()
        engine.process_task = MagicMock()

        wiki = MagicMock()
        wiki.get_space.return_value = {
            "code": 0,
            "data": {
                "space": {
                    "space_id": "test_space",
                    "name": "测试知识库",
                    "wiki_url": "https://example.com/wiki/test_space",
                }
            },
        }
        # 只返回一个快捷方式节点
        wiki.list_space_nodes.return_value = {
            "code": 0,
            "data": {
                "items": [
                    {
                        "node_token": "invalid_shortcut",
                        "title": "无效快捷方式",
                        "obj_type": "shortcut",
                        "obj_token": "shortcut_obj",
                        "has_child": False,
                        "obj_edit_time": "1704067200",
                    }
                ],
                "has_more": False,
            },
        }
        # 模拟 get_node 返回没有有效目标信息的快捷方式
        wiki.get_node.return_value = {
            "code": 0,
            "data": {
                "node": {
                    "node_token": "invalid_shortcut",
                    "title": "无效快捷方式",
                    "node_type": "shortcut",  # 标记为 shortcut
                    "obj_type": "shortcut",
                    # 没有 shortcut_info 或者 shortcut_info 为空
                }
            },
        }

        drive = MagicMock()
        registry = MagicMock()
        storage = MagicMock()
        storage.root = Path("/tmp/test_wiki_output")
        storage.ensure_document_dir = MagicMock()

        context = WikiSyncContext(
            engine=engine,
            wiki=wiki,
            drive=drive,
            registry=registry,
            storage=storage,
        )

        metadata_store = MagicMock()
        metadata_store.should_download = MagicMock(return_value=True)
        metadata_store.mark_synced = MagicMock()
        metadata_store.flush = MagicMock()

        synchronizer = WikiSpaceSynchronizer(
            context, metadata_store, limit=10, incremental=True
        )

        synchronizer.sync("test_space")

        # 验证 get_node 被调用
        wiki.get_node.assert_called_with("invalid_shortcut")

        # 验证 summary：无效快捷方式被跳过，计入 skip_count
        summary = synchronizer.summary()
        assert summary["total_files"] == 0  # 没有有效文件
        assert summary["skipped"] == 1  # 跳过了无效快捷方式

        # 验证 engine.process_task 没有被调用
        engine.process_task.assert_not_called()
