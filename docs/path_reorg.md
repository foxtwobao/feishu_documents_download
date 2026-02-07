目标：仅修改本地 Path 结构（不改现有能力），明确 refer/assets vs refer/larkfiles，支持递归嵌入

你需要在保持现有代码“能正常运行”的前提下，**只修改本地文件/文件夹的 path 结构与落盘位置**。
**禁止**修改 token 提取逻辑、解析逻辑、下载逻辑、触发下载的范围与类型支持能力。
**只支持导出 Markdown**，不要 pdf/docx/html、多格式导出，不做缩略图/转码。

---

# 1) 目标目录结构（必须严格遵守）

```
<root>/
  <entry_tree>/                          # 与飞书目录层级一致
    <title>_<folder_token>/
      <title>_<file_token>.<ext>
      <title>_<doc_token>.md             # docx 导出的 Markdown（入口文件）

  refer/
    assets/
      <token>/
        original.<ext>
    larkfiles/
      <token>/
        content.md
```

## 命名强约束

* 所有 **Entry Tree** 的文件夹必须命名为：`<title>_<folder_token>/`
* 所有 **Entry Tree** 的文件必须命名为：`<title>_<file_token>.<ext>`
* 所有 **Entry Tree** 的 docx 导出必须命名为：`<title>_<doc_token>.md`
* refer/assets 的文件名固定为：`original.<ext>`
* refer/larkfiles 的文件名固定为：`content.md`
* refer 下的目录名必须是 token 本身：`<token>/`
* title 的 sanitize/截断等逻辑沿用现有实现即可（不要大改），但必须确保 `_token` 后缀存在。

---

# 2) refer 归类规则（assets vs larkfiles）——按“产物类型”划分

## 核心原则（必须执行）

* **最终落盘为二进制文件的下载结果 → refer/assets/**
* **最终落盘为 Markdown 的导出结果 → refer/larkfiles/**

---

# 3) 与现有 docx 实现对齐的明确归类表（必须按此实现）

以下“类型与 token 来源”与你现有实现一致；你只改落盘路径。

## A) 图片块（含行内图片）

* token 来源：`image.token` / `image_token` / `file_token`（缺失回退 block_id 也保持现有行为）
* **落盘：** `refer/assets/<token>/original.<ext>`

## B) 附件块

* token 来源：`file_token` / `token`（缺失回退 block_id 也保持现有行为）
* **落盘：** `refer/assets/<token>/original.<ext>`

## C) 文档内链接“引用下载”（从 URL 抽 token）

现有支持类型：`doc/docx、sheet/sheets、base/bitable、mindnote/mindnotes、slides、file`

* 若类型为 `file`：

  * **落盘：** `refer/assets/<token>/original.<ext>`
* 若类型为 `doc/docx/sheet/sheets/base/bitable/mindnote/mindnotes/slides`：

  * **落盘：** `refer/larkfiles/<token>/content.md` （导出 Markdown）

## D) 表格块（sheet）

* token 来源：`token/sheet_token/sheet_id`（拆为 spreadsheet_token + sheet_id；现有逻辑不改）
* **落盘：** `refer/larkfiles/<spreadsheet_token>/content.md`

## E) 白板块（board/whiteboard）

* 当前实现会下载文件（缩略图/JSON等），不改下载行为
* **落盘：** 统一归入 assets
  `refer/assets/<token>/original.<ext>`（或同目录下以现有方式保存，但目录必须是 `refer/assets/<token>/`）

## F) 占位类型

* 保持现状：不触发下载
* **不产生 refer 落盘**

---

# 4) 为什么 refer/larkfiles 用 content.md（必须遵守，不要改成 title_token.md）

* refer 是按 token 的全局去重缓存池，路径必须稳定，不随 title 改名而变化
* 因此 larkfiles 固定：`refer/larkfiles/<token>/content.md`
* Entry Tree 才使用 `<title>_<token>.md`（面向用户可读）

---

# 5) 递归嵌入规则（关键，必须实现）

无论嵌入发生在：

* Entry Tree 的 `<title>_<doc_token>.md`
  还是发生在：
* `refer/larkfiles/<token>/content.md`

只要解析到嵌入/引用的在线文档 token（doc/docx/sheet/base/bitable/mindnote/slides），都必须：

* **统一落盘到：** `refer/larkfiles/<that_token>/content.md`
* 并且该 `content.md` 导出完成后，也要继续按现有逻辑解析其嵌入，触发下一层 refer 下载（直到无新 token）

示例：
A（Entry）嵌入 B（docx），B 又嵌入 C（docx）：

* `entry_tree/.../A_<A>.md`
* `refer/larkfiles/<B>/content.md`
* `refer/larkfiles/<C>/content.md`

禁止把 C 放到 `refer/larkfiles/<B>/` 下面，也禁止复制嵌入层级结构。

---

# 6) assets 的 original.<ext> 扩展名规则（最小改动）

* 若现有下载结果/响应提供文件名（含 ext）→ 取该 ext
* 否则若提供 mime → 用现有 mime->ext 映射
* 否则兜底 `.bin`
  只需保证最终文件名是 `original.<ext>`。

---

# 7) 仅允许改动的代码点

1. Entry Tree 的命名：文件夹/文件统一加 `_token`
2. refer 的输出路径构造（把原来散落的路径改成本文要求）
3. Markdown 引用重写若依赖原路径：仅更新为新的 refer 相对路径（不要改内容逻辑）

---

# 8) 禁止事项（必须遵守）

* 不新增导出格式（只 Markdown）
* 不新增缩略图/转码
* 不改变哪些 block/link 会触发下载
* 不改变 token 提取/回退逻辑
* 不引入新的 refer 子目录结构

---

只完成以上 path 结构修改与归类即可，不要做额外优化或重构。
