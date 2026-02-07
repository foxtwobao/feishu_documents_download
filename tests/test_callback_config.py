#!/usr/bin/env python3
"""测试回调地址配置功能"""

import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from larksync.config import load_config
from larksync.cli_oauth import CLIOAuthClient, CLITokenManager


def test_callback_url_config():
    """测试回调 URL 配置"""
    print("=" * 70)
    print("测试回调地址配置功能")
    print("=" * 70)
    
    # 加载配置
    config = load_config(Path("config.toml"))
    
    print("\n配置信息:")
    print(f"  app_id: {config.auth.app_id}")
    print(f"  app_secret: {config.auth.app_secret[:10]}..." if config.auth.app_secret else "  app_secret: None")
    print(f"  oauth_callback_url: {config.auth.oauth_callback_url}")
    
    # 创建 OAuth 客户端
    if config.auth.app_id and config.auth.app_secret:
        print("\n创建 OAuth 客户端...")
        
        # 测试使用配置的回调 URL
        client = CLIOAuthClient(
            config.auth.app_id,
            config.auth.app_secret,
            callback_url=config.auth.oauth_callback_url
        )
        
        print(f"\n✅ OAuth 客户端创建成功")
        print(f"  回调 URL: {client.callback_url}")
        print(f"  回调主机: {client.callback_host}")
        print(f"  回调端口: {client.callback_port}")
        
        # 测试授权 URL 构建
        test_state = "test_state_123"
        auth_url = client.build_authorization_url(test_state)
        
        print(f"\n授权 URL 示例:")
        print(f"  {auth_url}")
        
        # 验证回调 URL 在授权 URL 中
        from urllib.parse import unquote
        if config.auth.oauth_callback_url:
            if config.auth.oauth_callback_url in unquote(auth_url):
                print(f"\n✅ 回调 URL 正确包含在授权 URL 中")
            else:
                print(f"\n⚠️  回调 URL 未正确包含在授权 URL 中")
        
        # 测试 TokenManager
        print("\n创建 Token 管理器...")
        manager = CLITokenManager(config.auth)
        
        if manager.oauth_client:
            print(f"✅ Token 管理器创建成功")
            print(f"  使用的回调 URL: {manager.oauth_client.callback_url}")
        else:
            print("❌ Token 管理器创建失败")
        
        print("\n" + "=" * 70)
        print("测试完成！")
        print("=" * 70)
        
        # 输出使用提示
        print("\n📋 配置说明:")
        print("""
1. 默认回调地址: http://localhost:8899/callback
   - 适用于本机浏览器访问

2. 自定义回调地址: 在 config.toml 中配置
   [auth]
   oauth_callback_url = "http://192.168.10.35:8899/callback"
   
   - 适用于远程访问或特定 IP 需求
   - 需要在飞书应用后台配置相同的回调地址

3. 注意事项:
   - 回调地址必须与飞书应用后台配置一致
   - 支持自定义端口（如 :9000）
   - IP 地址可以是内网 IP（如 192.168.x.x）或公网 IP
        """)
        
    else:
        print("\n❌ 未配置 app_id 和 app_secret")
        print("请在 config.toml 中配置:")
        print("""
[auth]
app_id = "your_app_id"
app_secret = "your_app_secret"
oauth_callback_url = "http://192.168.10.35:8899/callback"
        """)


if __name__ == "__main__":
    test_callback_url_config()
