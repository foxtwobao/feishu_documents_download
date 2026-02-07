#!/bin/bash
# 测试增量下载功能

cd /root/code/feishu_docx_download
source .venv/bin/activate

echo "========================================="
echo "测试增量下载功能"
echo "========================================="
echo ""

echo "【步骤 1】 查看元数据中已记录的文件数..."
if [ -f "/mnt/share/n8ndata/feishufiles/.metadata.json" ]; then
    CACHED_COUNT=$(cat /mnt/share/n8ndata/feishufiles/.metadata.json | grep -o '"status": "ok"' | wc -l)
    echo "已缓存的文件数: $CACHED_COUNT"
else
    echo "未找到元数据文件"
    CACHED_COUNT=0
fi
echo ""

echo "【步骤 2】 运行 sync-space（limit=10），观察是否跳过已下载的文件..."
echo ""
larksync sync-space --limit 10 2>&1 | grep -E '(增量策略跳过|已下载|Processing task|Synced space)' || echo "未找到相关日志"
echo ""

echo "【步骤 3】 完成测试"
echo "========================================="
