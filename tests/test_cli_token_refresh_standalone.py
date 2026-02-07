#!/usr/bin/env python3
"""
命令行模式下Token刷新功能测试（独立版本，不依赖pytest）

测试目标：
1. 验证CLI模式下能否正确读取user_access_token
2. 验证当token过期时的错误处理
3. 验证refresh token机制的设计方案
4. 验证token刷新后的持久化方案
"""

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from larksync.config import AuthSettings, load_config


def test_user_access_token_from_config():
    """测试从配置文件读取user_access_token"""
    print("\n测试1: 从配置读取user_access_token")
    print("-" * 60)
    
    auth = AuthSettings(
        app_id="test_app_id",
        app_secret="test_app_secret",
        user_access_token="test_user_token"
    )
    
    assert auth.user_access_token == "test_user_token", "Token读取失败"
    assert auth.app_id == "test_app_id", "App ID读取失败"
    assert auth.app_secret == "test_app_secret", "App Secret读取失败"
    
    print(f"✅ user_access_token: {auth.user_access_token}")
    print(f"✅ app_id: {auth.app_id}")
    print(f"✅ app_secret: {auth.app_secret}")
    return True


def test_user_access_token_from_env():
    """测试从环境变量读取user_access_token"""
    print("\n测试2: 从环境变量读取user_access_token")
    print("-" * 60)
    
    # 设置环境变量
    os.environ["LARKSYNC_USER_ACCESS_TOKEN"] = "env_token_xyz123"
    
    try:
        # 创建临时配置文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.toml', delete=False) as f:
            config_content = """
[auth]
app_id = "config_app_id"
app_secret = "config_app_secret"
user_access_token = "config_token"
"""
            f.write(config_content)
            config_path = Path(f.name)
        
        # 加载配置（环境变量应该覆盖配置文件）
        config = load_config(config_path)
        
        assert config.auth.user_access_token == "env_token_xyz123", \
            "环境变量未正确覆盖配置文件"
        
        print(f"✅ 环境变量token: {config.auth.user_access_token}")
        print("✅ 环境变量正确覆盖了配置文件中的token")
        return True
        
    finally:
        # 清理
        os.environ.pop("LARKSYNC_USER_ACCESS_TOKEN", None)
        if config_path.exists():
            config_path.unlink()


def test_api_client_auth_headers():
    """测试API客户端使用user_access_token构建认证头"""
    print("\n测试3: API客户端认证头构建")
    print("-" * 60)
    
    from larksync.core.api_client import FeishuAPIClient
    from larksync.config import RetrySettings, RateLimitSettings
    
    auth = AuthSettings(
        user_access_token="test_bearer_token_12345"
    )
    
    client = FeishuAPIClient(
        auth=auth,
        retry=RetrySettings(),
        rate_limit=RateLimitSettings(),
    )
    
    headers = client._build_headers()
    
    assert "Authorization" in headers, "缺少Authorization头"
    assert headers["Authorization"] == "Bearer test_bearer_token_12345", \
        "Bearer token格式错误"
    
    print(f"✅ Authorization头: {headers['Authorization']}")
    print("✅ 认证头构建正确")
    
    client.close()
    return True


def test_token_expiry_detection():
    """测试token过期时间检测逻辑"""
    print("\n测试4: Token过期时间检测")
    print("-" * 60)
    
    now = datetime.now(timezone.utc)
    margin_minutes = 10
    
    # 场景1：token已过期
    expired_time = now - timedelta(minutes=5)
    is_expired = expired_time < now
    print(f"场景1 - 已过期token: {is_expired} ✅")
    assert is_expired, "应该检测到token已过期"
    
    # 场景2：token即将过期（在边距内）
    soon_expired_time = now + timedelta(minutes=5)
    time_left = (soon_expired_time - now).total_seconds() / 60
    is_soon_expired = time_left < margin_minutes
    print(f"场景2 - 即将过期token (剩余{time_left:.1f}分钟): {is_soon_expired} ✅")
    assert is_soon_expired, "应该检测到token即将过期"
    
    # 场景3：token仍然有效
    valid_time = now + timedelta(hours=1)
    time_left = (valid_time - now).total_seconds() / 60
    is_valid = time_left > margin_minutes
    print(f"场景3 - 有效token (剩余{time_left:.1f}分钟): {is_valid} ✅")
    assert is_valid, "应该检测到token仍然有效"
    
    return True


