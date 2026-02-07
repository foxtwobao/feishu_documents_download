'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { initializeAuth, parseCallbackParams, setStoredUser, SessionUser } from '@/lib/auth';
import api, { SyncConfig, SyncRun, User } from '@/lib/api';
import Shell from '@/components/Shell';
import Dashboard from '@/components/Dashboard';
import AccessDenied from '@/components/AccessDenied';

export default function Home() {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);
  const [userProfile, setUserProfile] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);

  useEffect(() => {
    // Check for callback params first
    const callbackUser = parseCallbackParams();
    if (callbackUser) {
      setStoredUser(callbackUser);
      setUser(callbackUser);
      // Clear URL params
      router.replace('/');
      setLoading(false);
      return;
    }

    // Otherwise, check stored user
    const storedUser = initializeAuth();
    if (storedUser) {
      setUser(storedUser);
      // Fetch full profile
      api.getMe()
        .then(profile => setUserProfile(profile))
        .catch((error) => {
          if ((error as Error).message.includes('not allowed')) {
            setAccessDenied(true);
          }
        })
        .finally(() => setLoading(false));
      return;
    }
    setLoading(false);
  }, [router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-pulse-slow text-dark-muted">加载中...</div>
      </div>
    );
  }

  if (accessDenied) {
    return <AccessDenied />;
  }

  if (!user) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <div className="card p-8 max-w-md w-full text-center animate-fade-in">
          <div className="mb-6">
            <div className="w-16 h-16 mx-auto mb-4 bg-gradient-to-br from-feishu-blue to-feishu-green rounded-2xl flex items-center justify-center">
              <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
              </svg>
            </div>
            <h1 className="text-2xl font-bold text-dark-text mb-2">LarkSync</h1>
            <p className="text-dark-muted">飞书文档自动同步系统</p>
          </div>

          <div className="space-y-4">
            <p className="text-sm text-dark-muted">
              登录后即可配置自动同步任务，将飞书个人空间和知识库的文档同步到本地。
            </p>
            
            <button
              onClick={async () => {
                try {
                  const { authorization_url } = await api.getAuthorizationUrl();
                  window.location.href = authorization_url;
                } catch (error) {
                  alert('获取授权链接失败：' + (error as Error).message);
                }
              }}
              className="btn btn-primary w-full py-3 flex items-center justify-center gap-2"
            >
              <svg className="w-5 h-5" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 3c1.66 0 3 1.34 3 3s-1.34 3-3 3-3-1.34-3-3 1.34-3 3-3zm0 14.2c-2.5 0-4.71-1.28-6-3.22.03-1.99 4-3.08 6-3.08 1.99 0 5.97 1.09 6 3.08-1.29 1.94-3.5 3.22-6 3.22z"/>
              </svg>
              使用飞书账号登录
            </button>
          </div>

          <div className="mt-8 pt-6 border-t border-dark-border">
            <div className="flex items-center justify-center gap-6 text-sm text-dark-muted">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-feishu-green" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                增量同步
              </div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-feishu-green" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                定时任务
              </div>
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-feishu-green" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
                多用户隔离
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  return (
    <Shell user={user} userProfile={userProfile}>
      <Dashboard user={user} userProfile={userProfile} />
    </Shell>
  );
}
