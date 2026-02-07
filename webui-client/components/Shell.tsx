'use client';

import { useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { logout, SessionUser } from '@/lib/auth';
import { User } from '@/lib/api';

interface ShellProps {
  user: SessionUser;
  userProfile: User | null;
  children: React.ReactNode;
}

const navItems = [
  { href: '/', label: '仪表板', icon: 'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6' },
  { href: '/sync-configs', label: '同步配置', icon: 'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z M15 12a3 3 0 11-6 0 3 3 0 016 0z' },
  { href: '/sync-runs', label: '执行记录', icon: 'M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01' },
];

export default function Shell({ user, userProfile, children }: ShellProps) {
  const pathname = usePathname();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);

  const formatTimestamp = (value?: string | null) => {
    if (!value) {
      return '未设置';
    }
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return '无效时间';
    }
    try {
      return new Intl.DateTimeFormat(undefined, {
        dateStyle: 'medium',
        timeStyle: 'short',
        timeZoneName: 'short',
      }).format(date);
    } catch (error) {
      return date.toLocaleString();
    }
  };

  const handleLogout = async () => {
    await logout();
    window.location.href = '/';
  };

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-50 w-64 bg-dark-surface/95 backdrop-blur-xl border-r border-dark-border transform transition-transform duration-200 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full lg:translate-x-0'
        }`}
      >
        <div className="flex flex-col h-full">
          {/* Logo */}
          <div className="p-4 border-b border-dark-border">
            <Link href="/" className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-feishu-blue to-feishu-green rounded-xl flex items-center justify-center">
                <svg className="w-5 h-5 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                </svg>
              </div>
              <span className="text-lg font-semibold text-dark-text">LarkSync</span>
            </Link>
          </div>

          {/* Navigation */}
          <nav className="flex-1 p-4 space-y-1">
            {navItems.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${
                  pathname === item.href
                    ? 'bg-feishu-blue/20 text-feishu-blue'
                    : 'text-dark-muted hover:bg-dark-border/50 hover:text-dark-text'
                }`}
              >
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={item.icon} />
                </svg>
                {item.label}
              </Link>
            ))}
          </nav>

          {/* User section */}
          <div className="p-4 border-t border-dark-border">
            <div
              className="flex items-center gap-3 p-2 rounded-lg hover:bg-dark-border/50 cursor-pointer transition-colors"
              onClick={() => setUserMenuOpen(!userMenuOpen)}
            >
              {user.avatar_url ? (
                <img
                  src={user.avatar_url}
                  alt={user.display_name || 'User'}
                  className="w-8 h-8 rounded-full"
                />
              ) : (
                <div className="w-8 h-8 rounded-full bg-feishu-blue/20 flex items-center justify-center">
                  <span className="text-feishu-blue text-sm font-medium">
                    {(user.display_name || 'U')[0]}
                  </span>
                </div>
              )}
              <div className="flex-1 min-w-0">
                <div className="text-sm font-medium text-dark-text truncate">
                  {user.display_name || '用户'}
                </div>
                <div className="text-xs text-dark-muted truncate">
                  {userProfile?.token_status === 'valid' ? '已授权' : '需要重新授权'}
                </div>
              </div>
              <svg className="w-4 h-4 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
              </svg>
            </div>

            {userMenuOpen && (
              <div className="mt-2 py-1 bg-dark-bg border border-dark-border rounded-lg animate-fade-in">
                <div className="px-4 py-2 text-xs text-dark-muted space-y-1">
                  <div className="flex justify-between gap-2">
                    <span>Access 过期</span>
                    <span className="text-dark-text">
                      {formatTimestamp(userProfile?.token_expires_at)}
                    </span>
                  </div>
                  <div className="flex justify-between gap-2">
                    <span>Refresh 过期</span>
                    <span className="text-dark-text">
                      {formatTimestamp(userProfile?.refresh_token_expires_at)}
                    </span>
                  </div>
                </div>
                <div className="my-1 border-t border-dark-border" />
                <button
                  onClick={handleLogout}
                  className="w-full px-4 py-2 text-left text-sm text-feishu-red hover:bg-dark-border/50 transition-colors"
                >
                  退出登录
                </button>
              </div>
            )}
          </div>
        </div>
      </aside>

      {/* Mobile sidebar overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Main content */}
      <main className="flex-1 min-w-0">
        {/* Mobile header */}
        <header className="lg:hidden sticky top-0 z-30 bg-dark-surface/95 backdrop-blur-xl border-b border-dark-border px-4 py-3">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setSidebarOpen(true)}
              className="p-2 rounded-lg hover:bg-dark-border/50 transition-colors"
            >
              <svg className="w-5 h-5 text-dark-muted" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
              </svg>
            </button>
            <span className="text-lg font-semibold text-dark-text">LarkSync</span>
          </div>
        </header>

        {/* Page content */}
        <div className="p-4 lg:p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
