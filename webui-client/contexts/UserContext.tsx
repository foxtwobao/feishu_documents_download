'use client';

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';

export type UserIdentity = {
  id: string;
  displayName?: string | null;
  avatarUrl?: string | null;
};

type UserContextValue = {
  user: UserIdentity | null;
  setUser: (value: UserIdentity | null) => void;
};

const STORAGE_KEY = 'larksync.user';

const UserContext = createContext<UserContextValue | undefined>(undefined);

export function UserProvider({ children }: { children: React.ReactNode }): JSX.Element {
  const [user, setUserState] = useState<UserIdentity | null>(null);

  useEffect(() => {
    if (typeof window === 'undefined') {
      return;
    }
    const cached = window.localStorage.getItem(STORAGE_KEY);
    if (cached) {
      try {
        const parsed = JSON.parse(cached) as UserIdentity;
        if (parsed && parsed.id) {
          setUserState(parsed);
        }
      } catch {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    }
  }, []);

  const setUser = useCallback((value: UserIdentity | null) => {
    if (typeof window === 'undefined') {
      return;
    }
    if (value) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    setUserState(value);
  }, []);

  const value = useMemo<UserContextValue>(() => ({ user, setUser }), [user, setUser]);

  return <UserContext.Provider value={value}>{children}</UserContext.Provider>;
}

export function useUserContext(): UserContextValue {
  const ctx = useContext(UserContext);
  if (!ctx) {
    throw new Error('useUserContext must be used inside UserProvider');
  }
  return ctx;
}
