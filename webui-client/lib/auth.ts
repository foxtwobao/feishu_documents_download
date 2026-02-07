/**
 * Authentication and session management
 */

import api from './api';

const USER_KEY = 'larksync_user';

export interface SessionUser {
  user_id: string;
  display_name: string | null;
  avatar_url: string | null;
}

export function getStoredUser(): SessionUser | null {
  if (typeof window === 'undefined') return null;
  
  const stored = localStorage.getItem(USER_KEY);
  if (!stored) return null;
  
  try {
    return JSON.parse(stored);
  } catch {
    return null;
  }
}

export function setStoredUser(user: SessionUser | null): void {
  if (typeof window === 'undefined') return;
  
  if (user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    api.setUserId(user.user_id);
  } else {
    localStorage.removeItem(USER_KEY);
    api.setUserId(null);
  }
}

export function initializeAuth(): SessionUser | null {
  const user = getStoredUser();
  if (user) {
    api.setUserId(user.user_id);
  }
  return user;
}

export async function logout(): Promise<void> {
  try {
    await api.logout();
  } catch {
    // Ignore errors during logout
  }
  setStoredUser(null);
}

export function parseCallbackParams(): SessionUser | null {
  if (typeof window === 'undefined') return null;
  
  const params = new URLSearchParams(window.location.search);
  const userId = params.get('user_id');
  const displayName = params.get('display_name');
  const avatarUrl = params.get('avatar_url');
  
  if (!userId) return null;
  
  return {
    user_id: userId,
    display_name: displayName || null,
    avatar_url: avatarUrl || null,
  };
}