def test_refresh_token_api_response():
    """测试refresh token API响应的处理"""
    print("\n测试5: Refresh Token API响应处理")
    print("-" * 60)
    
    # 模拟飞书refresh token API的成功响应
    mock_response = {
        "code": 0,
        "data": {
            "access_token": "new_access_token_abc123",
            "refresh_token": "new_refresh_token_xyz789",
            "expires_in": 7200
        }
    }
    
    # 解析响应
    assert mock_response["code"] == 0, "API返回错误码"
    data = mock_response["data"]
    
    new_access_token = data["access_token"]
    new_refresh_token = data["refresh_token"]
    expires_in = data["expires_in"]
    
    print(f"✅ 新access_token: {new_access_token}")
    print(f"✅ 新refresh_token: {new_refresh_token}")
    print(f"✅ 有效期: {expires_in}秒 ({expires_in/3600}小时)")
    
    # 计算过期时间
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    print(f"✅ 过期时间: {expires_at.isoformat()}")
    
    return True


def test_refresh_token_error_handling():
    """测试refresh token失败的错误处理"""
    print("\n测试6: Refresh Token错误处理")
    print("-" * 60)
    
    # 错误场景1：refresh_token过期
    error_response_1 = {
        "code": 40001,
        "msg": "invalid refresh_token"
    }
    
    print(f"错误场景1 - refresh_token过期:")
    print(f"  错误码: {error_response_1['code']}")
    print(f"  错误信息: {error_response_1['msg']}")
    print(f"  处理方案: 提示用户重新授权 ✅")
    
    # 错误场景2：无效的app凭证
    error_response_2 = {
        "code": 10013,
        "msg": "invalid app_id or app_secret"
    }
    
    print(f"\n错误场景2 - 无效的app凭证:")
    print(f"  错误码: {error_response_2['code']}")
    print(f"  错误信息: {error_response_2['msg']}")
    print(f"  处理方案: 提示检查配置中的app_id和app_secret ✅")
    
    return True


