"""测试file类型增量下载的真实场景"""

import json
import tempfile
from pathlib import Path

from larksync.storage.metadata_store import MetadataStore


def test_file_incremental_real_api_scenario():
    """
    模拟真实API场景：
    1. 第一次下载file，API返回 modified_time = "1759994958"
    2. 文件已下载并记录元数据
    3. 第二次sync，API返回相同的 modified_time = "1759994958"
    4. 应该跳过下载（因为时间未变化）
    5. 但如果文件实际被删除了，且force_on_missing=True，应该重新下载
    """
    
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)
        
        token = "UKM5bPurHot2YXxqGKFcVXzRnCc"
        name = "日本长期修缮计划.docx"
        parent_path = Path(".")
        expected_path = Path("日本长期修缮计划.docx")
        
        # 模拟API返回的元数据（file类型没有revision和checksum）
        api_meta = {
            "modified_time": "1759994958",  # Unix时间戳字符串
            "revision": None,
            "checksum": None,
        }
        
        print("=" * 60)
        print("场景1: 首次下载file")
        print("=" * 60)
        
        should_dl = store.should_download(
            token=token,
            current_meta=api_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=parent_path,
        )
        
        print(f"首次下载: should_download = {should_dl}")
        assert should_dl is True, "首次下载应该返回True"
        
        # 模拟下载完成，记录元数据
        actual_file = root / expected_path
        actual_file.write_bytes(b"file content here")
        
        store.mark_synced(
            token=token,
            name=name,
            file_type="file",
            parent_path=parent_path,
            modified_time="1759994958",
            local_path=expected_path,
            revision=None,
            checksum=None,
        )
        store.flush()
        
        print(f"✅ 文件已下载并记录元数据")
        print()
        
        # ----------------------------------------------------------------
        print("=" * 60)
        print("场景2: 第二次sync，时间未变化，文件存在")
        print("=" * 60)
        
        should_dl = store.should_download(
            token=token,
            current_meta=api_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=parent_path,
        )
        
        print(f"文件存在，时间未变: should_download = {should_dl}")
        assert should_dl is False, "文件存在且时间未变化，应该跳过"
        print("✅ 正确跳过")
        print()
        
        # ----------------------------------------------------------------
        print("=" * 60)
        print("场景3: 第二次sync，时间未变化，但文件被删除")
        print("=" * 60)
        
        # 删除本地文件
        actual_file.unlink()
        print(f"删除了本地文件: {actual_file}")
        
        should_dl = store.should_download(
            token=token,
            current_meta=api_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,  # 强制检查文件存在
            parent_path=parent_path,
        )
        
        print(f"文件不存在: should_download = {should_dl}")
        assert should_dl is True, "文件不存在时，应该重新下载"
        print("✅ 正确触发重新下载")
        print()
        
        # ----------------------------------------------------------------
        print("=" * 60)
        print("场景4: 时间变化，应该重新下载")
        print("=" * 60)
        
        # 恢复文件
        actual_file.write_bytes(b"file content")
        
        new_api_meta = {
            "modified_time": "1760000000",  # 时间变化
            "revision": None,
            "checksum": None,
        }
        
        should_dl = store.should_download(
            token=token,
            current_meta=new_api_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=True,
            parent_path=parent_path,
        )
        
        print(f"时间变化: should_download = {should_dl}")
        assert should_dl is True, "时间变化时应该重新下载"
        print("✅ 正确触发重新下载")
        print()
        
        # ----------------------------------------------------------------
        print("=" * 60)
        print("场景5: 全量模式，即使文件存在也要下载")
        print("=" * 60)
        
        should_dl = store.should_download(
            token=token,
            current_meta=api_meta,
            expected_local_path=expected_path,
            incremental=False,  # 全量模式
            force_on_missing=True,
            parent_path=parent_path,
        )
        
        print(f"全量模式: should_download = {should_dl}")
        assert should_dl is True, "全量模式应该下载"
        print("✅ 正确")
        print()
        
        # ----------------------------------------------------------------
        print("=" * 60)
        print("场景6: 不检查文件存在，即使文件被删除也跳过")
        print("=" * 60)
        
        actual_file.unlink()
        
        should_dl = store.should_download(
            token=token,
            current_meta=api_meta,
            expected_local_path=expected_path,
            incremental=True,
            force_on_missing=False,  # 不强制检查文件
            parent_path=parent_path,
        )
        
        print(f"不检查存在: should_download = {should_dl}")
        assert should_dl is False, "不检查存在时，应该跳过"
        print("⚠️  注意：文件虽然不存在，但因为 force_on_missing=False 仍然跳过")
        print()
        
        print("=" * 60)
        print("✅ 所有场景测试通过")
        print("=" * 60)


def test_metadata_json_format():
    """测试元数据JSON的实际格式"""
    
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        store = MetadataStore(root)
        
        # 记录几个file
        store.mark_synced(
            token="file1",
            name="test1.pdf",
            file_type="file",
            parent_path=Path("."),
            modified_time="1759994958",
            local_path=Path("test1.pdf"),
            revision=None,
            checksum=None,
        )
        
        store.mark_synced(
            token="docx1",
            name="test.docx",
            file_type="docx",
            parent_path=Path("."),
            modified_time="2024-01-01T10:00:00Z",
            local_path=Path("test.md"),
            revision="12",
            checksum=None,
        )
        
        store.flush()
        
        # 读取JSON
        metadata_path = root / ".metadata.json"
        content = json.loads(metadata_path.read_text())
        
        print("=" * 60)
        print("元数据JSON格式")
        print("=" * 60)
        print(json.dumps(content, indent=2, ensure_ascii=False))
        print()
        
        # 验证
        assert "file1" in content
        assert content["file1"]["file_type"] == "file"
        assert content["file1"]["modified_time"] == "1759994958"
        assert content["file1"].get("revision") is None
        assert content["file1"].get("checksum") is None
        
        assert "docx1" in content
        assert content["docx1"]["file_type"] == "docx"
        assert content["docx1"]["revision"] == "12"
        
        print("✅ 元数据格式正确")


if __name__ == "__main__":
    test_file_incremental_real_api_scenario()
    print()
    test_metadata_json_format()
