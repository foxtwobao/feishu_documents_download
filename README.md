# LarkSync

LarkSync 提供 **命令行同步工具** 与 **浏览器 Web UI** 两套体验，用于从飞书个人云空间和知识库批量下载文档、表格、附件等内容，并在本地生成 Markdown 或原始文件。核心特性包括：

- DocX/Doc → Markdown，自动处理图片、附件、公式、白板以及嵌套的 Feishu 链接。
- Sheet/Bitable 导出为 `.xlsx`，普通 `file` 类型直接下载，Slides/Mindnote/Wiki 生成说明性 Markdown 或占位符。
- Folder、Shortcut 递归遍历；Wiki 支持首次下载实体，后续生成指向本地的占位说明。
- `sync-space` 支持个人云空间整库遍历，并在 `output/.metadata.json` 记录增量状态。
- `sync-wiki` 支持知识库整库遍历，自动保持知识库层级结构。
- **多用户 Web 同步系统**：支持飞书 OAuth 登录，每个用户独立存储和元数据库，支持定时/间隔自动同步与排队执行。
- Web UI 与 CLI 共用一套 OAuth 流程，可通过浏览器授权后让多个终端复用同一个回调服务。
- CLI 与 Web 数据完全隔离，互不影响。

更多背景与规划参见仓库内的 `requirement.md`、`technique.md`。

## 环境要求

- Python 3.11 及以上
- Node.js 18 LTS（仅 Web UI 需要）
- 飞书开放平台凭据：`user_access_token` 或配置完整的 OAuth 应用（`app_id`/`app_secret`）

## 安装

### 后端 / CLI

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e .

# 可选：安装测试依赖
pip install -e ".[dev]"
```

### 前端（Web UI）

```bash
cd webui-client
npm install
```

开发阶段在仓库根目录运行脚本启动服务（单端口架构，统一访问 8000 端口）：

```bash
./scripts/start_dev.sh   # 访问 http://localhost:8000
```

脚本会：
- 启动 Next.js 开发服务器（内部端口 3001，不对外暴露）
- 启动 FastAPI 并反向代理前端请求到 Next.js

生产模式需先构建前端，然后只启动 FastAPI：

```bash
# 构建前端
cd webui-client && npm run build && cd ..

# 启动服务
source .venv/bin/activate
uvicorn larksync.web.app:create_app --factory --host 0.0.0.0 --port 8000
```

## 配置

LarkSync 默认读取仓库根目录的 `config.toml`。可通过环境变量 `LARKSYNC_CONFIG` 指定其它路径。示例配置：

```toml
[auth]
# CLI 模式可直接填 user_access_token；启用 OAuth 时配置 app_id/app_secret
app_id = "your_app_id"
app_secret = "your_app_secret"
user_access_token = "YOUR_USER_ACCESS_TOKEN"
# CLI OAuth 回调（转发到本地 8899 端口）
# oauth_callback_url = "https://cli-callback.example.com/auth/callback"
# oauth_service_base_url = "https://callback.example.com"

[storage]
root = "./output"
download_root = "./output"  # 统一控制 CLI/Web 下载目录（可选，CLI 用 {root}/cli，Web 用 {root}/web）
nested_dir = "nested_docs"
images_dir = "images"
attachments_dir = "attachments"
preserve_remote_structure = true

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

[web]
enabled = true
database_url = "sqlite:////data/web/larksync.db"  # 多用户系统数据库
# user_storage_base = "./data/web/users"            # 用户数据存储根目录
# allow_download_user_ids = "*"                      # 允许使用系统的用户白名单（逗号分隔；"*" 表示全部允许）
# allow_download_wiki_user_ids = "ou_xxx,ou_yyy"     # 允许配置知识库同步的用户白名单（逗号分隔）
# secret_key = "change-me"

[web.oauth]
app_id = "your_app_id"
app_secret = "your_app_secret"
callback_url = "http://localhost:8000/api/auth/callback"  # 必须与 CLI 回调不同
token_refresh_margin_minutes = 10

