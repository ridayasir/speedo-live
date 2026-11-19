// Empty NEXT_PUBLIC_API_URL = the API is served from the same origin as the website (single-container deploy).
const configured = process.env.NEXT_PUBLIC_API_URL;
export const API_URL = (
  configured !== undefined && configured !== ""
    ? configured
    : typeof window !== "undefined"
      ? window.location.origin
      : "http://localhost:8000"
).replace(/\/$/, "");
export const WS_URL = API_URL.replace(/^http/, "ws");

const TOKEN_KEY = "speedo.token";
const REFRESH_KEY = "speedo.refresh";

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Store the Firebase ID token (and its refresh token). Passing null signs out. */
export function setToken(token: string | null, refreshToken?: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
    if (refreshToken) window.localStorage.setItem(REFRESH_KEY, refreshToken);
    else if (!token || refreshToken === null) window.localStorage.removeItem(REFRESH_KEY);
  } catch {
    /* storage unavailable */
  }
}

function getRefreshToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(REFRESH_KEY);
  } catch {
    return null;
  }
}

// Firebase ID tokens last one hour; swap the refresh token for a new one (once, shared by parallel calls).
let refreshing: Promise<boolean> | null = null;
function refreshSession(): Promise<boolean> {
  const rt = getRefreshToken();
  if (!rt) return Promise.resolve(false);
  refreshing ??= fetch(`${API_URL}/api/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  })
    .then(async (r) => {
      if (!r.ok) return false;
      const d = await r.json();
      setToken(d.access_token, d.refresh_token);
      return true;
    })
    .catch(() => false)
    .finally(() => (refreshing = null));
  return refreshing;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== "object") return fallback;
  const d = (body as { detail?: unknown }).detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) {
    return d
      .map((e: { msg?: string; loc?: unknown[] }) => {
        const field = Array.isArray(e.loc) ? e.loc.filter((x) => x !== "body").join(".") : "";
        return `${field ? field + ": " : ""}${(e.msg || "").replace(/^Value error, /, "")}`;
      })
      .join("; ");
  }
  if (d && typeof d === "object" && Array.isArray((d as { errors?: string[] }).errors)) {
    return (d as { errors: string[] }).errors.join("\n");
  }
  return fallback;
}

export async function api<T = unknown>(path: string, opts: RequestInit & { json?: unknown } = {}, retried = false): Promise<T> {
  const headers = new Headers(opts.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let body = opts.body;
  if (opts.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(opts.json);
  }
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, { ...opts, headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the Speedo Live server. Check your connection.");
  }
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  const data = text ? (() => { try { return JSON.parse(text); } catch { return text; } })() : undefined;
  if (!res.ok) {
    if (res.status === 401 && token && !retried && !path.startsWith("/api/auth/refresh") && (await refreshSession())) {
      return api<T>(path, opts, true);
    }
    if (res.status === 401 && token) setToken(null);
    throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  }
  return data as T;
}

export async function download(path: string, filename: string) {
  const get = () => {
    const token = getToken();
    return fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  };
  let res = await get();
  if (res.status === 401 && (await refreshSession())) res = await get();
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
