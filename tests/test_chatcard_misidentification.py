"""测试ChatCard被误判为Image的问题"""

from larksync.core.parsers.docx_parser import DocxMarkdownParser


def test_chatcard_should_not_be_identified_as_image():
    """测试ChatCard不应该被误判为Image"""
    
    parser = DocxMarkdownParser()
    
    # 模拟ChatCard block (type 20)
    chatcard_block = {
        "block_type": 20,
        "block_id": "test_chatcard_block",
        "chat_card": {
            "chat_id": "oc_xxx",
            "title": "测试会话",
            "image": {  # ChatCard中包含image字段
                "token": "chat_image_token_xxx",
                "url": "https://example.com/chat_image.png"
            },
            "description": "这是一个会话卡片"
        }
    }
    
    # 标准化block类型
    block_type = parser._normalise_block_type(chatcard_block)
    
    print(f"ChatCard Block (type 20) 被识别为: {block_type}")
    
    # 验证
    if block_type == "image":
        print("❌ 错误：ChatCard被误判为Image！")
        print("   这会导致尝试下载 chat_image_token_xxx")
        print("   可能返回400 Bad Request错误")
        return False
    elif block_type == "chat_card":
        print("✅ 正确：ChatCard被正确识别")
        return True
    elif block_type == "20":
        print("⚠️  部分正确：返回原始type 20（触发fallback）")
        print("   虽然不会误判为image，但没有专门处理")
        return True
    else:
        print(f"⚠️  未预期：被识别为 {block_type}")
        return False


def test_image_block_correct_identification():
    """测试真正的Image block能正确识别"""
    
    parser = DocxMarkdownParser()
    
    # 真正的Image block (type 27)
    image_block = {
        "block_type": 27,
        "block_id": "test_image_block",
        "image": {
            "token": "real_image_token_xxx",
            "width": 1024,
            "height": 768
        }
    }
    
    block_type = parser._normalise_block_type(image_block)
    
    print(f"Image Block (type 27) 被识别为: {block_type}")
    
    if block_type == "image":
        print("✅ 正确：Image被正确识别")
        return True
    else:
        print(f"❌ 错误：Image被识别为 {block_type}")
        return False


def test_diagram_should_not_be_image():
    """测试Diagram (type 21) 不应被误判为Image"""
    
    parser = DocxMarkdownParser()
    
    # Diagram block可能也包含image字段
    diagram_block = {
        "block_type": 21,
        "block_id": "test_diagram_block",
        "diagram": {
            "diagram_type": "flowchart",
            "image": {  # Diagram导出的图片
                "token": "diagram_image_token_xxx"
            }
        }
    }
    
    block_type = parser._normalise_block_type(diagram_block)
    
    print(f"Diagram Block (type 21) 被识别为: {block_type}")
    
    if block_type == "image":
        print("❌ 错误：Diagram被误判为Image！")
        return False
    elif block_type in ["diagram", "21"]:
        print("✅ 正确：Diagram未被误判")
        return True
    else:
        print(f"⚠️  被识别为: {block_type}")
        return False


def test_bitable_should_not_be_table():
    """测试Bitable (type 18) 不应被误判为Table"""
    
    parser = DocxMarkdownParser()
    
    # Bitable可能包含table字段
    bitable_block = {
        "block_type": 18,
        "block_id": "test_bitable_block",
        "bitable": {
            "token": "bitable_token_xxx",
            "table": {  # Bitable内部的表格结构
                "rows": []
            }
        }
    }
    
    block_type = parser._normalise_block_type(bitable_block)
    
    print(f"Bitable Block (type 18) 被识别为: {block_type}")
    
    if block_type == "table":
        print("❌ 错误：Bitable被误判为Table！")
        return False
    elif block_type in ["bitable", "18"]:
        print("✅ 正确：Bitable未被误判")
        return True
    else:
        print(f"⚠️  被识别为: {block_type}")
        return False


def test_unknown_type_with_image_field():
    """测试未知类型包含image字段的情况"""
    
    parser = DocxMarkdownParser()
    
    # 模拟一个未知类型（比如未来新增的type）
    unknown_block = {
        "block_type": 99,  # 假设的未来类型
        "block_id": "test_unknown_block",
        "unknown_data": {
            "image": {
                "token": "unknown_image_token"
            }
        }
    }
    
    block_type = parser._normalise_block_type(unknown_block)
    
    print(f"Unknown Block (type 99) 被识别为: {block_type}")
    
    if block_type == "image":
        print("❌ 危险：未知类型被误判为Image！")
        print("   这是payload推断的副作用")
        return False
    elif block_type == "99":
        print("✅ 安全：返回原始type，触发fallback")
        return True
    else:
        print(f"⚠️  被识别为: {block_type}")
        return False


if __name__ == "__main__":
    print("=" * 80)
    print("测试Block类型误判问题")
    print("=" * 80)
    print()
    
    results = []
    
    print("1️⃣  测试ChatCard (type 20)")
    print("-" * 80)
    results.append(("ChatCard", test_chatcard_should_not_be_identified_as_image()))
    print()
    
    print("2️⃣  测试Image (type 27)")
    print("-" * 80)
    results.append(("Image", test_image_block_correct_identification()))
    print()
    
    print("3️⃣  测试Diagram (type 21)")
    print("-" * 80)
    results.append(("Diagram", test_diagram_should_not_be_image()))
    print()
    
    print("4️⃣  测试Bitable (type 18)")
    print("-" * 80)
    results.append(("Bitable", test_bitable_should_not_be_table()))
    print()
    
    print("5️⃣  测试未知类型")
    print("-" * 80)
    results.append(("Unknown", test_unknown_type_with_image_field()))
    print()
    
    # 总结
    print("=" * 80)
    print("测试总结")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status} - {name}")
    
    print()
    print(f"总计: {passed}/{total} 通过")
    
    if passed == total:
        print("🎉 所有测试通过！")
    else:
        print("⚠️  存在误判问题，需要修复")
        print()
        print("📝 建议：")
        print("  1. 补全 _BLOCK_TYPE_ALIASES 表，添加所有官方Block类型")
        print("  2. 在payload推断前检查block_type是否存在")
        print("  3. 为ChatCard等类型添加专门的处理逻辑")
