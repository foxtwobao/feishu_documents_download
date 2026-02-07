# 飞书文档信息获取流程分析

## 一、整体架构概览

项目采用分层架构设计，主要包含以下核心组件：

```
CLI/Web入口 → SyncEngine → Downloader → Adapter → FeishuAPIClient → 飞书API
                ↓              ↓            ↓
            Registry      Parser      Storage
```

## 二、主要流程

### 2.1 入口点

#### CLI 入口 (`larksync/cli.py`)
- **命令**: `download` 或 `download-docx`
- **流程**:
  1. 解析文档 token（从 URL 或直接 token）
  2. 构建 `SyncTask` 对象
  3. 调用 `SyncEngine.process_task()` 处理任务

```43:87:larksync/cli.py
@app.command("download")
def download(
    token: str = typer.Argument(..., help="Feishu document token or full URL"),
    file_type: str = typer.Option("docx", "--type", "-t", help="Document file type, e.g. docx, doc"),
    name: str | None = typer.Option(None, "--name", "-n", help="Override output filename (without extension)"),
    config_path: Path | None = typer.Option(None, "--config", "-c", help="Path to config.toml"),
) -> None:
    """Download a single document and convert/store locally."""

    file_type = file_type.lower()
    source_url: str | None = None
    parsed_token = token
    if "://" in token:
        source_url = token.strip()
        parsed_token = token.rstrip("/").split("/")[-1]
        parsed_token = parsed_token.split("?")[0].split("#")[0]
    else:
        parsed_token = token.split("?")[0].split("#")[0]

    config, engine = _build_engine(config_path)
    task_name = name or parsed_token
    task = SyncTask(
        token=parsed_token,
        file_type=file_type,
        name=task_name,
        parent_path=Path("."),
        extra={"source_url": source_url} if source_url else {},
    )
    success = False
    try:
        engine.process_task(task)
        success = True
    except KeyError as exc:
        typer.secho(str(exc), fg=typer.colors.RED)
        raise typer.Exit(code=1) from exc
    except FeishuAPIError as exc:
        payload = exc.payload or {}
        if exc.status_code == 400 and payload.get("code") == 1770003:
            typer.secho("目标资源已在飞书端删除，跳过下载。", fg=typer.colors.YELLOW)
            return
        raise
    finally:
        engine.close()
    if success:
        typer.echo(f"Downloaded {file_type} {token} → {config.storage.root}")
```

### 2.2 运行时初始化 (`larksync/bootstrap.py`)

```25:42:larksync/bootstrap.py
def build_runtime(config_path: Path | None = None) -> Tuple[LarkSyncConfig, FeishuAPIClient, StorageManager, DownloaderRegistry]:
    """Instantiate core components needed for running the sync engine."""

    config = load_config(config_path)
    client = FeishuAPIClient.from_config(config)
    storage = StorageManager(config.storage)
    registry = DownloaderRegistry()
    registry.register("docx", DocxDownloader)
    registry.register("doc", DocxDownloader)
    registry.register("sheet", SheetDownloader)
    registry.register("bitable", BitableDownloader)
    registry.register("file", FileDownloader)
    registry.register("folder", FolderDownloader)
    registry.register("shortcut", ShortcutDownloader)
    registry.register("wiki", WikiDownloader)
    registry.register("slides", SlidesPlaceholderDownloader)
    registry.register("mindnote", MindnotePlaceholderDownloader)
    return config, client, storage, registry
```

### 2.3 同步引擎 (`larksync/core/sync_engine.py`)

**核心职责**:
- 协调下载任务执行
- 管理适配器和解析器
- 支持并发处理

```87:99:larksync/core/sync_engine.py
    def process_task(self, task: SyncTask) -> None:
        logger.debug("Processing sync task", extra={"token": task.token, "file_type": task.file_type})
        context = DownloaderContext(
            config=self._config,
            client=self._client,
            storage=self._storage,
            docx_adapter=self._docx_adapter,
            drive_adapter=self._drive_adapter,
            docx_parser=self._docx_parser,
            registry=self._registry,
        )
        downloader = self._registry.build(task.file_type, context)
        downloader.execute(task)
```

