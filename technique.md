# LarkSync 技术实现方案（对齐 requirements.md）

文档版本：v1.4-implementation  
最后更新：2025-10  
适用范围：`larksync` 全量模块（核心下载、同步编排、解析、存储、配置与监控）

## 目标与原则
- 对齐单一事实源：`requirements.md` 1.2.2 文件类型支持清单与 3.1.2 分类说明。
- 统一术语：`docx`（含旧版 `doc` 按 DocX 路径处理）、`sheet`、`bitable`、`file`、`slides`、`mindnote`、`wiki`、`folder`、`shortcut`。
- 明确能力边界：`wiki` 暂不支持；DocX 同步块（`doc_sync_block`）为块类型，当前不展开；`slides`/`mindnote`以占位导出策略保存。
- 面向演进：模块注册、管线中间件、任务队列与并发控制，支持增量扩展与灰度。

## 架构总览
- 组件划分：
  - `API Client`：封装 Feishu Open API（文档块、导出任务、文件/媒体下载、白板等）。
  - `Downloader Registry`：类型→下载器模块映射，支持动态开关。
  - `Type Downloaders`：按类型实现导出/下载/解析与保存的具体逻辑。
  - `Queue & Concurrency`：优先级队列、并发上限、速率限制与背压。
  - `Middleware Pipeline`：前置/后置钩子，统一鉴权、日志、重试与指标。
  - `Storage`：统一资源目录，安全文件名与大文件分块写入。
  - `Logging & Metrics`：结构化日志与指标上报，形成可观测性闭环。
- 关键流程（简化）：
  - 发现/遍历 → 类型识别 → 注册表路由 → 前置中间件 → 下载/导出执行 → 解析/保存 → 后置中间件 → 指标与日志 → 嵌套资源递归。

## 代码目录与文件规划

### 项目架构设计原则
- **分层架构**：采用适配器-解析器-处理器-下载器的分层设计，职责清晰分离
- **模块化设计**：每个文件类型独立下载器，支持动态注册和开关控制
- **可扩展性**：通过注册表机制支持新文件类型的快速接入
- **可观测性**：内置中间件管线，统一处理日志、指标、重试等横切关注点

### 目录结构设计

