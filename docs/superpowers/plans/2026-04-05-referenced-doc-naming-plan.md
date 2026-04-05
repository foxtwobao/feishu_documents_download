# 引用文档命名优化实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 引用文档下载后使用 `{sanitized_title}_{token}.{ext}` 命名，提升可读性

**Architecture:** 修改 `_reference_output_filename()` 和 `_resolve_reference_output()` 两个方法，使引用文档使用标题+token命名，保留原去重逻辑

**Tech Stack:** Python 3.11+, pytest

---

## 文件结构

- 修改: `larksync/core/downloaders/docx_downloader.py`
- 修改: `tests/test_docx_downloader.py`

---

## Task 1: 修改 `_reference_output_filename()` 签名和实现

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py:905-910`

- [ ] **Step 1: 写测试**

```python
def test_reference_output_filename_with_title_and_token():
    """引用文档输出文件名应为 {safe_name}_{token}.{ext}"""
    from larksync.core.downloaders.docx_downloader import DocxDownloader

    # DocX: "产品文档" + "abc12345" -> "产品文档_abc12345.md"
    result = DocxDownloader._reference_output_filename("docx", "产品文档", "abc12345")
    assert result == "产品文档_abc12345.md"

    # Sheet: "数据表" + "xyz98765" -> "数据表_xyz98765.xlsx"
    result = DocxDownloader._reference_output_filename("sheet", "数据表", "xyz98765")
    assert result == "数据表_xyz98765.xlsx"

    # Bitable: "数据库" + "bit98765" -> "数据库_bit98765.xlsx"
    result = DocxDownloader._reference_output_filename("bitable", "数据库", "bit98765")
    assert result == "数据库_bit98765.xlsx"

    # File 类型返回 None，由 FileDownloader 处理原始文件名
    result = DocxDownloader._reference_output_filename("file", "原始文件", "abc12345")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docx_downloader.py::test_reference_output_filename_with_title_and_token -v`
Expected: FAIL (method doesn't accept those arguments yet)

- [ ] **Step 3: 修改 `_reference_output_filename()` 方法签名和实现**

原方法 (line 905-910):
```python
@staticmethod
def _reference_output_filename(ref_type: str) -> Optional[str]:
    if ref_type == "file":
        return None
    if ref_type in {"sheet", "sheets", "bitable", "base"}:
        return "content.xlsx"
    return "content.md"
```

新实现:
```python
@staticmethod
def _reference_output_filename(ref_type: str, safe_name: str, token: str) -> Optional[str]:
    if ref_type == "file":
        # File 类型由 FileDownloader 通过 force_original_name 保留原始文件名
        return None
    if ref_type in {"sheet", "sheets", "bitable", "base"}:
        return f"{safe_name}_{token}.xlsx"
    return f"{safe_name}_{token}.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_docx_downloader.py::test_reference_output_filename_with_title_and_token -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add larksync/core/downloaders/docx_downloader.py tests/test_docx_downloader.py
git commit -m "refactor: 更新 _reference_output_filename 支持标题+token命名"
```

---

## Task 2: 更新调用处传入 `safe_name` 和 `token`

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py:796`

- [ ] **Step 1: 写测试**

```python
def test_reference_output_filename_called_with_name_and_token():
    """验证 _reference_output_filename 被传入正确的参数"""
    from larksync.core.downloaders.docx_downloader import DocxDownloader

    # 验证静态方法可以正确处理参数组合
    assert DocxDownloader._reference_output_filename("docx", "测试文档", "tok123") == "测试文档_tok123.md"
    assert DocxDownloader._reference_output_filename("sheet", "表格", "tok456") == "表格_tok456.xlsx"
    assert DocxDownloader._reference_output_filename("bitable", "数据库", "tok789") == "数据库_tok789.xlsx"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_docx_downloader.py::test_reference_output_filename_called_with_name_and_token -v`
Expected: PASS

- [ ] **Step 3: 更新调用处 (line 796)**

原代码:
```python
output_filename = self._reference_output_filename(ref_type)
```

新代码:
```python
output_filename = self._reference_output_filename(ref_type, safe_name, token)
```

- [ ] **Step 4: Run all docx downloader tests**

Run: `pytest tests/test_docx_downloader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add larksync/core/downloaders/docx_downloader.py
git commit -m "refactor: 传入 safe_name 和 token 到 _reference_output_filename"
```

---