## 三、DocX 文档获取详细流程

### 3.1 DocX 下载器 (`larksync/core/downloaders/docx_downloader.py`)

#### 主要步骤：

1. **获取文档元信息**
   ```python
   document = self.docx_adapter.get_document(task.token)
   ```
   - 调用 `GET /open-apis/docx/v1/documents/{document_id}`

2. **获取文档块（Blocks）**
   ```python
   blocks = list(self.docx_adapter.iter_blocks(task.token))
   ```
   - 调用 `GET /open-apis/docx/v1/documents/{document_id}/blocks`
   - 支持分页获取（默认每页 200 条）

3. **解析文档为 Markdown**
   ```python
   parse_result = self.docx_parser.parse(doc_meta, blocks)
   ```
   - 将飞书文档块结构转换为 Markdown
   - 提取图片、附件、嵌套链接等资源

4. **下载资源文件**
   - 图片：并发下载（最多 5 个并发）
   - 附件：并发下载（最多 5 个并发）
   - 白板：下载图片和 JSON 数据

5. **处理嵌套引用**
   - 提取文档中的嵌套链接（其他文档引用）
   - 递归下载引用的文档（受深度限制）

6. **保存 Markdown 文件**
   - 替换占位符为实际资源路径
   - 写入存储目录

```56:102:larksync/core/downloaders/docx_downloader.py
    def download(self, task: SyncTask) -> None:  # noqa: D401 - doc inherited
        document = self.docx_adapter.get_document(task.token)
        blocks = list(self.docx_adapter.iter_blocks(task.token))
        data = document.get("data", {})
        doc_meta: Mapping[str, object] = data.get("document") or data

        parse_result = self.docx_parser.parse(doc_meta, blocks)

        output_name = self._resolve_output_name(task, doc_meta)
        relative_base = task.parent_path / output_name
        doc_dir = self.storage.root / relative_base
        asset_dirs = self._prepare_asset_dirs(doc_dir)

        history: Set[str] = set()
        depth = 0
        if isinstance(task.extra, dict):
            history.update(task.extra.get("_history", []))
            raw_depth = task.extra.get("_depth")
            if isinstance(raw_depth, int):
                depth = raw_depth
            else:
                try:
                    depth = int(raw_depth)
                except (TypeError, ValueError):
                    depth = 0
        history.add(task.token)

        # Markdown 文件路径（用于计算相对路径）
        markdown_path = self.storage.target_path(relative_base.with_suffix(".md"))

        markdown = self._finalize_markdown(task, doc_meta, parse_result, asset_dirs, markdown_path)

        self.storage.write_text(markdown_path, markdown)
        register_resolved_path(task.token, markdown_path)

        references = self._extract_references(parse_result)
        referenced = self._download_referenced_docx(
            references,
            asset_dirs["refer_docx"],
            depth,
            history,
            task,
            markdown_path,
        )
        if referenced:
            self._replace_reference_links(markdown_path, referenced)
```

### 3.2 DocX 适配器 (`larksync/core/adapters/docx_adapter.py`)

**职责**: 封装飞书 DocX API 调用

```16:36:larksync/core/adapters/docx_adapter.py
    def get_document(self, document_id: str) -> Mapping[str, Any]:
        return self._client.get(f"/open-apis/docx/v1/documents/{document_id}")

    def get_block(self, document_id: str, block_id: str) -> Mapping[str, Any]:
        return self._client.get(f"/open-apis/docx/v1/documents/{document_id}/blocks/{block_id}")

    def iter_blocks(self, document_id: str, page_size: int = 200) -> Iterator[Mapping[str, Any]]:
        page_token: Optional[str] = None
        while True:
            params: Dict[str, Any] = {"page_size": page_size}
            if page_token:
                params["page_token"] = page_token
            response = self._client.get(f"/open-apis/docx/v1/documents/{document_id}/blocks", params=params)
            data = response.get("data", {})
            items = data.get("items", [])
            for item in items:
                yield item

            page_token = data.get("page_token") or data.get("next_page_token")
            if not page_token:
                break
```