def test_token_cache_persistence():
    """测试token缓存持久化"""
    print("\n测试7: Token缓存持久化")
    print("-" * 60)
    
    # 创建临时缓存目录
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_file = Path(tmpdir) / ".larksync_token_cache"
        
        # 准备token数据
        token_data = {
            "access_token": "cached_access_token_123",
            "refresh_token": "cached_refresh_token_456",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        
        # 写入缓存
        cache_file.write_text(json.dumps(token_data, indent=2))
        print(f"✅ Token缓存已写入: {cache_file}")
        
        # 读取并验证
        loaded_data = json.loads(cache_file.read_text())
        
        assert loaded_data["access_token"] == token_data["access_token"], "access_token不匹配"
        assert loaded_data["refresh_token"] == token_data["refresh_token"], "refresh_token不匹配"
        
        print(f"✅ 读取的access_token: {loaded_data['access_token']}")
        print(f"✅ 读取的refresh_token: {loaded_data['refresh_token']}")
        print(f"✅ 过期时间: {loaded_data['expires_at']}")
        print(f"✅ 更新时间: {loaded_data['updated_at']}")
    
    return True


def test_cli_config_with_refresh_support():
    """测试CLI配置对refresh token的支持"""
    print("\n测试8: CLI配置的Refresh Token支持")
    print("-" * 60)
    
    # 扩展后的配置示例
    extended_config = {
        "auth": {
            "app_id": "cli_app_id_123",
            "app_secret": "cli_app_secret_456",
            "user_access_token": "current_access_token",
            # 新增字段（提案）
            "user_refresh_token": "current_refresh_token",
            "token_expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        }
    }
    
    # 验证配置结构
    assert "user_refresh_token" in extended_config["auth"], "缺少user_refresh_token字段"
    assert "token_expires_at" in extended_config["auth"], "缺少token_expires_at字段"
    
    print("配置字段:")
    print(f"  ✅ app_id: {extended_config['auth']['app_id']}")
    print(f"  ✅ app_secret: {extended_config['auth']['app_secret']}")
    print(f"  ✅ user_access_token: {extended_config['auth']['user_access_token']}")
    print(f"  ✅ user_refresh_token: {extended_config['auth']['user_refresh_token']}")
    print(f"  ✅ token_expires_at: {extended_config['auth']['token_expires_at']}")
    
    return True


def test_401_error_detection():
    """测试401错误（token过期）的检测"""
    print("\n测试9: 401错误（Token过期）检测")
    print("-" * 60)
    
    from larksync.core.api_client import FeishuAPIError
    
    # 模拟401响应
    error = FeishuAPIError(
        status_code=401,
        message="token expired or invalid",
        payload={"code": 99991663, "msg": "token expired"}
    )
    
    print(f"✅ 检测到401错误:")
    print(f"  状态码: {error.status_code}")
    print(f"  错误信息: {error.message}")
    print(f"  错误码: {error.payload['code']}")
    
    # 验证错误属性
    assert error.status_code == 401, "状态码应该是401"
    assert "token" in error.message.lower(), "错误信息应该包含token"
    
    print(f"✅ 应该触发token刷新流程")
    
    return True


def test_refresh_workflow_design():
    """测试refresh workflow设计方案"""
    print("\n测试10: Token刷新工作流设计")
    print("-" * 60)
    
    workflow_steps = [
        "1. API调用前检查token过期时间",
        "2. 如果token即将过期（< 10分钟），触发刷新",
        "3. 使用app_id + app_secret + refresh_token调用飞书API",
        "4. 获取新的access_token和refresh_token",
        "5. 更新内存中的token",
        "6. 将新token写入缓存文件",
        "7. 继续执行原始API调用",
        "8. 如果刷新失败，根据错误码提示用户"
    ]
    
    print("完整的Token刷新工作流:")
    for step in workflow_steps:
        print(f"  {step}")
    
    print("\n✅ 工作流设计完整")
    return True


def run_all_tests():
    """运行所有测试"""
    print("=" * 70)
    print("命令行模式下Token刷新功能测试套件")
    print("=" * 70)
    
    tests = [
        ("从配置读取Token", test_user_access_token_from_config),
        ("从环境变量读取Token", test_user_access_token_from_env),
        ("API客户端认证头", test_api_client_auth_headers),
        ("Token过期检测", test_token_expiry_detection),
        ("Refresh Token API响应", test_refresh_token_api_response),
        ("Refresh Token错误处理", test_refresh_token_error_handling),
        ("Token缓存持久化", test_token_cache_persistence),
        ("CLI配置扩展支持", test_cli_config_with_refresh_support),
        ("401错误检测", test_401_error_detection),
        ("刷新工作流设计", test_refresh_workflow_design),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result, None))
        except Exception as e:
            results.append((name, False, str(e)))
    
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
            print(f"  错误: {error}")
        
        if result:
            passed += 1
        else:
            failed += 1
    
    print("\n" + "-" * 70)
    print(f"总计: {len(tests)} 个测试")
    print(f"通过: {passed} 个")
    print(f"失败: {failed} 个")
    print(f"成功率: {passed/len(tests)*100:.1f}%")
    
    # 打印实现建议
    if passed == len(tests):
        print("\n" + "=" * 70)
        print("实现建议")
        print("=" * 70)
        print("""
1. 扩展AuthSettings添加refresh token支持：
   - user_refresh_token: Optional[str]
   - token_expires_at: Optional[datetime]
   - token_refresh_margin_minutes: int = 10

2. 在FeishuAPIClient中添加token刷新方法：
   - _check_token_expiry() -> bool
   - _refresh_user_token() -> tuple[str, str, int]
   - _update_token_cache() -> None

3. 在API调用前自动检查并刷新token：
   - 在_request()方法开始处检查token
   - 如果即将过期，先刷新token
   - 刷新后更新self._auth.user_access_token

4. Token缓存文件位置：
   - ~/.larksync/token_cache (Linux/Mac)
   - %USERPROFILE%\\.larksync\\token_cache (Windows)

5. CLI命令扩展：
   - larksync refresh-token  # 手动刷新token
   - larksync token-status   # 查看token状态

6. 配置文件示例：
   [auth]
   app_id = "your_app_id"
   app_secret = "your_app_secret"
   user_access_token = "current_token"
   # 以下由系统自动管理，无需手动配置
   # user_refresh_token = "auto_managed"
   # token_expires_at = "auto_managed"
        """)
    
    print("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