```
feishu_sync/                     # 项目根目录
├── larksync/                    # 核心包目录
│   ├── __init__.py
│   ├── core/                    # 核心功能模块
│   │   ├── __init__.py
│   │   ├── adapters/            # API适配层：封装飞书API调用
│   │   │   ├── __init__.py
│   │   │   ├── docx_adapter.py      # DocX文档API适配器
│   │   │   ├── drive_adapter.py     # 云盘文件API适配器
│   │   │   └── board_adapter.py     # 白板API适配器
│   │   ├── parsers/             # 解析层：内容格式转换
│   │   │   ├── __init__.py
│   │   │   ├── docx_parser.py       # DocX块解析为Markdown
│   │   │   ├── block_parser.py      # 通用块解析器
│   │   │   └── whiteboard_parser.py # 白板节点解析器
│   │   ├── processors/          # 业务处理层：复杂业务逻辑
│   │   │   ├── __init__.py
│   │   │   ├── nested_processor.py  # 嵌套文档处理器
│   │   │   ├── resource_processor.py # 资源文件处理器
│   │   │   └── link_processor.py    # 云链接处理器
│   │   ├── downloaders/         # 下载器层：文件类型专用下载器
│   │   │   ├── __init__.py
│   │   │   ├── base_downloader.py   # 下载器基类
│   │   │   ├── docx_downloader.py   # DocX文档下载器
│   │   │   ├── sheet_downloader.py  # 表格下载器
│   │   │   ├── bitable_downloader.py # 多维表格下载器
│   │   │   ├── file_downloader.py   # 普通文件下载器
│   │   │   ├── slides_downloader.py # 演示文稿下载器（占位）
│   │   │   └── mindnote_downloader.py # 思维笔记下载器（占位）
│   │   ├── registry/            # 注册表：类型路由管理
│   │   │   ├── __init__.py
│   │   │   └── downloader_registry.py # 下载器注册表
│   │   ├── middleware/          # 中间件：横切关注点
│   │   │   ├── __init__.py
│   │   │   ├── auth_middleware.py   # 认证中间件
│   │   │   ├── retry_middleware.py  # 重试中间件
│   │   │   ├── logging_middleware.py # 日志中间件
│   │   │   └── metrics_middleware.py # 指标中间件
│   │   ├── queue/               # 队列系统：并发控制
│   │   │   ├── __init__.py
│   │   │   ├── task_queue.py        # 任务队列
│   │   │   ├── worker_pool.py       # 工作线程池
│   │   │   └── rate_limiter.py      # 速率限制器
│   │   ├── api_client.py        # 统一API客户端
│   │   ├── sync_engine.py       # 同步引擎主控制器
│   │   └── change_detector.py   # 变更检测器
│   ├── storage/                 # 存储层：本地文件管理
│   │   ├── __init__.py
│   │   ├── local_storage.py         # 本地存储管理器
│   │   ├── path_manager.py          # 路径管理器
│   │   └── file_manager.py          # 文件操作管理器
│   ├── utils/                   # 工具模块：通用工具函数
│   │   ├── __init__.py
│   │   ├── file_type_detector.py    # 文件类型检测
│   │   ├── logger.py                # 日志工具
│   │   ├── token_validator.py       # Token验证工具
│   │   ├── url_parser.py            # URL解析工具
│   │   └── exceptions.py            # 自定义异常类
│   ├── config/                  # 配置管理
│   │   ├── __init__.py
│   │   ├── settings.py              # 配置管理器
│   │   └── defaults.py              # 默认配置
│   ├── auth/                    # 认证模块
│   │   ├── __init__.py
│   │   ├── oauth_server.py          # OAuth认证服务器
│   │   └── token_manager.py         # Token管理器
│   └── commands/                # 命令行接口
│       ├── __init__.py
│       ├── sync_command.py          # 同步命令
│       └── history_command.py       # 历史记录命令
├── tests/                       # 测试用例
│   ├── __init__.py
│   ├── unit/                    # 单元测试
│   │   ├── test_downloaders/        # 下载器测试
│   │   ├── test_parsers/            # 解析器测试
│   │   └── test_processors/         # 处理器测试
│   ├── integration/             # 集成测试
│   │   ├── test_sync_flow.py        # 同步流程测试
│   │   └── test_api_integration.py  # API集成测试
│   └── fixtures/                # 测试数据
├── docs/                        # 项目文档
│   ├── api_reference.md             # API参考文档
│   ├── architecture.md             # 架构设计文档
│   └── development_guide.md        # 开发指南
├── config/                      # 配置文件
│   ├── config.yaml                  # 主配置文件
│   └── config.example.yaml         # 配置示例文件
├── requirements.txt             # Python依赖
├── setup.py                     # 安装脚本
├── README.md                    # 项目说明
└── .gitignore                   # Git忽略文件
```

### 核心模块职责说明

#### 适配器层 (Adapters)
- **职责**：封装飞书Open API调用，提供统一的接口抽象
- **设计原则**：单一职责，只负责API调用和响应处理，不包含业务逻辑
- **关键模块**：
  - `docx_adapter.py`：DocX文档相关API（获取文档、获取块、批量查询等）
  - `drive_adapter.py`：云盘文件API（文件下载、媒体下载、导出任务等）
  - `board_adapter.py`：白板API（获取节点、下载图片等）

#### 解析器层 (Parsers)
- **职责**：将飞书格式内容转换为标准格式（如Markdown）
- **设计原则**：纯函数式设计，无副作用，专注格式转换
- **关键模块**：
  - `docx_parser.py`：DocX块结构解析为Markdown
  - `block_parser.py`：通用块类型解析器
  - `whiteboard_parser.py`：白板节点解析器

