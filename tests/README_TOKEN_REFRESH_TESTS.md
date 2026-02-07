# CLI模式Token刷新测试说明

## 快速开始

### 运行测试

```bash
# 激活虚拟环境
cd /root/code/feishu_docx_download
source .venv/bin/activate

# 运行独立测试（推荐）
python tests/test_cli_token_refresh_standalone.py

# 或使用pytest（如果已安装）
pytest tests/test_cli_token_refresh.py -v
```

### 期望输出

```
✅ 通过 - 从配置读取Token
✅ 通过 - 从环境变量读取Token
✅ 通过 - API客户端认证头
✅ 通过 - Token过期检测
✅ 通过 - Refresh Token API响应
✅ 通过 - Refresh Token错误处理
✅ 通过 - Token缓存持久化
✅ 通过 - CLI配置扩展支持
✅ 通过 - 401错误检测
✅ 通过 - 刷新工作流设计

总计: 10 个测试
通过: 10 个
成功率: 100.0%
```

## 测试文件说明

### test_cli_token_refresh.py
- 基于pytest的完整测试套件
- 需要安装pytest依赖
- 适合CI/CD集成

### test_cli_token_refresh_standalone.py
- 独立运行版本，不依赖pytest
- 可以直接用python运行
- 适合快速验证

### CLI_TOKEN_REFRESH_TEST_REPORT.md
- 详细的测试报告
- 包含实现建议
- 包含配置示例

## 测试覆盖范围

✅ **基础功能**
- Token从配置文件读取
- Token从环境变量读取
- API认证头构建

✅ **核心机制**
- Token过期时间检测
- Refresh Token API调用
- Token缓存持久化

✅ **错误处理**
- Token过期错误
- 凭证无效错误
- 401错误检测

✅ **设计验证**
- 配置扩展方案
- 工作流设计

## 当前状态

这些测试验证了CLI模式token刷新功能的**设计方案**。

实际功能还未实现，需要按照测试报告中的"实现建议"进行开发。

## 实现步骤

1. **配置扩展** - 在AuthSettings添加refresh token字段
2. **API客户端** - 在FeishuAPIClient添加刷新方法
3. **自动刷新** - 在API调用前检查并刷新token
4. **Token缓存** - 实现token持久化机制
5. **CLI命令** - 添加手动刷新和查看状态命令
6. **集成测试** - 使用真实API进行测试

详细实现建议请参考: `CLI_TOKEN_REFRESH_TEST_REPORT.md`

## 相关命令（计划中）

```bash
# 手动刷新token
larksync refresh-token

# 查看token状态
larksync token-status

# 正常下载（自动刷新token）
larksync download --type docx <token>
```

## 配置示例

```toml
[auth]
app_id = "your_app_id"
app_secret = "your_app_secret"  
user_access_token = "current_token"
token_refresh_margin_minutes = 10
```

## 问题排查

### 测试失败
1. 检查虚拟环境是否激活
2. 检查依赖是否安装完整
3. 查看详细错误信息

### 导入错误
```bash
# 重新安装项目依赖
pip install -e .
```

## 更多信息

- 完整测试报告: `CLI_TOKEN_REFRESH_TEST_REPORT.md`
- 项目文档: `../README.md`
- 需求文档: `../requirement.md`
