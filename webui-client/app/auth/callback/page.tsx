'use client';

import Link from 'next/link';
import { useRouter, useSearchParams } from 'next/navigation';
import { useEffect, useMemo, useState } from 'react';
import { exchangeAuthorizationCode, fetchUserProfile } from '../../../lib/auth';
import { useUserContext } from '../../../contexts/UserContext';

export default function AuthCallbackPage(): JSX.Element {
  const searchParams = useSearchParams();
  const router = useRouter();
  const { setUser } = useUserContext();
  const [message, setMessage] = useState('正在处理授权结果...');
  const [error, setError] = useState<string | null>(null);

  const query = useMemo(() => Object.fromEntries(searchParams.entries()), [searchParams]);

  useEffect(() => {
    const statusParam = query.status;
    const code = query.code;
    const state = query.state;

    const handleSuccess = async (userId: string, displayName?: string | null, avatarUrl?: string | null) => {
      try {
        if (!displayName && !avatarUrl) {
          const profile = await fetchUserProfile(userId);
          setUser({ id: profile.id, displayName: profile.displayName, avatarUrl: profile.avatarUrl });
        } else {
          setUser({ id: userId, displayName, avatarUrl });
        }
        setMessage('授权成功，正在跳转...');
        setTimeout(() => router.replace('/'), 1200);
      } catch (err) {
        console.error('Failed to hydrate profile after login', err);
        setUser({ id: userId });
        setMessage('授权成功，但获取用户信息失败，可稍后在控制台重试');
        setTimeout(() => router.replace('/'), 1500);
      }
    };

    const handleError = (info: string) => {
      setError(info);
      setMessage('');
    };

    if (statusParam) {
      if (statusParam === 'success' && query.user_id) {
        void handleSuccess(query.user_id, query.display_name, query.avatar_url);
        return;
      }
      const info = query.message ?? '授权失败，请重新尝试';
      handleError(info);
      return;
    }

    if (code && state) {
      const run = async () => {
        try {
          const result = await exchangeAuthorizationCode(code, state);
          if (!result.success || !result.user_id) {
            throw new Error(result.message ?? '授权失败');
          }
          const userId = String(result.user_id);
          await handleSuccess(userId, result.display_name, result.avatar_url);
        } catch (err) {
          console.error('OAuth callback failed', err);
          handleError(err instanceof Error ? err.message : '授权失败，请重试');
        }
      };
      void run();
      return;
    }

    handleError('缺少授权参数，无法完成登录。');
  }, [query, router, setUser]);

  return (
    <div className="card" style={{ maxWidth: 420, margin: '80px auto', display: 'grid', gap: 16, textAlign: 'center' }}>
      <h1>登录状态</h1>
      {message ? <div style={{ color: 'var(--muted)' }}>{message}</div> : null}
      {error ? <div style={{ color: 'var(--danger)' }}>{error}</div> : null}
      <Link href="/" className="button" style={{ justifyContent: 'center' }}>
        返回任务列表
      </Link>
    </div>
  );
}
