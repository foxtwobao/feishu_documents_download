"""Token显示和刷新测试页面"""

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 添加项目根目录到Python路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from larksync.config import load_config
from larksync.web.auth import FeishuOAuthClient, compute_expiry
from larksync.web.database import configure_database, init_database, session_scope
from larksync.web.models import User


class TokenDisplayPage:
    """Token显示和刷新测试页面"""
    
    def __init__(self):
        self.config = None
        self.oauth_client = None
        self.setup_database()
        self.load_config()
    
    def setup_database(self):
        """设置数据库"""
        try:
            db_path = project_root / "test.db"
            configure_database(db_path)
            init_database()
            print("✅ 数据库初始化成功")
        except Exception as e:
            print(f"❌ 数据库初始化失败: {e}")
            raise
    
    def load_config(self):
        """加载配置"""
        try:
            config_path = project_root / "config.toml"
            if not config_path.exists():
                raise FileNotFoundError("配置文件不存在")
            
            self.config = load_config(config_path)
            self.oauth_client = FeishuOAuthClient(self.config.web.oauth)
            print("✅ 配置加载成功")
        except Exception as e:
            print(f"❌ 配置加载失败: {e}")
            raise
    
    def display_user_tokens(self):
        """显示所有用户的token信息"""
        print("\n" + "="*80)
        print("用户Token信息显示")
        print("="*80)
        
        try:
            with session_scope() as session:
                users = session.query(User).all()
                
                if not users:
                    print("❌ 没有找到任何用户")
                    return False
                
                print(f"找到 {len(users)} 个用户:")
                print()
                
                for i, user in enumerate(users, 1):
                    print(f"用户 {i}: {user.display_name or '未命名用户'}")
                    print(f"  - 飞书用户ID: {user.feishu_user_id}")
                    print(f"  - 头像URL: {user.avatar_url or '无'}")
                    print(f"  - 创建时间: {user.created_at}")
                    print(f"  - 更新时间: {user.updated_at}")
                    print()
                    
                    # Token信息
                    print("  🔑 Token信息:")
                    if user.access_token:
                        print(f"    - Access Token: {user.access_token[:30]}...")
                    else:
                        print("    - Access Token: 无")
                    
                    if user.refresh_token:
                        print(f"    - Refresh Token: {user.refresh_token[:30]}...")
                    else:
                        print("    - Refresh Token: 无")
                    
                    if user.token_expires_at:
                        now = datetime.now(timezone.utc)
                        time_diff = user.token_expires_at - now
                        if time_diff.total_seconds() > 0:
                            print(f"    - Token过期时间: {user.token_expires_at}")
                            print(f"    - 剩余时间: {time_diff}")
                            if time_diff.total_seconds() < 300:  # 5分钟内过期
                                print("    ⚠️  Token即将过期!")
                        else:
                            print(f"    - Token过期时间: {user.token_expires_at}")
                            print("    ❌ Token已过期!")
                    else:
                        print("    - Token过期时间: 无")
                    
                    print()
                    print("-" * 60)
                
                return True
                
        except Exception as e:
            print(f"❌ 显示用户token信息失败: {e}")
            return False
    
    async def test_token_refresh(self, user_id: str = None):
        """测试token刷新功能"""
        print("\n" + "="*80)
        print("Token刷新测试")
        print("="*80)
        
        try:
            with session_scope() as session:
                # 选择要测试的用户
                if user_id:
                    user = session.query(User).filter_by(feishu_user_id=user_id).first()
                    if not user:
                        print(f"❌ 未找到用户ID: {user_id}")
                        return False
                    users_to_test = [user]
                else:
                    # 选择有refresh_token的用户
                    users_to_test = session.query(User).filter(
                        User.refresh_token.isnot(None),
                        User.refresh_token != ""
                    ).all()
                
                if not users_to_test:
                    print("❌ 没有找到有refresh_token的用户")
                    return False
                
                print(f"将测试 {len(users_to_test)} 个用户的token刷新...")
                print()
                
                success_count = 0
                for user in users_to_test:
                    print(f"🔄 测试用户: {user.display_name} ({user.feishu_user_id})")
                    print(f"   当前Access Token: {user.access_token[:30] if user.access_token else '无'}...")
                    print(f"   当前Refresh Token: {user.refresh_token[:30] if user.refresh_token else '无'}...")
                    print(f"   当前过期时间: {user.token_expires_at}")
                    
                    try:
                        # 记录刷新前的token
                        old_access_token = user.access_token
                        old_refresh_token = user.refresh_token
                        old_expires_at = user.token_expires_at
                        
                        print("   正在刷新token...")
                        
                        # 执行token刷新
                        new_access_token, new_refresh_token, expires_in = await self.oauth_client.refresh_token(user.refresh_token)
                        
                        print("   ✅ Token刷新成功!")
                        print(f"   新Access Token: {new_access_token[:30]}...")
                        print(f"   新Refresh Token: {new_refresh_token[:30]}...")
                        print(f"   新过期时间: {expires_in}秒")
                        
                        # 更新用户信息
                        user.access_token = new_access_token
                        user.refresh_token = new_refresh_token
                        user.token_expires_at = compute_expiry(expires_in)
                        session.add(user)
                        session.commit()
                        
                        print(f"   更新后过期时间: {user.token_expires_at}")
                        
                        # 验证token是否真的更新了
                        if new_access_token != old_access_token:
                            print("   ✅ Access Token已更新")
                        else:
                            print("   ⚠️  Access Token未变化")
                        
                        if new_refresh_token != old_refresh_token:
                            print("   ✅ Refresh Token已更新")
                        else:
                            print("   ⚠️  Refresh Token未变化")
                        
                        success_count += 1
                        
                    except Exception as e:
                        print(f"   ❌ Token刷新失败: {e}")
                        continue
                    
                    print()
                    print("-" * 60)
                
                print(f"\n📊 刷新结果: {success_count}/{len(users_to_test)} 个用户token刷新成功")
                return success_count > 0
                
        except Exception as e:
            print(f"❌ Token刷新测试失败: {e}")
            return False
    
    async def test_user_info_fetch(self, user_id: str = None):
        """测试使用新token获取用户信息"""
        print("\n" + "="*80)
        print("用户信息获取测试")
        print("="*80)
        
        try:
            with session_scope() as session:
                # 选择要测试的用户
                if user_id:
                    user = session.query(User).filter_by(feishu_user_id=user_id).first()
                    if not user:
                        print(f"❌ 未找到用户ID: {user_id}")
                        return False
                    users_to_test = [user]
                else:
                    # 选择有有效token的用户
                    users_to_test = session.query(User).filter(
                        User.access_token.isnot(None),
                        User.token_expires_at > datetime.now(timezone.utc)
                    ).all()
                
                if not users_to_test:
                    print("❌ 没有找到有有效token的用户")
                    return False
                
                print(f"将测试 {len(users_to_test)} 个用户的token有效性...")
                print()
                
                success_count = 0
                for user in users_to_test:
                    print(f"🔍 测试用户: {user.display_name} ({user.feishu_user_id})")
                    print(f"   Access Token: {user.access_token[:30] if user.access_token else '无'}...")
                    print(f"   Token过期时间: {user.token_expires_at}")
                    
                    try:
                        # 使用access_token获取用户信息
                        user_info = await self.oauth_client.fetch_user_info(user.access_token)
                        print("   ✅ 成功获取用户信息:")
                        for key, value in user_info.items():
                            print(f"     {key}: {value}")
                        
                        success_count += 1
                        
                    except Exception as e:
                        print(f"   ❌ 获取用户信息失败: {e}")
                        continue
                    
                    print()
                    print("-" * 60)
                
                print(f"\n📊 用户信息获取结果: {success_count}/{len(users_to_test)} 个用户成功")
                return success_count > 0
                
        except Exception as e:
            print(f"❌ 用户信息获取测试失败: {e}")
            return False
    
    def create_test_user(self):
        """创建测试用户"""
        print("\n" + "="*80)
        print("创建测试用户")
        print("="*80)
        
        try:
            with session_scope() as session:
                # 检查是否已有测试用户
                test_user = session.query(User).filter_by(feishu_user_id="test_user_display").first()
                
                if test_user:
                    print("✅ 测试用户已存在")
                    return test_user
                
                # 创建测试用户
                test_user = User(
                    feishu_user_id="test_user_display",
                    display_name="Token显示测试用户",
                    access_token="test_access_token_12345",
                    refresh_token="test_refresh_token_67890",
                    token_expires_at=datetime.now(timezone.utc) + timedelta(minutes=2)  # 即将过期
                )
                session.add(test_user)
                session.commit()
                
                print("✅ 测试用户创建成功")
                print(f"   用户ID: {test_user.feishu_user_id}")
                print(f"   显示名称: {test_user.display_name}")
                print(f"   Access Token: {test_user.access_token}")
                print(f"   Refresh Token: {test_user.refresh_token}")
                print(f"   过期时间: {test_user.token_expires_at}")
                
                return test_user
                
        except Exception as e:
            print(f"❌ 创建测试用户失败: {e}")
            return None


