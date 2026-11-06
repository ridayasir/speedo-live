import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import * as Location from "expo-location";
import { api, loadToken, setToken, WS_URL } from "./api";
import type { BusState, User } from "./types";

export function useFetch<T>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!!path);
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
  return { data, error, loading, reload };
}

/* ---------------------------------------------------------------- auth */
interface AuthCtx {
  user: User | null;
  ready: boolean;
  login: (identifier: string, password: string) => Promise<void>;
  register: (b: { full_name: string; email?: string; phone?: string; password: string }) => Promise<void>;
  logout: () => Promise<void>;
  refresh: () => Promise<void>;
}
const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children, onSignedIn }: { children: React.ReactNode; onSignedIn?: () => void }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);
  const refresh = useCallback(async () => {
    try {
      setUser(await api<User>("/api/auth/me"));
    } catch {
      setUser(null);
    }
  }, []);
  useEffect(() => {
    loadToken()
      .then((t) => (t ? refresh() : undefined))
      .finally(() => setReady(true));
  }, [refresh]);
  useEffect(() => {
    if (user) onSignedIn?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.id]);
  const login = async (identifier: string, password: string) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", json: { identifier, password } });
    await setToken(r.access_token);
    setUser(r.user);
  };
  const register = async (b: { full_name: string; email?: string; phone?: string; password: string }) => {
    const r = await api<{ access_token: string; user: User }>("/api/auth/register", { method: "POST", json: b });
    await setToken(r.access_token);
    setUser(r.user);
  };
  const logout = async () => {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    await setToken(null);
    setUser(null);
  };
  return <Ctx.Provider value={{ user, ready, login, register, logout, refresh }}>{children}</Ctx.Provider>;
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth outside provider");
  return c;
}

/* ---------------------------------------------------------------- live buses */
export function useLiveBuses(routeIds: number[] = []) {
  const [buses, setBuses] = useState<Record<number, BusState>>({});
  const [conn, setConn] = useState<"connecting" | "live" | "reconnecting">("connecting");
  const key = routeIds.join(",");
  const ws = useRef<WebSocket | null>(null);
  useEffect(() => {
    let closed = false;
    let retry = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const connect = () => {
      if (closed) return;
      const s = new WebSocket(`${WS_URL}/ws/live${key ? `?route_id=${key}` : ""}`);
      ws.current = s;
      s.onopen = () => {
        retry = 0;
        setConn("live");
      };
      s.onmessage = (ev) => {
        try {
          const m = JSON.parse(String(ev.data));
          if (m.type === "snapshot") {
            const map: Record<number, BusState> = {};
            for (const b of m.buses as BusState[]) map[b.bus_id] = b;
            setBuses(map);
          } else if (m.bus_id) setBuses((p) => ({ ...p, [m.bus_id]: { ...p[m.bus_id], ...m } }));
        } catch {
          /* ignore */
        }
      };
      s.onclose = () => {
        if (closed) return;
        setConn("reconnecting");
        retry++;
        timer = setTimeout(connect, Math.min(15000, 1000 * 2 ** retry));
      };
      s.onerror = () => s.close();
    };
    connect();
    const ping = setInterval(() => ws.current?.readyState === 1 && ws.current.send("ping"), 25000);
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      clearInterval(ping);
      ws.current?.close();
    };
  }, [key]);
  const [, force] = useState(0);
  useEffect(() => {
    const t = setInterval(() => force((x) => x + 1), 5000);
    return () => clearInterval(t);
  }, []);
  return { buses: Object.values(buses), conn };
}

/* ---------------------------------------------------------------- location */
export function useMyLocation() {
  const [pos, setPos] = useState<{ lat: number; lng: number } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const locate = useCallback(async () => {
    setBusy(true);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== "granted") {
        setError("Location permission was not granted");
        return;
      }
      const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
      setPos({ lat: p.coords.latitude, lng: p.coords.longitude });
      setError(null);
    } catch {
      setError("Could not get your location");
    } finally {
      setBusy(false);
    }
  }, []);
  return { pos, error, busy, locate };
}