**API 端点**:
- `GET /open-apis/docx/v1/documents/{document_id}` - 获取文档元信息
- `GET /open-apis/docx/v1/documents/{document_id}/blocks` - 获取文档块（分页）

### 3.3 DocX 解析器 (`larksync/core/parsers/docx_parser.py`)

**职责**: 将飞书文档块结构转换为 Markdown

**主要功能**:
1. **块类型识别**: 支持 50+ 种块类型（标题、段落、列表、表格、图片等）
2. **富文本渲染**: 处理文本样式（粗体、斜体、链接等）
3. **资源提取**: 识别图片、附件、白板等资源
4. **嵌套链接提取**: 提取文档中的其他文档链接

```219:252:larksync/core/parsers/docx_parser.py
    def parse(self, document_meta: Mapping[str, object], blocks: Sequence[Mapping[str, object]]) -> DocxParseResult:
        self._builder.reset()
        self._images.clear()
        self._attachments.clear()
        self._nested_links.clear()
        self._consumed_blocks.clear()
        self._whiteboards.clear()
        self._block_index = {
            str(block.get("block_id")): block for block in blocks if isinstance(block.get("block_id"), str)
        }
        self._children_index.clear()
        for block in blocks:
            parent_id = str(block.get("parent_id") or "")
            self._children_index.setdefault(parent_id, []).append(block)

        title = str(document_meta.get("title") or "").strip()
        if title:
            self._builder.add_heading(1, title)

        roots = [block for block in blocks if self._normalise_block_type(block) == "page"]
        if roots:
            for root in roots:
                self._render_block_tree(root, parent_type=None, list_level=0)
        for block in self._children_index.get("", []):
            self._render_block_tree(block, parent_type=None, list_level=0)

        markdown = self._builder.build()
        return DocxParseResult(
            markdown=markdown,
            images=list(self._images),
            attachments=list(self._attachments),
            nested_links=sorted(self._nested_links),
            whiteboards=list(self._whiteboards),
        )
```

## 四、API 客户端 (`larksync/core/api_client.py`)

**职责**: 底层 HTTP 请求处理

**核心功能**:
1. **认证**: 自动获取和刷新 user access token
2. **限流**: 根据 API 类型应用不同的速率限制
3. **重试**: 处理临时错误和速率限制
4. **连接池**: 优化大量请求的性能

```110:112:larksync/core/api_client.py
    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        response = self._request("GET", path, params=params)
        return response.json()
```

**请求流程**:
1. 构建请求头（包含 Authorization）
2. 应用速率限制
3. 发送 HTTP 请求
4. 处理错误和重试
5. 返回响应

## 五、Drive 适配器 (`larksync/core/adapters/drive_adapter.py`)

**职责**: 封装文件、媒体和导出任务相关的 API

**主要方法**:
- `download_file()` - 下载文件
- `download_media()` - 下载媒体（图片）
- `batch_get_metadata()` - 批量获取文档元数据
- `create_export_task()` - 创建导出任务（用于 Sheet/Bitable）

```44:47:larksync/core/adapters/drive_adapter.py
    def batch_get_metadata(self, docs: Iterable[tuple[str, str]]) -> Mapping[str, Any]:
        request_docs = [{"doc_token": token, "doc_type": doc_type} for token, doc_type in docs]
        payload = {"request_docs": request_docs}
        return self._client.post("/open-apis/drive/v1/metas/batch_query", json=payload)
```

## 六、关键文件清单

### 6.1 核心流程文件
- `larksync/cli.py` - CLI 入口
- `larksync/bootstrap.py` - 运行时初始化
- `larksync/core/sync_engine.py` - 同步引擎
- `larksync/core/downloaders/docx_downloader.py` - DocX 下载器

### 6.2 API 封装文件
- `larksync/core/api_client.py` - HTTP 客户端
- `larksync/core/adapters/docx_adapter.py` - DocX API 适配器
- `larksync/core/adapters/drive_adapter.py` - Drive API 适配器

