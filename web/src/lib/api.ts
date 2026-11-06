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

export function getToken(): string | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable */
  }
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

export async function api<T = unknown>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
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
    if (res.status === 401 && token) setToken(null);
    throw new ApiError(res.status, errorMessage(data, `Request failed (${res.status})`));
  }
  return data as T;
}

export async function download(path: string, filename: string) {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