#### 处理器层 (Processors)
- **职责**：处理复杂业务逻辑，如嵌套文档、资源管理、链接解析
- **设计原则**：业务逻辑封装，支持递归和异步处理
- **关键模块**：
  - `nested_processor.py`：嵌套文档递归处理
  - `resource_processor.py`：图片、附件等资源处理
  - `link_processor.py`：云链接识别和处理

#### 下载器层 (Downloaders)
- **职责**：文件类型专用的下载和处理逻辑
- **设计原则**：每种文件类型一个下载器，统一接口，独立实现
- **接口规范**：
  ```python
  class BaseDownloader:
      def execute(self, task: DownloadTask) -> DownloadResult:
          """执行下载任务的统一接口"""
          pass
  ```

#### 注册表系统 (Registry)
- **职责**：管理文件类型到下载器的映射关系
- **功能特性**：
  - 动态注册和注销下载器
  - 支持下载器开关控制
  - 提供类型路由和验证

#### 中间件系统 (Middleware)
- **职责**：处理横切关注点，如认证、重试、日志、指标
- **设计模式**：管道模式，支持前置和后置处理
- **扩展性**：支持自定义中间件插件

### 命名规范与约定

#### 文件和类命名
- **下载器**：类名 `XxxDownloader`，文件名 `xxx_downloader.py`
- **适配器**：类名 `XxxAdapter`，文件名 `xxx_adapter.py`  
- **解析器**：类名 `XxxParser`，文件名 `xxx_parser.py`
- **处理器**：类名 `XxxProcessor`，文件名 `xxx_processor.py`

#### 接口约定
- **下载器接口**：`execute(task: DownloadTask) -> DownloadResult`
- **解析器接口**：`parse(content: Any) -> str`
- **处理器接口**：`process(data: Any, context: ProcessContext) -> ProcessResult`

#### 异常处理规范
- **网络异常**：`NetworkError`（可重试）
- **API异常**：`ApiError`（根据错误码决定重试）
- **解析异常**：`ParseError`（不可重试）
- **存储异常**：`StorageError`（可重试）
- **配置异常**：`ConfigError`（不可重试）

### 存储约定
- **根目录**：`output/` 作为同步输出根目录
- **资源目录**：
  - `images/`：图片资源
  - `attachments/`：附件文件
  - `nested_docs/`：嵌套文档
- **引用方式**：使用相对路径引用，便于目录迁移

### 开发阶段规划
1. **基础架构阶段**：建立核心框架、注册表、中间件系统
2. **核心功能阶段**：实现DocX和普通文件下载器
3. **扩展功能阶段**：实现表格、多维表格下载器
4. **完善优化阶段**：性能优化、错误处理完善、监控告警

注：本规划与 `requirements.md` 中的文件类型支持清单保持一致，所有模块均为期望实现的目标架构。

## 命名规范与约定
- 模块命名：
  - 下载器类名：`XxxDownloader`；文件名：`xxx_downloader.py`（`xxx` 为文件类型）。
  - 适配器类名：`XxxAdapter`；文件名：`xxx_adapter.py`（如 `docx_adapter.py`）。
  - 解析器类名：`DocParser` 等；文件名统一为 `doc_parser.py`（DocX 入口）。
  - 处理器与桥接：`NestedDocProcessor`、`CloudLinkBridge`（过渡：`cloud_doc_processor.py`）。
- 接口约定：
  - 下载器统一暴露：`execute(task)`；`task` 字段包含 `file_type`、`token`、`target_path`、`options`。
  - 处理器提供：`process_url_to_markdown(url)`（嵌套云链接统一入口）。
  - 注册表：`get(file_type)` 返回下载器类；未启用或不支持时抛统一异常。
- 存储与引用：统一 `output/` 根目录；`nested_docs/`、`images/`、`attachments/`；相对路径引用。