[web.scheduler]
check_interval = 60              # 调度器检查间隔（秒）
token_refresh_interval = 300     # Token 自动刷新间隔（秒）
force_queue = true              # 强制排队执行（默认 true）
max_concurrent_jobs = 3          # 最大并发同步任务
```

### 关键配置说明

- `[auth]`（CLI 配置）
  - `user_access_token`：直接使用 Feishu 用户访问令牌（适合纯 CLI 场景）。
  - `app_id` / `app_secret`：启用 OAuth 时必填；CLI 可执行 `larksync login` 触发浏览器授权。
  - `oauth_callback_url`：CLI OAuth 回调地址，CLI 会启动本地服务器（8899 端口）接收授权码。如使用反向代理，需将此 URL 转发到本地 8899 端口。
  - `oauth_service_base_url`：CLI 授权所依赖的 Web 服务地址；未显式设置时自动继承 `web.oauth.base_url`。
- `[web]` / `[web.oauth]` / `[web.scheduler]`（Web 配置）
  - `enabled = true` 启用 FastAPI Web API 与多用户同步系统。
  - `database_url`：多用户系统数据库（存储用户、同步配置、执行记录），默认 SQLite。
- `user_storage_base`：用户数据存储根目录，每个用户数据保存在 `{user_storage_base}/{feishu_user_id}/` 下。
- `allow_download_user_ids`：允许使用系统的用户白名单（Feishu user_id，逗号分隔；`*` 表示全部允许）。未配置或不包含当前用户时，Web 端提示无权限使用系统。
- `allow_download_wiki_user_ids`：允许配置知识库同步的用户白名单（Feishu user_id，逗号分隔）；未配置或不包含当前用户时，Web 端禁用知识库同步。
- `callback_url`：Web OAuth 回调地址，**必须与 CLI 的 `oauth_callback_url` 不同**。需将此 URL 转发到 Web 服务的 8000 端口。
  - `token_refresh_margin_minutes`：Token 过期前多少分钟自动刷新。
  - `[web.scheduler]`：定时任务调度器配置，支持 Cron 和固定间隔两种调度方式。
  - `force_queue`：强制同步任务按队列串行执行（默认 true）。
- 常用环境变量覆盖：
  - `LARKSYNC_USER_ACCESS_TOKEN`、`LARKSYNC_STORAGE_ROOT`、`LARKSYNC_LOG_LEVEL`。
  - `LARKSYNC__WEB__OAUTH__BASE_URL=https://demo.example.com` 可覆盖嵌套字段。
  - 开发模式可通过 `FRONTEND_DEV_URL` 指定 Next.js 开发服务器地址（通常由 `start_dev.sh` 自动设置）。
- 调整 CLI 日志噪音（例如复制授权链接时）：

  ```bash
  LARKSYNC_LOG_LEVEL=ERROR larksync login
  ```

## 使用方式

### CLI 命令

- **OAuth 流程**
  ```bash
  larksync login          # 通过浏览器授权，token 写入 ~/.larksync/token_cache.json
  larksync token-status   # 查看缓存 token 的有效期/状态
  larksync logout         # 清空缓存，准备重新授权
  ```

- **下载单个资源**
  ```bash
  # DocX / Doc
  larksync download --type docx <token 或完整 URL>

  # Sheet / Bitable / File 等
  larksync download --type sheet <token>
  larksync download --type bitable <token>
  larksync download --type file <token>

  # 指定配置文件
  larksync download --config ./config.toml --type docx <token>
  ```

  生成的目录结构示例：
  ```
  output/
    └── 示例文档/
        ├── 示例文档.md
        ├── images/
        ├── attachments/
        └── ...
  ```

- **遍历个人空间（增量/批量）**
  ```bash
  # 下载前 50 个可访问文件 / 子目录（默认启用增量）
  larksync sync-space --config config.toml --limit 50

  # 取消限制并强制全量
  larksync sync-space --config config.toml --limit 0 --full

  # 仅重建 metadata（清空缓存）
  larksync sync-space --config config.toml --limit 0 --reset-metadata

  # 临时关闭增量
  larksync sync-space --config config.toml --no-incremental

  # 静默模式（仅显示进度）
  larksync sync-space --quiet
  ```

  该命令会：
  - 基于 `limit` 控制下载条数。
  - 在 `output/.metadata.json` 记录 `token`、`file_type`、`parent_path`、`modified_time`、`local_path` 等字段，用于增量判定。
  - 本地缺失文件自动补齐；云端删除的条目可根据 `clean_deleted` 决定是否清理或标记。
  - 遇到权限不足/无法导出的资源时写入占位 Markdown 并记录日志。

