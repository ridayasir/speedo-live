// API client, session storage and the live bus feed (SSE with polling fallback).
export const API_BASE = window.SPEEDO_API_BASE || "";
export class ApiError extends Error {
    status;
    code;
    details;
    constructor(status, code, message, details) {
        super(message);
        this.status = status;
        this.code = code;
        this.details = details;
    }
}
export class Session {
    key;
    constructor(key) {
        this.key = key;
    }
    get token() { try {
        return localStorage.getItem(this.key);
    }
    catch {
        return null;
    } }
    get user() { try {
        return JSON.parse(localStorage.getItem(this.key + ".user") || "null");
    }
    catch {
        return null;
    } }
    set(token, user) { try {
        localStorage.setItem(this.key, token);
        localStorage.setItem(this.key + ".user", JSON.stringify(user));
    }
    catch { /* private mode */ } }
    clear() { try {
        localStorage.removeItem(this.key);
        localStorage.removeItem(this.key + ".user");
    }
    catch { /* ignore */ } }
}
export function makeApi(session, onUnauthorized) {
    async function request(method, path, body, opts = {}) {
        const headers = { Accept: "application/json", ...(opts.headers || {}) };
        if (body !== undefined)
            headers["Content-Type"] = "application/json";
        if (session.token)
            headers.Authorization = `Bearer ${session.token}`;
        let res;
        try {
            res = await fetch(API_BASE + path, { method, headers, body: opts.raw ?? (body !== undefined ? JSON.stringify(body) : undefined) });
        }
        catch {
            throw new ApiError(0, "network", "Can't reach Speedo Live. Check your internet connection.");
        }
        const ctype = res.headers.get("content-type") || "";
        const data = ctype.includes("json") ? await res.json().catch(() => null) : await res.text();
        if (!res.ok) {
            const err = (data && data.error) || {};
            if (res.status === 401 && session.token) {
                session.clear();
                onUnauthorized?.();
            }
            const msg = err.details?.length ? `${err.message}: ${err.details.map((d) => `${d.field.split(".").pop()} ${d.message}`).join("; ")}` : err.message;
            throw new ApiError(res.status, err.code || "error", msg || `Request failed (${res.status})`, err.details);
        }
        return data;
    }
    return {
        get: (p) => request("GET", p),
        post: (p, b = {}) => request("POST", p, b),
        put: (p, b) => request("PUT", p, b),
        patch: (p, b) => request("PATCH", p, b),
        del: (p) => request("DELETE", p),
        upload: (p, form) => request("POST", p, undefined, { raw: form }),
        request,
    };
}
/** Live bus positions. Uses Server-Sent Events; if the stream keeps failing it falls back to polling. */
export class LiveFeed {
    params;
    handlers;
    pollUrl;
    pollMs;
    es = null;
    pollTimer;
    failures = 0;
    stopped = false;
    state = "connecting";
    constructor(params, handlers, pollUrl = "/api/buses", pollMs = 5000) {
        this.params = params;
        this.handlers = handlers;
        this.pollUrl = pollUrl;
        this.pollMs = pollMs;
    }
    setState(s) { this.state = s; this.handlers.state?.(s); }
    async start() {
        this.stopped = false;
        if (!("EventSource" in window))
            return this.startPolling();
        const q = new URLSearchParams();
        if (this.params.route_id)
            q.set("route_id", this.params.route_id);
        if (this.params.bus_id)
            q.set("bus_id", this.params.bus_id);
        if (this.params.ticket) {
            try {
                q.set("ticket", await this.params.ticket());
            }
            catch {
                return this.startPolling();
            }
        }
        this.es = new EventSource(`${API_BASE}/api/live/stream?${q}`);
        this.setState(this.failures ? "reconnecting" : "connecting");
        this.es.addEventListener("snapshot", (e) => {
            this.failures = 0;
            this.setState("live");
            this.handlers.snapshot(JSON.parse(e.data).buses);
        });
        this.es.addEventListener("bus", (e) => this.handlers.bus(JSON.parse(e.data).bus));
        this.es.addEventListener("alert", (e) => this.handlers.alert?.(JSON.parse(e.data).alert));
        this.es.onerror = () => {
            if (this.stopped)
                return;
            this.failures++;
            this.setState(navigator.onLine === false ? "offline" : "reconnecting");
            // CLOSED = the server refused the stream (e.g. 503 on serverless hosts); the browser won't retry by itself
            const refused = this.es?.readyState === EventSource.CLOSED;
            if (refused || this.failures >= 3 || this.params.ticket) { // tickets expire: reopen with a fresh one
                this.es?.close();
                this.es = null;
                if (refused || this.failures >= 3)
                    this.startPolling();
                else
                    setTimeout(() => this.start(), 3000);
            }
        };
    }
    startPolling() {
        this.setState("polling");
        const tick = async () => {
            if (this.stopped)
                return;
            try {
                const qs = this.params.route_id ? `?route_id=${this.params.route_id.split(",")[0]}` : "";
                const res = await fetch(`${API_BASE}${this.pollUrl}${qs}`, { headers: this.pollHeaders() });
                if (res.ok) {
                    this.handlers.snapshot(await res.json());
                    this.setState("polling");
                }
            }
            catch {
                this.setState("offline");
            }
            this.pollTimer = window.setTimeout(tick, this.pollMs);
            if (this.failures >= 3 && this.failures % 6 === 0)
                this.retrySse();
            this.failures++;
        };
        tick();
    }
    pollHeaders = () => ({ Accept: "application/json" });
    retrySse() { clearTimeout(this.pollTimer); this.failures = 1; this.start(); }
    stop() {
        this.stopped = true;
        this.es?.close();
        this.es = null;
        clearTimeout(this.pollTimer);
    }
}
export const recent = {
    key: "speedo.recent",
    list() { try {
        return JSON.parse(localStorage.getItem(this.key) || "[]");
    }
    catch {
        return [];
    } },
    add(item) {
        const label = `${item.from.label}→${item.to.label}`;
        const items = [item, ...this.list().filter((x) => `${x.from.label}→${x.to.label}` !== label)].slice(0, 6);
        try {
            localStorage.setItem(this.key, JSON.stringify(items));
        }
        catch { /* ignore */ }
    },
};
