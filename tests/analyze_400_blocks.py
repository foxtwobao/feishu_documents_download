"""分析哪些block类型导致400 Bad Request错误"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from larksync.config import load_config
from larksync.core.api_client import FeishuAPIClient

# 从日志中提取的失败token列表
FAILED_400_TOKENS = [
    "DXkzboljookfIbx6pSzcDHYKnVg",
    "AAn5bjCM4oZmoVx7njIcORYHnEg",
    "Plf0bBSckor8QaxLmxNcq0JfnOc",
    "EIgNbD10Vo5AcoxNlLVcWJsznTg",
    "VDBIbymvwoQyf4x5oPlczL5An5f",
    "Ri56bJduvofducx2tddcPQlMnSg",
    "Hb9DbHw71ouB7DxKMkWcNgt6nzd",
    "ZWaWbJ9TAoxjVOxShutcsffsn1f",
    "OEwDbHe96oM2Hcxdcu6c7ta8nKc",
    "NEVwbgm6OodX9WxlOQycTeEanHf",
    "Kdgcb8MtjocPN1xpEfYcV5gYnVf",
    "JCnSbGM4QoHIDwxABULcUK6Jnff",
    "OgqZbrIBnoh2lUx20n2ch6mMntb",
    "RqQ2b8obcoLKpaxjANMczEAenog",
    "FZsSbLkkQo4fkCxOCbEc35o9nOh",
    "I9nMbaCCaoW7LAx0CNJcj1APnmc",
    "NWb5biZDNoFgJXxzoqzchbHonff",
    "Sr9PboqfQoGC7wxk2yGcrnNpnCh",
    "NxXLbI288o8xkyxkbewcR4X4nFg",
    "IXsqboT2Go4OfLxYfzWcXETtnrh",
]

FAILED_403_TOKENS = [
    # 从之前的日志添加
    "OgqZbrIBnoh2lUx20n2ch6mMntb",
    "JCnSbGM4QoHIDwxABULcUK6Jnff",
]

BLOCK_TYPE_NAMES = {
    "1": "page",
    "2": "paragraph",
    "3": "heading1",
    "4": "heading2",
    "5": "heading3",
    "6": "heading4",
    "7": "heading5",
    "8": "heading6",
    "12": "bullet",
    "13": "ordered",
    "14": "code",
    "15": "quote",
    "17": "todo",
    "22": "divider",
    "23": "file",
    "24": "grid",
    "25": "grid_column",
    "27": "image",
    "31": "table",
    "32": "table_cell",
    "33": "view",
    "34": "quote_container",
    "43": "whiteboard",
}


def analyze_blocks():
    """分析文档blocks，找出400错误对应的block类型"""
    
    config_path = Path(__file__).parent.parent / "config.toml"
    config = load_config(config_path)
    client = FeishuAPIClient.from_config(config)
    
    doc_token = "FUQOdprnboHVHMxEhbkc0clhn3e"
    
    print("=" * 80)
    print("获取文档blocks信息...")
    print("=" * 80)
    print()
    
    # 获取所有blocks
    blocks = []
    page_token = None
    
    while True:
        params = {"page_size": 200}
        if page_token:
            params["page_token"] = page_token
        
        response = client.get(f"/open-apis/docx/v1/documents/{doc_token}/blocks", params=params)
        data = response.get("data", {})
        
        items = data.get("items", [])
        blocks.extend(items)
        
        if not data.get("has_more"):
            break
        
        page_token = data.get("page_token")
    
    print(f"✅ 获取到 {len(blocks)} 个blocks")
    print()
    
    # 分析blocks，查找包含失败token的block
    failed_blocks_400 = []
    failed_blocks_403 = []
    block_type_stats = {}
    
    for block in blocks:
        block_type = str(block.get("block_type", "unknown"))
        block_type_name = BLOCK_TYPE_NAMES.get(block_type, f"type_{block_type}")
        block_id = block.get("block_id", "")
        
        # 检查block中的所有字段，查找media token
        block_str = json.dumps(block)
        
        for token in FAILED_400_TOKENS:
            if token in block_str:
                failed_blocks_400.append({
                    "block_id": block_id,
                    "block_type": block_type,
                    "block_type_name": block_type_name,
                    "token": token,
                    "block": block,
                })
                
                # 统计
                key = f"{block_type_name} (type {block_type})"
                block_type_stats[key] = block_type_stats.get(key, 0) + 1
        
        for token in FAILED_403_TOKENS:
            if token in block_str:
                failed_blocks_403.append({
                    "block_id": block_id,
                    "block_type": block_type,
                    "block_type_name": block_type_name,
                    "token": token,
                    "block": block,
                })
    
    # 输出分析结果
    print("=" * 80)
    print("🔍 400 Bad Request 错误分析")
    print("=" * 80)
    print()
    
    if failed_blocks_400:
        print(f"找到 {len(failed_blocks_400)} 个导致400错误的block")
        print()
        
        print("📊 按block类型统计:")
        for block_type, count in sorted(block_type_stats.items(), key=lambda x: -x[1]):
            print(f"  {block_type}: {count} 个")
        print()
        
        print("📝 详细信息（前10个）:")
        for i, info in enumerate(failed_blocks_400[:10], 1):
            print(f"\n  [{i}] Block类型: {info['block_type_name']} (type {info['block_type']})")
            print(f"      Block ID: {info['block_id']}")
            print(f"      失败Token: {info['token']}")
            
            # 提取关键字段
            block = info['block']
            if info['block_type'] == "27":  # image block
                image_data = block.get("image", {})
                print(f"      Image Token: {image_data.get('token', 'N/A')}")
                print(f"      Width: {image_data.get('width', 'N/A')}")
                print(f"      Height: {image_data.get('height', 'N/A')}")
            elif info['block_type'] == "2":  # paragraph with inline image
                elements = block.get("paragraph", {}).get("elements", [])
                for elem in elements:
                    if "inline_file" in elem:
                        file_data = elem.get("inline_file", {})
                        print(f"      Inline File Token: {file_data.get('file_token', 'N/A')}")
                        print(f"      Source Block ID: {file_data.get('source_block_id', 'N/A')}")
    else:
        print("⚠️  未找到匹配的block（可能token在嵌套字段中）")
    
    print()
    print("=" * 80)
    print("🔍 403 Forbidden 错误分析")
    print("=" * 80)
    print()
    
    if failed_blocks_403:
        print(f"找到 {len(failed_blocks_403)} 个导致403错误的block")
        for i, info in enumerate(failed_blocks_403[:5], 1):
            print(f"\n  [{i}] Block类型: {info['block_type_name']} (type {info['block_type']})")
            print(f"      Block ID: {info['block_id']}")
            print(f"      失败Token: {info['token']}")
    else:
        print("⚠️  未找到匹配的block")
    
    print()
    print("=" * 80)
    
    # 保存完整分析结果
    output_file = Path("/tmp/block_analysis_400.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump({
            "total_blocks": len(blocks),
            "failed_400_count": len(failed_blocks_400),
            "failed_403_count": len(failed_blocks_403),
            "block_type_stats": block_type_stats,
            "failed_blocks_400": failed_blocks_400,
            "failed_blocks_403": failed_blocks_403,
        }, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 完整分析结果已保存到: {output_file}")
    print()


if __name__ == "__main__":
    try:
        analyze_blocks()
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
