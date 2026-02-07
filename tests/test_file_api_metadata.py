"""测试file类型从飞书API获取的元数据"""

import os
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from larksync.config import load_config
from larksync.core.api_client import FeishuAPIClient
from larksync.core.adapters.drive_adapter import DriveAdapter


def test_file_metadata_from_real_api():
    """测试从真实API获取file元数据"""
    
    # 检查配置文件
    config_path = Path(__file__).parent.parent / "config.toml"
    if not config_path.exists():
        print("⚠️  配置文件不存在，跳过真实API测试")
        return
    
    try:
        config = load_config(config_path)
        client = FeishuAPIClient.from_config(config)
        drive = DriveAdapter(client)
        
        print("=" * 60)
        print("获取根文件夹列表并检查file类型的元数据字段")
        print("=" * 60)
        print()
        
        # 获取根文件夹
        root_meta = drive.get_root_folder_meta()
        root_token = root_meta.get("data", {}).get("token")
        
        if not root_token:
            print("❌ 无法获取根文件夹token")
            return
        
        print(f"✅ 根文件夹token: {root_token}")
        print()
        
        # 列出文件
        payload = drive.list_folder_children(root_token, page_size=20)
        data = payload.get("data", {})
        files = data.get("files", [])
        
        print(f"获取到 {len(files)} 个文件/文件夹")
        print()
        
        # 查找file类型的条目
        file_items = [f for f in files if f.get("type") == "file"]
        
        if not file_items:
            print("⚠️  未找到file类型的条目，尝试查看所有类型...")
            print()
            for item in files[:5]:
                print(f"类型: {item.get('type')}, 名称: {item.get('name')}")
        else:
            print(f"找到 {len(file_items)} 个file类型条目")
            print()
            
            # 分析第一个file的元数据
            for i, file_item in enumerate(file_items[:3], 1):
                print(f"--- File #{i} ---")
                print(f"名称: {file_item.get('name')}")
                print(f"token: {file_item.get('token')}")
                print(f"类型: {file_item.get('type')}")
                
                # 检查时间字段
                print("\n时间字段:")
                for time_field in ['modified_time', 'latest_modify_time', 'update_time', 'modify_time', 'created_time']:
                    if time_field in file_item:
                        print(f"  {time_field}: {file_item[time_field]}")
                
                # 检查版本/校验字段
                print("\n版本/校验字段:")
                for meta_field in ['revision', 'rev', 'checksum', 'sha256', 'md5']:
                    if meta_field in file_item:
                        print(f"  {meta_field}: {file_item[meta_field]}")
                
                # 显示所有字段
                print("\n所有字段:")
                for key in sorted(file_item.keys()):
                    value = file_item[key]
                    if len(str(value)) > 100:
                        value = str(value)[:100] + "..."
                    print(f"  {key}: {value}")
                print()
        
        print("=" * 60)
        print("分析完成")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    test_file_metadata_from_real_api()
