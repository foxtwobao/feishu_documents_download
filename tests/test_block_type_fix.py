"""测试Block类型识别修复"""

from larksync.core.parsers.docx_parser import DocxMarkdownParser


def test_chatcard_identification_fix():
    """测试ChatCard识别修复"""
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
    if block_type == "chat_card":
        print("✅ 正确：ChatCard被正确识别")
        return True
    elif block_type == "20":
        print("✅ 部分正确：返回原始type 20（在别名表中）")
        return True
    elif block_type == "image":
        print("❌ 错误：ChatCard被误判为Image！")
        return False
    else:
        print(f"⚠️  未预期：被识别为 {block_type}")
        return False


def test_diagram_identification():
    """测试Diagram识别"""
    parser = DocxMarkdownParser()
    
    diagram_block = {
        "block_type": 21,
        "block_id": "test_diagram_block",
        "diagram": {
            "diagram_type": "flowchart"
        }
    }
    
    block_type = parser._normalise_block_type(diagram_block)
    
    print(f"Diagram Block (type 21) 被识别为: {block_type}")
    
    if block_type == "diagram":
        print("✅ 正确：Diagram被正确识别")
        return True
    elif block_type == "21":
        print("✅ 部分正确：返回原始type 21")
        return True
    else:
        print(f"❌ 错误：被识别为 {block_type}")
        return False


def test_bitable_identification():
    """测试Bitable识别"""
    parser = DocxMarkdownParser()
    
    bitable_block = {
        "block_type": 18,
        "block_id": "test_bitable_block",
        "bitable": {
            "token": "bitable_token_xxx"
        }
    }
    
    block_type = parser._normalise_block_type(bitable_block)
    
    print(f"Bitable Block (type 18) 被识别为: {block_type}")
    
    if block_type == "bitable":
        print("✅ 正确：Bitable被正确识别")
        return True
    elif block_type == "18":
        print("✅ 部分正确：返回原始type 18")
        return True
    else:
        print(f"❌ 错误：被识别为 {block_type}")
        return False


def test_payload_inference_still_works():
    """测试payload推断仍然在block_type缺失时工作"""
    parser = DocxMarkdownParser()
    
    # 模拟block_type缺失的情况
    block_no_type = {
        "block_id": "test_no_type",
        "image": {  # 顶层直接有image字段
            "token": "some_token"
        }
    }
    
    block_type = parser._normalise_block_type(block_no_type)
    
    print(f"无block_type，但有image字段 被识别为: {block_type}")
    
    if block_type == "image":
        print("✅ 正确：Payload推断仍然工作")
        return True
    else:
        print(f"❌ 错误：被识别为 {block_type}")
        return False


def test_all_new_block_types_in_aliases():
    """测试所有新添加的Block类型都在别名表中"""
    parser = DocxMarkdownParser()
    
    # 测试一些关键的新类型
    test_cases = [
        (20, "chat_card"),
        (21, "diagram"),
        (18, "bitable"),
        (30, "sheet"),
        (29, "mindnote"),
        (19, "callout"),
        (26, "iframe"),
    ]
    
    all_passed = True
    for block_type, expected_alias in test_cases:
        alias = parser._BLOCK_TYPE_ALIASES.get(str(block_type))
        if alias == expected_alias:
            print(f"✅ Block type {block_type} -> {alias}")
        else:
            print(f"❌ Block type {block_type} 期望 {expected_alias}，实际 {alias}")
            all_passed = False
    
    return all_passed


if __name__ == "__main__":
    print("=" * 80)
    print("测试Block类型识别修复")
    print("=" * 80)
    print()
    
    results = []
    
    print("1️⃣  测试ChatCard识别修复")
    print("-" * 80)
    results.append(("ChatCard识别", test_chatcard_identification_fix()))
    print()
    
    print("2️⃣  测试Diagram识别")
    print("-" * 80)
    results.append(("Diagram识别", test_diagram_identification()))
    print()
    
    print("3️⃣  测试Bitable识别")
    print("-" * 80)
    results.append(("Bitable识别", test_bitable_identification()))
    print()
    
    print("4️⃣  测试payload推断仍然工作")
    print("-" * 80)
    results.append(("Payload推断", test_payload_inference_still_works()))
    print()
    
    print("5️⃣  测试所有新Block类型在别名表中")
    print("-" * 80)
    results.append(("别名表完整性", test_all_new_block_types_in_aliases()))
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
        print("🎉 所有测试通过！修复成功！")
    else:
        print("⚠️  存在问题，需要进一步修复")
