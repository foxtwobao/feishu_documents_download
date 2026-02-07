# SQLite Metadata 存储方案设计

## 📋 概述

本文档描述将 LarkSync 的 metadata 存储从 JSON 文件迁移到 SQLite 数据库的方案设计，同时重构重复判定逻辑，针对不同文件类型实施差异化策略。

## 🎯 设计目标

1. **性能提升**：JSON 文件在大量文件时加载慢，SQLite 支持索引查询
2. **原子性写入**：SQLite 支持事务，避免并发写入导致数据损坏
3. **增量查询**：支持高效的 WHERE 条件查询，无需全量加载
4. **数据完整性**：支持外键约束、唯一约束等
5. **扩展性**：便于添加新字段和统计查询

---

## 📊 飞书不同文件类型的 Metadata 特征分析

通过 API 返回数据分析，不同文件类型具有不同的元数据字段：

### 文件类型 Metadata 对比表

| 文件类型 | modified_time | revision | checksum | 其他特征 |
|---------|--------------|----------|----------|---------|
| `docx`/`doc` | ✅ 有（Unix时间戳） | ✅ 有 | ❌ 无 | 有 title、块结构 |
| `sheet` | ✅ 有 | ✅ 有 | ❌ 无 | 有子表(sub_id) |
| `bitable` | ✅ 有 | ✅ 有 | ❌ 无 | 多维表格，有表结构 |
| `file` | ✅ 有 | ❌ **无** | ❌ **无** | 只有时间戳可用 |
| `folder` | ✅ 有 | ❌ 无 | ❌ 无 | 目录结构 |
| `shortcut` | ✅ 有 | ❌ 无 | ❌ 无 | 有 target_token, target_type |
| `wiki` | ✅ 有 | ✅ 有 | ❌ 无 | 类似 docx |
| `slides` | ✅ 有 | ✅ 有 | ❌ 无 | 占位符处理 |
| `mindnote` | ✅ 有 | ✅ 有 | ❌ 无 | 占位符处理 |

### 关键发现

1. **file 类型只有 modified_time**：无法通过 revision 或 checksum 判断是否变更
2. **云文档类型有 revision**：docx、sheet、bitable 等可通过 revision 精确判断
3. **所有类型都有 modified_time**：可作为通用的变更指示器

---

## 🔄 重复判定策略设计

### 策略 1：云文档类型（docx, sheet, bitable, wiki, slides, mindnote）

```
判定优先级：
1. revision 变化 → 需要下载
2. modified_time 变化 → 需要下载  
3. 本地文件不存在 → 需要下载
4. parent_path 变化 → 需要下载（位置移动）
5. 以上都不满足 → 跳过下载
```

### 策略 2：普通文件类型（file）

```
判定优先级：
1. modified_time 变化 → 需要下载
2. 本地文件不存在 → 需要下载
3. 本地文件大小变化 → 需要下载（新增：本地检查）
4. parent_path 变化 → 需要下载
5. 以上都不满足 → 跳过下载
```

### 策略 3：目录类型（folder）

```
判定：
- 仅检查目录是否存在
- 不下载内容，只创建目录结构
```

### 策略 4：快捷方式类型（shortcut）

```
判定：
1. 解析 target_token 和 target_type
2. 对目标文档应用相应类型的判定策略
3. 记录 shortcut token 与 target token 的映射关系
```

---

## 🗄️ SQLite 表结构设计

### 主表：`sync_metadata`

```sql
CREATE TABLE IF NOT EXISTS sync_metadata (
    -- 主键
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    
    -- 飞书文档标识
    token TEXT NOT NULL UNIQUE,           -- 文档/文件 token
    file_type TEXT NOT NULL,              -- 文件类型：docx, sheet, file, folder 等
    
    -- 基本信息
    name TEXT,                            -- 文件名称
    parent_path TEXT,                     -- 父目录相对路径
    local_path TEXT,                      -- 本地存储路径
    
    -- 变更检测字段
    modified_time TEXT,                   -- 远程修改时间（ISO8601格式）
    revision TEXT,                        -- 版本号（云文档类型有）
    checksum TEXT,                        -- 校验和（预留，当前 API 不返回）
    local_file_size INTEGER,              -- 本地文件大小（字节）
    
    -- 状态信息
    status TEXT DEFAULT 'ok',             -- ok, missing, deleted, error
    last_error TEXT,                      -- 最近一次错误信息
    
    -- 同步记录
    last_synced_at TEXT,                  -- 最后同步时间
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
    -- 来源信息
    source_url TEXT,                      -- 飞书原始链接
    
    -- 索引支持
    UNIQUE(token)
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_metadata_file_type ON sync_metadata(file_type);
CREATE INDEX IF NOT EXISTS idx_metadata_status ON sync_metadata(status);
CREATE INDEX IF NOT EXISTS idx_metadata_parent_path ON sync_metadata(parent_path);
CREATE INDEX IF NOT EXISTS idx_metadata_modified_time ON sync_metadata(modified_time);
```

### 快捷方式映射表：`shortcut_mappings`