## Task 3: 更新 `_resolve_reference_output()` 回退逻辑

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py:949-987`

- [ ] **Step 1: 写测试**

```python
def test_resolve_reference_output_uses_new_naming_pattern(tmp_path):
    """_resolve_reference_output 应该按新命名模式查找文件"""
    downloader = _build_downloader(tmp_path)

    # 模拟 docx 文档目录，文件按新命名
    doc_dir = tmp_path / "docx_token"
    doc_dir.mkdir()
    (doc_dir / "产品文档_abc12345.md").write_text("# Test")

    # 回退查找应能找到新命名的文件
    result = downloader._resolve_reference_output("docx", "abc12345", "产品文档", doc_dir)
    assert result is not None
    assert result.name == "产品文档_abc12345.md"

    # Sheet 类型
    sheet_dir = tmp_path / "sheet_token"
    sheet_dir.mkdir()
    (sheet_dir / "数据表_xyz98765.xlsx").write_bytes(b"xlsx content")

    result = downloader._resolve_reference_output("sheets", "xyz98765", "数据表", sheet_dir)
    assert result is not None
    assert result.name == "数据表_xyz98765.xlsx"

    # 向后兼容: 旧命名 content.md 仍能被找到
    old_doc_dir = tmp_path / "old_doc_token"
    old_doc_dir.mkdir()
    (old_doc_dir / "content.md").write_text("# Old Format")
    result = downloader._resolve_reference_output("docx", "old_doc_token", "旧文档", old_doc_dir)
    assert result is not None
    assert result.name == "content.md"

    # File 类型: 新命名 original_{token}.* 优先
    file_dir = tmp_path / "file_token"
    file_dir.mkdir()
    (file_dir / "original_file_token.pdf").write_bytes(b"pdf content")
    result = downloader._resolve_reference_output("file", "file_token", "原始文件", file_dir)
    assert result is not None
    assert "file_token" in result.name
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docx_downloader.py::test_resolve_reference_output_uses_new_naming_pattern -v`
Expected: FAIL (查找 `content.md` 而非新命名)

- [ ] **Step 3: 更新 `_resolve_reference_output()` 的文件查找逻辑**

原逻辑 (line 956-963):
```python
if ref_type == "file":
    candidates = sorted(target_dir.glob("original.*"))
elif ref_type in {"sheet", "sheets", "bitable", "base"}:
    candidates = [target_dir / "content.md", target_dir / "content.xlsx"]
elif ref_type in {"docx", "slides", "mindnote"}:
    candidates = [target_dir / "content.md"]
else:
    candidates = [target_dir / "content.md"]
```

新逻辑:
```python
if ref_type == "file":
    # 新命名: original_{token}.{ext}，兼容旧命名: original.*
    candidates = (
        sorted(target_dir.glob(f"original_{token}.*")) or
        sorted(target_dir.glob("original.*"))
    )
else:
    # 按新命名模式查找: {safe_name}_{token}.{ext}
    ext = "xlsx" if ref_type in {"sheet", "sheets", "bitable", "base"} else "md"
    new_name = target_dir / f"{safe_name}_{token}.{ext}"
    # 向后兼容: 优先新命名，fallback 到旧命名 content.md / content.xlsx
    if new_name.exists():
        candidates = [new_name]
    else:
        old_candidates = [target_dir / "content.md", target_dir / "content.xlsx"]
        candidates = [c for c in old_candidates if c.exists()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_docx_downloader.py::test_resolve_reference_output_uses_new_naming_pattern -v`
Expected: PASS

- [ ] **Step 5: Run all tests**

Run: `pytest tests/test_docx_downloader.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add larksync/core/downloaders/docx_downloader.py
git commit -m "refactor: _resolve_reference_output 使用新命名模式查找文件"
```

---

## Task 4: 边界情况测试

**Files:**
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 写边界情况测试**

```python
def test_reference_output_filename_edge_cases():
    """特殊字符、空标题、超长标题的处理"""
    from larksync.core.downloaders.docx_downloader import DocxDownloader

    # 特殊字符处理: safe_name 已由 sanitize_filename 处理过，输出不含特殊字符
    result = DocxDownloader._reference_output_filename("docx", "产品文档_测试", "tok123")
    assert "/" not in result and ":" not in result

    # 空标题处理: 使用 token 作为回退
    result = DocxDownloader._reference_output_filename("docx", "", "tok123")
    assert "tok123" in result

    # Slides/Mindnote 类型
    result = DocxDownloader._reference_output_filename("slides", "演示", "slide123")
    assert result == "演示_slide123.md"
    result = DocxDownloader._reference_output_filename("mindnote", "思维导图", "mind456")
    assert result == "思维导图_mind456.md"
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/test_docx_downloader.py::test_reference_output_filename_edge_cases -v`
Expected: PASS

- [ ] **Step 3: 运行完整测试套件**

Run: `pytest tests/ -v --tb=short`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: 引用文档命名边界情况测试"
```

---

## 验收标准

1. 引用文档命名包含真实标题（如 `产品文档_abc12345.md`）
2. 同 token 引用多次不重复下载（路径一致命中 `lookup_resolved_path`）
3. 不同文档同名时通过 token 区分（不冲突）
4. `file` 类型引用保持 `original_{token}.{ext}` 命名
5. 现有测试全部通过
