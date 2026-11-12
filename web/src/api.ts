// API client, session storage and the live bus feed (SSE with polling fallback).

export const API_BASE: string = (window as any).SPEEDO_API_BASE || "";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: any) { super(message); }
}

export class Session {
  constructor(private key: string) {}
  get token(): string | null { try { return localStorage.getItem(this.key); } catch { return null; } }
  get user(): any | null { try { return JSON.parse(localStorage.getItem(this.key + ".user") || "null"); } catch { return null; } }
  set(token: string, user: any) { try { localStorage.setItem(this.key, token); localStorage.setItem(this.key + ".user", JSON.stringify(user)); } catch { /* private mode */ } }
  clear() { try { localStorage.removeItem(this.key); localStorage.removeItem(this.key + ".user"); } catch { /* ignore */ } }
}

export function makeApi(session: Session, onUnauthorized?: () => void) {
  async function request<T = any>(method: string, path: string, body?: any, opts: { raw?: BodyInit; headers?: Record<string, string> } = {}): Promise<T> {
    const headers: Record<string, string> = { Accept: "application/json", ...(opts.headers || {}) };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    if (session.token) headers.Authorization = `Bearer ${session.token}`;
    let res: Response;
    try {
      res = await fetch(API_BASE + path, { method, headers, body: opts.raw ?? (body !== undefined ? JSON.stringify(body) : undefined) });
    } catch {
      throw new ApiError(0, "network", "Can't reach Speedo Live. Check your internet connection.");
    }
    const ctype = res.headers.get("content-type") || "";
    const data = ctype.includes("json") ? await res.json().catch(() => null) : await res.text();
    if (!res.ok) {
      const err = (data && (data as any).error) || {};
      if (res.status === 401 && session.token) { session.clear(); onUnauthorized?.(); }
      const msg = err.details?.length ? `${err.message}: ${err.details.map((d: any) => `${d.field.split(".").pop()} ${d.message}`).join("; ")}` : err.message;
      throw new ApiError(res.status, err.code || "error", msg || `Request failed (${res.status})`, err.details);
    }
    return data as T;
  }
  return {
    get: <T = any>(p: string) => request<T>("GET", p),
    post: <T = any>(p: string, b: any = {}) => request<T>("POST", p, b),
    put: <T = any>(p: string, b: any) => request<T>("PUT", p, b),
    patch: <T = any>(p: string, b: any) => request<T>("PATCH", p, b),
    del: <T = any>(p: string) => request<T>("DELETE", p),
    upload: <T = any>(p: string, form: FormData) => request<T>("POST", p, undefined, { raw: form }),
    request,
  };
}

export type Api = ReturnType<typeof makeApi>;

export type FeedState = "connecting" | "live" | "reconnecting" | "polling" | "offline";

/** Live bus positions. Uses Server-Sent Events; if the stream keeps failing it falls back to polling. */
export class LiveFeed {
  private es: EventSource | null = null;
  private pollTimer: number | undefined;
  private failures = 0;
  private stopped = false;
  state: FeedState = "connecting";

  constructor(private params: { route_id?: string; bus_id?: string; ticket?: () => Promise<string> },
              private handlers: { snapshot: (buses: any[]) => void; bus: (bus: any) => void; alert?: (a: any) => void; state?: (s: FeedState) => void },
              private pollUrl = "/api/buses", private pollMs = 5000) {}

  private setState(s: FeedState) { this.state = s; this.handlers.state?.(s); }

  async start() {
    this.stopped = false;
    if (!("EventSource" in window)) return this.startPolling();
    const q = new URLSearchParams();
    if (this.params.route_id) q.set("route_id", this.params.route_id);
    if (this.params.bus_id) q.set("bus_id", this.params.bus_id);
    if (this.params.ticket) {
      try { q.set("ticket", await this.params.ticket()); } catch { return this.startPolling(); }
    }
    this.es = new EventSource(`${API_BASE}/api/live/stream?${q}`);
    this.setState(this.failures ? "reconnecting" : "connecting");
    this.es.addEventListener("snapshot", (e: MessageEvent) => {
      this.failures = 0; this.setState("live");
      this.handlers.snapshot(JSON.parse(e.data).buses);
    });
    this.es.addEventListener("bus", (e: MessageEvent) => this.handlers.bus(JSON.parse(e.data).bus));
    this.es.addEventListener("alert", (e: MessageEvent) => this.handlers.alert?.(JSON.parse(e.data).alert));
    this.es.onerror = () => {
      if (this.stopped) return;
      this.failures++;
      this.setState(navigator.onLine === false ? "offline" : "reconnecting");
      if (this.failures >= 3 || this.params.ticket) {  // tickets expire: reopen with a fresh one
        this.es?.close(); this.es = null;
        if (this.failures >= 3) this.startPolling(); else setTimeout(() => this.start(), 3000);
      }
    };
  }

  private startPolling() {
    this.setState("polling");
    const tick = async () => {
      if (this.stopped) return;
      try {
        const qs = this.params.route_id ? `?route_id=${this.params.route_id.split(",")[0]}` : "";
        const res = await fetch(`${API_BASE}${this.pollUrl}${qs}`, { headers: this.pollHeaders() });
        if (res.ok) { this.handlers.snapshot(await res.json()); this.setState("polling"); }
      } catch { this.setState("offline"); }
      this.pollTimer = window.setTimeout(tick, this.pollMs);
      if (this.failures >= 3 && this.failures % 6 === 0) this.retrySse();
      this.failures++;
    };
    tick();
  }

  pollHeaders: () => Record<string, string> = () => ({ Accept: "application/json" });

  private retrySse() { clearTimeout(this.pollTimer); this.failures = 1; this.start(); }

  stop() {
    this.stopped = true;
    this.es?.close(); this.es = null;
    clearTimeout(this.pollTimer);
  }
}

export const recent = {
  key: "speedo.recent",
  list(): any[] { try { return JSON.parse(localStorage.getItem(this.key) || "[]"); } catch { return []; } },
  add(item: { from: any; to: any }) {
    const label = `${item.from.label}→${item.to.label}`;
    const items = [item, ...this.list().filter((x: any) => `${x.from.label}→${x.to.label}` !== label)].slice(0, 6);
    try { localStorage.setItem(this.key, JSON.stringify(items)); } catch { /* ignore */ }
  },
};