```sql
CREATE TABLE IF NOT EXISTS shortcut_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shortcut_token TEXT NOT NULL UNIQUE,  -- 快捷方式 token
    target_token TEXT NOT NULL,           -- 目标文档 token
    target_type TEXT NOT NULL,            -- 目标文档类型
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    
    FOREIGN KEY (shortcut_token) REFERENCES sync_metadata(token) ON DELETE CASCADE
);
```

### 同步历史表：`sync_history`（可选，用于审计）

```sql
CREATE TABLE IF NOT EXISTS sync_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token TEXT NOT NULL,
    action TEXT NOT NULL,                 -- download, skip, delete, error
    file_type TEXT,
    reason TEXT,                          -- 触发原因描述
    old_revision TEXT,
    new_revision TEXT,
    old_modified_time TEXT,
    new_modified_time TEXT,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_history_token ON sync_history(token);
CREATE INDEX IF NOT EXISTS idx_history_timestamp ON sync_history(timestamp);
```

---

## 🏗️ 类设计

### SQLiteMetadataStore 类

```python
class SQLiteMetadataStore:
    """SQLite 持久化的 metadata 存储"""
    
    def __init__(self, db_path: Path):
        """初始化数据库连接"""
        
    def should_download(
        self,
        token: str,
        *,
        file_type: str,
        current_meta: Mapping[str, Any],
        expected_local_path: Optional[Path],
        incremental: bool,
        force_on_missing: bool,
        parent_path: Path,
    ) -> Tuple[bool, str]:
        """
        判断是否需要下载
        
        Returns:
            (should_download, reason): 是否下载及原因
        """
        
    def mark_synced(self, token: str, **kwargs) -> None:
        """标记文档已同步"""
        
    def mark_missing(self, token: str, error: str, **kwargs) -> None:
        """标记文档下载失败"""
        
    def mark_deleted(self, token: str) -> None:
        """标记文档已删除"""
        
    def get(self, token: str) -> Optional[Dict[str, Any]]:
        """获取单个文档的 metadata"""
        
    def tokens(self) -> Iterable[str]:
        """获取所有已记录的 token"""
        
    def migrate_from_json(self, json_path: Path) -> int:
        """从 JSON 文件迁移数据"""
```

### 判定策略接口

```python
class DuplicateCheckStrategy(ABC):
    """重复判定策略基类"""
    
    @abstractmethod
    def should_download(
        self,
        stored: Optional[Dict[str, Any]],
        current: Dict[str, Any],
        local_path: Optional[Path],
    ) -> Tuple[bool, str]:
        """判断是否需要下载"""
        
class CloudDocStrategy(DuplicateCheckStrategy):
    """云文档判定策略（docx, sheet, bitable, wiki, slides, mindnote）"""
    
class FileStrategy(DuplicateCheckStrategy):
    """普通文件判定策略"""
    
class FolderStrategy(DuplicateCheckStrategy):
    """文件夹判定策略"""
```

---

## 📁 文件结构

```
larksync/storage/
├── __init__.py
├── manager.py                    # StorageManager（保持不变）
├── metadata_store.py             # 原 JSON 实现（保留为备选）
├── sqlite_store.py               # 新 SQLite 实现
├── strategies/
│   ├── __init__.py
│   ├── base.py                   # DuplicateCheckStrategy 基类
│   ├── cloud_doc.py              # CloudDocStrategy
│   ├── file.py                   # FileStrategy  
│   └── folder.py                 # FolderStrategy
└── migration.py                  # JSON → SQLite 迁移工具
```

---

## 🔧 配置扩展

在 `config.py` 中添加新配置项：

```toml
[storage]
root = "./output"
metadata_backend = "sqlite"       # "sqlite" 或 "json"
metadata_db_name = ".sync.db"     # SQLite 数据库文件名
enable_sync_history = false       # 是否记录同步历史
```

---

## 📈 迁移方案

### 阶段 1：并行运行
- 同时支持 JSON 和 SQLite 两种后端
- 默认使用 JSON，可通过配置切换
- 提供迁移命令：`larksync migrate-metadata`

### 阶段 2：默认 SQLite
- SQLite 成为默认后端
- 首次运行时自动迁移 JSON 数据
- JSON 实现保留但标记为废弃

### 阶段 3：移除 JSON
- 移除 JSON 实现代码
- 仅保留迁移工具用于升级场景

---

## 🧪 测试计划

1. **单元测试**
   - SQLiteMetadataStore CRUD 操作
   - 各文件类型的判定策略
   - JSON → SQLite 迁移正确性

2. **集成测试**
   - 与 space_sync 模块集成
   - 并发写入安全性
   - 大数据量性能测试

3. **兼容性测试**
   - 现有 JSON 数据迁移
   - 跨平台（Linux/macOS/Windows）

---

## 📋 实施检查清单

- [ ] 创建 `sqlite_store.py` 实现
- [ ] 实现各文件类型的判定策略
- [ ] 更新配置模型
- [ ] 实现迁移工具
- [ ] 更新 `bootstrap.py` 和 `space_sync.py`
- [ ] 编写单元测试
- [ ] 编写集成测试
- [ ] 更新文档
