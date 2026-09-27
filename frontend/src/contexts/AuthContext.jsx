import React, { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { authAPI } from '../services/api';

const AuthContext = createContext(null);

function normalizeUserPayload(payload) {
  if (!payload) return null;

  if (payload.user && typeof payload.user === 'object') {
    return payload.user;
  }

  const { token, remember_token, ...user } = payload;
  return user.id ? user : null;
}

function storeUser(u) {
  localStorage.setItem('admin_user', JSON.stringify(u));
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Roles come from /api/users/me → admin_roles (spec §19.1.14). Refresh them on
  // every start so a role change made by a super admin applies on reload.
  const refresh = useCallback(async () => {
    try {
      const { data } = await authAPI.me();
      if (data?.code === 1 && data.data) {
        const me = normalizeUserPayload(Array.isArray(data.data) ? data.data[0] : data.data);
        if (me) {
          storeUser(me);
          setUser(me);
          return me;
        }
      }
    } catch {
      /* 401 is handled by the interceptor */
    }
    return null;
  }, []);

  useEffect(() => {
    const token = localStorage.getItem('admin_token');
    const stored = localStorage.getItem('admin_user');
    if (token && stored) {
      try { setUser(JSON.parse(stored)); } catch { localStorage.clear(); }
      refresh().finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, [refresh]);

  const login = useCallback(async (email, password) => {
    const { data } = await authAPI.login({ email, password });
    if (data.code === 1) {
      const payload = data.data || {};
      const userData = normalizeUserPayload(payload);
      const token = payload.token || payload.remember_token;

      if (!token || !userData) {
        throw new Error('Login response is missing user session data');
      }

      localStorage.setItem('admin_token', token);
      storeUser(userData);
      const me = (await refresh()) || userData;
      const roles = me.admin_roles || [];
      if (!roles.length) {
        localStorage.removeItem('admin_token');
        localStorage.removeItem('admin_user');
        setUser(null);
        throw new Error('This account has no admin role.');
      }
      setUser(me);
      return data;
    }
    throw new Error(data.message || 'Login failed');
  }, [refresh]);

  const logout = useCallback(() => {
    localStorage.removeItem('admin_token');
    localStorage.removeItem('admin_user');
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refresh, isAuthenticated: !!user }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be used within AuthProvider');
  return ctx;
}
