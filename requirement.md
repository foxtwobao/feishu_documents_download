# 飞书个人文件定时同步系统需求文档

## 1. 项目概述

### 1.1 项目背景
飞书作为企业级协作平台，用户在日常工作中会产生大量的文档、表格、演示文稿等文件。为了确保数据安全和便于本地管理，需要开发一个自动化系统，定时将飞书个人云空间中的文件同步到本地存储。

### 1.2 项目目标

- 实现飞书个人云空间文件的本地同步核心能力（期望实现：按类型路由与保存）
- 支持上传文件类型 `file` 的直接下载与保存（期望实现）
- 支持云文档类型 `docx`/`doc` 转换为 Markdown 并保存（期望实现）
- 支持 `sheet`/`bitable` 导出为 `.xlsx`（期望实现）
- 支持 `whiteboard` 导出为 Markdown（期望实现）
- 对不支持的文件如`mindnote`、`slides` 生成占位 Markdown（期望实现`mindnote`、`slides` ,还有哪些类型不支持，待确认）
- 提供日志记录与错误处理（期望实现）
- 增量同步策略

#### 1.2.1 飞书官方文件类型清单（MCP 调查结论）
- 云空间/云文档节点类型（Drive/Docs）：
  - `doc`（旧版文档，后续可升级为 `docx`）
  - `docx`（新版文档）
  - `sheet`（电子表格）
  - `slides`（幻灯片）
  - `bitable`（多维表格）
  - `mindnote`（思维笔记/导图）
  - `file`（上传文件，非云文档）
  - `wiki`（知识库）
  - `folder`（文件夹）
  - `shortcut`（快捷方式）

引用来源：
- 搜索云文档：`docs_types` 枚举（`doc`、`sheet`、`slides`、`bitable`、`mindnote`、`file`）
- 获取文件元数据：`doc_type` 可选值（文档/电子表格/多维表格/思维笔记/文件/知识库/新版文档/文件夹/文档同步块）
- 删除文件或文件夹：`type` 可选值（文件/新版文档/多维表格/文件夹/文档/电子表格/思维笔记/快捷方式/幻灯片）

#### 1.2.2 本项目文件类型支持清单
- 期望支持并输出内容：
  - `file`：原始文件流直接下载与保存（保留扩展名）
  - `docx`/`doc`：Blocks → Markdown（含嵌套链接、图片与附件）
  - `sheet`/`bitable`：导出任务 → 轮询 → 下载 `.xlsx`
  - `folder`：遍历/解析
- 占位或暂不支持：
  - `mindnote`、`slides`：生成占位 Markdown（官方暂无内容导出接口）
  - `wiki`：首次自动下载节点指向的实际文档，若已存在则生成占位 Markdown 指向本地路径（全文导出待迭代）
  - `shortcut`：不直接下载
  
#### 1.2.3 DocX 文档块类型支持清单（块级能力）

说明：本节描述 DocX 文档内部的块（Block）能力，不是顶层文件类型。路由与文件类型清单见 1.2.2；DocX 块支持度以解析与导出的具体能力为准。

- 期望支持块（解析为 Markdown 或资源文件）：
  - 页面与段落：`page`、`paragraph`
  - 标题：`heading1`-`heading6`（按 Markdown 1-6 级映射）
  - 列表：`bullet_list`、`ordered_list`
  - 代码块：`code`
  - 引用：`quote`
  - 图片：`image`（`medias` 下载接口）
  - 文件附件：`file_attachment`（Drive 下载接口）
  - 表格/网格：`table`、`grid_container`/`grid`（按当前 parser 能力输出）
  - 待办（Todo）：`todo`
  - 分隔线：`divider`
  - 数学公式：`equation`
  - 白板：`whiteboard`（`block_type` 为 43，通过 Board API 获取节点并渲染为 Markdown）
  - 嵌套云链接：识别并递归处理（由嵌套处理器负责）

- 暂不支持或占位块：
  - 文档同步块：`doc_sync_block`（块类型，当前不展开；不作为文件类型参与路由）
  - 其他未知/灰度块：降级为原文或占位提示

