import { apiUrl } from './api';
import type { UserIdentity } from '../contexts/UserContext';

export type OAuthAuthorizeResponse = {
  authorization_url: string;
  state: string;
};

export type OAuthCallbackResult = {
  success: boolean;
  message?: string | null;
  user_id?: number;
  display_name?: string | null;
  avatar_url?: string | null;
};

export async function requestAuthorizationUrl(): Promise<OAuthAuthorizeResponse> {
  const response = await fetch(apiUrl('/auth/authorize'));
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `获取授权地址失败（${response.status}）`);
  }
  return (await response.json()) as OAuthAuthorizeResponse;
}

export async function exchangeAuthorizationCode(code: string, state: string): Promise<OAuthCallbackResult> {
  const response = await fetch(apiUrl('/auth/callback'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ code, state }),
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `授权失败（${response.status}）`);
  }
  return (await response.json()) as OAuthCallbackResult;
}

export async function fetchUserProfile(userId: string): Promise<UserIdentity> {
  const response = await fetch(apiUrl('/users/me'), {
    headers: {
      'X-User-ID': userId,
    },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `获取用户信息失败（${response.status}）`);
  }
  const data = (await response.json()) as {
    id: number;
    feishu_user_id: string;
    display_name?: string | null;
    avatar_url?: string | null;
  };
  return {
    id: String(data.id),
    displayName: data.display_name,
    avatarUrl: data.avatar_url,
  };
}