async def main():
    """主函数"""
    print("="*80)
    print("飞书文档下载系统 - Token显示和刷新测试页面")
    print("="*80)
    
    try:
        # 创建测试页面实例
        page = TokenDisplayPage()
        
        # 1. 显示当前用户token信息
        print("\n1️⃣ 显示当前用户token信息")
        page.display_user_tokens()
        
        # 2. 创建测试用户（如果没有的话）
        print("\n2️⃣ 创建测试用户")
        test_user = page.create_test_user()
        
        # 3. 再次显示用户信息（包括新创建的测试用户）
        print("\n3️⃣ 显示所有用户token信息")
        page.display_user_tokens()
        
        # 4. 测试token刷新功能
        print("\n4️⃣ 测试token刷新功能")
        refresh_success = await page.test_token_refresh()
        
        # 5. 显示刷新后的token信息
        print("\n5️⃣ 显示刷新后的token信息")
        page.display_user_tokens()
        
        # 6. 测试使用新token获取用户信息
        print("\n6️⃣ 测试使用新token获取用户信息")
        if refresh_success:
            await page.test_user_info_fetch()
        
        print("\n" + "="*80)
        print("测试完成!")
        print("="*80)
        
        return True
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        return False


if __name__ == "__main__":
    # 运行测试
    success = asyncio.run(main())
    sys.exit(0 if success else 1)