注：DocX 块类型清单用于规范解析能力与输出一致性；不影响顶层文件类型枚举与路由策略。文件类型的统一来源与支持状态请参考 1.2.2。

#### 1.2.4 术语与约定
- 文件类型（File Type）：顶层路由的类别，如 `docx`、`sheet`、`bitable`、`file`、`whiteboard`、`folder`、`shortcut`、`wiki` 等。
- 文档块类型（DocX Block Type）：DocX 内部的结构化块，如 `heading`、`list`、`image`、`file_attachment` 等，不参与顶层路由。
- DocX 与 Doc：旧版 `doc` 按 DocX 路径处理并统一为 `docx` 的解析流程。
- 不支持项：`wiki` 当前不纳入下载流程；`doc_sync_block` 为块类型，仅占位不展开。
- 参考实现与目录结构请见 `technique.md` 的分层架构说明（Adapters/Parsers/Processors/Bridges/Downloaders/Registry）。

### 1.3 期望实现能力总览

- 类型与处理概览
  - 详细类型与当前支持状态统一见 1.2.2“本项目文件类型支持清单”。
  - 本节仅提炼能力提要，不重复逐项类型说明。
- 路由策略
  - 期望实现
    - 使用下载器注册表（类型→模块）统一路由所有文件类型；同步引擎只负责遍历与任务生成，具体处理由注册表派发。
    - DocX 采用分层模块：DocX会包含各种内联的block_type，每个block_type对应一个解析器，解析器负责将block_type转换为Markdown或者直接下载。同时DocX中也会嵌套其他的DocX文档，这些嵌套的DocX文档也会采用相同的解析流程，同时需要注意循环引用的问题。
    - 各类型下载器（`core/downloaders/*`）负责"导出/下载→解析→保存→嵌套调度"；中间件管线与队列统一承载鉴权、日志、重试、限流。
- 存储策略
  - 文档 `.md`、表格 `.xlsx`、上传文件保留扩展名；图片至 `images/`、附件至 `attachments/`；嵌套文档采用 `nested_docs/` 目录
- 增量策略
  - 期望实现：所有文件首先基于最后修改时间
  - 对 `docx`/`bitable` 叠加基于 `revision` 判断


## 3. 功能需求

### 3.1 核心功能

#### 3.1.1 文件发现与列举
- 个人云空间扫描：遍历用户个人云空间根目录及所有子文件夹
- 文件信息获取：获取文件名称、类型、创建时间、修改时间、所有者等元数据
- 增量扫描：支持基于修改时间的增量文件发现

#### 3.1.2 文件类型支持
- 支持云文档（Docs/Drive）：`doc`/`docx`、`sheet`、`bitable`、`mindnote`、`slides`、`wiki`
- 上传文件（非云文档）：`file`
- 非文档节点（遍历/解析，不直接下载）：`folder`、`shortcut`

说明：本章节给出分类与处理方向，具体支持状态（已实现/占位/未实现）统一见 1.2.2“本项目文件类型支持清单”。

#### 3.1.3 文件下载与转换

- 上传文件下载：直接下载原始文件并保存到本地
- 云文档转换：通过 Blocks JSON 解析为 Markdown 保存
- 批量处理：当前串行执行；并发下载进入“下一步实现的需求池”
- 断点续传：无需实现，断点文件全部重新下载

#### 3.1.4 定时同步

- 当前未实现：定时任务、预览与确认、全量同步命令与状态跟踪将移入“下一步实现的需求池”

#### 3.1.5 同步前预览与确认

- 当前未实现：功能移入“下一步实现的需求池”

### 2.2 高级功能

#### 2.2.1 本地存储管理
- **目录结构映射**：保持与飞书云空间相同的目录结构（期望实现：DocX/嵌套文档与资源目录）
- **文件命名规则**：处理文件名冲突和特殊字符（期望实现）
- **版本管理**：支持文件版本历史保存（待实现）
- **存储优化**：重复文件检测和去重（待实现）

#### 2.2.2 同步策略配置
- **增量同步**：基于文件修改时间和版本号的智能同步（期望实现）
- **过滤规则**：支持文件类型、大小、路径的过滤配置（期望实现）
- **并发控制**：可配置的并发下载数量和速率限制（期望实现）
- **错误处理**：失败重试机制和错误日志记录（期望实现）

