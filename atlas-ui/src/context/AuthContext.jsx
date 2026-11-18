import { createContext, useCallback, useContext, useEffect, useState } from "react";
import * as api from "../services/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    return api.getAuthToken() ? api.getCachedAuthUser() : null;
  });
  const [ready, setReady] = useState(() => {
    const token = api.getAuthToken();
    if (!token) return true;
    return Boolean(api.getCachedAuthUser());
  });

  const refresh = useCallback(async () => {
    const token = api.getAuthToken();
    if (!token) {
      setUser(null);
      setReady(true);
      return null;
    }
    const cached = api.getCachedAuthUser();
    if (cached) {
      setUser(cached);
      setReady(true);
    }
    try {
      const me = await api.getMe();
      setUser(me);
      api.setAuthToken(token, me);
      setReady(true);
      return me;
    } catch {
      api.clearAuthToken();
      setUser(null);
      setReady(true);
      return null;
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    function onAuthRequired() {
      setUser(null);
    }
    window.addEventListener("cf:auth-required", onAuthRequired);
    return () => window.removeEventListener("cf:auth-required", onAuthRequired);
  }, []);

  const signIn = useCallback(async (username, password) => {
    const data = await api.login(username, password);
    setUser({ username: data.username, role: data.role });
    setReady(true);
    return data;
  }, []);

  const signOut = useCallback(async () => {
    await api.logout();
    setUser(null);
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, ready, signedIn: Boolean(user), signIn, signOut, refresh }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return ctx;
}
