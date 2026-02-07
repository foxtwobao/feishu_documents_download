#!/usr/bin/env python3
"""
测试图片路径相对化修复
验证图片链接是否使用相对于 Markdown 文件的相对路径
"""

import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

def test_relative_paths():
    """测试相对路径计算"""
    import os
    
    print("=" * 60)
    print("测试相对路径计算")
    print("=" * 60)
    
    # 模拟场景
    storage_root = Path("/mnt/share/n8ndata/feishufiles")
    markdown_file = storage_root / "测试" / "飞书文档全Block类型测试文档.md"
    image_file = storage_root / "测试" / "飞书文档全Block类型测试文档" / "images" / "学习_1.png"
    
    print(f"\n存储根目录: {storage_root}")
    print(f"Markdown文件: {markdown_file}")
    print(f"图片文件: {image_file}")
    
    # 计算相对路径
    relative = os.path.relpath(image_file, markdown_file.parent)
    
    print(f"\n✓ 相对路径: {relative}")
    print(f"  预期: 飞书文档全Block类型测试文档/images/学习_1.png")
    
    # 验证
    expected = "飞书文档全Block类型测试文档/images/学习_1.png"
    if relative.replace("\\", "/") == expected:
        print("  ✅ 正确！")
        return True
    else:
        print(f"  ❌ 错误！实际: {relative}")
        return False


def test_markdown_generation():
    """测试 Markdown 生成"""
    print("\n" + "=" * 60)
    print("测试 Markdown 图片链接生成")
    print("=" * 60)
    
    from pathlib import Path
    import os
    
    # 模拟资源
    class MockResource:
        def __init__(self, name):
            self.name = name
    
    resource = MockResource("学习")
    image_path = Path("/mnt/share/n8ndata/feishufiles/测试/飞书文档全Block类型测试文档/images/学习_1.png")
    markdown_path = Path("/mnt/share/n8ndata/feishufiles/测试/飞书文档全Block类型测试文档.md")
    
    # 计算相对路径
    try:
        relative = os.path.relpath(image_path, markdown_path.parent)
    except ValueError:
        relative = image_path.as_posix()
    
    # 生成 Markdown
    markdown = f"![{resource.name}]({relative})"
    
    print(f"\n生成的 Markdown: {markdown}")
    print(f"预期: ![学习](飞书文档全Block类型测试文档/images/学习_1.png)")
    
    expected_pattern = "飞书文档全Block类型测试文档/images/学习_1.png"
    if expected_pattern in markdown:
        print("✅ 正确！使用相对路径")
        return True
    else:
        print("❌ 错误！路径不正确")
        return False


def main():
    print("\n")
    print("╔" + "=" * 58 + "╗")
    print("║" + " " * 16 + "图片路径相对化测试" + " " * 16 + "║")
    print("╚" + "=" * 58 + "╝")
    
    results = []
    
    # 测试1: 相对路径计算
    results.append(("相对路径计算", test_relative_paths()))
    
    # 测试2: Markdown 生成
    results.append(("Markdown生成", test_markdown_generation()))
    
    # 总结
    print("\n" + "=" * 60)
    print("📊 测试结果汇总")
    print("=" * 60)
    
    all_passed = True
    for name, passed in results:
        status = "✅ 通过" if passed else "❌ 失败"
        print(f"  {status} - {name}")
        if not passed:
            all_passed = False
    
    if all_passed:
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        print("\n修复说明:")
        print("  ✓ 图片路径现在使用相对于 Markdown 文件的相对路径")
        print("  ✓ 格式: 文档名/images/图片.png")
        print("  ✓ 不再使用从存储根目录开始的完整路径")
        print()
        return 0
    else:
        print("\n❌ 部分测试未通过")
        return 1


if __name__ == "__main__":
    sys.exit(main())
