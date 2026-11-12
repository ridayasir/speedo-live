// Map abstraction: Leaflet + OpenStreetMap tiles when available, otherwise a built-in
// SVG schematic map (so the app still works offline or when tiles are blocked).
import { h, svg } from "./dom.js";

export type LL = [number, number];
export interface MapRoute { id: number; code: string; color: string; shape: LL[] }
export interface MapStop { id: number; name: string; lat: number; lon: number }
export interface MapBus { id: number; bus_number: string; route_color: string | null; status: string; is_demo: boolean;
  position: { lat: number; lon: number; heading: number | null } | null }
export interface MapOpts { center: LL; zoom: number; tiles?: string; attribution?: string }

const L: any = (window as any).L;

const BUS_GLYPH = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#fff" fill-rule="evenodd" d="M6.5 2.5h11A2.5 2.5 0 0 1 20 5v11.2a2 2 0 0 1-1 1.73V20a1 1 0 0 1-1 1h-1.2a1 1 0 0 1-1-1v-1.3H8.2V20a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-2.07a2 2 0 0 1-1-1.73V5a2.5 2.5 0 0 1 2.5-2.5zM6 6.2v5.3h12V6.2zm1.8 7.6a1.4 1.4 0 1 0 0 2.8 1.4 1.4 0 0 0 0-2.8zm8.4 0a1.4 1.4 0 1 0 0 2.8 1.4 1.4 0 0 0 0-2.8zM8.5 3.8v1.1h7V3.8z"/></svg>';

