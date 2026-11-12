import * as SecureStore from "expo-secure-store";

export const API_URL: string = process.env.EXPO_PUBLIC_API_URL || "http://10.0.2.2:8000";
let token: string | null = null;

export const auth = {
  async load() { token = await SecureStore.getItemAsync("speedo.token"); return token; },
  get token() { return token; },
  async set(t: string) { token = t; await SecureStore.setItemAsync("speedo.token", t); },
  async clear() { token = null; await SecureStore.deleteItemAsync("speedo.token"); },
};

export class ApiError extends Error { constructor(public status: number, public code: string, message: string) { super(message); } }

export async function api<T = any>(method: string, path: string, body?: any): Promise<T> {
  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  let res: Response;
  try { res = await fetch(API_URL + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined }); }
  catch { throw new ApiError(0, "network", "No internet connection"); }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data?.error?.code || "error", data?.error?.message || `Request failed (${res.status})`);
  return data as T;
}
export const get = <T = any>(p: string) => api<T>("GET", p);
export const post = <T = any>(p: string, b: any = {}) => api<T>("POST", p, b);

export function fmtAgo(iso?: string | null) {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 5 ? "just now" : s < 60 ? `${s}s ago` : s < 3600 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`;
}