- **遍历知识库（增量/批量）**
  ```bash
  # 列出可访问的知识库
  larksync sync-wiki --list

  # 同步指定知识库（默认完整遍历）
  larksync sync-wiki --space-id <SPACE_ID>

  # 完整同步（无数量限制，与默认行为一致）
  larksync sync-wiki --space-id <SPACE_ID> --limit 0

  # 强制全量同步
  larksync sync-wiki --space-id <SPACE_ID> --full

  # 临时关闭增量
  larksync sync-wiki --space-id <SPACE_ID> --no-incremental

  # 静默模式
  larksync sync-wiki --space-id <SPACE_ID> --quiet
  ```

  该命令会：
  - 递归遍历知识库所有节点，保持层级结构。
  - 根据节点类型（docx、sheet、bitable 等）调用相应的下载器。
  - 支持增量同步，通过节点编辑时间判断是否需要更新。
  - 生成的目录结构示例：
    ```
    output/
      └── wiki_知识库名称_abc12345/
          ├── 一级节点/
          │   ├── 文档1.md
          │   └── 子节点/
          │       └── 文档2.md
          └── 另一个节点.md
    ```

### Web UI（多用户同步系统）

Web UI 提供完整的多用户同步管理功能，每个用户通过飞书登录后可独立配置和管理自己的同步任务。

#### 功能特性

- **飞书 OAuth 登录**：用户通过飞书账号授权登录，无需手动配置 Token。
- **多用户数据隔离**：每个用户的数据存储在独立目录 `{user_storage_base}/{feishu_user_id}/`，拥有独立的元数据库。
- **同步配置管理**：
  - 支持同步「我的空间」和指定「知识库」。
  - 支持增量/全量同步模式切换。
  - 支持设置单次同步文件数限制。
- **定时任务调度**：
  - 手动触发
  - Cron 表达式（如 `0 3 * * *` 每天凌晨 3 点）
  - 固定间隔（如每 6 小时）
- **实时进度**：SSE 推送同步进度，实时显示当前下载文件和完成状态。
- **Token 自动刷新**：后台定时刷新即将过期的用户 Token。

#### 使用方式

1. 配置 `config.toml`（确保 `[web].enabled = true`，并正确填写 `[web.oauth]`）。
2. 启动服务（单端口架构，前后端统一在 8000 端口）：
   ```bash
   # 开发模式
   ./scripts/start_dev.sh
   
   # 或直接启动后端（生产模式需先构建前端）
   cd webui-client && npm run build  # 仅生产模式需要
   uvicorn larksync.web.app:create_app --factory --host 0.0.0.0 --port 8000
   ```
3. 打开 `http://localhost:8000`，点击「使用飞书账号登录」完成授权。
4. 在仪表板创建同步配置，选择同步类型、调度方式等。
5. 手动触发或等待定时任务自动执行同步。

#### 数据存储结构

```
{web.user_storage_base}/
├── {feishu_user_id_1}/         # Web 用户1 的独立目录
│   ├── .sync.db                # 用户1 的元数据库
│   ├── {用户名}_{user_id}/     # 我的空间同步内容
│   └── wiki_{space_id}/        # 知识库同步内容
├── {feishu_user_id_2}/         # Web 用户2 的独立目录
│   └── ...
└── ...

/data/web/larksync.db          # Web 系统主数据库（用户、配置、执行记录，SQLite 示例）
```

> **注意**：CLI 和 Web 的数据默认隔离；如需统一或自定义路径，请通过 `storage.download_root` 与 `web.user_storage_base` 控制。

#### 单端口架构说明

LarkSync 采用单端口架构，前端和后端统一通过 8000 端口访问：