#### 2.2.3 监控与日志
- **同步日志**：详细记录同步过程和结果（期望实现）
- **错误处理**：异常情况的记录和重试机制（期望实现基础重试与异常封装）
- **进度监控**：实时显示同步进度（期望实现）
- **统计报告**：同步统计和性能分析（期望实现）

#### 2.2.4 多级嵌套处理原则
- **循环检测**（已实现）：通过 `_history` 传递已访问 token，避免重复下载或自引用。
- **目录结构**（已实现）：各主文档下创建 `refer_<type>` 子目录存放嵌套文档/表格/思维笔记等本地化结果，资源继续落在 `images/`、`attachments/`。
- **相对引用**（已实现）：主文档与嵌套产物之间的链接统一替换为相对路径，支持多层级跳转。
- **深度阈值**：尚未引入显式递归深度限制与告警机制。
- **指标与日志**：待补充嵌套层级统计、失败计数等监控数据。

## 3. 技术需求

### 3.1 飞书API集成

#### 3.1.1 认证授权
- 访问凭证：通过配置文件提供 `user_access_token`
- 权限申请：应用需具备“查看、评论和下载云空间中所有文件”等权限

#### 3.1.3 核心 API 接口
- 期望集成的核心接口：
  - 下载文件：`GET /open-apis/drive/v1/files/{file_token}/download`
  - 媒体/附件下载：`GET /open-apis/drive/v1/medias/{image_token}/download`
  - DocX 文档与块：`GET /open-apis/docx/v1/documents/{document_id}`、`GET /open-apis/docx/v1/documents/{document_id}/blocks`
  - 导出任务（Sheet/Bitable）：`POST /open-apis/drive/v1/export_tasks`、`GET /open-apis/drive/v1/export_tasks/{ticket}`、`GET /open-apis/drive/v1/export_tasks/file/{file_token}/download`
  - 白板：`GET /open-apis/board/v1/whiteboards/{whiteboard_id}/nodes`、`GET /open-apis/board/v1/whiteboards/{whiteboard_id}/download_as_image`
  - 元信息查询：`POST /open-apis/drive/v1/metas/batch_query`
- 待集成：
  - 获取根目录元数据：`GET /open-apis/drive/explorer/v2/root_folder/meta`
  - 获取文件夹文件清单：`GET /open-apis/drive/v1/files?folder_token=...`

#### 3.1.4 API限制处理
- **频率限制**：实现请求频率控制和重试机制
- **文件大小限制**：
  - 导出文件：Word文档资源总计不超过1GB，PDF不超过128MB
  - 下载文件：单文件不超过100MB
- **并发限制**：控制并发请求数量

### 3.2 系统架构

#### 3.2.1 技术栈
- 编程语言：Python 3.10+
- HTTP 客户端：requests
- 任务调度：APScheduler
- 数据存储：本地文件状态（JSON）
- 配置管理：YAML 配置文件，支持环境变量覆盖
- 日志系统：Python logging 模块


设计原则：
- 每种文件类型的下载功能独立为单一文件模块（单一职责、可测试、易扩展）。
- 下载器核心模块仅保留三类职责：
  - 路由分发：基于类型/Token映射到具体下载器模块；
  - 下载调度：统一的队列/并发控制，任务优先级与重试策略；
- 解析调用：协调具体文件类型解析与保存流程，并汇总结果与指标。

#### 3.2.2 模块分层与职责（推荐方案）
- 分层与目录：
  - Adapters：`core/adapters/docx_adapter.py`（DocX API 适配与分页、容错，输出原始 Blocks 与元信息）
  - Parsers：`core/parsers/docx_parser.py`（DocX Blocks → Markdown 的纯解析器；不发网络请求）
  - Processors：`core/processors/nested_doc_processor.py`（嵌套链接识别与递归调度，维护 `nested_docs/` 目录与相对引用）
  - Bridges：`core/bridges/cloud_doc_processor.py`（链接块桥接，过渡期保留；后续并入处理器或退役）
  - Type Downloaders：`core/downloaders/*`（各类型编排入口：导出/下载→解析→保存→嵌套调度）
  - Registry：`core/registry/downloader_registry.py`（类型→下载器映射与动态开关）