## 错误分类与重试策略
- 异常分层：
  - `NetworkError`：网络错误与超时；可重试（指数退避）。
  - `ExportTaskError`：导出任务创建/轮询失败；可重试（固定/退避混合）。
  - `DownloadError`：文件/媒体下载失败；视状态码决定重试。
  - `UnsupportedTypeError` / `DisabledTypeError`：类型不支持或被禁用；不可重试，记录指标。
- 重试与背压：
  - 指数退避：`base=0.5s * 2^attempt`，最大退避 32s；封顶重试次数（默认 3）。
  - 轮询导出：固定周期（默认 2s），最大等待（默认 60s），状态机驱动。
  - 速率限制与并发：按类型并发上限与全局速率限制结合，避免雪崩重试。
- 结构化日志：
  - 统一字段：`{type, code, message, retryable, ctx}`；关键路径均打点。
  - 关键上下文：`file_type`、`doc_id`、`task_id`、`attempt`、`elapsed_ms`。

## 观测指标与基线
- 下载/导出链路：
  - 延迟：`export_poll_latency_ms`、`download_latency_ms`；
  - 成功率：`export_success_rate`、`download_success_rate`；
  - 重试：`retry_count`、`backoff_total_ms`。
- 解析/保存链路：
  - 解析耗时：`parse_latency_ms`；资源数：`parsed_blocks_count`、`nested_links_count`。
  - IO 指标：`write_bytes_total`、`write_ops_count`、`conflict_rename_count`。
- 队列与并发：
  - 等待时长：`queue_wait_ms`；并发占用：`concurrency_in_use{type}`；
  - 限流：`rate_limit_hits`；拒绝/降级：`drop_or_defer_count`。
- 验收基线（Checklist 对应）：形成“最小可用”的基线报表与图表汇总。

## 注册表路由示例（伪代码）
```
def process_task(task):
    # 前置中间件（鉴权/日志/重试上下文）
    task = pipeline.apply_pre(task)

    # 通过注册表取得下载器并执行
    DownloaderCls = registry.get(task.file_type)
    downloader = DownloaderCls(api_client, storage, options)
    result = downloader.execute(task)

    # 后置中间件（指标/日志/错误归类）
    result = pipeline.apply_post(result)

    # 如检测到嵌套链接，交由处理器递归
    if result.nested_links:
        for link in result.nested_links:
            processors.nested_doc_processor.process_url_to_markdown(link)
    return result
```

## 文件类型与处理策略（与 requirements.md 对齐）

### DocX 文档块类型支持清单（块级能力）
- 说明：DocX 文档块用于描述文档内部结构，不属于顶层文件类型；路由与文件类型清单参考 `requirements.md` 1.2.2。
- 期望支持块（解析为 Markdown 或资源文件）：
  - 页面与段落：`page`、`paragraph`
  - 标题：`heading1`-`heading6`（按 Markdown 1-6 级映射）
  - 列表：`bullet_list`、`ordered_list`
  - 代码块：`code`
  - 引用：`quote`
  - 图片：`image`（`medias` 下载接口）
  - 文件附件：`file_attachment`（Drive 下载接口）
  - 表格/网格：`table`、`grid_container`/`grid`
  - 待办（Todo）：`todo`
  - 分隔线：`divider`
  - 数学公式：`equation`
  - 白板：`whiteboard`（`block_type` 为 43，通过 Board API 获取节点并渲染为 Markdown）
  - 嵌套云链接：识别并递归处理（由嵌套处理器负责）
- 暂不支持或占位块：
  - 文档同步块：`doc_sync_block`（块类型，当前不展开；不作为文件类型参与路由）
  - 其他未知/灰度块：降级为原文或占位提示