- **开发模式**：FastAPI 反向代理请求到内部的 Next.js 开发服务器（3001 端口），支持热重载。
- **生产模式**：FastAPI 直接服务 Next.js 构建后的静态文件，无需独立的前端进程。

这种架构简化了部署和配置：
- 只需管理一个端口
- 无跨域（CORS）问题
- OAuth 回调地址配置简单

> 生产环境建议提供持久化数据库（默认使用 SQLite WAL 模式）。

### 共享 OAuth 回调服务

当多台 CLI 需复用统一的授权入口时：

1. **服务端**
   ```toml
   [web]
   enabled = true

   [web.oauth]
   app_id = "your_app_id"
   app_secret = "your_app_secret"
   callback_url = "https://callback.example.com/api/auth/callback"
   base_url = "https://callback.example.com"
   ```
   ```bash
   source .venv/bin/activate
   uvicorn larksync.web.app:create_app --factory --host 0.0.0.0 --port 8000 --workers 1
   ```
   在飞书开放平台填写相同的回调地址。

2. **客户端**
   ```toml
   [auth]
   app_id = "your_app_id"
   app_secret = "your_app_secret"
   oauth_service_base_url = "https://callback.example.com"
   # 可选：显式指定回调
   # oauth_callback_url = "https://callback.example.com/auth/callback"
   ```

3. CLI 执行 `larksync login`，浏览器完成授权后，终端轮询 `/cli/oauth/session/{session_id}` 获取 token 并写入 `~/.larksync/token_cache.json`。

## 飞书应用权限要求

### 基础权限（CLI 和 Web 通用）
- `drive:drive:readonly` - 云空间文件读取（sync-space）
- `wiki:wiki:readonly` - 知识库读取权限（sync-wiki）
- `docx:document:readonly` - 文档读取
- `sheets:spreadsheet:readonly` - 电子表格读取（Sheet/Bitable 导出）

### Web 多用户系统额外权限
- `contact:user.base:readonly` - 获取用户基本信息（用于显示用户名和头像）

### 飞书开放平台配置
1. 创建企业自建应用，获取 `app_id` 和 `app_secret`。
2. 在「安全设置」→「重定向 URL」中添加回调地址（CLI 和 Web 需要不同的回调地址）：
   - **CLI 回调**：`http://localhost:8899/callback`（或反向代理地址，转发到本地 8899 端口）
   - **Web 回调**：`http://localhost:8000/api/auth/callback`（或反向代理地址，转发到 Web 服务 8000 端口）
   
   > **重要**：CLI 和 Web 必须使用不同的回调地址，因为：
   > - CLI 在本地启动临时服务器（8899 端口）接收授权码
   > - Web 服务有自己的 `/api/auth/callback` 路由（8000 端口）处理授权码
   > 
   > 如果使用反向代理，需要配置两条规则分别转发到不同端口。

3. 申请并开通上述权限。

## 测试

```bash
pytest
```

## Docker

仓库提供 `Dockerfile`，构建包含 FastAPI 后端与 Next.js 前端的镜像（单端口架构）。

### Docker 部署步骤（推荐）

1) 准备目录结构（宿主机）
```
/data/
├── config/
│   └── config.toml        # 基于 config.docker.toml 修改
├── sync/                  # CLI 同步目录（建议）
└── web/
    ├── larksync.db        # Web 数据库
    └── users/             # Web 用户数据目录
```

/download/
├── cli/                   # CLI 下载目录（默认）
└── web/                   # Web 用户数据目录（默认）

2) 复制并修改配置
```bash
cp config.docker.toml /data/config/config.toml
```
按需调整：
- `[web].database_url = "sqlite:////data/web/larksync.db"`
- `[web].user_storage_base = "/data/web/users"`
- `[storage].download_root`（建议显式设置）

3) 构建镜像
```bash
docker build -t larksync:latest .
```

4) 启动容器（端口映射必选）
```bash
docker run -d \
  -p 8000:8000 \
  -v /data:/data \
  -v /download:/download \
  -e LARKSYNC_CONFIG=/data/config/config.toml \
  --name larksync \
  larksync:latest
```

该镜像会：
- 启动 FastAPI（监听 `0.0.0.0:8000`）
- FastAPI 直接服务前端静态文件（单端口架构）
- 运行数据存放在 `/data` 与 `/download` 挂载目录