### 6.3 解析和转换文件
- `larksync/core/parsers/docx_parser.py` - DocX 到 Markdown 解析器

### 6.4 存储和注册文件
- `larksync/storage/manager.py` - 存储管理器
- `larksync/core/registry/registry.py` - 下载器注册表

### 6.5 配置和工具文件
- `larksync/config.py` - 配置管理
- `larksync/utils/rate_limit.py` - 速率限制工具

## 七、数据流图

```
用户输入 token
    ↓
CLI 解析 token → 创建 SyncTask
    ↓
SyncEngine.process_task()
    ↓
DownloaderRegistry.build() → 获取 DocxDownloader
    ↓
DocxDownloader.execute()
    ↓
├─→ DocxAdapter.get_document() → FeishuAPIClient.get() → 飞书API
│   └─→ 返回文档元信息
│
├─→ DocxAdapter.iter_blocks() → FeishuAPIClient.get() → 飞书API
│   └─→ 返回文档块列表（分页）
│
├─→ DocxParser.parse() → 解析块结构
│   ├─→ 提取文本内容 → 生成 Markdown
│   ├─→ 提取图片资源
│   ├─→ 提取附件资源
│   └─→ 提取嵌套链接
│
├─→ DriveAdapter.download_media() → 下载图片
│   └─→ 并发下载（最多5个）
│
├─→ DriveAdapter.download_file() → 下载附件
│   └─→ 并发下载（最多5个）
│
├─→ 处理嵌套引用文档
│   └─→ 递归调用 downloader.execute()
│
└─→ StorageManager.write_text() → 保存 Markdown 文件
```

## 八、关键 API 端点

### 8.1 DocX 相关
- `GET /open-apis/docx/v1/documents/{document_id}` - 获取文档元信息
- `GET /open-apis/docx/v1/documents/{document_id}/blocks` - 获取文档块（分页）

### 8.2 Drive 相关
- `GET /open-apis/drive/v1/files/{file_token}/download` - 下载文件
- `GET /open-apis/drive/v1/medias/{image_token}/download` - 下载媒体
- `POST /open-apis/drive/v1/metas/batch_query` - 批量查询元数据
- `POST /open-apis/drive/v1/export_tasks` - 创建导出任务
- `GET /open-apis/drive/v1/export_tasks/{ticket}` - 查询导出任务状态

### 8.3 Board 相关
- `GET /open-apis/board/v1/whiteboards/{whiteboard_id}/download_as_image` - 下载白板图片
- `GET /open-apis/board/v1/whiteboards/{whiteboard_id}/nodes` - 获取白板节点

## 九、性能优化特性

1. **并发下载**: 图片和附件使用线程池并发下载（最多5个并发）
2. **批量查询**: 嵌套文档元数据使用批量查询 API
3. **连接池**: HTTP 客户端使用连接池优化性能
4. **速率限制**: 根据 API 类型应用不同的速率限制规则
5. **分页处理**: 文档块使用分页获取，避免单次请求过大

## 十、错误处理

1. **API 错误**: 捕获 `FeishuAPIError`，处理特定错误码（如 1770003 表示资源已删除）
2. **资源下载失败**: 记录警告日志，在 Markdown 中使用占位符
3. **嵌套引用失败**: 创建错误占位符文件，不中断主流程
4. **重试机制**: 对临时错误（429, 502, 503, 504）自动重试

## 十一、总结

项目通过清晰的分层架构实现了飞书文档的下载和转换：

1. **入口层**: CLI 命令解析和任务创建
2. **编排层**: SyncEngine 协调任务执行
3. **下载层**: 各种类型的下载器实现
4. **适配层**: 封装飞书 API 调用
5. **解析层**: 将飞书文档结构转换为 Markdown
6. **存储层**: 管理文件保存和元数据

整个流程支持：
- 单文档下载
- 批量同步
- 嵌套文档递归下载
- 资源文件（图片、附件）下载
- 白板导出
- 增量同步




