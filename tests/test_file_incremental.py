"""测试file类型的增量下载逻辑"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from larksync.config import StorageSettings
from larksync.core.space_sync import DriveSpaceSynchronizer, SpaceSyncContext
from larksync.storage import StorageManager
from larksync.storage.metadata_store import MetadataStore
from larksync.utils.time import normalize_timestamp


def test_file_incremental_logic():
    """测试file类型的增量下载逻辑是否正常"""
    
    # 创建临时目录
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)
        
        # 场景1: 新文件，应该下载
        token = "test_file_token_001"
        current_meta = {
            "modified_time": "2024-01-01T10:00:00Z",
            "revision": None,  # file类型通常没有revision
            "checksum": "abc123",
        }
        expected_path = Path("test_folder/test_file.pdf")
        
        result = store.should_download(
            token=token,
            current_meta=current_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("test_folder"),
        )
        
        print(f"场景1 - 新文件: should_download = {result}")
        assert result is True, "新文件应该下载"
        
        # 记录元数据
        store.mark_synced(
            token=token,
            name="test_file.pdf",
            file_type="file",
            parent_path=Path("test_folder"),
            modified_time="2024-01-01T10:00:00Z",
            local_path=expected_path,
            revision=None,
            checksum="abc123",
        )
        store.flush()
        
        # 场景2: 文件未变化，应该跳过
        result = store.should_download(
            token=token,
            current_meta=current_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=False,  # 不强制检查文件存在
            parent_path=Path("test_folder"),
        )
        
        print(f"场景2 - 文件未变化(不检查存在): should_download = {result}")
        assert result is False, "文件未变化且不检查存在时应该跳过"
        
        # 场景3: 文件未变化但需要检查存在，文件不存在，应该下载
        result = store.should_download(
            token=token,
            current_meta=current_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,  # 强制检查文件存在
            parent_path=Path("test_folder"),
        )
        
        print(f"场景3 - 文件未变化但不存在: should_download = {result}")
        assert result is True, "文件不存在时应该下载"
        
        # 创建实际文件
        actual_file = root / expected_path
        actual_file.parent.mkdir(parents=True, exist_ok=True)
        actual_file.write_text("test content")
        
        # 场景4: 文件未变化且存在，应该跳过
        result = store.should_download(
            token=token,
            current_meta=current_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("test_folder"),
        )
        
        print(f"场景4 - 文件未变化且存在: should_download = {result}")
        assert result is False, "文件未变化且存在时应该跳过"
        
        # 场景5: 文件modified_time变化，应该下载
        new_meta = {
            "modified_time": "2024-01-02T10:00:00Z",  # 时间变化
            "revision": None,
            "checksum": "abc123",
        }
        
        result = store.should_download(
            token=token,
            current_meta=new_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("test_folder"),
        )
        
        print(f"场景5 - modified_time变化: should_download = {result}")
        assert result is True, "modified_time变化时应该下载"
        
        # 场景6: 文件checksum变化，应该下载
        new_meta2 = {
            "modified_time": "2024-01-01T10:00:00Z",
            "revision": None,
            "checksum": "def456",  # checksum变化
        }
        
        result = store.should_download(
            token=token,
            current_meta=new_meta2,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("test_folder"),
        )
        
        print(f"场景6 - checksum变化: should_download = {result}")
        assert result is True, "checksum变化时应该下载"
        
        # 场景7: 全量模式，应该下载
        result = store.should_download(
            token=token,
            current_meta=current_meta,
            expected_local_path=expected_path,
            incremental=False,  # 全量模式
            force_on_missing=True,
            parent_path=Path("test_folder"),
        )
        
        print(f"场景7 - 全量模式: should_download = {result}")
        assert result is True, "全量模式应该下载"
        
        print("\n✅ 所有测试通过")


def test_file_metadata_from_api():
    """测试从API返回的file元数据结构"""
    
    # 模拟飞书API返回的file条目
    api_response = {
        "token": "file_token_001",
        "name": "测试文档.pdf",
        "type": "file",
        "modified_time": "2024-01-01T10:00:00Z",
        "latest_modify_time": "2024-01-01T10:00:00Z",
        "checksum": "abc123def456",
        # file类型通常没有revision
    }
    
    # 提取元数据（模拟space_sync.py中的逻辑）
    modified_time_raw = (
        api_response.get("latest_modify_time")
        or api_response.get("update_time")
        or api_response.get("modify_time")
        or api_response.get("modified_time")
    )
    modified_time = normalize_timestamp(modified_time_raw)
    
    current_meta = {
        "modified_time": modified_time,
        "revision": api_response.get("revision") or api_response.get("rev"),
        "checksum": api_response.get("checksum"),
    }
    
    print(f"提取的元数据: {current_meta}")
    
    # 验证元数据
    assert current_meta["modified_time"] == "2024-01-01T10:00:00+00:00"
    assert current_meta["checksum"] == "abc123def456"
    assert current_meta["revision"] is None  # file类型通常没有revision
    
    print("✅ file元数据提取正常")


def test_file_without_checksum():
    """测试没有checksum的file（可能某些API版本不返回）"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)
        
        token = "file_no_checksum"
        
        # 第一次：只有modified_time
        current_meta1 = {
            "modified_time": "2024-01-01T10:00:00Z",
            "revision": None,
            "checksum": None,  # 没有checksum
        }
        
        # 创建文件
        expected_path = Path("test.pdf")
        actual_file = root / expected_path
        actual_file.write_text("test")
        
        # 标记已同步
        store.mark_synced(
            token=token,
            name="test.pdf",
            file_type="file",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00Z",
            local_path=expected_path,
            checksum=None,
        )
        store.flush()
        
        # 第二次：modified_time相同，checksum也没有
        result = store.should_download(
            token=token,
            current_meta=current_meta1,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("."),
        )
        
        print(f"场景 - 无checksum，时间相同: should_download = {result}")
        assert result is False, "没有checksum时，应该依赖modified_time判断"
        
        # 第三次：modified_time变化
        current_meta2 = {
            "modified_time": "2024-01-02T10:00:00Z",  # 变化
            "revision": None,
            "checksum": None,
        }
        
        result = store.should_download(
            token=token,
            current_meta=current_meta2,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("."),
        )
        
        print(f"场景 - 无checksum，时间变化: should_download = {result}")
        assert result is True, "modified_time变化时应该下载"
        
    print("✅ 无checksum场景测试通过")


