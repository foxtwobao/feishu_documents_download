# 引用文档与资源落盘结构实现计划（Obsidian 优先）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让下载结果更适合在 Obsidian 中直接使用：主树保持飞书结构，独立云文档引用统一 flat 到 `refer/`，资源类内容落到宿主文档 `<doc>.assets/`，并支持对象在“树节点 / 引用对象”之间切换时的路径迁移。

**Architecture:** 路径策略由“按类型固定 refer 落盘”改为“按语义来源分流”：

- 飞书树节点 → 主树
- 独立云文档引用 → flat `refer/`
- 宿主文档资源 → `<doc>.assets/`

**Tech Stack:** Python 3.11+, pytest

---

## 文件结构

- 修改: `docs/path_reorg.md`
- 修改: `larksync/core/downloaders/docx_downloader.py`
- 修改: `larksync/core/downloaders/file_downloader.py`
- 修改: `tests/test_docx_downloader.py`
- 如有需要修改: 主树同步相关模块（space/wiki sync 路径生成处）

---

## Task 1: 先更新仓库路径规范文档

**Files:**
- Modify: `docs/path_reorg.md`

- [ ] **Step 1: 废除旧 refer 规则**

删除或重写以下旧规则：

- `refer/larkfiles/<token>/content.md`
- `refer/assets/<token>/original.<ext>`
- “不要改成 title_token.md”

- [ ] **Step 2: 写入新规则**

明确文档中应描述：

- 飞书树节点保持主树结构；
- 独立云文档引用统一进入顶层 flat `refer/`；
- 图片/附件/白板等资源进入宿主文档 `<doc>.assets/`；
- `file` 类型按“独立对象 / 宿主资源”分流。

---

## Task 2: 提炼“对象归属判定”逻辑

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- 如有需要修改: 主树同步模块 / 元数据辅助模块

- [ ] **Step 1: 先确定实现入口**

需要一个明确判定函数或等价逻辑，用于回答：

```python
def classify_reference(...):
    -> "tree_node" | "refer_object" | "host_asset"
```

至少要能区分：

- 当前 token 是否属于主树节点；
- 当前引用是否是独立云文档对象；
- 当前引用是否是宿主资源。

- [ ] **Step 2: 写测试用例设计说明**

覆盖以下判定场景：

1. A 引用 B，且 B 在当前同步树中 → `tree_node`
2. A 引用树外 docx/sheet/slides/mindnote → `refer_object`
3. A 中图片/附件/白板资源 → `host_asset`
4. file 链接型引用 → `refer_object`
5. file 附件块 → `host_asset`

- [ ] **Step 3: 实现判定逻辑**

实现方式可以是：

- 通过主树遍历时建立 token 索引；
- 或在引用下载前通过 metadata/任务上下文判断当前 token 是否属于主树节点。

> 关键不是具体放在哪个函数，而是**必须有单一且可测试的分流规则**。

---

## Task 3: 改造云文档引用为 flat `refer/`

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 改路径生成逻辑**

对于 `refer_object`，目标路径应改为：

```text
<vault_root>/refer/{safe_name}_{token}.md
<vault_root>/refer/{safe_name}_{token}.xlsx
```

而不是：

```text
refer/larkfiles/<token>/content.md
```

- [ ] **Step 2: 更新 `_reference_output_filename()`**

目标行为：

```python
docx/slides/mindnote -> {safe_name}_{token}.md
sheet/sheets/bitable/base -> {safe_name}_{token}.xlsx
file -> None  # file 由 file_downloader 决定最终文件名
```

- [ ] **Step 3: 更新 `_resolve_reference_output()`**

`refer/` 按 spec 固定为 **direct flat files**，因此不再查找 `content.md/content.xlsx`，而直接解析：

```python
refer_root / f"{safe_name}_{token}.md"
refer_root / f"{safe_name}_{token}.xlsx"
```

如果当前函数仍以 `target_dir` 为参数，则应同步改造成接收或推导 `refer_root`，不要继续保留“每个 token 一个子目录”的旧模型。

- [ ] **Step 4: 写测试**

最少覆盖：

```python
def test_tree_external_docx_reference_downloads_to_flat_refer(...)
def test_tree_external_sheet_reference_downloads_to_flat_refer(...)
def test_same_refer_token_is_reused_across_multiple_docs(...)
```

---

## Task 4: 改造宿主资源为 `<doc>.assets/`

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- Modify: `larksync/core/downloaders/file_downloader.py`
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 定义 sidecar 目录规则**

