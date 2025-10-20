'use client';

import { FormEvent, useState } from 'react';
import { requestAuthorizationUrl } from '../lib/auth';
import { useUserContext } from '../contexts/UserContext';

export default function UserGate({ children }: { children: React.ReactNode }): JSX.Element {
  const { user, setUser } = useUserContext();
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleManualSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmed = value.trim();
    if (!trimmed) {
      setError('请输入有效的用户 ID');
      return;
    }
    setUser({ id: trimmed });
    setValue('');
    setError(null);
  };

  const handleOAuthLogin = async () => {
    try {
      setLoading(true);
      const { authorization_url } = await requestAuthorizationUrl();
      window.location.href = authorization_url;
    } catch (err) {
      console.error('Failed to fetch authorization url', err);
      setError(err instanceof Error ? err.message : '无法获取授权地址');
      setLoading(false);
    }
  };

  if (user) {
    return <>{children}</>;
  }

  return (
    <div className="card" style={{ maxWidth: 460, margin: '80px auto', display: 'grid', gap: 24 }}>
      <div>
        <h1>登录 LarkSync 控制台</h1>
        <p style={{ marginTop: 12, color: 'var(--muted)', lineHeight: 1.6 }}>
          建议通过 Feishu OAuth 授权登录，系统将自动保存访问令牌并在后台刷新。
        </p>
      </div>

      <button
        className="button"
        style={{ justifyContent: 'center', fontSize: '1rem', padding: '12px 18px' }}
        onClick={handleOAuthLogin}
        disabled={loading}
      >
        {loading ? '跳转中...' : '使用飞书账号登录'}
      </button>

      <div style={{ color: 'var(--muted)', fontSize: '0.85rem' }}>或手动填写已授权的用户 ID（调试用途）</div>

      <form onSubmit={handleManualSubmit} className="form-inline" style={{ flexDirection: 'column', gap: 12 }}>
        <div style={{ width: '100%' }}>
          <label htmlFor="userId">用户 ID</label>
          <input
            id="userId"
            placeholder="例如：ou_xxxxxx"
            value={value}
            onChange={(event) => setValue(event.target.value)}
          />
        </div>
        {error ? (
          <span style={{ color: 'var(--danger)', fontSize: '0.85rem' }}>{error}</span>
        ) : (
          <span style={{ color: 'var(--muted)', fontSize: '0.8rem' }}>
            ID 仅保存在浏览器的 LocalStorage 中，可在设置中清除。
          </span>
        )}
        <button type="submit" className="button" style={{ width: '100%', justifyContent: 'center' }}>
          直接绑定
        </button>
      </form>
    </div>
  );
}
