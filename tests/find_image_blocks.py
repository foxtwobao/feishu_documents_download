"""查找文档中所有的image blocks并分析"""

import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from larksync.config import load_config
from larksync.core.api_client import FeishuAPIClient

# 从日志中提取的失败token（前20个）
FAILED_400_TOKENS = set([
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
    "PDanbTIS1oQZdSxT1TQcp3NQh",
    "RqQ2b8obcoLKpaxjANMczEAenog",
    "FZsSbLkkQo4fkCxOCbEc35o9nOh",
    "I9nMbaCCaoW7LAx0CNJcj1APnmc",
    "NWb5biZDNoFgJXxzoqzchbHonff",
    "Sr9PboqfQoGC7wxk2yGcrnNpnCh",
    "NxXLbI288o8xkyxkbewcR4X4nFg",
    "IXsqboT2Go4OfLxYfzWcXETtnrh",
])

BLOCK_TYPE_NAMES = {
    "1": "page",
    "2": "paragraph",
    "27": "image",
    "43": "whiteboard",
    "24": "grid",
    "25": "grid_column",
}


def find_all_image_tokens(block):
    """递归查找block中所有的image/media token"""
    tokens = []
    
    def extract_from_dict(d, path=""):
        if not isinstance(d, dict):
            return
        
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key
            
            # 检查常见的token字段
            if key in ["token", "file_token", "image_token", "media_token"]:
                if isinstance(value, str) and len(value) > 10:
                    tokens.append({
                        "token": value,
                        "path": current_path,
                        "parent_key": key,
                    })
            
            # 递归处理
            if isinstance(value, dict):
                extract_from_dict(value, current_path)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        extract_from_dict(item, f"{current_path}[{i}]")
    
    extract_from_dict(block)
    return tokens


def analyze():
    """分析文档中的image blocks"""
    
    config_path = Path(__file__).parent.parent / "config.toml"
    config = load_config(config_path)
    client = FeishuAPIClient.from_config(config)
    
    doc_token = "FUQOdprnboHVHMxEhbkc0clhn3e"
    
    print("=" * 80)
    print("分析文档中的图片token")
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
    
    # 统计block类型
    block_types = Counter()
    image_blocks = []
    all_tokens = []
    matched_400_tokens = []
    
    for block in blocks:
        block_type = str(block.get("block_type", ""))
        block_type_name = BLOCK_TYPE_NAMES.get(block_type, f"type_{block_type}")
        block_types[block_type_name] += 1
        
        # 查找所有token
        tokens = find_all_image_tokens(block)
        
        for token_info in tokens:
            token = token_info["token"]
            all_tokens.append({
                "token": token,
                "block_type": block_type_name,
                "block_id": block.get("block_id"),
                "path": token_info["path"],
                **token_info,
            })
            
            # 检查是否是失败的token
            if token in FAILED_400_TOKENS:
                matched_400_tokens.append({
                    "token": token,
                    "block_type": block_type_name,
                    "block_id": block.get("block_id"),
                    "path": token_info["path"],
                    "block": block,
                })
        
        # 专门查找image block
        if block_type == "27":
            image_blocks.append(block)
    
    print("📊 Block类型统计:")
    for block_type, count in block_types.most_common(15):
        print(f"  {block_type}: {count}")
    print()
    
    print(f"🖼️  Image blocks: {len(image_blocks)}")
    print(f"🔗 总共找到 {len(all_tokens)} 个token")
    print()
    
    # 显示失败token的匹配结果
    print("=" * 80)
    print("🔍 400 Bad Request Token匹配结果")
    print("=" * 80)
    print()
    
    if matched_400_tokens:
        print(f"✅ 匹配到 {len(matched_400_tokens)} 个失败token")
        print()
        
        # 按block类型统计
        block_type_stats = Counter()
        path_stats = Counter()
        for item in matched_400_tokens:
            block_type_stats[item["block_type"]] += 1
            path_stats[item["path"]] += 1
        
        print("📊 按Block类型统计:")
        for block_type, count in block_type_stats.most_common():
            print(f"  {block_type}: {count} 个")
        print()
        
        print("📊 按Token路径统计:")
        for path, count in path_stats.most_common():
            print(f"  {path}: {count} 个")
        print()
        
        print("📝 详细示例（前5个）:")
        for i, item in enumerate(matched_400_tokens[:5], 1):
            print(f"\n  [{i}] Token: {item['token']}")
            print(f"      Block类型: {item['block_type']}")
            print(f"      Block ID: {item['block_id']}")
            print(f"      Token路径: {item['path']}")
            
            # 显示block部分内容
            if item['block_type'] == 'image':
                image_data = item['block'].get('image', {})
                print(f"      Image信息:")
                print(f"        - token: {image_data.get('token', 'N/A')}")
                print(f"        - width: {image_data.get('width', 'N/A')}")
                print(f"        - height: {image_data.get('height', 'N/A')}")
    else:
        print("⚠️  未匹配到任何失败token")
        print()
        print("📋 所有token示例（前10个）:")
        for i, item in enumerate(all_tokens[:10], 1):
            print(f"  [{i}] {item['token'][:30]}... - {item['block_type']} - {item['path']}")
    
    print()
    print("=" * 80)
    
    # 保存详细结果
    output = {
        "total_blocks": len(blocks),
        "block_types": dict(block_types),
        "total_tokens": len(all_tokens),
        "matched_400_count": len(matched_400_tokens),
        "matched_400_tokens": matched_400_tokens,
        "sample_tokens": all_tokens[:50],
    }
    
    output_file = Path("/tmp/image_token_analysis.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    
    print(f"✅ 详细结果已保存到: {output_file}")


if __name__ == "__main__":
    try:
        analyze()
    except Exception as e:
        print(f"❌ 分析失败: {e}")
        import traceback
        traceback.print_exc()