宿主文档 `A_aaa111.md` 的资源目录统一为：

```text
A_aaa111.assets/
```

不要再使用：

- `refer/assets/<token>/...`
- 杂散的资源目录命名

- [ ] **Step 2: 资源类引用统一改写到 sidecar**

至少包括：

- 图片
- 附件块
- 白板导出图 / JSON
- 非独立对象语义的 file

- [ ] **Step 3: 定义无 token 资源命名规则**

命名优先级要固定：

1. 原始文件名
2. `{safe_name}_{token_or_block_id}{ext}`
3. `{host_doc_safe_name}_{resource_type}_{index}{ext}`

并写成测试。

- [ ] **Step 4: 写测试**

覆盖：

```python
def test_embedded_image_downloads_to_host_assets(...)
def test_attachment_block_downloads_to_host_assets(...)
def test_whiteboard_export_downloads_to_host_assets(...)
def test_resource_without_token_uses_host_based_fallback_name(...)
```

---

## Task 5: 树节点引用优先链接主树

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 增加树节点优先规则**

如果 A 引用 B，且 B 属于当前同步树，则：

- B 只存主树；
- 不再进入 `refer/`；
- A 的链接改写为指向主树中的 B。

- [ ] **Step 2: 写测试**

```python
def test_reference_to_tree_node_rewrites_to_main_tree_path(...)
```

至少验证：

- B 不在 `refer/` 中生成副本；
- A 的最终链接指向主树的相对路径。

---

## Task 6: 支持“树节点 / 引用对象”状态切换

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- 如有需要修改: metadata / sync state 相关模块
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 明确迁移策略**

需要支持两种迁移：

1. `refer/` → 主树
2. 主树 → `refer/`

迁移动作至少应包括：

- 移动或重建目标文件；
- 更新 token 对应的 canonical path；
- 更新相关引用链接；
- 删除旧位置文件。

- [ ] **Step 2: 写测试**

```python
def test_reference_object_moves_into_tree_when_it_becomes_tree_node(...)
def test_tree_node_moves_to_refer_when_it_is_no_longer_in_tree(...)
```

> 如果完整自动迁移过重，也至少要在本轮实现里把“状态变化时重新生成正确路径并更新链接”定义清楚。

---

## Task 7: `file` 类型按语义来源分流

**Files:**
- Modify: `larksync/core/downloaders/file_downloader.py`
- Modify: `larksync/core/downloaders/docx_downloader.py`
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 定义两种 file 语义**

1. 独立对象型 file → `refer/`
2. 宿主资源型 file → `<doc>.assets/`

- [ ] **Step 2: 调整最终文件名逻辑**

对于 file：

- 优先原始文件名；
- 原始文件名不可得时，使用 `{safe_name}_{token}{ext}`；
- 再不行兜底 `original.bin`。

- [ ] **Step 3: 写测试**

```python
def test_file_link_reference_downloads_to_refer(...)
def test_attachment_file_downloads_to_host_assets(...)
def test_file_preserves_original_filename_when_available(...)
```

---

## Task 8: 链接重写与 Obsidian 体验验证

**Files:**
- Modify: `larksync/core/downloaders/docx_downloader.py`
- Modify: `tests/test_docx_downloader.py`

- [ ] **Step 1: 链接重写必须直接指向真实文件**

目标：

- A 引主树中的 B → 链到主树 `.md`
- A 引树外云文档 → 链到 `refer/*.md|xlsx`
- A 引宿主资源 → 链到 `A_aaa111.assets/...`

- [ ] **Step 2: 写测试**

```python
def test_replace_reference_links_points_to_real_files_not_stubs(...)
```

- [ ] **Step 3: 跑相关测试**

Run: `pytest tests/test_docx_downloader.py -v`

- [ ] **Step 4: 跑更广验证**

Run: `pytest tests/ -v --tb=short`

---

## 验收标准

1. 飞书树节点按主树结构落盘；
2. 独立云文档引用统一 flat 进入 `refer/`；
3. 宿主资源统一进入 `<doc>.assets/`；
4. A 引 B 且 B 在树中时，B 不进入 `refer/`；
5. A 引树外独立云文档时，目标进入 `refer/`；
6. `file` 类型能够按“独立对象 / 宿主资源”分流；
7. 无 token 资源有稳定且可读的 fallback 命名；
8. 对象在“树节点 / 引用对象”之间切换时，路径与链接能更新到正确位置；
9. Obsidian 中用户看到的是可直接打开和链接的真实文件；
10. 相关测试全部通过。