- 边界约束：
  - Adapter 不做解析或存储；Parser 仅做纯转换，不进行下载；Processor 不做主文档解析，仅做递归与调度；Downloader 负责外部 IO 与编排。
  - Utils 仅存放跨类型的通用工具（字符串、IO、路径安全等），不承载领域解析/适配代码。


#### 3.2.3 下载中间件机制
- 在下载器核心构建中间件管线（前置/后置钩子）：
  - 前置：鉴权校验、参数标准化、幂等校验、日志开始、指标计时启动；
  - 后置：结果记录、异常捕获与统一封装、重试策略应用、日志结束、指标计时结束；
- 中间件可按顺序注册，支持开关与配置化，保证通用逻辑与业务逻辑解耦。

#### 3.2.4 统一错误处理与重试规范
- 统一异常类型：`DownloadError`（含类型/阶段/错误码）、`ExportTaskError`、`NetworkError` 等；
- 重试策略：指数退避 + 最大尝试次数 + 失败分级（网络/任务/内容）；
- 错误上报：统一日志字段（file_type、token、stage、attempt、duration、message）。

#### 3.2.5 可扩展的模块注册机制
- 通过注册表实现类型→模块映射，如 `register_downloader('docx', DocxDownloader)`；
- 支持动态加载（按需导入）与配置开关（启用/禁用某类型）；
- 提供默认实现与占位实现（例如 `mindnote`、`slides`）。

#### 3.2.6 下载任务队列与并发控制
- 引入下载任务队列（支持优先级），协调资源与并发；
- 并发策略：按类型/接口特性设定最大并发与速率限制；
- 任务生命周期：待处理 → 进行中 → 成功/失败（含重试计数与最后错误）。

#### 3.2.7 性能监控与耗时统计
- 指标维度：
  - 端到端下载耗时（per file）
  - 分阶段耗时：元信息查询、导出任务创建、轮询、下载、解析、保存
  - 成功/失败率、重试次数与原因分布
- 输出形式：结构化日志与统计摘要（供评审与优化）。

### 3.3 数据模型

#### 3.3.1 文件元数据表
```sql
CREATE TABLE file_metadata (
    id INTEGER PRIMARY KEY,
    token VARCHAR(50) UNIQUE NOT NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(20) NOT NULL,
    parent_token VARCHAR(50),
    url TEXT,
    created_time TIMESTAMP,
    modified_time TIMESTAMP,
    owner_id VARCHAR(50),
    local_path TEXT,
    sync_status VARCHAR(20),
    last_sync_time TIMESTAMP,
    file_size INTEGER,
    checksum VARCHAR(64)
);
```

#### 3.3.2 同步任务表
```sql
CREATE TABLE sync_tasks (
    id INTEGER PRIMARY KEY,
    task_type VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    start_time TIMESTAMP,
    end_time TIMESTAMP,
    files_processed INTEGER DEFAULT 0,
    files_success INTEGER DEFAULT 0,
    files_failed INTEGER DEFAULT 0,
    error_message TEXT
);
```

## 4. 非功能需求

### 4.1 性能要求

- 并发下载：当前串行；并发能力移入“下一步实现的需求池”
- 单次同步：可稳定处理 300+ 文件
- 资源占用：内存 < 512MB

### 4.2 可靠性要求

- 错误恢复：网络异常的重试机制
- 数据完整性：保存后进行文件大小校验，后续加入校验和
- 事务性：同步过程的原子性尽可能保证

### 4.3 安全要求

- 凭证安全：`user_access_token` 不写入代码仓库，存放于配置/环境变量
- 权限控制：最小权限原则，仅申请必要权限

### 4.4 可维护性要求

- **配置化**：所有关键参数支持配置文件管理
- **日志完整**：详细的操作日志和错误日志
- **模块化**：清晰的模块划分和接口设计

## 5. 实现方案

### 5.1 开发阶段规划

#### 阶段一：基础框架搭建
1. 项目结构初始化
2. 配置管理系统
3. 日志系统搭建
4. 飞书 API 客户端（基于 `user_access_token`）

