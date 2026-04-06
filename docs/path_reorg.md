目标：为 Obsidian 使用场景重新定义本地落盘结构。

这次不是继续沿用 `refer/assets/<token>/original.*` 与 `refer/larkfiles/<token>/content.md` 模式，而是把下载结果拆成三类：

1. **飞书树节点** → 主树
2. **树外独立云文档引用** → 顶层 flat `refer/`
3. **宿主文档资源** → 由 `storage.assets_dir_mode` 控制，默认 `_<doc>.assets/`

---

# 1) 目标目录结构

```text
<root>/
  <entry_tree>/
    <title>_<folder_token>/
      <title>_<doc_token>.md
      _<title>_<doc_token>.assets/
        <resource files>

  refer/
    <title>_<token>.md
    <title>_<token>.xlsx
    <original_filename_or_fallback>
```

---

# 2) 主树规则

## 飞书文件夹

* 落为本地目录
* 目录名使用：`<title>_<folder_token>/`

## 飞书树中的文件 / 云文档

* 落为主树中的真实文件
* 文件名使用：`<title>_<token>.<ext>`
* 不要为了资源管理把主文档再包成“每个文档一个目录”

---

# 3) `refer/` 规则

`refer/` 只放“**不属于当前主树节点**、但可以独立打开和复用的云文档对象”。

包括：

* doc / docx
* sheet / sheets
* bitable / base
* slides
* mindnote
* 语义上属于“独立对象”的 file 链接

## 命名规则

统一使用：

* `{safe_name}_{token}.md`
* `{safe_name}_{token}.xlsx`
* file 类型优先原始文件名；若不可得，再用 `{safe_name}_{token}{ext}`

## 结构约束

* `refer/` 默认 **flat**
* 不再使用：
  * `refer/larkfiles/<token>/content.md`
  * `refer/assets/<token>/original.<ext>`
* 不再新增深层 `refer/docs/`、`refer/sheets/` 等多级目录，除非后续规模过大另行设计

---

# 4) sidecar assets 规则

宿主文档资源统一跟宿主文档走。

目录名由 `storage.assets_dir_mode` 控制：

```text
plain     -> <doc_filename_without_ext>.assets/
prefixed  -> _<doc_filename_without_ext>.assets/
hidden    -> .<doc_filename_without_ext>.assets/
```

默认推荐值是 `prefixed`，因为它：

- 比普通目录更不抢眼；
- 不会像 dot 目录一样被某些工具默认隐藏或忽略；
- 更适合 Obsidian 日常浏览。

例如（默认 `prefixed`）：

```text
需求文档_abc123.md
_需求文档_abc123.assets/
```

这里放的是：

* 图片块
* 附件块
* 白板导出图 / JSON
* 其他块级资源
* 不具备独立云文档语义的 file

## 命名优先级

1. 原始文件名
2. `{safe_name}_{token_or_block_id}{ext}`
3. `{host_doc_safe_name}_{resource_type}_{index}{ext}`

---

# 5) A 引 B 的规则

## 场景 A：B 在飞书树中

* B 只存主树
* A 链接主树中的 B
* B 不进入 `refer/`

## 场景 B：B 不在飞书树中，但 B 是独立云文档对象

* B 落 `refer/`
* A 链接 `refer/` 中对应真实文件

## 场景 C：A 引用的是资源类内容

* 资源落当前配置模式对应的 sidecar 目录
* A 链接自己对应的 sidecar 目录中的真实文件

---

# 6) `file` 类型特殊规则

`file` 不按类型一刀切，而按“语义来源”分流：

## 独立对象型 file

* 落 `refer/`
* 优先原始文件名

## 宿主资源型 file

* 落当前配置模式对应的 sidecar 目录
* 与图片/附件块同等处理

---

# 7) 状态切换规则

会有这种情况：

* 第一次同步时，对象不在主树，因此进入 `refer/`
* 后续同步时，对象出现在主树

或者反过来。

Obsidian 优先方案接受真实文件迁移：

* `refer/` → 主树：迁移文件、更新引用、删除旧 refer 文件
* 主树 → `refer/`：迁移文件、更新引用、删除旧主树文件

不引入 stub / view / 占位页作为常态方案。

---

# 8) 禁止事项

* 不为了路径稳定引入大量 stub/view 文件
* 不继续使用 `content.md` / `content.xlsx` 作为 refer 默认文件名
* 不继续使用 `original.<ext>` 作为所有资源的统一命名目标
* 不把飞书树节点和宿主资源混放在同一个语义层级里

---

# 9) 实现关注点

1. 主树路径生成仍由主树同步流程决定
2. 引用下载时必须先判断：树节点 / refer 对象 / 宿主资源
3. 链接重写必须直接指向真实文件
4. Obsidian 中用户看到的尽量都是真文件
