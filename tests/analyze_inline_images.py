"""分析paragraph中的inline images"""

import json
import sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent.parent))

from larksync.config import load_config
from larksync.core.api_client import FeishuAPIClient

# 从日志中提取的失败token
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
    "DBNjbX7aToyRjmxP9qKc4AS2nKg",  # image block
])


def analyze():
    """分析paragraph中的inline images"""
    
    config_path = Path(__file__).parent.parent / "config.toml"
    config = load_config(config_path)
    client = FeishuAPIClient.from_config(config)
    
    doc_token = "FUQOdprnboHVHMxEhbkc0clhn3e"
    
    print("=" * 80)
    print("分析Paragraph中的Inline Images")
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
    
    # 查找paragraph blocks并分析elements
    paragraph_blocks = []
    inline_images = []
    matched_400 = []
    element_types = Counter()
    
    for block in blocks:
        block_type = str(block.get("block_type", ""))
        
        if block_type in ["2", "paragraph"]:  # paragraph
            paragraph_blocks.append(block)
            
            # 提取paragraph中的elements
            paragraph_data = block.get("paragraph", {})
            elements = paragraph_data.get("elements", [])
            
            for elem_idx, elem in enumerate(elements):
                # 统计element类型
                for key in elem.keys():
                    element_types[key] += 1
                
                # 查找inline image
                if "image" in elem:
                    image_data = elem.get("image", {})
                    token = image_data.get("token") or image_data.get("image_token")
                    block_id = image_data.get("block_id") or image_data.get("image_id")
                    
                    inline_image_info = {
                        "token": token,
                        "block_id": block_id,
                        "parent_block_id": block.get("block_id"),
                        "element_index": elem_idx,
                        "image_data": image_data,
                    }
                    inline_images.append(inline_image_info)
                    
                    # 检查是否是失败的token
                    if token in FAILED_400_TOKENS:
                        matched_400.append(inline_image_info)
    
    print(f"📄 Paragraph blocks: {len(paragraph_blocks)}")
    print(f"🖼️  Inline images找到: {len(inline_images)}")
    print()
    
    print("📊 Paragraph Element类型统计:")
    for elem_type, count in element_types.most_common(15):
        print(f"  {elem_type}: {count}")
    print()
    
    if inline_images:
        print("=" * 80)
        print("🖼️  Inline Images详情（前10个）")
        print("=" * 80)
        print()
        
        for i, img in enumerate(inline_images[:10], 1):
            print(f"[{i}] Token: {img['token']}")
            print(f"    Block ID: {img['block_id']}")
            print(f"    Parent Block: {img['parent_block_id']}")
            print(f"    Element Index: {img['element_index']}")
            
            # 检查是否失败
            if img['token'] in FAILED_400_TOKENS:
                print(f"    ❌ 400 Bad Request")
            
            # 显示image_data
            image_data = img['image_data']
            print(f"    Image Data Keys: {list(image_data.keys())}")
            print()
    
    # 匹配400错误
    print("=" * 80)
    print("🔍 400 Bad Request匹配结果")
    print("=" * 80)
    print()
    
    if matched_400:
        print(f"✅ 在paragraph inline images中找到 {len(matched_400)} 个失败token")
        print()
        
        for i, img in enumerate(matched_400, 1):
            print(f"[{i}] Token: {img['token']}")
            print(f"    Parent Block: {img['parent_block_id']}")
            print(f"    Image Data: {json.dumps(img['image_data'], ensure_ascii=False, indent=6)}")
            print()
    else:
        print("⚠️  未在paragraph inline images中找到失败token")
        print()
        print("💡 失败token可能来自:")
        print("  1. Image blocks (独立的图片block)")
        print("  2. Whiteboard中的图片")
        print("  3. Table中的图片")
        print("  4. 其他嵌套结构")
    
    print()
    print("=" * 80)
    
    # 保存结果
    output = {
        "paragraph_count": len(paragraph_blocks),
        "inline_image_count": len(inline_images),
        "matched_400_count": len(matched_400),
        "element_types": dict(element_types),
        "inline_images": inline_images[:30],
        "matched_400": matched_400,
    }
    
    output_file = Path("/tmp/inline_image_analysis.json")
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
