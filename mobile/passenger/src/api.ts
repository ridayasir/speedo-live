// API client for the Speedo Live backend (same REST API as the web app).
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";

export const API_URL: string = process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000"; // 10.0.2.2 = host machine from the Android emulator
const TOKEN_KEY = "speedo.token";

let token: string | null = null;
let user: any = null;
const listeners = new Set<() => void>();

export const auth = {
  async load() {
    token = await SecureStore.getItemAsync(TOKEN_KEY);
    const u = await AsyncStorage.getItem("speedo.user");
    user = u ? JSON.parse(u) : null;
    listeners.forEach(f => f());
  },
  get token() { return token; },
  get user() { return user; },
  async set(t: string, u: any) { token = t; user = u; await SecureStore.setItemAsync(TOKEN_KEY, t); await AsyncStorage.setItem("speedo.user", JSON.stringify(u)); listeners.forEach(f => f()); },
  async clear() { token = null; user = null; await SecureStore.deleteItemAsync(TOKEN_KEY); await AsyncStorage.removeItem("speedo.user"); listeners.forEach(f => f()); },
  subscribe(f: () => void) { listeners.add(f); return () => listeners.delete(f); },
};

export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }

export async function api<T = any>(method: string, path: string, body?: any): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(API_URL + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch {
    throw new ApiError(0, "network", "No internet connection. Showing what we have.");
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    if (res.status === 401 && token) await auth.clear();
    throw new ApiError(res.status, data?.error?.code || "error", data?.error?.message || `Request failed (${res.status})`);
  }
  return data as T;
}

export const get = <T = any>(p: string) => api<T>("GET", p);
export const post = <T = any>(p: string, b: any = {}) => api<T>("POST", p, b);
export const put = <T = any>(p: string, b: any) => api<T>("PUT", p, b);
export const del = <T = any>(p: string) => api<T>("DELETE", p);

/** Live bus positions over WebSocket (/ws/live), with polling fallback. */
export function liveBuses(onBuses: (buses: Map<number, any>) => void, routeId?: number): () => void {
  const buses = new Map<number, any>();
  let ws: WebSocket | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;
  let closed = false;
  let failures = 0;
  const emit = () => onBuses(new Map(buses));
  const startPolling = () => {
    if (poll) return;
    const tick = async () => {
      try {
        const list = await get<any[]>(`/api/buses${routeId ? `?route_id=${routeId}` : ""}`);
        buses.clear(); list.forEach(b => buses.set(b.id, b)); emit();
      } catch { /* keep last known */ }
    };
    tick(); poll = setInterval(tick, 5000);
  };
  const connect = () => {
    if (closed) return;
    ws = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws/live${routeId ? `?route_id=${routeId}` : ""}`);
    ws.onmessage = e => {
      const msg = JSON.parse(String(e.data));
      if (msg.type === "snapshot") { failures = 0; buses.clear(); msg.buses.forEach((b: any) => buses.set(b.id, b)); emit(); }
      else if (msg.type === "bus") { buses.set(msg.bus.id, msg.bus); emit(); }
    };
    ws.onclose = () => {
      if (closed) return;
      failures++;
      if (failures >= 3) startPolling(); else setTimeout(connect, 2000 * failures);
    };
  };
  connect();
  return () => { closed = true; ws?.close(); if (poll) clearInterval(poll); };
}

export function fmtEta(s: number | null | undefined) {
  if (s === null || s === undefined) return "—";
  if (s < 45) return "Arriving";
  const m = Math.round(s / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function fmtAgo(iso?: string | null) {
  if (!iso) return "no GPS yet";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 5 ? "just now" : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}

export function fmtDist(m?: number | null) {
  if (m === null || m === undefined) return "—";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}
