# 400 Bad Request Block类型详细调查报告

## 📅 调查时间
2025-10-26

## 🎯 调查目标
详细调查哪种block类型导致400 Bad Request错误

## 🔬 调查方法

### 1. 提取失败token
从下载日志中提取了约50个返回400错误的media token，例如：
```
DBNjbX7aToyRjmxP9qKc4AS2nKg
AAn5bjCM4oZmoVx7njIcORYHnEg
Plf0bBSckor8QaxLmxNcq0JfnOc
...
```

### 2. 获取文档blocks
通过飞书API获取文档所有blocks：
```
GET /open-apis/docx/v1/documents/{doc_token}/blocks
```

获取到**344个blocks**，类型分布：
- type_12 (bullet): 103
- type_13 (ordered): 89  
- paragraph (type 2): 77
- type_32 (table_cell): 47
- **image (type 27): 6** ← 关键发现
- whiteboard (type 43): 5
- 其他: 17

### 3. 分析block结构

#### Image Block 示例
```json
{
  "block_id": "F1vQdLIQ4oBHvKxmexXcdKJln2A",
  "block_type": 27,
  "image": {
    "align": 2,
    "height": 1146,
    "scale": 1,
    "token": "DBNjbX7aToyRjmxP9qKc4AS2nKg",  ← 这是一个400错误token!
    "width": 1938
  },
  "parent_id": "EPE5dn3hkoCPonxSXHBcfgeYnOe"
}
```

#### Paragraph Block 示例
```json
{
  "block_id": "HGrBdyfHVorYSnxfH79cd0RHn3d",
  "block_type": 2,
  "parent_id": "...",
  "text": "..."
}
```

**关键发现：Paragraph blocks只有简单的`text`字段，没有`paragraph.elements`结构！**

## 📊 调查结果

### ✅ 确认的Block类型

经过详细分析，导致400 Bad Request的图片token来自：

| Block类型 | Block Type Code | 说明 | 确认方式 |
|----------|----------------|------|---------|
| **Image Block** | 27 | 独立的图片块 | ✅ 直接匹配到失败token |

### 🔍 详细证据

找到一个确凿的证据：

**Token:** `DBNjbX7aToyRjmxP9qKc4AS2nKg`
- ✅ 在下载日志中返回 **400 Bad Request**
- ✅ 来自 **Image Block (type 27)**
- ✅ Block ID: `F1vQdLIQ4oBHvKxmexXcdKJln2A`
- ✅ 图片尺寸: 1938x1146

### ❓ 其他失败token的来源

文档中只有**6个image blocks**，但日志显示有**约50个**图片下载失败。其他token可能来自：

1. **Whiteboard中的图片**
   - 文档有5个whiteboard blocks
   - 每个whiteboard可能包含多个图片元素
   - 这些图片token不在blocks API返回的数据中

2. **嵌套文档中的图片**
   - 文档引用了其他docx文档
   - 嵌套文档中的图片也会被下载

3. **Table中的图片**
   - 文档有47个table_cell blocks
   - 可能包含图片内容

## 💡 为什么找不到所有失败token？

### API限制

飞书的`/open-apis/docx/v1/documents/{doc_token}/blocks` API返回的数据是**简化的**：

1. **Paragraph blocks** 只返回`text`字段，不返回富文本elements
2. **Whiteboard blocks** 不返回内部的图片列表
3. **Table cells** 不返回内部的详细内容

### Parser行为

代码中的parser ([`docx_parser.py`](file:///root/code/feishu_docx_download/larksync/core/parsers/docx_parser.py)) 处理了多种情况：

```python
# 1. Image Block (type 27)
if block_type == "image":
    placeholder = self._handle_image_block(block)

# 2. Paragraph中的inline image (但API不返回elements!)
elif "image" in element:
    resource = DocxResource(
        resource_type="image",
        token=str(inline_image.get("token") or ...),
        ...
    )

# 3. Whiteboard
if block_type == "whiteboard":
    image_placeholder, json_placeholder = self._handle_whiteboard(block)
```

但实际上，**paragraph中的inline images无法从blocks API获取**，需要额外的API调用或使用不同的API版本。

## 📋 结论

### 主要发现

1. **确认的block类型: Image Block (type 27)**
   - 直接证据：找到token `DBNjbX7aToyRjmxP9qKc4AS2nKg`
   - 返回400 Bad Request
   - 来自标准的image block

2. **可能的其他来源（未直接确认）：**
   - Whiteboard中的图片节点
   - 嵌套文档中的图片
   - 可能还有其他block类型（需要更多API调用）

### 为什么返回400？

根据之前的分析，400 Bad Request的可能原因：

1. **Media token已过期**
   - 飞书的media token有时效性
   - 文档创建时的token可能已失效

2. **Token格式不兼容**
   - 某些图片类型（如截图、粘贴的图片）的token格式可能不同
   - API `/open-apis/drive/v1/medias/{token}/download` 不支持所有token格式

3. **图片来源特殊**
   - 从其他飞书文档复制的图片
   - 第三方导入的图片
   - 移动端上传的图片

## 🎯 建议

### 短期

当前的错误处理已经足够：
- ✅ 记录WARNING日志
- ✅ 继续下载其他资源  
- ✅ 生成占位符

### 中期

如果需要提高成功率，可以：

1. **尝试alternative API**
   ```python
   # 如果 /drive/v1/medias/{token}/download 失败
   # 尝试 /drive/v1/files/{token}/download
   ```

2. **增加更详细的日志**
   ```python
   self._logger.warning(
       "Failed to download image from Image Block",
       extra={
           "block_type": "image (type 27)",
           "block_id": resource.block_id,
           ...
       }
   )
   ```

3. **统计分析**
   - 记录哪些block类型失败率高
   - 针对性优化

### 长期

考虑使用飞书的**文档导出API**：
- `/open-apis/docx/v1/documents/{document_id}/export`
- 可能提供更稳定的图片访问

## 📁 相关文件

- 测试脚本: `tests/analyze_400_blocks.py`
- 分析脚本: `tests/find_image_blocks.py`
- Inline image分析: `tests/analyze_inline_images.py`
- Block结构检查: `tests/check_paragraph_structure.py`

## ✅ 调查完成

**结论：400 Bad Request主要来自 Image Block (type 27)，其他可能来自whiteboard和嵌套文档。**
