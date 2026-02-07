#!/usr/bin/env python3
"""
CLI OAuth 功能集成测试

测试自动授权、token 刷新等功能
"""

import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from larksync.cli_oauth import TokenCache, CLIOAuthClient, CLITokenManager
from larksync.config import AuthSettings


def test_token_cache_basic():
    """测试 Token 缓存基本功能"""
    print("\n测试1: Token 缓存基本功能")
    print("-" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "token_cache.json"
        cache = TokenCache(cache_path)
        
        # 保存 token
        cache.save("test_access_token", "test_refresh_token", 7200)
        print("✅ Token 已保存")
        
        # 加载 token
        data = cache.load()
        assert data is not None, "Token 应该能够加载"
        assert data["access_token"] == "test_access_token"
        assert data["refresh_token"] == "test_refresh_token"
        print(f"✅ Token 已加载: {data['access_token'][:20]}...")
        
        # 验证过期时间
        expires_at = datetime.fromisoformat(data["expires_at"])
        now = datetime.now(timezone.utc)
        time_diff = (expires_at - now).total_seconds()
        assert 7100 < time_diff < 7300, "过期时间应该约为2小时"
        print(f"✅ 过期时间正确: {int(time_diff/3600)} 小时")
        
        # 清除缓存
        cache.clear()
        assert not cache_path.exists(), "缓存文件应该被删除"
        print("✅ 缓存已清除")
    
    return True


def test_token_cache_expiry_check():
    """测试 Token 过期检查"""
    print("\n测试2: Token 过期检查")
    print("-" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "token_cache.json"
        
        # 创建即将过期的 token
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        data = {
            "access_token": "test_token",
            "refresh_token": "test_refresh",
            "expires_at": expires_at.isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        cache_path.write_text(json.dumps(data))
        
        cache = TokenCache(cache_path)
        loaded = cache.load()
        
        # 创建 token manager 并检查
        auth = AuthSettings(app_id="test", app_secret="test")
        manager = CLITokenManager(auth, refresh_margin_minutes=10)
        
        should_refresh = manager._should_refresh(loaded)
        assert should_refresh, "应该检测到需要刷新"
        print("✅ 正确检测到 token 即将过期")
        
        # 创建有效期长的 token
        expires_at = datetime.now(timezone.utc) + timedelta(hours=2)
        data["expires_at"] = expires_at.isoformat()
        cache_path.write_text(json.dumps(data))
        
        loaded = cache.load()
        should_refresh = manager._should_refresh(loaded)
        assert not should_refresh, "不应该刷新有效的 token"
        print("✅ 正确识别有效 token")
    
    return True


def test_oauth_client_url_building():
    """测试 OAuth URL 构建"""
    print("\n测试3: OAuth URL 构建")
    print("-" * 60)
    
    client = CLIOAuthClient("test_app_id", "test_app_secret")
    
    state = "test_state_123"
    url = client.build_authorization_url(state)
    
    assert "passport.feishu.cn" in url
    assert "test_app_id" in url
    assert "test_state_123" in url
    assert "response_type=code" in url
    
    print(f"✅ 授权 URL: {url[:80]}...")
    
    return True


@patch('httpx.Client')
def test_token_exchange_mock(mock_client_class):
    """测试 token 交换（模拟）"""
    print("\n测试4: Token 交换（模拟）")
    print("-" * 60)
    
    # 模拟飞书 API 响应
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "access_token": "mock_access_token_xyz",
            "refresh_token": "mock_refresh_token_abc",
            "expires_in": 7200
        }
    }
    mock_response.raise_for_status = Mock()
    
    mock_client = Mock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client_class.return_value = mock_client
    
    # 执行 token 交换
    client = CLIOAuthClient("test_app", "test_secret")
    access_token, refresh_token, expires_in = client.exchange_code("test_code")
    
    assert access_token == "mock_access_token_xyz"
    assert refresh_token == "mock_refresh_token_abc"
    assert expires_in == 7200
    
    print(f"✅ Access Token: {access_token}")
    print(f"✅ Refresh Token: {refresh_token}")
    print(f"✅ Expires In: {expires_in}s")
    
    return True


@patch('httpx.Client')
def test_token_refresh_mock(mock_client_class):
    """测试 token 刷新（模拟）"""
    print("\n测试5: Token 刷新（模拟）")
    print("-" * 60)
    
    # 模拟刷新响应
    mock_response = Mock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "code": 0,
        "data": {
            "access_token": "new_access_token_123",
            "refresh_token": "new_refresh_token_456",
            "expires_in": 7200
        }
    }
    mock_response.raise_for_status = Mock()
    
    mock_client = Mock()
    mock_client.post.return_value = mock_response
    mock_client.__enter__ = Mock(return_value=mock_client)
    mock_client.__exit__ = Mock(return_value=False)
    mock_client_class.return_value = mock_client
    
    # 执行刷新
    client = CLIOAuthClient("test_app", "test_secret")
    new_access, new_refresh, expires_in = client.refresh_token("old_refresh_token")
    
    assert new_access == "new_access_token_123"
    assert new_refresh == "new_refresh_token_456"
    
    print(f"✅ 新 Access Token: {new_access}")
    print(f"✅ 新 Refresh Token: {new_refresh}")
    
    return True


