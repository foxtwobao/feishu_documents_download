# CLI OAuth 功能快速开始

## 🚀 5分钟快速上手

### 步骤 1: 配置应用凭证

编辑 `config.toml`:

```toml
[auth]
app_id = "cli_a6xxxxxxxxxxxxxx"
app_secret = "your_app_secret_here"
```

> 💡 如何获取：访问 [飞书开放平台](https://open.feishu.cn/app) → 创建应用 → 获取凭证

### 步骤 2: 首次授权

```bash
larksync login
```

浏览器会自动打开，完成授权即可。

### 步骤 3: 开始使用

```bash
# 下载文档（自动使用缓存 token）
larksync download --type docx doccnxxxxxx

# 同步空间
larksync sync-space --limit 50
```

就这么简单！✨

---

## 📋 常用命令

```bash
# 查看 token 状态
larksync token-status

# 手动刷新 token
larksync refresh-token

# 退出登录
larksync logout
```

---

## 🎯 核心特性

✅ **自动打开浏览器授权** - 无需手动复制链接  
✅ **Token 自动刷新** - API 调用前自动检测并刷新  
✅ **本地安全缓存** - `~/.larksync/token_cache.json`  
✅ **无缝体验** - 整个过程透明，无需干预  

---

## 🔧 高级配置

### 设置回调端口

如果默认端口 8899 被占用：

```python
# larksync/cli_oauth.py
callback_port = 8899  # 修改为其他端口
```

### 自定义刷新时机

```toml
[auth]
token_refresh_margin_minutes = 10  # 提前10分钟刷新
```

---

## ❓ 常见问题

**Q: 浏览器没有自动打开？**  
A: 手动复制命令行输出的 URL 到浏览器

**Q: Token 多久过期？**  
A: Access token 2小时，Refresh token 30天

**Q: 如何在多台机器使用？**  
A: 每台机器运行 `larksync login` 独立授权

---

## 📖 完整文档

- [详细使用指南](docs/CLI_OAUTH_GUIDE.md)
- [测试报告](tests/CLI_TOKEN_REFRESH_TEST_REPORT.md)
- [项目 README](README.md)

---

**需要帮助？** 参考完整文档或提交 Issue