注：本清单与 `larksync/core/doc_parser.py` 当前能力对齐，后续扩展将同步更新两处文档。
- 云文档（Docs）：
  - `docx`/`doc`：拉取 Blocks → 转 Markdown → 解析嵌套链接 → 递归下载。
  - `sheet`：创建导出任务 → 轮询 → 下载 `.xlsx`。
  - `bitable`：同 `sheet` 流程，导出 `.xlsx`。
- 上传文件：
  - `file`：原始文件流下载，保留原扩展名保存。
- 非文档节点：
  - `folder`：遍历与递归；不直接导出内容。
  - `shortcut`：跳过或解析目标（当前实现为跳过）。
- 暂不支持：
  - `wiki`、`doc_sync_block`：不纳入下载队列，保持显式日志与指标。
- 占位导出：
  - `slides`、`mindnote`：生成说明性 Markdown（可随官方导出能力演进）。

## 模块注册机制（伪代码）
```
class DownloaderRegistry:
    def __init__(self):
        self._map = {}
        self._enabled = {}

    def register(self, file_type, downloader_cls, enabled=True):
        self._map[file_type] = downloader_cls
        self._enabled[file_type] = enabled

    def get(self, file_type):
        if not self._enabled.get(file_type, False):
            raise DisabledTypeError(file_type)
        cls = self._map.get(file_type)
        if not cls:
            raise UnsupportedTypeError(file_type)
        return cls

registry = DownloaderRegistry()
registry.register('docx', DocxDownloader)
registry.register('sheet', SheetDownloader)
registry.register('bitable', BitableDownloader)
registry.register('file', FileDownloader)
# whiteboard已移除：现为DocX文档中的block type，不再作为独立文件类型
registry.register('slides', SlidesPlaceholderDownloader)
registry.register('mindnote', MindnotePlaceholderDownloader)
registry.register('wiki', None, enabled=False)
registry.register('folder', None, enabled=False)
registry.register('shortcut', None, enabled=False)
```

## 中间件管线（伪代码）
```
class MiddlewarePipeline:
    def __init__(self, pre=None, post=None):
        self.pre = pre or []
        self.post = post or []

    def run(self, task, executor):
        for mw in self.pre:
            task = mw.before(task)
        result = executor(task)
        for mw in reversed(self.post):
            result = mw.after(result)
        return result

class AuthMW:
    def before(self, task):
        validate_token(task.credentials)
        return task
    def after(self, result):
        return result

class RetryMW:
    def before(self, task):
        task.retry_ctx = { 'attempt': 0, 'max': task.max_retry }
        return task
    def after(self, result):
        if result.failed and result.retryable and result.task.retry_ctx['attempt'] < result.task.retry_ctx['max']:
            backoff_sleep(result.task.retry_ctx['attempt'])
            return rerun_task(result.task)
        return result
```

## 任务队列与并发控制（伪代码）
```
class PriorityTask:
    def __init__(self, file_type, token, priority=5):
        self.file_type = file_type
        self.token = token
        self.priority = priority

class DownloadQueue:
    def __init__(self):
        self._heap = []
    def put(self, task):
        heapq.heappush(self._heap, (task.priority, time.time(), task))
    def get(self):
        _, _, task = heapq.heappop(self._heap)
        return task

class WorkerPool:
    def __init__(self, limits):  # limits: {'docx':3,'sheet':2,...}
        self.limits = limits
        self.running = defaultdict(int)

    def can_run(self, file_type):
        return self.running[file_type] < self.limits.get(file_type, 1)

    def run(self, queue, registry, pipeline):
        while not queue.empty():
            task = queue.get()
            if not self.can_run(task.file_type):
                queue.defer(task)  # 放回队列或调低优先级
                continue
            self.running[task.file_type] += 1
            try:
                downloader = registry.get(task.file_type)()
                pipeline.run(task, downloader.execute)
            finally:
                self.running[task.file_type] -= 1
```

