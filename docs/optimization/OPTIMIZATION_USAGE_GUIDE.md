# 性能优化使用指南

## 快速开始

### 1. 验证优化效果

运行自动化测试脚本：

```bash
cd /root/code/feishu_docx_download
source .venv/bin/activate
python test_performance_optimization.py
```

预期输出：
```
✅ 所有优化测试通过！

优化总结:
  ✓ 元数据批量刷盘: 磁盘IO减少 ~50倍
  ✓ 限流器分桶隔离: 不同API并发执行，提升 ~2倍
  ✓ 图片并发下载: 单文档下载提速 ~5倍

预期整体性能提升: 5-10倍 🚀
```

---

## 2. 配置调优

### 元数据刷盘间隔

默认每 50 个文件刷盘一次，可根据文件系统类型调整：

```python
# 在创建 MetadataStore 时指定
from larksync.storage import MetadataStore

# 本地SSD（可更频繁）
store = MetadataStore(root_path, flush_interval=20)

# 网络文件系统（减少网络开销）
store = MetadataStore(root_path, flush_interval=100)
```

### 图片并发数

在 `docx_downloader.py` 中，默认最多 5 个并发：

```python
# _materialize_images() 和 _materialize_attachments()
max_workers = min(5, len(resources_list))

# 可根据网络带宽调整：
# - 低带宽: max_workers = 3
# - 高带宽: max_workers = 10
```

---

## 3. 性能监控

### 元数据写入次数

查看日志中的元数据写入频率：

```bash
# 启用调试日志
export LARKSYNC_LOG_LEVEL=DEBUG

# 运行下载任务
larksync download <folder_token>

# 查看元数据写入次数
grep "metadata" output/.metadata.json.log
```

### API调用频次

检查是否触发飞书429限流：

```bash
# 查看日志中的限流警告
grep "429\|rate limit" larksync.log
```

---

## 4. 故障排查

### 问题1: 元数据丢失

**症状:** 程序异常退出后，部分文件元数据未保存

**解决方案:**
```python
# 确保程序退出时强制刷盘
try:
    synchronizer.sync()
finally:
    storage.metadata.flush()  # 强制刷盘
```

### 问题2: API频次超限

**症状:** 大量 429 错误

**解决方案:**
1. 降低并发配置
2. 检查 `config.toml` 中的 `rate_limit` 设置
3. 确认飞书应用的API配额

### 问题3: 内存占用过高

**症状:** 下载大量文件时内存持续增长

**解决方案:**
1. 减小 `flush_interval`（更频繁释放内存）
2. 降低图片并发数
3. 分批次下载

---

## 5. 性能基准测试

### 测试场景

```bash
# 场景1: 100个纯文本DocX文档
larksync download <folder_token> --limit 100

# 场景2: 20个图片密集型DocX文档
larksync download <folder_token> --limit 20

# 场景3: 混合类型文档
larksync download <folder_token>
```

### 性能指标

记录以下指标以评估优化效果：

| 指标 | 计算方式 | 目标值 |
|------|---------|--------|
| 平均下载速度 | 文件数 / 总耗时 | >0.5 文件/秒 |
| 磁盘IO次数 | 元数据写入次数 | <文件数/50 |
| API调用成功率 | (总请求-失败)/总请求 | >99% |
| 429错误率 | 429次数/总请求 | <1% |

---

## 6. 常见问题

### Q: 优化后性能提升不明显？

A: 检查以下因素：
1. 网络带宽是否是瓶颈
2. 飞书API响应时间
3. 文件类型分布（纯文本DocX优化效果有限）
4. 是否使用了增量同步（跳过已下载文件）

### Q: 如何临时禁用优化？

A: 
```python
# 禁用批量刷盘（每次立即写入）
store = MetadataStore(root_path, flush_interval=1)

# 禁用图片并发（改为串行）
max_workers = 1
```

### Q: 优化是否影响数据完整性？

A: 不影响。批量刷盘使用与原实现相同的原子写入机制，且程序退出时会强制刷盘。

---

## 7. 升级指南

### 从旧版本升级

```bash
# 1. 备份现有元数据
cp output/.metadata.json output/.metadata.json.backup

# 2. 更新代码
git pull origin main

# 3. 重新安装
pip install -e .

# 4. 验证优化
python test_performance_optimization.py

# 5. 测试下载
larksync download <test_folder_token> --limit 10
```

### 回滚方案

如遇问题需要回滚：

```bash
# 恢复旧版本代码
git checkout <previous_commit>

# 恢复元数据
cp output/.metadata.json.backup output/.metadata.json

# 重新安装
pip install -e .
```

---

## 8. 进阶优化

### 自定义批量刷盘策略

```python
import time

class TimedMetadataStore(MetadataStore):
    def __init__(self, root, flush_interval=50, flush_timeout=30):
        super().__init__(root, flush_interval)
        self._last_flush = time.time()
        self._flush_timeout = flush_timeout
    
    def mark_synced(self, token, **kwargs):
        super().mark_synced(token, **kwargs)
        
        # 超时也强制刷盘
        if time.time() - self._last_flush > self._flush_timeout:
            self._write()
            self._last_flush = time.time()
```

### 动态调整并发数

```python
class AdaptiveConcurrency:
    def __init__(self, initial_workers=5):
        self.workers = initial_workers
    
    def on_429_error(self):
        # API限流时降低并发
        self.workers = max(1, self.workers - 1)
    
    def on_success_batch(self):
        # 成功批次后尝试提升并发
        self.workers = min(10, self.workers + 1)
```

---

## 9. 参考文档

- [完整性能分析报告](PERFORMANCE_ANALYSIS.md)
- [优化实施报告](OPTIMIZATION_REPORT.md)
- [项目README](README.md)

---

**文档更新日期:** 2025-10-26  
**适用版本:** larksync 0.1.0+
