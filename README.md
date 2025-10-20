# LarkSync

LarkSync 是一个用于从飞书个人云空间批量下载文档、表格及常见附件的命令行工具。当前版本已实现：

- DocX/Doc → Markdown 转换，支持图片、附件、白板、公式及 Feishu 链接的递归解析。
- 嵌套链接自动识别：遇到嵌套的 DocX、Sheet、Bitable、Slides、Mindnote、File 等类型时调用对应下载器并重写为本地相对路径。
- Sheet/Bitable 导出为 `.xlsx`；普通文件 `file` 直接下载；Slides/Mindnote 生成说明性 Markdown。
- Folder/Shortcut、Wiki 节点的递归处理：快捷方式指向的目标会直接下载；Wiki 首次下载实际文档，重复访问时生成指向本地的占位说明。
- `sync-space` 命令可遍历个人空间根目录（默认限制下载条数），并在 `output/.metadata.json` 记录 token、类型、最后修改时间，为增量同步做准备。

完整的需求背景与后续规划可在 `requirement.md`、`technique.md` 中查看。

## 环境要求

- Python 3.11+
- 拥有飞书开放平台的个人访问令牌（User Access Token）。

## 安装

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .
```

开发环境可额外安装测试依赖：

```bash
pip install -e ".[dev]"
```

## 配置

- 默认读取仓库根目录的 `config.toml`（可通过 `LARKSYNC_CONFIG` 环境变量指定其它路径）。
- 最少需要在 `[auth]` 下提供 `user_access_token`，以及 `[storage]` 的 `root`（下载目录）。
- `[rate_limit]` 段用于配置每秒最大请求数，客户端会据此自动节流。（例如 docx=5 表示 DocX 接口单租户每秒最多 5 次请求）。
- `[sync]` 可控制增量下载：`enable_incremental`、`force_download_missing`（本地缺失时补全）、`clean_deleted`（云端删除时是否清理本地）。
- 其他并发/特性配置依旧占位，后续实现可直接启用。

示例：

```toml
[auth]
user_access_token = "YOUR_USER_ACCESS_TOKEN"

[storage]
root = "./output"

[logging]
level = "INFO"
structured = true

[rate_limit]
docx = 5
sheet = 5
bitable = 5
file = 5

[sync]
enable_incremental = true
force_download_missing = true
clean_deleted = false
```

常用环境变量覆盖：

- `LARKSYNC_USER_ACCESS_TOKEN`
- `LARKSYNC_STORAGE_ROOT`
- `LARKSYNC_LOG_LEVEL`

还可以使用 `LARKSYNC__<段>__<键>` 的形式覆盖任意配置字段。

## 使用方式

### 下载单个文档

```bash
# DocX / Doc
larksync download --type docx <token>

# Sheet / Bitable / File 等
larksync download --type sheet <token>
larksync download --type bitable <token>
larksync download --type file <token>

# 指定配置文件
larksync download --config ./config.toml --type docx <token>
```

执行后会在 `storage.root` 下创建同名目录，生成 Markdown 及相关资源：

```
output/
└── 示例文档/
    ├── 示例文档.md
    ├── images/
    ├── attachments/
    ├── refer_docx/
    └── ...
```

### 遍历个人空间（测试/分步下载）

```bash
# 下载个人空间前 50 个可访问文件 / 子目录（默认启用增量）
larksync sync-space --config config.toml --limit 50

# 取消限制（0 表示无限制）并强制全量
larksync sync-space --config config.toml --limit 0 --full

# 仅重建元数据，不下载
larksync sync-space --config config.toml --limit 0 --reset-metadata

# 临时关闭增量（保持 metadata，但本次全部重下）
larksync sync-space --config config.toml --no-incremental
```

该命令会：

- 基于 `limit` 控制下载条数（测试环境建议保留限制，生产环境可设置为 0 或省略以下载全部）。
- 在 `output/.metadata.json` 记录每个条目的 `token`、`file_type`、`parent_path`、`modified_time`、`local_path` 等，并据此进行增量对比。
- 本地缺失文件会自动补齐；云端删除的条目可按 `clean_deleted` 设置标记或清理。
- 遇到权限不足或无法导出的资源时写入占位 Markdown 并记录日志（`last_error` 字段可辅助排查）。

## 测试

项目提供基础解析器与下载流程的单元测试：

```bash
pytest
```

## 已实现能力摘要

- DocX/Doc Markdown 转换（含嵌套链接、图片、附件、白板 JSON/PNG）。
- Sheet/Bitable 导出 `.xlsx`；File 原样下载；Slides/Mindnote 生成说明性 Markdown。
- Folder/Shortcut/Wiki 节点遍历与本地化。
- 快捷方式自动识别目标类型并拉取实际内容。
- `.metadata.json` 保留下载条目的最后修改时间、revision、路径等信息，并驱动增量同步策略。

## 已知限制 / TODO

- 并发控制仍为后续规划（当前以串行方式执行）。
- 部分资源可能因权限不足出现“下载失败”占位，需要手动确认权限。
- 实际全量同步仍有性能优化空间（限速、重试、日志指标等）。

欢迎根据 `requirement.md` 中的 roadmap 持续完善。***

## 修订记录

| 日期         | 版本 | 说明                                   |
|--------------|------|----------------------------------------|
| 2025-10-20   | 1.1  | 增量同步落地：metadata 扩展、增量/全量 CLI 参数、即时落盘，配合 rate limit 重试策略 |
