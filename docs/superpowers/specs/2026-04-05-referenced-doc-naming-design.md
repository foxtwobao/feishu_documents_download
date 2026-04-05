# 引用文档命名优化设计

## 问题

引用文档（嵌套文档）下载后统一命名为 `content.md`，没有使用文档真实标题，可读性差。

当前逻辑：
- 父文档：`{sanitized_title}_{token}.md`（有 token 后缀）
- 引用文档：`larkfiles/{token}/content.md`（无标题信息）

## 方案

将引用文档的命名逻辑与父文档对齐，使用 `{sanitized_title}_{token}.{ext}` 格式。

### 命名规则

| 文档类型 | 输出文件名 | 示例 |
|---------|-----------|------|
| DocX | `{sanitized_title}_{token}.md` | `产品需求文档_abc12345.md` |
| Sheet/Bitable/Base | `{sanitized_title}_{token}.xlsx` | `数据表_xyz98765.xlsx` |
| File (assets) | `original_{token}_{ext}` | `original_abc12345.pdf` |
| 其他 | `{sanitized_title}_{token}.md` | 同 DocX |

### 去重逻辑

- **Token 唯一性**：`{title}_{token}` 保证同一 token 的文档始终解析到同一路径，不会重复下载
- **路径注册**：`_register_and_resolve_path()` 保持不变，继续处理同名不同 token 的冲突

### 代码修改

**修改位置：** `larksync/core/downloaders/docx_downloader.py`

1. `_reference_output_filename()` (line 905-910)：
   - 当前返回固定 `content.md` / `content.xlsx`
   - 改为接收 `safe_name` 和 `token`，返回 `{safe_name}_{token}.{ext}`

2. 调用处 (line 796-806)：
   - 传入 `safe_name` 和 `token` 给 `_reference_output_filename()`

3. `_resolve_reference_output()` (line 949-975)：
   - 回退逻辑中的 `content.md` 改为使用相同命名规则

### 行为变化

- **Before**: `larkfiles/abc12345/content.md`
- **After**: `larkfiles/abc12345/产品需求文档_abc12345.md`

- **Before**: `assets/abc12345/original.pdf`
- **After**: `assets/abc12345/original_abc12345.pdf`

### 测试要点

1. 引用文档命名包含真实标题
2. 同 token 引用多次不重复下载（路径一致）
3. 不同文档同名时通过 token 区分（不冲突）
4. `file` 类型引用保持 `original.*` 命名
