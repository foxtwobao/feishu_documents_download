import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from larksync.config import load_config
from larksync.core.api_client import FeishuAPIClient

config = load_config(Path(__file__).parent.parent / "config.toml")
client = FeishuAPIClient.from_config(config)

# 获取blocks  
response = client.get("/open-apis/docx/v1/documents/FUQOdprnboHVHMxEhbkc0clhn3e/blocks", params={"page_size": 50})
blocks = response.get("data", {}).get("items", [])

print(f"获取到 {len(blocks)} 个blocks\n")

# 找几个不同类型的block
image_count = 0
para_count = 0

for block in blocks:
    block_type = str(block.get("block_type"))
    
    # 找paragraph
    if block_type == "2" and para_count < 2:
        para_count += 1
        print(f"=== Paragraph #{para_count} ===")
        print(f"Block ID: {block.get('block_id')}")
        print(f"Keys: {list(block.keys())}")
        if "paragraph" in block:
            para_data = block["paragraph"]
            print(f"Paragraph keys: {list(para_data.keys())}")
        print()
    
    # 找image block
    if block_type == "27" and image_count < 3:
        image_count += 1
        print(f"=== Image Block #{image_count} ===")
        print(f"Block ID: {block.get('block_id')}")
        print(json.dumps(block, ensure_ascii=False, indent=2))
        print()

print(f"\n✅ 完成")
