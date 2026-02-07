"""实际测试token刷新功能的集成测试"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from larksync.config import load_config
from larksync.web.auth import FeishuOAuthClient
from larksync.web.database import session_scope
from larksync.web.models import User


async def test_actual_token_refresh():
    """实际测试token刷新功能"""
    print("开始测试实际的token刷新功能...")
    
    # 加载配置
    config_path = project_root / "config.toml"
    if not config_path.exists():
        print("❌ 配置文件不存在，请先配置config.toml")
        return False
    
    try:
        config = load_config(config_path)
        oauth_settings = config.web.oauth
        
        # 检查OAuth配置
        if not oauth_settings.app_id or not oauth_settings.app_secret:
            print("❌ OAuth配置不完整，请检查config.toml中的[web.oauth]配置")
            return False
        
        print(f"✅ OAuth配置检查通过: app_id={oauth_settings.app_id[:8]}...")
        
        # 创建OAuth客户端
        oauth_client = FeishuOAuthClient(oauth_settings)
        
        if not oauth_client.enabled:
            print("❌ OAuth客户端未启用")
            return False
        
        print("✅ OAuth客户端创建成功")
        
        # 查找有refresh_token的用户
        with session_scope() as session:
            users_with_refresh_token = session.query(User).filter(
                User.refresh_token.isnot(None),
                User.refresh_token != ""
            ).all()
            
            if not users_with_refresh_token:
                print("❌ 没有找到有refresh_token的用户，请先通过web界面登录")
                return False
            
            print(f"✅ 找到 {len(users_with_refresh_token)} 个有refresh_token的用户")
            
            # 测试每个用户的token刷新
            success_count = 0
            for user in users_with_refresh_token:
                print(f"\n测试用户: {user.display_name} (ID: {user.feishu_user_id})")
                print(f"当前token过期时间: {user.token_expires_at}")
                
                try:
                    # 尝试刷新token
                    print("正在刷新token...")
                    new_access_token, new_refresh_token, expires_in = await oauth_client.refresh_token(user.refresh_token)
                    
                    print(f"✅ Token刷新成功!")
                    print(f"   新access_token: {new_access_token[:20]}...")
                    print(f"   新refresh_token: {new_refresh_token[:20]}...")
                    print(f"   过期时间: {expires_in}秒")
                    
                    # 更新用户信息
                    user.access_token = new_access_token
                    user.refresh_token = new_refresh_token
                    user.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
                    session.add(user)
                    session.commit()
                    
                    success_count += 1
                    
                except Exception as e:
                    print(f"❌ Token刷新失败: {e}")
                    continue
            
            print(f"\n📊 测试结果: {success_count}/{len(users_with_refresh_token)} 个用户token刷新成功")
            
            if success_count > 0:
                print("✅ Token刷新功能正常工作!")
                return True
            else:
                print("❌ 所有用户的token刷新都失败了")
                return False
                
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False


async def test_user_info_fetch():
    """测试使用新token获取用户信息"""
    print("\n开始测试使用新token获取用户信息...")
    
    try:
        config = load_config(project_root / "config.toml")
        oauth_client = FeishuOAuthClient(config.web.oauth)
        
        with session_scope() as session:
            # 找一个有有效token的用户
            user = session.query(User).filter(
                User.access_token.isnot(None),
                User.token_expires_at > datetime.now(timezone.utc)
            ).first()
            
            if not user:
                print("❌ 没有找到有有效token的用户")
                return False
            
            print(f"测试用户: {user.display_name}")
            
            # 使用access_token获取用户信息
            user_info = await oauth_client.fetch_user_info(user.access_token)
            print(f"✅ 成功获取用户信息: {user_info}")
            return True
            
    except Exception as e:
        print(f"❌ 获取用户信息失败: {e}")
        return False


def test_token_expiry_logic():
    """测试token过期时间计算逻辑"""
    print("\n开始测试token过期时间计算逻辑...")
    
    try:
        from larksync.web.auth import compute_expiry
        
        # 测试不同的expires_in值
        test_cases = [3600, 7200, 1800]  # 1小时, 2小时, 30分钟
        
        for expires_in in test_cases:
            expiry = compute_expiry(expires_in)
            now = datetime.now(timezone.utc)
            expected = now + timedelta(seconds=expires_in)
            
            # 检查计算是否正确（允许1秒误差）
            diff = abs((expiry - expected).total_seconds())
            if diff < 1:
                print(f"✅ expires_in={expires_in}秒, 计算正确")
            else:
                print(f"❌ expires_in={expires_in}秒, 计算错误, 差异={diff}秒")
                return False
        
        print("✅ Token过期时间计算逻辑正确")
        return True
        
    except Exception as e:
        print(f"❌ 测试token过期时间计算失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("=" * 60)
    print("飞书文档下载系统 - Token刷新功能测试")
    print("=" * 60)
    
    # 测试1: token过期时间计算
    test1_result = test_token_expiry_logic()
    
    # 测试2: 实际token刷新
    test2_result = await test_actual_token_refresh()
    
    # 测试3: 使用新token获取用户信息
    test3_result = await test_user_info_fetch()
    
    print("\n" + "=" * 60)
    print("测试总结:")
    print(f"Token过期时间计算: {'✅ 通过' if test1_result else '❌ 失败'}")
    print(f"Token刷新功能: {'✅ 通过' if test2_result else '❌ 失败'}")
    print(f"用户信息获取: {'✅ 通过' if test3_result else '❌ 失败'}")
    
    overall_success = test1_result and test2_result and test3_result
    print(f"\n总体结果: {'✅ 所有测试通过' if overall_success else '❌ 部分测试失败'}")
    print("=" * 60)
    
    return overall_success


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(main())
    sys.exit(0 if success else 1)