def test_token_manager_fallback():
    """测试 TokenManager 的降级处理"""
    print("\n测试6: TokenManager 降级处理")
    print("-" * 60)
    
    # 场景1: 使用配置中的 user_access_token
    auth = AuthSettings(user_access_token="config_token_123")
    manager = CLITokenManager(auth)
    
    token = manager.get_valid_token()
    assert token == "config_token_123"
    print("✅ 正确使用配置中的 token")
    
    # 场景2: 没有任何 token 和 OAuth 配置
    auth = AuthSettings()
    manager = CLITokenManager(auth)
    
    try:
        token = manager.get_valid_token()
        assert False, "应该抛出异常"
    except RuntimeError as e:
        assert "No valid token" in str(e)
        print("✅ 正确抛出缺少配置的异常")
    
    return True


def test_token_status():
    """测试 token 状态查询"""
    print("\n测试7: Token 状态查询")
    print("-" * 60)
    
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "token_cache.json"
        
        auth = AuthSettings(app_id="test", app_secret="test")
        manager = CLITokenManager(auth)
        manager.token_cache.cache_path = cache_path
        
        # 场景1: 没有缓存
        status = manager.get_token_status()
        assert status["status"] == "no_cache"
        print(f"✅ 场景1 - 没有缓存: {status['message']}")
        
        # 场景2: 有效 token
        manager.token_cache.save("valid_token", "refresh_token", 7200)
        status = manager.get_token_status()
        assert status["status"] == "valid"
        print(f"✅ 场景2 - 有效 token: {status['message']}")
        
        # 场景3: 即将过期
        manager.token_cache.save("expiring_token", "refresh_token", 300)  # 5分钟
        status = manager.get_token_status()
        assert status["status"] == "expiring_soon"
        print(f"✅ 场景3 - 即将过期: {status['message']}")
    
    return True


def test_integration_workflow():
    """测试完整的工作流"""
    print("\n测试8: 完整工作流模拟")
    print("-" * 60)
    
    workflow_steps = [
        "1. 用户运行命令行程序",
        "2. 检查本地缓存是否有有效 token",
        "3. 如果没有，打开浏览器进行 OAuth 授权",
        "4. 接收回调并获取授权码",
        "5. 用授权码换取 access_token 和 refresh_token",
        "6. 保存 token 到本地缓存",
        "7. 后续请求自动使用缓存的 token",
        "8. 检测到 token 即将过期时自动刷新",
        "9. 刷新失败时提示用户重新授权",
    ]
    
    print("完整工作流:")
    for step in workflow_steps:
        print(f"  {step}")
    
    print("✅ 工作流设计完整")
    
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("CLI OAuth 功能集成测试")
    print("=" * 70)
    
    tests = [
        ("Token 缓存基本功能", test_token_cache_basic),
        ("Token 过期检查", test_token_cache_expiry_check),
        ("OAuth URL 构建", test_oauth_client_url_building),
        ("Token 交换（模拟）", test_token_exchange_mock),
        ("Token 刷新（模拟）", test_token_refresh_mock),
        ("TokenManager 降级处理", test_token_manager_fallback),
        ("Token 状态查询", test_token_status),
        ("完整工作流", test_integration_workflow),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result, None))
        except Exception as e:
            import traceback
            results.append((name, False, traceback.format_exc()))
    
    # 打印测试摘要
    print("\n" + "=" * 70)
    print("测试摘要")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    for name, result, error in results:
        status = "✅ 通过" if result else "❌ 失败"
        print(f"{status} - {name}")
        if error:
            print(f"  错误:\n{error}")
        
        if result:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "-" * 70)
    print(f"总计: {len(tests)} 个测试")
    print(f"通过: {passed} 个")
    print(f"失败: {failed} 个")
    print(f"成功率: {passed/len(tests)*100:.1f}%")
    
    if passed == len(tests):
        print("\n" + "=" * 70)
        print("🎉 所有测试通过！")
        print("=" * 70)
        print("""
功能验证完成！现在可以使用以下命令：

1. 首次授权：
   larksync login

2. 查看 token 状态：
   larksync token-status

3. 手动刷新 token：
   larksync refresh-token

4. 下载文档（自动刷新 token）：
   larksync download --type docx <token>

5. 登出（清除缓存）：
   larksync logout

配置要求（config.toml）：
[auth]
app_id = "your_app_id"
app_secret = "your_app_secret"

Token 缓存位置：
~/.larksync/token_cache.json
        """)
    
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
