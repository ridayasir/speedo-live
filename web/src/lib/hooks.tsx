"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { api, setToken, getToken, WS_URL } from "./api";
import type { BusState, Meta, User } from "./types";

/* ------------------------------------------------------------------ data fetching */
export function useApi<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let alive = true;
    setLoading(true);
    api<T>(path)
      .then((d) => alive && (setData(d), setError(null)))
      .catch((e: Error) => alive && setError(e.message))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, ...deps]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, error, loading, reload, setData };
}

/* ------------------------------------------------------------------ auth */
interface AuthCtx {
  user: User | null;
  ready: boolean;
  login: (identifier: string, password: string) => Promise<User>;
  register: (body: { full_name: string; email?: string; phone?: string; password: string }) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null);
      return;
    }
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setReady(true));
  }, [refresh]);

  const login = async (identifier: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", json: { identifier, password } });
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  };
  const register = async (body: { full_name: string; email?: string; phone?: string; password: string }) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/register", { method: "POST", json: body });
    setToken(r.access_token);
    setUser(r.user);
    return r.user;
  };
  const logout = async () => {
    try {
      await api("/api/auth/logout", { method: "POST" });
    } catch {
      /* ignore */
    }
    setToken(null);
    setUser(null);
  };
  return <AuthContext.Provider value={{ user, ready, login, register, logout, refresh }}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth outside AuthProvider");
  return ctx;
}

/* ------------------------------------------------------------------ meta */
let metaCache: Meta | null = null;
export function useMeta() {
  const [meta, setMeta] = useState<Meta | null>(metaCache);
  useEffect(() => {
    if (metaCache) return;
    api<Meta>("/api/meta").then((m) => ((metaCache = m), setMeta(m))).catch(() => {});
  }, []);
  return meta;
}

/* ------------------------------------------------------------------ live buses */
export type LiveConn = "connecting" | "live" | "reconnecting" | "offline";

export function useLiveBuses(filter?: { routeIds?: number[]; busIds?: number[] }) {
  const [buses, setBuses] = useState<Record<number, BusState>>({});
  const [conn, setConn] = useState<LiveConn>("connecting");
  const [lastEvent, setLastEvent] = useState<number>(0);
  const routeKey = (filter?.routeIds || []).join(",");
  const busKey = (filter?.busIds || []).join(",");
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let poll: ReturnType<typeof setInterval> | null = null;

    const params = new URLSearchParams();
    if (routeKey) params.set("route_id", routeKey);
    if (busKey) params.set("bus_id", busKey);

    const restFallback = async () => {
      try {
        const r = await api<{ buses: BusState[] }>(`/api/buses/live${routeKey && !routeKey.includes(",") ? `?route_id=${routeKey}` : ""}`);
        const map: Record<number, BusState> = {};
        for (const b of r.buses) {
          if (busKey && !busKey.split(",").includes(String(b.bus_id)) && !routeKey) continue;
          map[b.bus_id] = b;
        }
        setBuses(map);
        setLastEvent(Date.now());
      } catch {
        /* still offline */
      }
    };

    const connect = () => {
      if (closed) return;
      const ws = new WebSocket(`${WS_URL}/ws/live?${params.toString()}`);
      wsRef.current = ws;
      ws.onopen = () => {
        retry = 0;
        setConn("live");
        if (poll) clearInterval(poll), (poll = null);
      };
      ws.onmessage = (ev) => {
        try {
          const msg = JSON.parse(ev.data);
          if (msg.type === "snapshot") {
            const map: Record<number, BusState> = {};
            for (const b of msg.buses as BusState[]) map[b.bus_id] = b;
            setBuses(map);
          } else if (msg.bus_id) {
            setBuses((prev) => ({ ...prev, [msg.bus_id]: { ...prev[msg.bus_id], ...msg } }));
          }
          setLastEvent(Date.now());
        } catch {
          /* ignore */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setConn(retry > 2 ? "offline" : "reconnecting");
        if (!poll) {
          restFallback();
          poll = setInterval(restFallback, 10000);
        }
        retry++;
        timer = setTimeout(connect, Math.min(15000, 1000 * 2 ** retry));
      };
      ws.onerror = () => ws.close();
    };
    connect();
    const ping = setInterval(() => wsRef.current?.readyState === 1 && wsRef.current.send("ping"), 25000);
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      if (poll) clearInterval(poll);
      clearInterval(ping);
      wsRef.current?.close();
    };
  }, [routeKey, busKey]);

  // re-render every 5 s so "updated Xs ago" and stale labels stay honest without events
  const [, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 5000);
    return () => clearInterval(t);
  }, []);

  return { buses: Object.values(buses), conn, lastEvent };
}

/* ------------------------------------------------------------------ geolocation */
export function useGeolocation() {
  const [pos, setPos] = useState<{ lat: number; lng: number; accuracy: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const locate = useCallback(() => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      setError("Location is not available in this browser");
      return;
    }
    setBusy(true);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        setPos({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy });
        setError(null);
        setBusy(false);
      },
      (e) => {
        setError(e.code === 1 ? "Location permission was denied" : "Could not get your location");
        setBusy(false);
      },
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 },
    );
  }, []);
  return { pos, error, busy, locate };
}

/* ------------------------------------------------------------------ local recents */
export interface RecentSearch {
  from: { label: string; lat: number; lng: number; stop_id?: number };
  to: { label: string; lat: number; lng: number; stop_id?: number };
  at: number;
}
const RECENT_KEY = "speedo.recent";

export function loadRecent(): RecentSearch[] {
  try {
    return JSON.parse(window.localStorage.getItem(RECENT_KEY) || "[]");
  } catch {
    return [];
  }
}

export function saveRecent(r: RecentSearch) {
  try {
    const list = loadRecent().filter((x) => !(x.from.label === r.from.label && x.to.label === r.to.label));
    window.localStorage.setItem(RECENT_KEY, JSON.stringify([r, ...list].slice(0, 8)));
  } catch {
    /* ignore */
  }
}

/* ------------------------------------------------------------------ formatting */
export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}

export function km(m: number | null | undefined): string {
  if (m == null) return "–";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

export function clock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-PK", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Karachi" });
}
