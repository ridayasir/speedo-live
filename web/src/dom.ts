// Tiny DOM helpers. Text is always set via textContent (never innerHTML) to avoid XSS.

type Child = Node | string | number | null | undefined | false | Child[];
type Attrs = Record<string, any>;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Attrs | null = null, ...children: Child[]): HTMLElementTagNameMap[K] {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") el.className = String(v);
      else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2).toLowerCase(), v);
      else if (k === "dataset") Object.assign(el.dataset, v);
      else if (v === true) el.setAttribute(k, "");
      else el.setAttribute(k, String(v));
    }
  }
  append(el, children);
  return el;
}

export function append(el: Element, children: Child[]): void {
  for (const c of children.flat(Infinity as 1) as Child[]) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
}

export function clear<T extends Element>(el: T): T {
  while (el.firstChild) el.removeChild(el.firstChild);
  return el;
}

/** Append children, skipping null/undefined/false (Element.append would print "null"). */
export function put<T extends Element>(el: T, ...children: Child[]): T {
  append(el, children);
  return el;
}

export function $(sel: string, root: ParentNode = document): HTMLElement {
  const el = root.querySelector(sel);
  if (!el) throw new Error(`missing element ${sel}`);
  return el as HTMLElement;
}

const SVG_NS = "http://www.w3.org/2000/svg";
export function svg(tag: string, attrs: Record<string, string | number> = {}, ...children: (SVGElement | string)[]): SVGElement {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) el.setAttribute(k, String(v));
  for (const c of children) el.append(typeof c === "string" ? document.createTextNode(c) : c);
  return el;
}

// Inline icons (simple strokes, 24px grid) -----------------------------------
const ICONS: Record<string, string> = {
  home: "M3 11l9-7 9 7v9a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z",
  bus: "M6 3h12a3 3 0 0 1 3 3v10a2 2 0 0 1-2 2v2h-3v-2H8v2H5v-2a2 2 0 0 1-2-2V6a3 3 0 0 1 3-3zM3 11h18M7 15h.01M17 15h.01",
  route: "M6 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM18 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM6 15V9a4 4 0 0 1 4-4h6M18 9v6a4 4 0 0 1-4 4H8",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18zM12 7v5l3 2",
  star: "M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z",
  user: "M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21a8 8 0 0 1 16 0",
  map: "M9 4L3 6v14l6-2 6 2 6-2V4l-6 2zM9 4v14M15 6v14",
  search: "M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM21 21l-4.3-4.3",
  pin: "M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11zM12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  locate: "M12 19a7 7 0 1 0 0-14 7 7 0 0 0 0 14zM12 2v3M12 19v3M2 12h3M19 12h3M12 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z",
  bell: "M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9M10.3 21a1.9 1.9 0 0 0 3.4 0",
  swap: "M7 4v16M7 20l-3-3M7 20l3-3M17 20V4M17 4l-3 3M17 4l3 3",
  walk: "M13 4a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3zM9 21l2-6 3 2v5M10 9l3-2 2 4 3 1M10 9l-1 5",
  chevron: "M9 6l6 6-6 6",
  back: "M15 6l-6 6 6 6",
  up: "M6 15l6-6 6 6",
  down: "M6 9l6 6 6-6",
  x: "M6 6l12 12M18 6L6 18",
  plus: "M12 5v14M5 12h14",
  trash: "M4 7h16M10 11v6M14 11v6M5 7l1 13h12l1-13M9 7V4h6v3",
  edit: "M4 20h4L19 9l-4-4L4 16zM14 6l4 4",
  logout: "M15 4h4v16h-4M10 17l5-5-5-5M15 12H3",
  alert: "M12 3l10 18H2zM12 10v5M12 18h.01",
  signal: "M5 12.5a10 10 0 0 1 14 0M8.5 16a5 5 0 0 1 7 0M12 19.5h.01M2 9a15 15 0 0 1 20 0",
  play: "M7 4l13 8-13 8z",
  stop: "M6 6h12v12H6z",
  chart: "M4 20V10M10 20V4M16 20v-7M22 20H2",
  settings: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  upload: "M12 16V4M7 9l5-5 5 5M4 20h16",
  download: "M12 4v12M7 11l5 5 5-5M4 20h16",
  list: "M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01",
  calendar: "M4 5h16v16H4zM4 10h16M9 3v4M15 3v4",
  flag: "M5 21V4M5 4h12l-2.5 4.5L17 13H5",
  copy: "M9 9h11v11H9zM5 15H4V4h11v1",
  stopSign: "M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 8v4l2.5 2.5",
};