#### 阶段二：核心功能实现
1. 文件扫描和列举功能
2. 上传文件直接下载与保存
3. 云文档 Blocks 转 Markdown 并保存
4. 本地存储管理与增量同步逻辑

#### 阶段三：高级功能开发
1. 定时任务调度（APScheduler）
2. 错误处理和重试机制
3. 监控和统计功能

#### 阶段四：优化和完善
1. 性能优化
2. 用户界面设计(需要具备简单的操作流程，例如用户登录授权->选择待同步的文件夹/WIKI->启动同步->查看同步进度/日志)
3. 文档完善
4. 测试和部署

### 5.2 关键技术实现

#### 5.2.1 认证流程（后续版本）
```python
# OAuth 2.0 授权码流程
1. 引导用户访问飞书授权页面
2. 获取授权码 (authorization_code)
3. 使用授权码换取访问令牌 (access_token)
4. 定期刷新访问令牌
```

#### 5.2.2 文件同步流程
```python
# 同步流程伪代码
def sync_files():
    # 1. 扫描云端文件
    cloud_files = scan_cloud_files()
    
    # 2. 比较本地文件
    local_files = get_local_file_metadata()
    
    # 3. 确定需要同步的文件
    files_to_sync = compare_files(cloud_files, local_files)
    
    # 4. 执行同步
    for file in files_to_sync:
        if file.type in ['docx', 'doc', 'sheet', 'bitable']:
            export_and_download(file)
        else:
            direct_download(file)
    
    # 5. 更新本地元数据
    update_metadata(files_to_sync)
```

### 5.3 部署方案
- 本地部署：支持 Windows、macOS、Linux 系统
- 配置管理：环境变量和配置文件支持

## 6. 风险评估

### 6.1 技术风险
- **API变更**：飞书API接口变更的适配风险
- **限制调整**：API频率限制和文件大小限制的变化
- **网络依赖**：网络不稳定对同步的影响

### 6.2 业务风险
- **权限变更**：用户权限变化导致的同步失败
- **存储空间**：本地存储空间不足的处理
- **数据丢失**：同步过程中的数据丢失风险

### 6.3 缓解措施
- **版本兼容**：保持对多版本API的兼容性
- **监控告警**：实时监控同步状态和异常
- **备份策略**：重要数据的备份和恢复机制

## 7. 验收标准

### 7.1 功能验收

- [x] 上传文件（`file`）可直接下载并保存到本地
- [x] 云文档（`docx`/`doc`）转换为 Markdown 并保存到本地
- [x] 电子表格（`sheet`）与多维表（`bitable`）导出为 `.xlsx`
- [x] 白板（`whiteboard`）转换为 Markdown（含图片）
- [x] 思维导图（`mindnote`）生成占位 Markdown
- [x] 演示文稿（`slides`）生成占位 Markdown
- [x] 文档内图片与附件下载并按 `images/` 与 `attachments/` 存储
- [x] 嵌套 Feishu 链接识别与递归处理（按类型路由）
- [ ] 成功连接飞书 API 并获取根目录与文件清单
- [ ] 定时同步功能正常运行
- [ ] 增量同步（全面）准确识别变更文件（当前仅 `bitable` 基于 revision）
- [ ] 本地文件结构与云端保持一致（按云空间路径）

### 7.2 性能验收

- [x] 错误重试机制基本可用，异常封装与日志输出完整
- [ ] 并发下载在默认 5 并发下稳定运行（移入需求池）

### 7.3 稳定性验收

- [ ] 连续运行7天无崩溃
- [ ] 网络异常恢复后自动继续同步
- [ ] 日志记录完整无遗漏

## 8. 后续规划

### 8.1 功能扩展

- **双向同步**：支持本地文件上传到飞书
- **团队空间**：支持团队共享空间的同步
- **实时同步**：基于Webhook的实时文件变更同步
- **Web界面**：提供Web管理界面

### 8.2 集成扩展

- **其他平台**：支持钉钉、企业微信等平台
- **云存储**：集成阿里云OSS、腾讯云COS等
- **版本控制**：集成Git进行文件版本管理

---

**文档版本**：v1.4-architecture（与技术实现方案对齐）  
**创建日期**：2024年12月  
**最后更新**：2025年10月（架构与实现评审版）  
**负责人**：开发团队

