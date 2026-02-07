'use client';

import { useRouter } from 'next/navigation';
import { logout } from '@/lib/auth';

export default function AccessDenied() {
  const router = useRouter();

  const handleLogout = async () => {
    await logout();
    router.replace('/');
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="card p-8 max-w-md w-full text-center animate-fade-in">
        <div className="mb-4 text-lg font-semibold text-dark-text">无权限使用本系统</div>
        <p className="text-sm text-dark-muted">
          当前账号未被授权使用 Web 同步功能，请联系管理员配置权限。
        </p>
        <button
          onClick={handleLogout}
          className="btn btn-secondary w-full mt-6"
        >
          退出登录
        </button>
      </div>
    </div>
  );
}