### Docker 环境变量

必要：
- 端口映射必选（例如 `-p 8000:8000`）。
- 容器内 `/data` 与 `/download` 必须挂载到宿主机（持久化配置与数据）。
- 必须配置用户白名单：
  - `LARKSYNC__WEB__ALLOW_DOWNLOAD_USER_IDS`（`*` 表示全部允许）

默认值（若未配置上述变量）：
- `storage.download_root` 默认 `/download`，CLI 下载路径为 `/download/cli`
- `web.user_storage_base` 默认 `/download/web`

如不提供 `config.toml`，Docker 部署需至少提供以下环境变量：
- `LARKSYNC__WEB__ENABLED=true`（默认已启用，可不设置）
- `LARKSYNC__WEB__OAUTH__APP_ID`
- `LARKSYNC__WEB__OAUTH__APP_SECRET`
- `LARKSYNC__WEB__OAUTH__CALLBACK_URL`
- `LARKSYNC__WEB__DATABASE_URL`
- `LARKSYNC__WEB__USER_STORAGE_BASE`（可选，默认 `/download/web`）
- `LARKSYNC__WEB__ALLOW_DOWNLOAD_USER_IDS`

建议同时设置：
- `LARKSYNC__STORAGE__DOWNLOAD_ROOT`（会自动派生 `download_root/cli` 与 `download_root/web`，默认 `/download`）

推荐（使用 `/data` 挂载时）：
- `LARKSYNC_CONFIG`：指定配置文件路径（例如 `/data/config/config.toml`）。

可选：
- `BACKEND_HOST` / `BACKEND_PORT`：控制 FastAPI 监听地址与端口（默认 `0.0.0.0:8000`，变更后需同步调整端口映射）。
- `LARKSYNC__STORAGE__DOWNLOAD_ROOT`：统一控制 CLI/Web 下载目录（CLI 用 `{root}/cli`，Web 用 `{root}/web`）。
- `LARKSYNC__WEB__USER_STORAGE_BASE`：覆盖 Web 用户数据目录（优先级高于 `download_root`）。
- `LARKSYNC__WEB__ALLOW_DOWNLOAD_USER_IDS`：允许使用系统的用户白名单（逗号分隔；`*` 表示全部允许）。
- `LARKSYNC__WEB__ALLOW_DOWNLOAD_WIKI_USER_IDS`：允许配置知识库同步的用户白名单（逗号分隔）。
- `LARKSYNC__WEB__DATABASE_URL`：覆盖 Web 数据库连接串。
- `LARKSYNC__WEB__SCHEDULER__FORCE_QUEUE`：是否强制排队执行（`true/false`）。

示例：
```bash
docker run -d \
  -p 8000:8000 \
  -v /data:/data \
  -e LARKSYNC_CONFIG=/data/config/config.toml \
  -e LARKSYNC__WEB__DATABASE_URL=sqlite:////data/web/larksync.db \
  -e LARKSYNC__WEB__USER_STORAGE_BASE=/data/web/users \
  -e LARKSYNC__STORAGE__DOWNLOAD_ROOT=/data \
  -e LARKSYNC__WEB__SCHEDULER__FORCE_QUEUE=true \
  --name larksync \
  larksync:latest
```

## 打包发布

`releases/` 目录内提供示例脚本用于生成独立可执行文件：

- macOS：`chmod +x releases/build_mac.sh && ./releases/build_mac.sh`
- Windows：`Set-ExecutionPolicy -Scope Process RemoteSigned; ./releases/build_windows.ps1`

脚本会在 `releases/dist-<platform>/` 生成打包文件，并自动创建隔离虚拟环境。请在目标平台执行（PyInstaller 不支持跨平台交叉编译），并准备好 `config.toml` 或环境变量以便运行后的客户端能够访问飞书 API。

## 送阿杜

日期：2026-02-07

群聊未散夜微凉，
风向微调各自忙。
世事无常人会走，
唯有文档最经常。

未等江湖起波澜，
已将资料入行囊。
回头一笑云淡处：
“都在本地，心不慌。”
