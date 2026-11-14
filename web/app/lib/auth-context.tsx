"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { ApiUser, webApi } from "@/lib/api";

const STORAGE_KEY = "nasa_sac_auth_v1";

interface AuthContextValue {
  user: ApiUser | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (
    email: string,
    name: string,
    password: string,
    role: "farm_admin" | "viewer"
  ) => Promise<void>;
  loginDemo: (kind: "farmer" | "viewer") => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<ApiUser | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let active = true;
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(STORAGE_KEY) : null;
    if (!raw) {
      setIsLoading(false);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as { token?: string; user?: ApiUser };
      if (!parsed.token) {
        setIsLoading(false);
        return;
      }
      setToken(parsed.token);
      if (parsed.user) setUser(parsed.user);
      webApi
        .me(parsed.token)
        .then((res) => {
          if (!active) return;
          setUser(res.user);
          window.localStorage.setItem(
            STORAGE_KEY,
            JSON.stringify({ token: parsed.token, user: res.user })
          );
        })
        .catch(() => {
          if (!active) return;
          window.localStorage.removeItem(STORAGE_KEY);
          setToken(null);
          setUser(null);
        })
        .finally(() => {
          if (active) setIsLoading(false);
        });
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
      setIsLoading(false);
    }
    return () => {
      active = false;
    };
  }, []);

  const persistSession = useCallback((nextUser: ApiUser, nextToken: string) => {
    setUser(nextUser);
    setToken(nextToken);
    window.localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ token: nextToken, user: nextUser })
    );
  }, []);

  const login = useCallback(
    async (email: string, password: string) => {
      const res = await webApi.login(email, password);
      persistSession(res.user, res.token);
    },
    [persistSession]
  );

  const register = useCallback(
    async (email: string, name: string, password: string, role: "farm_admin" | "viewer") => {
      const res = await webApi.register(email, name, password, role);
      persistSession(res.user, res.token);
    },
    [persistSession]
  );

  const loginDemo = useCallback(
    async (kind: "farmer" | "viewer") => {
      if (kind === "farmer") {
        await login("marco@turinfarm.it", "demo-farmer-2026");
      } else {
        await login("elena@agronomy.it", "demo-agro-2026");
      }
    },
    [login]
  );

  const logout = useCallback(() => {
    setUser(null);
    setToken(null);
    window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  return (
    <AuthContext.Provider value={{ user, token, isLoading, login, register, loginDemo, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
