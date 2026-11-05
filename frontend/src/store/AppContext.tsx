import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, setToken, TOKEN_KEY } from "../lib/api";
import type { ModelStatus, Settings, User } from "../lib/types";

export type ToastKind = "success" | "error" | "info";
export interface Toast {
  id: string;
  kind: ToastKind;
  message: string;
  detail?: string;
}

interface AppContextValue {
  user: User | null;
  settings: Settings | null;
  model: ModelStatus | null;
  ready: boolean;
  authed: boolean;
  login: (token: string, user: User, settings: Settings) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
  updateSettings: (patch: Partial<Settings>) => Promise<void>;
  setTheme: (theme: "light" | "dark" | "system") => Promise<void>;
  setModel: (model: ModelStatus) => void;
  toast: (message: string, kind?: ToastKind, detail?: string) => void;
  toasts: Toast[];
  dismissToast: (id: string) => void;
}

const AppContext = createContext<AppContextValue | null>(null);

function applyTheme(theme: "light" | "dark" | "system") {
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const resolved = theme === "system" ? (prefersDark ? "dark" : "light") : theme;
  document.documentElement.dataset.theme = resolved;
  document.documentElement.style.colorScheme = resolved;
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [model, setModel] = useState<ModelStatus | null>(null);
  const [ready, setReady] = useState(false);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Record<string, number>>({});

  const dismissToast = useCallback((id: string) => {
    setToasts((current) => current.filter((item) => item.id !== id));
    window.clearTimeout(timers.current[id]);
    delete timers.current[id];
  }, []);

  const toast = useCallback(
    (message: string, kind: ToastKind = "info", detail?: string) => {
      const id = Math.random().toString(36).slice(2);
      setToasts((current) => [...current.slice(-3), { id, kind, message, detail }]);
      timers.current[id] = window.setTimeout(() => dismissToast(id), kind === "error" ? 6000 : 3800);
    },
    [dismissToast],
  );

  const load = useCallback(async () => {
    const response = await api<{ user: User; settings: Settings; model: ModelStatus }>("/settings");
    setUser(response.user);
    setSettings(response.settings);
    setModel(response.model);
    applyTheme(response.settings.theme);
  }, []);

  useEffect(() => {
    const stored = (localStorage.getItem("paperlens.theme") as "light" | "dark" | "system" | null) || "light";
    applyTheme(stored);
    if (!localStorage.getItem(TOKEN_KEY)) {
      setReady(true);
      return;
    }
    load()
      .catch(() => {
        setToken(null);
      })
      .finally(() => setReady(true));
  }, [load]);

  useEffect(() => {
    const onUnauthorized = () => {
      setUser(null);
      setSettings(null);
      setModel(null);
    };
    window.addEventListener("paperlens:unauthorized", onUnauthorized);
    return () => window.removeEventListener("paperlens:unauthorized", onUnauthorized);
  }, []);

  useEffect(() => {
    if (!settings?.theme) return;
    applyTheme(settings.theme);
    localStorage.setItem("paperlens.theme", settings.theme);
    if (settings.theme !== "system") return;
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const listener = () => applyTheme("system");
    media.addEventListener("change", listener);
    return () => media.removeEventListener("change", listener);
  }, [settings?.theme]);

  const login = useCallback(
    async (token: string, nextUser: User, nextSettings: Settings) => {
      setToken(token);
      setUser(nextUser);
      setSettings(nextSettings);
      applyTheme(nextSettings.theme);
      try {
        const response = await api<{ model: ModelStatus }>("/settings");
        setModel(response.model);
      } catch {
        setModel(null);
      }
    },
    [],
  );

  const logout = useCallback(() => {
    setToken(null);
    setUser(null);
    setSettings(null);
    setModel(null);
  }, []);

  const refresh = useCallback(async () => {
    try {
      await load();
    } catch {
      // keep the current session data on transient errors
    }
  }, [load]);

  const updateSettings = useCallback(
    async (patch: Partial<Settings>) => {
      const response = await api<{ settings: Settings; model: ModelStatus }>("/settings", {
        method: "PATCH",
        body: patch as Record<string, unknown>,
      });
      setSettings(response.settings);
      setModel(response.model);
      applyTheme(response.settings.theme);
      return;
    },
    [],
  );

  const setTheme = useCallback(
    async (theme: "light" | "dark" | "system") => {
      applyTheme(theme);
      localStorage.setItem("paperlens.theme", theme);
      setSettings((current) => (current ? { ...current, theme } : current));
      try {
        await updateSettings({ theme });
      } catch {
        // theme still applies locally when the network is unavailable
      }
    },
    [updateSettings],
  );

  const value = useMemo<AppContextValue>(
    () => ({
      user,
      settings,
      model,
      ready,
      authed: Boolean(user),
      login,
      logout,
      refresh,
      updateSettings,
      setTheme,
      setModel,
      toast,
      toasts,
      dismissToast,
    }),
    [user, settings, model, ready, login, logout, refresh, updateSettings, setTheme, toast, toasts, dismissToast],
  );

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppContextValue {
  const context = useContext(AppContext);
  if (!context) throw new Error("useApp must be used inside AppProvider");
  return context;
}