## 9. 下一步实现的需求池

- 云空间根目录与文件夹列表 API 集成与递归遍历
- 并发下载（默认 5 并发，可配置），任务并发与限流控制
- 断点续传与失败重试增强（覆盖文件/媒体流与导出任务）
- 定时同步（APScheduler）与 CLI `sync-now`/`schedule` 指令
- 同步前预览与交互确认（`sync.confirm_before_sync`）
- 增量同步全面化：除 `bitable` 外，基于修改时间/校验和识别变更
- 通过注册表完善 `file_downloader`，复用 `download_file_stream`；不再向统一下载器扩展新类型
- `wiki` 的下载与 Markdown 生成，纳入注册表路由与嵌套处理
- `slides` 使用官方导出接口（PDF）替代占位，完善导出轮询
- 本地目录结构映射与冲突处理策略完善（对齐云空间路径）
- 版本管理与重复文件去重（校验和/内容指纹）
- 文件过滤/目录选择/格式偏好（基于配置）

## 10. 重构流程与评审
- 文档更新优先：先完成需求与设计文档更新并评审，代码修改在文档评审后进行。
- 评审流程：需求与设计合并评审 → 形成决议与行动项 → 建立迭代计划与里程碑。
- 输出物：更新后的 requirements.md 与 technique.md 标注“重构专项版本”。

## 11. 重构 Checklist（执行与验收）
- 模块拆分：各文件类型独立 downloader 模块完成并通过静态检查。
- 核心下载器：路由分发/下载调度/中间件管线落地并联调通过。
- 注册机制：类型→模块注册与动态加载验证。
- 错误与重试：统一异常与重试策略在关键路径验证（含导出任务）。
- 性能与监控：指标埋点与统计输出联调，形成基线数据。
- 队列与并发：优先级/并发控制在 5 并发基准下稳定运行。
- 文档与版本：requirements.md/technique.md 更新完毕并标注“v1.4”。
- 评审与发布：技术评审通过，Checklist 全项勾选后进入实施。
- 进度监控与统计报告（含图表汇总）
- 进度监控与统计报告（含�

## 12. Web UI 需求补充

为提升易用性与多用户协同体验，新增 Web 管控台，满足以下能力：

1. **同步任务编排**
   - 通过 Web 页面选择需要执行的同步类型：单文档下载、文件夹同步、个人空间全量/增量同步。
   - 为不同任务设置参数（限流、增量/全量、输出目录等）。
   - 支持立即执行及定时计划。

2. **飞书登录与鉴权**
   - 使用飞书 OAuth 授权流程，让终端用户自行登录授权。
   - 后端保存用户侧的 `user_access_token` / `refresh_token`，并通过飞书接口定期刷新，确保长时有效。

3. **任务隔离与可见性**
   - 所有任务以“用户 + 任务 ID”维度隔离：用户只能查看自己的任务与输出。
   - 提供任务列表、状态页，展示进行中、排队、成功/失败记录。
   - 支持查看执行历史的日志、输出目录、错误详情。

4. **实时状态与通知**
   - Web UI 轮询 / WebSocket 推送任务进度（排队、执行、完成、异常）。
   - 可选配置：任务完成后向飞书机器人/邮件推送通知。

5. **热门前端技术栈**
   - 前端推荐使用 React + TypeScript（或 Next.js）并接入组件库（Ant Design / Material UI）。
   - 后端提供 GraphQL/REST API，封装同步任务调度与状态查询。

6. **后台任务调度**
   - 引入任务队列（如 Celery/RQ/自研队列），配合现有限流与重试策略。
   - 任务运行环境与 CLI 逻辑共用组件，便于维护。

7. **安全与权限**
   - 所有敏感信息（Token、下载列表）均按用户隔离；管理员可配置全局策略。
   - 支持登出、Token 失效后的重新授权流程。

8. **后续扩展**
   - 支持团队共享任务视图、任务模板；
   - 可选开关“自动清理过期输出”、“生成带下载链接的任务报告”。

> 以上需求待进入设计评审后拆解为 UI 原型、后端接口与任务调度实现。