function busHtml(b: MapBus): string {
  const rot = b.position?.heading ?? 0;
  const color = b.route_color || "#D0102B";
  const label = b.bus_number.replace(/[<>&"]/g, "");
  return `<div class="bus-marker st-${b.status}" style="--c:${color}"><span class="bus-pulse"></span>` +
    `<span class="bus-arrow" style="transform:rotate(${rot}deg)"></span>` +
    `<span class="bus-icon">${BUS_GLYPH}</span><span class="bus-label">${label}</span></div>`;
}

// ---- smooth movement: glide each bus from where it is drawn now to the new GPS fix
const GLIDE_MAX_MS = 6000;
const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
interface Glide { from: LL; to: LL; t0: number; dur: number; last: number }
function glideAt(g: Glide, now: number): LL {
  const k = g.dur <= 0 ? 1 : Math.min(1, (now - g.t0) / g.dur);
  return [g.from[0] + (g.to[0] - g.from[0]) * k, g.from[1] + (g.to[1] - g.from[1]) * k];
}
function nextGlide(prev: Glide | undefined, to: LL, now: number): Glide {
  if (!prev || reduceMotion) return { from: to, to, t0: now, dur: 0, last: now };
  const from = glideAt(prev, now);
  const far = Math.abs(from[0] - to[0]) + Math.abs(from[1] - to[1]) > 0.02; // ~2 km jump: don't animate
  const dur = far ? 0 : Math.min(GLIDE_MAX_MS, Math.max(800, now - prev.last));
  return { from, to, t0: now, dur, last: now };
}

interface Backend {
  setRoutes(r: MapRoute[], highlight?: number | null): void;
  setStops(s: MapStop[]): void;
  setBus(b: MapBus): void;
  removeBus(id: number): void;
  fit(points: LL[]): void;
  setUser(p: LL | null): void;
  setOverlay(lines: { color: string; points: LL[]; dashed?: boolean }[], pins: { p: LL; label: string; kind: string }[]): void;
  center(p: LL, zoom?: number): void;
  resize(): void;
  follow(id: number | null): void;
}

export class MapView {
  private b: Backend;
  readonly kind: "leaflet" | "svg";
  onStopClick: (id: number) => void = () => {};
  onBusClick: (id: number) => void = () => {};
  onPick: ((p: LL) => void) | null = null;

  constructor(el: HTMLElement, opts: MapOpts) {
    if (L && opts.tiles) {
      this.kind = "leaflet";
      this.b = new LeafletBackend(el, opts, this);
    } else {
      this.kind = "svg";
      this.b = new SvgBackend(el, opts, this);
    }
  }
  setRoutes(r: MapRoute[], highlight: number | null = null) { this.b.setRoutes(r, highlight); }
  setStops(s: MapStop[]) { this.b.setStops(s); }
  setBuses(list: MapBus[]) {
    const keep = new Set<number>();
    for (const b of list) { if (b.position) { this.b.setBus(b); keep.add(b.id); } }
    for (const id of this.busIds) if (!keep.has(id)) this.b.removeBus(id);
    this.busIds = keep;
  }
  private busIds = new Set<number>();
  updateBus(b: MapBus) {
    if (b.position && !["out_of_service", "not_in_service"].includes(b.status)) { this.b.setBus(b); this.busIds.add(b.id); }
    else { this.b.removeBus(b.id); this.busIds.delete(b.id); }
  }
  fit(points: LL[]) { if (points.length) this.b.fit(points); }
  setUser(p: LL | null) { this.b.setUser(p); }
  setOverlay(lines: { color: string; points: LL[]; dashed?: boolean }[], pins: { p: LL; label: string; kind: string }[] = []) { this.b.setOverlay(lines, pins); }
  center(p: LL, zoom?: number) { this.b.center(p, zoom); }
  resize() { this.b.resize(); }
  /** Keep the map centred on this bus while it moves (null = stop following). */
  follow(id: number | null) { this.b.follow(id); }
  onFollowEnd: () => void = () => {};
}

// ------------------------------------------------------------------ Leaflet
class LeafletBackend implements Backend {
  map: any; routes: any; stops: any; buses = new Map<number, any>(); user: any = null; overlay: any;
  glides = new Map<number, Glide>(); keys = new Map<number, string>(); followId: number | null = null; raf = 0;
  constructor(el: HTMLElement, opts: MapOpts, private view: MapView) {
    this.map = L.map(el, { zoomControl: true, attributionControl: true }).setView(opts.center, opts.zoom);
    L.tileLayer(opts.tiles, { maxZoom: 19, attribution: opts.attribution }).addTo(this.map);
    this.routes = L.layerGroup().addTo(this.map);
    this.stops = L.layerGroup().addTo(this.map);
    this.overlay = L.layerGroup().addTo(this.map);
    this.map.on("click", (e: any) => view.onPick?.([e.latlng.lat, e.latlng.lng]));
    this.map.on("dragstart", () => { if (this.followId !== null) { this.followId = null; view.onFollowEnd(); } });
    const zoomClass = () => el.classList.toggle("map-far", this.map.getZoom() < 13);
    this.map.on("zoomend", zoomClass); zoomClass();
  }
  follow(id: number | null) {
    this.followId = id;
    const g = id !== null ? this.glides.get(id) : undefined;
    if (g) this.map.setView(glideAt(g, performance.now()), Math.max(this.map.getZoom(), 15), { animate: true });
  }
  private tick = () => {
    this.raf = 0;
    const now = performance.now(); let moving = false;
    for (const [id, g] of this.glides) {
      const m = this.buses.get(id); if (!m) continue;
      const p = glideAt(g, now); m.setLatLng(p);
      if (id === this.followId) this.map.setView(p, this.map.getZoom(), { animate: false });
      if (now - g.t0 < g.dur) moving = true;
    }
    if (moving) this.raf = requestAnimationFrame(this.tick);
  };
  setRoutes(r: MapRoute[], hl?: number | null) {
    this.routes.clearLayers();
    for (const x of r) {
      if (x.shape.length < 2) continue;
      const faded = hl && hl !== x.id;
      L.polyline(x.shape, { color: "#fff", weight: faded ? 5 : 9, opacity: faded ? 0.4 : 0.9 }).addTo(this.routes);
      L.polyline(x.shape, { color: x.color, weight: faded ? 3 : 5, opacity: faded ? 0.35 : 0.95 }).bindTooltip(x.code, { sticky: true }).addTo(this.routes);
    }
  }
  setStops(s: MapStop[]) {
    this.stops.clearLayers();
    for (const x of s) {
      L.circleMarker([x.lat, x.lon], { radius: 6, color: "#6E0716", weight: 2, fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip(x.name).on("click", (e: any) => { L.DomEvent.stopPropagation(e); this.view.onStopClick(x.id); }).addTo(this.stops);
    }
  }
  setBus(b: MapBus) {
    const p = b.position!; const now = performance.now();
    const g = nextGlide(this.glides.get(b.id), [p.lat, p.lon], now); this.glides.set(b.id, g);
    const key = `${b.status}|${b.route_color}|${b.bus_number}`;
    const m = this.buses.get(b.id);
    if (m) {
      if (this.keys.get(b.id) !== key) { m.setIcon(this.icon(b)); this.keys.set(b.id, key); }
      const arrow = m.getElement()?.querySelector(".bus-arrow") as HTMLElement | null;
      if (arrow) arrow.style.transform = `rotate(${p.heading ?? 0}deg)`;
    } else {
      const nm = L.marker(g.from, { icon: this.icon(b), zIndexOffset: 1000, keyboard: true, title: `Bus ${b.bus_number}` })
        .on("click", () => this.view.onBusClick(b.id)).addTo(this.map);
      this.buses.set(b.id, nm); this.keys.set(b.id, key);
    }
    if (!this.raf) this.raf = requestAnimationFrame(this.tick);
  }
  private icon(b: MapBus) { return L.divIcon({ className: "bus-divicon", html: busHtml(b), iconSize: [40, 40], iconAnchor: [20, 20] }); }
  removeBus(id: number) { this.buses.get(id)?.remove(); this.buses.delete(id); this.glides.delete(id); this.keys.delete(id); }
  fit(points: LL[]) { this.map.fitBounds(L.latLngBounds(points), { padding: [30, 30], maxZoom: 15 }); }
  setUser(p: LL | null) {
    this.user?.remove(); this.user = null;
    if (p) this.user = L.circleMarker(p, { radius: 8, color: "#fff", weight: 3, fillColor: "#F5B400", fillOpacity: 1 }).bindTooltip("You").addTo(this.map);
  }
  setOverlay(lines: { color: string; points: LL[]; dashed?: boolean }[], pins: { p: LL; label: string; kind: string }[]) {
    this.overlay.clearLayers();
    for (const l of lines) L.polyline(l.points, { color: l.color, weight: l.dashed ? 4 : 7, dashArray: l.dashed ? "6 8" : null, opacity: 0.95 }).addTo(this.overlay);
    for (const p of pins) L.marker(p.p, { icon: L.divIcon({ className: "", html: `<div class="pin pin-${p.kind}"></div>`, iconSize: [26, 26], iconAnchor: [13, 26] }) })
      .bindTooltip(p.label).addTo(this.overlay);
  }
  center(p: LL, zoom?: number) { this.map.setView(p, zoom ?? this.map.getZoom()); }
  resize() { setTimeout(() => this.map.invalidateSize(), 50); }
}

// --------------------------------------------------------- SVG fallback map
class SvgBackend implements Backend {
  root: SVGSVGElement; g: SVGElement;
  routes: MapRoute[] = []; hl: number | null = null; stops: MapStop[] = []; buses = new Map<number, MapBus>();
  glides = new Map<number, Glide>(); followId: number | null = null;
  user: LL | null = null; lines: { color: string; points: LL[]; dashed?: boolean }[] = []; pins: { p: LL; label: string; kind: string }[] = [];
  cLat: number; cLon: number; ppd: number; // pixels per degree (lat)
  w = 600; hgt = 400; raf = 0;

  constructor(private el: HTMLElement, opts: MapOpts, private view: MapView) {
    this.cLat = opts.center[0]; this.cLon = opts.center[1];
    this.ppd = 256 * Math.pow(2, opts.zoom) / 360 * 1.15;
    this.root = svg("svg", { class: "svgmap", role: "img", "aria-label": "Route map" }) as SVGSVGElement;
    this.g = svg("g");
    this.root.append(this.g);
    const note = h("div", { class: "map-note" }, "Simplified map — street map tiles unavailable");
    const zoom = h("div", { class: "map-zoom" },
      h("button", { "aria-label": "Zoom in", onclick: () => this.zoom(1.5) }, "+"),
      h("button", { "aria-label": "Zoom out", onclick: () => this.zoom(1 / 1.5) }, "−"));
    el.append(this.root, note, zoom);
    let drag: { x: number; y: number; lat: number; lon: number; moved: boolean } | null = null;
    this.root.addEventListener("pointerdown", e => { drag = { x: e.clientX, y: e.clientY, lat: this.cLat, lon: this.cLon, moved: false }; });
    window.addEventListener("pointermove", e => {
      if (!drag) return;
      const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
      this.cLon = drag.lon - dx / (this.ppd * this.kx()); this.cLat = drag.lat + dy / this.ppd; this.schedule();
    });
    window.addEventListener("pointerup", e => {
      if (drag && !drag.moved && e.target instanceof Element && this.root.contains(e.target) && !e.target.closest("[data-hit]")) {
        const r = this.root.getBoundingClientRect();
        this.view.onPick?.(this.unproject(e.clientX - r.left, e.clientY - r.top));
      }
      drag = null;
    });
    this.root.addEventListener("wheel", e => { e.preventDefault(); this.zoom(e.deltaY < 0 ? 1.25 : 0.8); }, { passive: false });
    new ResizeObserver(() => this.resize()).observe(el);
    this.resize();
  }
  kx() { return Math.cos(this.cLat * Math.PI / 180); }
  project(lat: number, lon: number): [number, number] {
    return [this.w / 2 + (lon - this.cLon) * this.ppd * this.kx(), this.hgt / 2 - (lat - this.cLat) * this.ppd];
  }
  unproject(x: number, y: number): LL { return [this.cLat - (y - this.hgt / 2) / this.ppd, this.cLon + (x - this.w / 2) / (this.ppd * this.kx())]; }
  zoom(f: number) { this.ppd = Math.max(200, Math.min(400000, this.ppd * f)); this.schedule(); }
  schedule() { if (!this.raf) this.raf = requestAnimationFrame(() => { this.raf = 0; this.render(); }); }
  follow(id: number | null) { this.followId = id; this.schedule(); }
  resize() { const r = this.el.getBoundingClientRect(); this.w = r.width || 600; this.hgt = r.height || 400; this.root.setAttribute("viewBox", `0 0 ${this.w} ${this.hgt}`); this.schedule(); }
  path(points: LL[]) { return points.map((p, i) => { const [x, y] = this.project(p[0], p[1]); return `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`; }).join(""); }

  render() {
    const now = performance.now();
    const moving = [...this.glides.values()].some(x => now - x.t0 < x.dur);
    if (this.followId !== null) { const fg = this.glides.get(this.followId); if (fg) [this.cLat, this.cLon] = glideAt(fg, now); }
    const g = this.g; while (g.firstChild) g.removeChild(g.firstChild);
    g.append(svg("rect", { x: 0, y: 0, width: this.w, height: this.hgt, class: "svgmap-bg" }));
    // light grid (~1 km)
    const step = 0.01;
    const [la0, lo0] = this.unproject(0, this.hgt), [la1, lo1] = this.unproject(this.w, 0);
    if ((la1 - la0) / step < 120) {
      for (let la = Math.ceil(la0 / step) * step; la < la1; la += step) { const y = this.project(la, lo0)[1]; g.append(svg("line", { x1: 0, x2: this.w, y1: y, y2: y, class: "svgmap-grid" })); }
      for (let lo = Math.ceil(lo0 / step) * step; lo < lo1; lo += step) { const x = this.project(la0, lo)[0]; g.append(svg("line", { y1: 0, y2: this.hgt, x1: x, x2: x, class: "svgmap-grid" })); }
    }
    for (const r of this.routes) {
      const faded = this.hl && this.hl !== r.id;
      g.append(svg("path", { d: this.path(r.shape), class: "svgmap-casing", "stroke-width": faded ? 5 : 9, opacity: faded ? 0.5 : 1 }));
      g.append(svg("path", { d: this.path(r.shape), fill: "none", stroke: r.color, "stroke-width": faded ? 3 : 5, "stroke-linecap": "round", "stroke-linejoin": "round", opacity: faded ? 0.35 : 1 }));
    }
    for (const l of this.lines) g.append(svg("path", { d: this.path(l.points), fill: "none", stroke: l.color, "stroke-width": l.dashed ? 3 : 7, "stroke-dasharray": l.dashed ? "6 7" : "none", "stroke-linecap": "round" }));
    const showLabels = this.ppd > 9000;
    for (const s of this.stops) {
      const [x, y] = this.project(s.lat, s.lon);
      const c = svg("circle", { cx: x, cy: y, r: 6, class: "svgmap-stop", "data-hit": "1", tabindex: 0 }, svg("title", {}, s.name));
      c.addEventListener("click", () => this.view.onStopClick(s.id));
      g.append(c);
      if (showLabels) g.append(svg("text", { x: x + 9, y: y + 4, class: "svgmap-label" }, s.name));
    }
    for (const p of this.pins) {
      const [x, y] = this.project(p.p[0], p.p[1]);
      g.append(svg("circle", { cx: x, cy: y, r: 9, class: `svgmap-pin pin-${p.kind}` }, svg("title", {}, p.label)));
    }
    if (this.user) {
      const [x, y] = this.project(this.user[0], this.user[1]);
      g.append(svg("circle", { cx: x, cy: y, r: 8, class: "svgmap-user" }, svg("title", {}, "You")));
    }
    for (const b of this.buses.values()) {
      if (!b.position) continue;
      const gl = this.glides.get(b.id); const pos: LL = gl ? glideAt(gl, now) : [b.position.lat, b.position.lon];
      const [x, y] = this.project(pos[0], pos[1]);
      const color = b.route_color || "#D0102B";
      const grp = svg("g", { transform: `translate(${x.toFixed(1)},${y.toFixed(1)})`, class: `svgmap-bus st-${b.status}`, "data-hit": "1", tabindex: 0 });
      grp.append(svg("title", {}, `Bus ${b.bus_number}`));
      grp.append(svg("path", { d: "M0,-21 L6,-14 L-6,-14 Z", fill: color, transform: `rotate(${b.position.heading ?? 0})` }));
      grp.append(svg("rect", { x: -13, y: -13, width: 26, height: 26, rx: 8, fill: color, class: "svgmap-busdot" }));
      grp.append(svg("path", { d: "M-6,-8 h12 a2,2 0 0 1 2,2 v11 h-16 v-11 a2,2 0 0 1 2,-2 z M-5,-5 v5 h10 v-5 z", fill: "#fff", "fill-rule": "evenodd" }));
      grp.append(svg("circle", { cx: -3.5, cy: 7, r: 1.6, fill: "#fff" }));
      grp.append(svg("circle", { cx: 3.5, cy: 7, r: 1.6, fill: "#fff" }));
      grp.append(svg("text", { x: 17, y: 4, class: "svgmap-buslabel" }, b.bus_number));
      grp.addEventListener("click", () => this.view.onBusClick(b.id));
      g.append(grp);
    }
    if (moving) this.schedule();
  }
  setRoutes(r: MapRoute[], hl?: number | null) { this.routes = r; this.hl = hl ?? null; this.schedule(); }
  setStops(s: MapStop[]) { this.stops = s; this.schedule(); }
  setBus(b: MapBus) {
    if (b.position) this.glides.set(b.id, nextGlide(this.glides.get(b.id), [b.position.lat, b.position.lon], performance.now()));
    this.buses.set(b.id, b); this.schedule();
  }
  removeBus(id: number) { this.buses.delete(id); this.glides.delete(id); this.schedule(); }
  fit(points: LL[]) {
    const lats = points.map(p => p[0]), lons = points.map(p => p[1]);
    const [a0, a1, o0, o1] = [Math.min(...lats), Math.max(...lats), Math.min(...lons), Math.max(...lons)];
    this.cLat = (a0 + a1) / 2; this.cLon = (o0 + o1) / 2;
    const spanY = Math.max(0.004, a1 - a0), spanX = Math.max(0.004, (o1 - o0) * this.kx());
    this.ppd = Math.min((this.hgt - 60) / spanY, (this.w - 60) / spanX);
    this.schedule();
  }
  setUser(p: LL | null) { this.user = p; this.schedule(); }
  setOverlay(lines: any[], pins: any[]) { this.lines = lines; this.pins = pins; this.schedule(); }
  center(p: LL) { this.cLat = p[0]; this.cLon = p[1]; this.schedule(); }
}
