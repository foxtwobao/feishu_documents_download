#!/usr/bin/env python3
"""调试增量下载行为不一致的问题"""

import json
import os
from pathlib import Path
from larksync.storage.metadata_store import MetadataStore


def analyze_metadata_behavior():
    """分析元数据存储的行为"""
    # 设置工作目录
    work_dir = Path("/mnt/share/n8ndata/feishufiles")
    metadata_path = work_dir / ".metadata.json"
    
    if not metadata_path.exists():
        print("❌ 元数据文件不存在")
        return
    
    # 读取元数据文件
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        print(f"✅ 成功读取元数据文件，包含 {len(metadata)} 个条目")
    except Exception as e:
        print(f"❌ 读取元数据文件失败: {e}")
        return
    
    # 分析条目状态
    status_count = {}
    file_types = {}
    
    for token, entry in metadata.items():
        status = entry.get("status", "unknown")
        file_type = entry.get("file_type", "unknown")
        
        status_count[status] = status_count.get(status, 0) + 1
        file_types[file_type] = file_types.get(file_type, 0) + 1
    
    print("\n📊 条目状态统计:")
    for status, count in status_count.items():
        print(f"  {status}: {count}")
    
    print("\n📂 文件类型统计:")
    for file_type, count in file_types.items():
        print(f"  {file_type}: {count}")
    
    # 检查文件是否存在
    print("\n🔍 文件存在性检查:")
    existing_files = 0
    missing_files = 0
    
    for token, entry in metadata.items():
        if entry.get("status") != "ok":
            continue
            
        local_path = entry.get("local_path")
        if not local_path:
            continue
            
        full_path = work_dir / local_path
        if full_path.exists():
            existing_files += 1
        else:
            missing_files += 1
            print(f"  ❌ 缺失文件: {local_path}")
    
    print(f"  存在的文件: {existing_files}")
    print(f"  缺失的文件: {missing_files}")
    
    # 分析should_download逻辑
    print("\n🔄 模拟should_download逻辑:")
    
    # 创建MetadataStore实例
    store = MetadataStore(work_dir)
    
    # 检查几个示例条目
    sample_count = 0
    for token, entry in list(metadata.items())[:10]:
        if entry.get("status") != "ok":
            continue
            
        if sample_count >= 3:  # 只检查前3个
            break
            
        sample_count += 1
        
        print(f"\n  条目 {token}:")
        print(f"    名称: {entry.get('name')}")
        print(f"    类型: {entry.get('file_type')}")
        print(f"    修改时间: {entry.get('modified_time')}")
        
        # 构造current_meta
        current_meta = {
            "modified_time": entry.get("modified_time"),
            "revision": entry.get("revision"),
            "checksum": entry.get("checksum"),
        }
        
        parent_path = Path(entry.get("parent_path", "."))
        local_path = Path(entry.get("local_path")) if entry.get("local_path") else None
        
        # 检查should_download的返回值
        should_download = store.should_download(
            token,
            current_meta=current_meta,
            expected_local_path=local_path,
            incremental=True,
            force_on_missing=True,
            parent_path=parent_path,
        )
        
        print(f"    should_download: {should_download}")
        
        if should_download:
            print("    🔄 将会被下载")
        else:
            print("    ✅ 将会被跳过")


def check_file_modification_times():
    """检查文件修改时间的一致性"""
    work_dir = Path("/mnt/share/n8ndata/feishufiles")
    metadata_path = work_dir / ".metadata.json"
    
    if not metadata_path.exists():
        print("❌ 元数据文件不存在")
        return
    
    try:
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
    except Exception as e:
        print(f"❌ 读取元数据文件失败: {e}")
        return
    
    print("\n⏰ 文件修改时间检查:")
    
    # 检查几个文档文件
    doc_count = 0
    for token, entry in metadata.items():
        if entry.get("file_type") not in ["docx", "sheet", "bitable"]:
            continue
            
        if entry.get("status") != "ok":
            continue
            
        if doc_count >= 5:  # 只检查前5个
            break
            
        doc_count += 1
        
        local_path = entry.get("local_path")
        if not local_path:
            continue
            
        full_path = work_dir / local_path
        if not full_path.exists():
            print(f"  ❌ 文件不存在: {local_path}")
            continue
        
        try:
            # 获取文件系统中的修改时间
            stat = full_path.stat()
            fs_mtime = int(stat.st_mtime)
            
            # 获取元数据中的修改时间
            meta_mtime = entry.get("modified_time")
            if meta_mtime:
                meta_mtime = int(meta_mtime)
            
            print(f"  文件: {local_path}")
            print(f"    文件系统修改时间: {fs_mtime}")
            print(f"    元数据修改时间: {meta_mtime}")
            
            if meta_mtime and fs_mtime != meta_mtime:
                print(f"    ⚠️  时间不一致，差值: {abs(fs_mtime - meta_mtime)} 秒")
            else:
                print(f"    ✅ 时间一致")
                
        except Exception as e:
            print(f"    ❌ 检查文件时间失败: {e}")


def simulate_sync_behavior():
    """模拟同步行为"""
    work_dir = Path("/mnt/share/n8ndata/feishufiles")
    store = MetadataStore(work_dir)
    
    print("\n🔄 模拟同步行为:")
    
    # 获取一些token进行测试
    tokens = list(store.tokens())[:5]
    
    for token in tokens:
        entry = store.get(token)
        if not entry:
            continue
            
        print(f"\n  Token: {token}")
        print(f"    名称: {entry.get('name')}")
        print(f"    类型: {entry.get('file_type')}")
        print(f"    状态: {entry.get('status')}")
        
        # 检查文件是否存在
        try:
            path = store.resolve_path(entry)
            exists = path.exists()
            print(f"    文件存在: {exists}")
        except Exception as e:
            print(f"    检查文件存在性失败: {e}")


if __name__ == "__main__":
    print("=" * 60)
    print("调试增量下载行为不一致问题")
    print("=" * 60)
    
    analyze_metadata_behavior()
    check_file_modification_times()
    simulate_sync_behavior()
    
    print("\n" + "=" * 60)
    print("分析完成")
    print("=" * 60)
