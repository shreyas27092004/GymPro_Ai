// src/auth/AuthContext.tsx
import React, { createContext, useContext, useEffect, useState } from 'react';
import { client, getAccessToken, setAccessToken } from '../api/client';
import type { UserRole, UserSession } from '../types';

interface AuthContextType {
  me: UserSession | null;
  isLoading: boolean;
  token: string | null;
  login: (token: string, session?: UserSession) => Promise<UserSession | null>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<UserSession | null>;
  theme: 'light' | 'dark';
  toggleTheme: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const homeFor = (role?: UserRole | string): string => {
  switch (role) {
    case 'TRAINER':
      return '/trainer';
    case 'ADMIN':
      return '/admin';
    case 'USER':
    default:
      return '/app';
  }
};

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [me, setMe] = useState<UserSession | null>(null);
  const [token, setTokenState] = useState<string | null>(getAccessToken());
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    return (localStorage.getItem('gympro_theme') as 'light' | 'dark') || 'light';
  });

  useEffect(() => {
    if (theme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
    localStorage.setItem('gympro_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme((t) => (t === 'light' ? 'dark' : 'light'));
  };

  const refreshMe = async (): Promise<UserSession | null> => {
    try {
      const res = await client.get<UserSession>('/me');
      setMe(res.data);
      return res.data;
    } catch {
      setMe(null);
      return null;
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => {
    if (token) {
      refreshMe();
    } else {
      setIsLoading(false);
    }
  }, [token]);

  const login = async (newToken: string, session?: UserSession): Promise<UserSession | null> => {
    setAccessToken(newToken);
    setTokenState(newToken);
    if (session) {
      setMe(session);
      setIsLoading(false);
      return session;
    } else {
      setIsLoading(true);
      const user = await refreshMe();
      return user;
    }
  };

  const logout = async () => {
    try {
      await client.post('/auth/logout', {});
    } catch {
      // ignore
    } finally {
      setAccessToken(null);
      setTokenState(null);
      setMe(null);
    }
  };

  return (
    <AuthContext.Provider
      value={{
        me,
        isLoading,
        token,
        login,
        logout,
        refreshMe,
        theme,
        toggleTheme,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return ctx;
};