## 错误、重试与幂等
- 异常分级：`NetworkError`、`ExportTaskError`、`DownloadError`、`UnsupportedTypeError`、`DisabledTypeError`。
- 重试策略：指数退避（如 0.5s、1s、2s、4s…）、最大尝试次数、可重试条件（HTTP 5xx/网络异常/导出任务暂不可用）。
- 幂等性：导出任务使用 `idempotency_key`；保存时使用安全文件名与冲突重命名。
- 可观测性：失败分布（类型、阶段、错误码）、重试次数与持续时间，支撑容量与稳定性评估。

## 配置示例（与 requirements.md 对齐）
```
concurrency:
  docx: 3
  sheet: 2
  bitable: 2
  file: 4
  # whiteboard已移除：现为DocX文档中的block type

rate_limit:
  docx: 5 rpm
  sheet: 3 rpm
  bitable: 3 rpm
  file: 20 rpm
  # whiteboard已移除：现为DocX文档中的block type

features:
  slides_placeholder: true
  mindnote_placeholder: true
  wiki_support: false

storage:
  root: ./output
  nested_dir: nested_docs
  images_dir: images
  attachments_dir: attachments

logging:
  level: info
  structured: true
```

## 监控指标字段（最小集）
- 维度：`file_type`、`token`、`stage`（meta/export/poll/download/parse/save）、`attempt`、`duration_ms`、`status`（success/fail）、`error_code`、`message`。
- 聚合：成功率、失败率、平均/分位耗时、重试分布、类型对（导出任务 vs 文档块）。

## API 映射（关键）
- 文档与块：`/open-apis/docx/v1/documents/{id}`、`/open-apis/docx/v1/documents/{id}/blocks`、`/open-apis/docx/v1/blocks/{block_id}`。
- 导出任务：`/open-apis/drive/v1/export_tasks`、`/open-apis/drive/v1/export_tasks/{ticket}`、`/open-apis/drive/v1/export_tasks/file/{file_token}/download`。
- 文件下载：`/open-apis/drive/v1/files/{file_token}/download`；媒体/附件：`/open-apis/drive/v1/medias/{image_token}/download`。
- 白板：`/open-apis/board/v1/whiteboards/{whiteboard_id}/nodes`、`/open-apis/board/v1/whiteboards/{whiteboard_id}/download_as_image`（用于DocX文档中的whiteboard block处理）。
- 元信息查询：`/open-apis/drive/v1/metas/batch_query`（类型确认与路由依赖）。

## 存储策略
- 资源目录统一：`images/` 与 `attachments/`，嵌套文档独立 `nested_docs/` 路径。
- 大文件分块写入、断点续传（按需）、冲突重命名，保证 Windows 路径安全。
- 嵌套 Markdown 引用相对路径，便于目录迁移与拆分。

## 测试与验收
- 单测：类型下载器的导出/下载/解析与保存；错误分级与重试；中间件管线的前/后序钩子。
- 集成：任务队列并发与速率限制；嵌套文档递归；存储层写入与路径安全。
- 验收：对齐 `requirements.md` 1.2.2 支持列表与 3.1.2 处理分类，成功率≥95%、关键类型端到端耗时与指标达标。

## 风险与限制
- 官方 `slides`/`mindnote` 导出能力缺失，当前采用说明性 Markdown 占位。
- `wiki` 与 `doc_sync_block` 暂不支持纳入下载流程，保持显式日志与指标以便后续评估。
- API 限流与大流量并发场景需按部署环境调优队列与速率参数。

## 迭代计划（示例）
- M1：落地注册表与类型模块拆分，完成 docx/file。
- M2：接入队列与并发控制，打通 sheet/bitable 导出链路。
- M3：完善DocX文档中whiteboard block的解析与图片下载，嵌套递归稳定化。
- M4：slides/mindnote 能力跟踪，如官方导出开放则替换占位实现。
- M5：监控与告警完善，形成容量评估与稳定性报告。

---

与 `requirements.md` 保持一致：类型定义、支持状态与分类说明以 1.2.2 与 3.1.2 为准；本文档仅描述实现路径与工程细节。