export function icon(name: keyof typeof ICONS | string, size = 20): SVGElement {
  return svg("svg", { viewBox: "0 0 24 24", width: size, height: size, fill: "none", stroke: "currentColor",
    "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", class: "icon" },
    svg("path", { d: ICONS[name] || ICONS.pin }));
}

// Formatting ------------------------------------------------------------------
export function fmtEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 45) return "Arriving";
  const m = Math.round(seconds / 60);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60} min`;
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return "no GPS yet";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 5) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export function fmtDist(m: number | null | undefined): string {
  if (m === null || m === undefined) return "—";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

export function fmtClock(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-PK", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Karachi" });
}

export const STATUS: Record<string, { label: string; cls: string; hint: string }> = {
  active: { label: "On the move", cls: "ok", hint: "Live GPS is fresh" },
  delayed: { label: "Delayed", cls: "warn", hint: "Running behind the timetable" },
  stale: { label: "GPS weak", cls: "muted", hint: "No recent GPS update; position may be out of date" },
  offline: { label: "Offline", cls: "bad", hint: "The bus has stopped sending GPS" },
  out_of_service: { label: "Out of service", cls: "bad", hint: "Bus is not in service" },
  not_in_service: { label: "Not in service", cls: "muted", hint: "No active trip" },
};

export function statusBadge(status: string): HTMLElement {
  const s = STATUS[status] || { label: status, cls: "muted", hint: "" };
  return h("span", { class: `badge badge-${s.cls}`, title: s.hint }, s.label);
}

export function demoBadge(show = true): HTMLElement | null {
  return null; // demo badge removed from the UI
}

export function routeChip(code: string, color: string | null | undefined): HTMLElement {
  return h("span", { class: "route-chip", style: { background: color || "#D0102B" } }, code);
}

// Feedback ----------------------------------------------------------------------
export function toast(message: string, kind: "ok" | "error" | "info" = "info", ms = 3500): void {
  let host = document.getElementById("toasts");
  if (!host) {
    host = h("div", { id: "toasts", role: "status", "aria-live": "polite" });
    document.body.append(host);
  }
  const t = h("div", { class: `toast toast-${kind}` }, message);
  host.append(t);
  setTimeout(() => t.classList.add("out"), ms);
  setTimeout(() => t.remove(), ms + 400);
}

export function modal(title: string, body: Node, actions: { label: string; kind?: string; onClick: () => any }[] = []): { close: () => void } {
  const backdrop = h("div", { class: "modal-backdrop", role: "dialog", "aria-modal": "true", "aria-label": title });
  const close = () => backdrop.remove();
  const box = h("div", { class: "modal" },
    h("div", { class: "modal-head" }, h("h3", null, title),
      h("button", { class: "icon-btn", "aria-label": "Close", onclick: close }, icon("x"))),
    h("div", { class: "modal-body" }, body),
    actions.length ? h("div", { class: "modal-actions" }, actions.map(a =>
      h("button", { class: `btn ${a.kind || ""}`, onclick: async () => { if ((await a.onClick()) !== false) close(); } }, a.label))) : null);
  backdrop.append(box);
  backdrop.addEventListener("click", e => { if (e.target === backdrop) close(); });
  document.addEventListener("keydown", function esc(e) { if (e.key === "Escape") { close(); document.removeEventListener("keydown", esc); } });
  document.body.append(backdrop);
  (box.querySelector("input, select, textarea, button") as HTMLElement | null)?.focus();
  return { close };
}

export function emptyState(text: string, iconName = "search"): HTMLElement {
  return h("div", { class: "empty" }, icon(iconName, 28), h("p", null, text));
}

export function loading(text = "Loading…"): HTMLElement {
  return h("div", { class: "loading" }, h("span", { class: "spinner" }), text);
}

export function errorBox(err: any, retry?: () => void): HTMLElement {
  return h("div", { class: "error-box" }, icon("alert"), h("span", null, err?.message || "Something went wrong"),
    retry ? h("button", { class: "btn btn-sm", onclick: retry }, "Try again") : null);
}

export function field(label: string, input: HTMLElement, hint?: string): HTMLElement {
  const id = input.id || `f-${Math.random().toString(36).slice(2, 8)}`;
  input.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), input, hint ? h("small", null, hint) : null);
}

export function debounce<T extends (...a: any[]) => void>(fn: T, ms: number): T {
  let t: number | undefined;
  return ((...a: any[]) => { clearTimeout(t); t = window.setTimeout(() => fn(...a), ms); }) as T;
}