def test_modified_time_format_variations():
    """同一时间不同格式应被视为相同，避免重复下载。"""

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)

        token = "doc_token_001"
        expected_path = Path("docs/test_doc.md")

        # 初次同步：API 返回没有时区符号的格式
        store.mark_synced(
            token=token,
            name="test_doc.md",
            file_type="docx",
            parent_path=Path("docs"),
            modified_time="2024-01-01 10:00:00",
            local_path=expected_path,
        )
        store.flush()

        # 创建实际文件，避免 force_on_missing 触发重复下载
        actual_file = root / expected_path
        actual_file.parent.mkdir(parents=True, exist_ok=True)
        actual_file.write_text("content")

        # 第二次：API 返回带 Z 的格式，应视为同一时间
        should_download = store.should_download(
            token=token,
            current_meta={
                "modified_time": "2024-01-01T10:00:00Z",
                "revision": None,
                "checksum": None,
            },
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=Path("docs"),
        )

        assert should_download is False, "同一时间不同格式不应触发重新下载"


def test_metadata_preserves_local_path_for_dotted_names():
    """验证包含点号的文件名在增量标记时不会丢失本地路径。"""

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)

        token = "slides_token"
        parent_path = Path("战略管理会议/数字化战略")
        filename = "4.长城物业数字化设计项目_二阶段工作细化_0305"
        local_path = parent_path / f"{filename}.md"

        # 准备本地文件
        actual_file = root / local_path
        actual_file.parent.mkdir(parents=True, exist_ok=True)
        actual_file.write_text("placeholder content", encoding="utf-8")

        # 初次同步（实际下载后）
        store.mark_synced(
            token=token,
            name=filename,
            file_type="slides",
            parent_path=parent_path,
            modified_time="2024-01-01T10:00:00Z",
            local_path=local_path,
        )
        original_path = store.get(token)["local_path"]

        # 模拟增量跳过时的 metadata 更新（local_path=None 应保留原值）
        store.mark_synced(
            token=token,
            name=filename,
            file_type="slides",
            parent_path=parent_path,
            modified_time="2024-01-01T10:00:00Z",
            local_path=None,
        )

        updated_path = store.get(token)["local_path"]
        assert updated_path == original_path == local_path.as_posix()

        should_download = store.should_download(
            token=token,
            current_meta={"modified_time": "2024-01-01T10:00:00Z"},
            expected_local_path=local_path,
            incremental=True,
            force_on_missing=True,
            parent_path=parent_path,
        )
        assert should_download is False, "本地路径存在时不应重复下载"


def test_expected_local_path_keeps_suffix(tmp_path):
    """_expected_local_path 应在包含点号的名称上保留完整名称。"""

    storage_settings = StorageSettings(root=tmp_path)
    storage = StorageManager(storage_settings)
    metadata = MetadataStore(storage.root)

    context = SpaceSyncContext(
        engine=MagicMock(),
        drive=MagicMock(),
        registry=MagicMock(),
        storage=storage,
    )

    syncer = DriveSpaceSynchronizer(
        context,
        metadata,
        limit=None,
        incremental=True,
        plan_only=True,
    )

    dotted_name = "CCPG.C1025战略规划务虚会.行业趋势模块"
    parent = Path("战略管理会议")
    result = syncer._expected_local_path("test_token", "slides", dotted_name, parent)
    assert result == parent / f"{dotted_name}.md"

    numeric_prefix = "4.长城物业数字化设计项目_二阶段工作细化_0305"
    nested_parent = Path("战略管理会议/数字化战略")
    result2 = syncer._expected_local_path("token2", "slides", numeric_prefix, nested_parent)
    assert result2 == nested_parent / f"{numeric_prefix}.md"


if __name__ == "__main__":
    print("=" * 60)
    print("测试 file 类型增量下载逻辑")
    print("=" * 60)
    print()
    
    test_file_incremental_logic()
    print()
    
    test_file_metadata_from_api()
    print()
    
    test_file_without_checksum()
    print()
    
    print("=" * 60)
    print("所有测试完成 ✅")
    print("=" * 60)
