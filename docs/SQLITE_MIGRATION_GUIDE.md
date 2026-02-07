# SQLite Metadata 迁移指南

本文档介绍如何将 LarkSync 的 metadata 存储从 JSON 迁移到 SQLite。

## 🎯 为什么要迁移？

| 特性 | JSON | SQLite |
|-----|------|--------|
| 并发安全 | ❌ 可能数据损坏 | ✅ 支持事务 |
| 查询性能 | ❌ 需全量加载 | ✅ 索引查询 |
| 大数据量 | ❌ 内存占用高 | ✅ 按需读取 |
| 增量统计 | ❌ 不支持 | ✅ SQL 聚合 |
| 历史记录 | ❌ 不支持 | ✅ 可选启用 |

## 📋 快速开始

### 1. 更新配置

在 `config.toml` 中设置：

```toml
[storage]
# 切换到 SQLite 后端
metadata_backend = "sqlite"

# 自动迁移 JSON 数据（首次运行时）
metadata_auto_migrate = true
```

### 2. 手动迁移（可选）

如果想先迁移再切换后端：

```bash
# 查看当前 metadata 统计
larksync metadata-stats

# 执行迁移
larksync migrate-metadata

# 迁移完成后修改配置
# metadata_backend = "sqlite"
```

### 3. 验证迁移

```bash
# 再次查看统计，确认 SQLite 数据正确
larksync metadata-stats
```

## 🔄 配置选项

```toml
[storage]
# Metadata 存储后端：json（传统）或 sqlite（推荐）
metadata_backend = "sqlite"

# JSON 格式的 metadata 文件名
metadata_json_file = ".metadata.json"

# SQLite 数据库文件名
metadata_sqlite_file = ".sync.db"

# 是否记录同步历史（仅 SQLite）
metadata_enable_history = false

# 切换到 SQLite 时自动迁移 JSON 数据
metadata_auto_migrate = true
```

## 📊 不同文件类型的重复判定策略

### 云文档类型（docx, sheet, bitable, wiki, slides, mindnote）

使用 **revision 优先策略**：

```
判定优先级：
1. ✅ revision 变化 → 需要下载
2. ✅ modified_time 变化 → 需要下载（回退）
3. ✅ 本地文件不存在 → 需要下载
4. ✅ parent_path 变化 → 需要下载（文件移动）
5. ❌ 以上都不满足 → 跳过
```

### 普通文件类型（file）

使用 **时间戳策略**（因为 API 不返回 revision/checksum）：

```
判定优先级：
1. ✅ modified_time 变化 → 需要下载
2. ✅ 本地文件不存在 → 需要下载
3. ✅ 本地文件大小变化 → 需要下载（防御性检查）
4. ✅ parent_path 变化 → 需要下载
5. ❌ 以上都不满足 → 跳过
```

### 文件夹类型（folder）

```
判定：
1. ✅ 目录不存在 → 创建
2. ❌ 目录存在 → 跳过（仅更新 metadata）
```

## 🗄️ SQLite 表结构

### sync_metadata 表

| 字段 | 类型 | 说明 |
|-----|------|------|
| token | TEXT | 文档唯一标识 |
| file_type | TEXT | 文件类型 |
| name | TEXT | 文件名 |
| parent_path | TEXT | 父目录相对路径 |
| local_path | TEXT | 本地存储路径 |
| modified_time | TEXT | 远程修改时间 |
| revision | TEXT | 版本号 |
| checksum | TEXT | 校验和（预留） |
| local_file_size | INTEGER | 本地文件大小 |
| status | TEXT | 状态：ok/missing/deleted |
| last_error | TEXT | 错误信息 |
| last_synced_at | TEXT | 最后同步时间 |
| source_url | TEXT | 飞书原始链接 |

### shortcut_mappings 表

| 字段 | 类型 | 说明 |
|-----|------|------|
| shortcut_token | TEXT | 快捷方式 token |
| target_token | TEXT | 目标文档 token |
| target_type | TEXT | 目标文档类型 |

### sync_history 表（可选）

| 字段 | 类型 | 说明 |
|-----|------|------|
| token | TEXT | 文档 token |
| action | TEXT | 操作：sync/error/delete |
| reason | TEXT | 触发原因 |
| old_revision | TEXT | 旧版本号 |
| new_revision | TEXT | 新版本号 |
| timestamp | TEXT | 操作时间 |

## 🔧 CLI 命令

```bash
# 迁移 metadata
larksync migrate-metadata [--backup/--no-backup]

# 查看 metadata 统计
larksync metadata-stats

# 同步时使用 SQLite（配置后自动生效）
larksync sync-space
```

## ⚠️ 注意事项

1. **首次迁移**：建议在迁移前备份 `.metadata.json` 文件
2. **回退**：如需回退到 JSON，修改 `metadata_backend = "json"`
3. **并行运行**：JSON 和 SQLite 可以同时存在，通过配置切换
4. **历史记录**：启用 `metadata_enable_history` 会增加存储空间

## 📁 文件结构

```
output/
├── .metadata.json          # JSON 存储（传统）
├── .metadata.json.backup.* # 迁移备份
├── .sync.db                # SQLite 存储（新）
└── ... 下载的文件
```
