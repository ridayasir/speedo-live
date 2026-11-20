import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";

export const API_URL: string = (
  process.env.EXPO_PUBLIC_API_URL || (Constants.expoConfig?.extra?.apiUrl as string) || "http://10.0.2.2:8000"
).replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");

const TOKEN_KEY = "speedo_token";
const REFRESH_KEY = "speedo_refresh";
let token: string | null = null;
let refreshToken: string | null = null;

export async function loadToken() {
  token = await SecureStore.getItemAsync(TOKEN_KEY);
  refreshToken = await SecureStore.getItemAsync(REFRESH_KEY);
  return token;
}

/** Store the Firebase ID token and its refresh token. Passing null signs out. */
export async function setToken(t: string | null, rt?: string | null) {
  token = t;
  if (t) await SecureStore.setItemAsync(TOKEN_KEY, t);
  else await SecureStore.deleteItemAsync(TOKEN_KEY);
  if (rt) {
    refreshToken = rt;
    await SecureStore.setItemAsync(REFRESH_KEY, rt);
  } else if (!t || rt === null) {
    refreshToken = null;
    await SecureStore.deleteItemAsync(REFRESH_KEY);
  }
}

// Firebase ID tokens last one hour; swap the refresh token for a new one (once, shared by parallel calls).
let refreshing: Promise<boolean> | null = null;
function refreshSession(): Promise<boolean> {
  if (!refreshToken) return Promise.resolve(false);
  refreshing ??= fetch(`${API_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refreshToken }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const d = await r.json();
      await setToken(d.access_token, d.refresh_token);
      return true;
    })
    .catch(() => false)
    .finally(() => (refreshing = null));
  return refreshing;
}

export function hasToken() {
  return !!token;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function message(body: any, fallback: string): string {
  const d = body?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((e: any) => String(e.msg || "").replace(/^Value error, /, "")).join("; ");
  return fallback;
}

export async function api<T = any>(path: string, opts: { method?: string; json?: unknown } = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.json !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      method: opts.method || "GET",
      headers,
      body: opts.json !== undefined ? JSON.stringify(opts.json) : undefined,
    });
  } catch {
    throw new ApiError(0, "No connection to Speedo Live. Check your internet.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  let data: any = undefined;
  try {
    data = text ? JSON.parse(text) : undefined;
  } catch {
    data = text;
  }
  if (!res.ok) {
    if (res.status === 401 && token && !retried && !path.startsWith("/api/auth/") && (await refreshSession())) {
      return api<T>(path, opts, true);
    }
    if (res.status === 401 && token) await setToken(null);
    throw new ApiError(res.status, message(data, `Request failed (${res.status})`));
  }
  return data as T;
}
