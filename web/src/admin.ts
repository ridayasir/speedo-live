// Speedo Live — administrator dashboard.
import { API_BASE, LiveFeed, Session, makeApi } from "./api.js";
import { $, clear, debounce, demoBadge, emptyState, errorBox, field, fmtAgo, h, icon, loading, modal, put, routeChip, statusBadge, toast } from "./dom.js";
import { MapView } from "./map.js";

const session = new Session("speedo.admin");
const api = makeApi(session, () => renderLogin());
let cfg: any = null;
let feed: LiveFeed | null = null;
const main = () => $("#panel");

const NAV = [
  ["overview", "Overview", "home"], ["buses", "Buses", "bus"], ["routes", "Routes", "route"], ["stops", "Stops", "pin"],
  ["drivers", "Drivers", "user"], ["fleet", "Live Fleet", "map"], ["schedules", "Schedules", "clock"], ["alerts", "Alerts", "alert"], ["complaints", "Complaints", "flag"],
  ["reports", "Reports", "chart"], ["settings", "Settings", "settings"],
];

async function boot() {
  cfg = await api.get("/api/config").catch(() => ({ demo: false, map: { center: [31.52, 74.35], zoom: 12 } }));
  $("#demo-banner").hidden = true;
  if (!session.token) return renderLogin();
  window.addEventListener("hashchange", route);
  route();
}

function renderLogin() {
  feed?.stop();
  $("#nav").hidden = true;
  const id = h("input", { autocomplete: "username", required: true }) as HTMLInputElement;
  const pw = h("input", { type: "password", autocomplete: "current-password", required: true }) as HTMLInputElement;
  const err = h("p", { class: "error-text", role: "alert" });
  put(clear(main()), h("div", { class: "login-wrap" }, h("div", { class: "card login-card" },
    h("img", { class: "login-cover", src: "img/bus-1.webp", alt: "Speedo bus in Lahore" }),
    h("h2", null, "Administrator sign in"), h("p", { class: "muted" }, "Only authorised Speedo Live administrators can access this dashboard."),
    h("form", { class: "form", onsubmit: async (e: Event) => {
      e.preventDefault(); err.textContent = "";
      try {
        const r = await api.post("/api/auth/login", { identifier: id.value, password: pw.value });
        if (r.user.role !== "admin") { err.textContent = "This account is not an administrator."; return; }
        session.set(r.token, r.user); $("#nav").hidden = false;
        window.addEventListener("hashchange", route); route();
      } catch (e2: any) { err.textContent = e2.message; }
    } }, field("Email or phone", id), field("Password", pw), err, h("button", { class: "btn btn-primary btn-block", type: "submit" }, "Sign in")),
    cfg?.demo ? h("p", { class: "hint" }, "Test account: admin@speedo.demo / Demo@12345") : null)));
}

function renderNav(active: string) {
  const nav = clear($("#nav"));
  nav.hidden = false;
  for (const [id, label, ic] of NAV) {
    put(nav, h("a", { href: `#/${id}`, class: `nav-item ${active === id ? "active" : ""}`, "aria-current": active === id ? "page" : null }, icon(ic), h("span", { class: "lg" }, label), h("span", { class: "sm" }, label)));
  }
  put(nav, h("div", { class: "spacer" }), h("button", { class: "nav-item", style: { border: 0, background: "none", cursor: "pointer" }, onclick: async () => {
    try { await api.post("/api/auth/logout"); } catch { /* ignore */ }
    session.clear(); renderLogin();
  } }, icon("logout"), h("span", { class: "lg" }, "Sign out"), h("span", { class: "sm" }, "Sign out")));
}

async function route() {
  if (!session.token) return renderLogin();
  feed?.stop(); feed = null;
  const [view, id] = (location.hash.slice(2).split("?")[0] || "overview").split("/");
  renderNav(view);
  const p = clear(main());
  p.append(loading());
  try {
    const views: Record<string, (p: HTMLElement, id?: string) => Promise<void>> = {
      overview, buses, routes, stops, drivers, fleet, schedules, alerts, complaints, reports, settings,
    };
    await (views[view] || overview)(p, id);
  } catch (e: any) {
    put(clear(p), errorBox(e, route));
  }
}

// ---------------------------------------------------------- helpers
function title(p: HTMLElement, text: string, ...actions: any[]) {
  put(clear(p), h("div", { class: "panel-head" }, h("h2", null, text), h("div", { class: "spacer" }), ...actions));
}

interface Col { label: string; get: (r: any) => any }
function table(rows: any[], cols: Col[], actions?: (r: any) => any[]) {
  if (!rows.length) return emptyState("Nothing here yet.", "list");
  return h("div", { class: "table-wrap" }, h("table", { class: "table" },
    h("thead", null, h("tr", null, cols.map(c => h("th", null, c.label)), actions ? h("th", null, "") : null)),
    h("tbody", null, rows.map(r => h("tr", null, cols.map(c => h("td", null, c.get(r) ?? "—")), actions ? h("td", { class: "actions" }, actions(r)) : null)))));
}

function searchBox(onInput: (q: string) => void) {
  return h("input", { type: "search", placeholder: "Search…", "aria-label": "Search", oninput: debounce((e: any) => onInput(e.target.value.toLowerCase()), 150) });
}

type FieldDef = { name: string; label: string; type?: string; options?: [any, string][]; required?: boolean; hint?: string; full?: boolean; step?: string };
function formModal(titleText: string, defs: FieldDef[], initial: any, submit: (v: any) => Promise<any>) {
  const inputs: Record<string, HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement> = {};
  const err = h("p", { class: "error-text", role: "alert" });
  const grid = h("div", { class: "form-grid" }, defs.map(d => {
    let el: any;
    if (d.type === "select") {
      el = h("select", null, (d.options || []).map(([v, l]) => h("option", { value: v ?? "", selected: String(initial[d.name] ?? "") === String(v ?? "") }, l)));
    } else if (d.type === "textarea") {
      el = h("textarea", { rows: 4 }); el.value = initial[d.name] ?? "";
    } else if (d.type === "checkbox") {
      el = h("input", { type: "checkbox", checked: !!initial[d.name] });
      return h("label", { class: `check ${d.full ? "full" : ""}` }, (inputs[d.name] = el), d.label);
    } else {
      el = h("input", { type: d.type || "text", value: initial[d.name] ?? "", required: d.required, step: d.step });
    }
    inputs[d.name] = el;
    return h("div", { class: d.full ? "full" : "" }, field(d.label, el, d.hint));
  }));
  modal(titleText, h("div", null, grid, err), [
    { label: "Cancel", onClick: () => true },
    { label: "Save", kind: "btn-primary", onClick: async () => {
      const v: any = {};
      for (const d of defs) {
        const el = inputs[d.name] as any;
        if (d.type === "checkbox") v[d.name] = el.checked;
        else if (d.type === "number") v[d.name] = el.value === "" ? null : Number(el.value);
        else if (d.type === "select") v[d.name] = el.value === "" ? null : (/^\d+$/.test(el.value) ? Number(el.value) : el.value);
        else v[d.name] = el.value === "" ? null : el.value;
      }
      try { await submit(v); toast("Saved", "ok"); route(); return true; }
      catch (e: any) { err.textContent = e.message; return false; }
    } }]);
}

function confirmDo(text: string, action: () => Promise<any>, label = "Delete") {
  modal("Please confirm", h("p", null, text), [{ label: "Cancel", onClick: () => true },
    { label, kind: "btn-danger", onClick: async () => { try { await action(); toast("Done", "ok"); route(); } catch (e: any) { toast(e.message, "error"); return false; } } }]);
}

const iconBtn = (name: string, label: string, onclick: () => void) => h("button", { class: "icon-btn", title: label, "aria-label": label, onclick }, icon(name, 16));

// ---------------------------------------------------------- views
async function overview(p: HTMLElement) {
  const [o, al] = await Promise.all([api.get("/api/admin/overview"), api.get("/api/alerts")]);
  title(p, "Overview", demoBadge(cfg.demo));
  const m = (label: string, v: any, cls = "") => h("div", { class: `metric ${cls}` }, h("span", null, label), h("strong", null, String(v)));
  p.append(
    h("div", { class: "admin-grid" }, m("Registered buses", o.buses_total), m("Active buses", o.buses_active, "ok"), m("Inactive / maintenance", o.buses_inactive),
      m("Routes", o.routes), m("Stops", o.stops), m("Drivers", o.drivers_total), m("Drivers on trip", o.drivers_on_trip, "ok"), m("Ongoing trips", o.ongoing_trips)),
    h("h3", null, "Live status"),
    h("div", { class: "admin-grid" }, m("Moving", o.live.active, "ok"), m("Delayed", o.live.delayed, "warn"), m("GPS stale", o.live.stale, "warn"),
      m("Offline", o.live.offline, "bad"), m("Out of service", o.live.out_of_service), m("Passengers watching live", o.realtime_subscribers)),
    h("div", { class: "section-head" }, h("h3", null, "Passenger complaints"), h("a", { class: "btn btn-sm", href: "#/complaints" }, "Review complaints")),
    h("div", { class: "admin-grid" }, m("Open complaints", o.complaints_open, o.complaints_open ? "bad" : "ok")),
    h("div", { class: "section-head" }, h("h3", null, `Current service alerts (${al.length})`), h("a", { class: "btn btn-sm", href: "#/alerts" }, "Manage alerts")),
    al.length ? h("div", { class: "alerts" }, al.map((a: any) => h("div", { class: `alert alert-${a.severity}` }, icon("alert", 18),
      h("div", null, h("strong", null, a.title), h("p", null, `${a.route_code ? `Route ${a.route_code} · ` : "All routes · "}${a.severity} · since ${fmtAgo(a.starts_at)}`))))) :
      h("p", { class: "muted" }, "No active alerts."));
}

async function buses(p: HTMLElement) {
  const [rows, rts, drv] = await Promise.all([api.get("/api/admin/buses"), api.get("/api/admin/routes"), api.get("/api/admin/drivers")]);
  const routeOpts: [any, string][] = [[null, "— No route —"], ...rts.map((r: any) => [r.id, `${r.code} — ${r.name}`] as [any, string])];
  const driverOpts: [any, string][] = [[null, "— No driver —"], ...drv.map((d: any) => [d.id, `${d.name} (${d.employee_code})${d.bus_number ? ` — on ${d.bus_number}` : ""}`] as [any, string])];
  const defs = (): FieldDef[] => [
    { name: "bus_number", label: "Bus number", required: true }, { name: "registration_no", label: "Registration no." },
    { name: "capacity", label: "Capacity", type: "number" }, { name: "status", label: "Status", type: "select", options: [["active", "Active"], ["inactive", "Inactive"], ["maintenance", "Maintenance"]] },
    { name: "route_id", label: "Assigned route", type: "select", options: routeOpts }, { name: "driver_id", label: "Assigned driver", type: "select", options: driverOpts },
    { name: "gps_device_id", label: "GPS device ID", hint: "For on-board trackers (real-world mode). Leave empty when the driver app shares location.", full: true },
  ];
  const list = h("div");
  const draw = (q = "") => put(clear(list), table(rows.filter((r: any) => !q || JSON.stringify(r).toLowerCase().includes(q)), [
    { label: "Bus", get: r => h("span", null, h("strong", null, r.bus_number), " ", demoBadge(r.is_demo)) },
    { label: "Route", get: r => r.route_code ? routeChip(r.route_code, rts.find((x: any) => x.id === r.route_id)?.color) : "—" },
    { label: "Driver", get: r => r.driver_name },
    { label: "Status", get: r => h("span", { class: `badge badge-${r.status === "active" ? "ok" : r.status === "maintenance" ? "warn" : "muted"}` }, r.status) },
    { label: "GPS device", get: r => r.gps_device_id },
    { label: "Last GPS", get: r => fmtAgo(r.last_gps_at) },
  ], r => [
    iconBtn("edit", "Edit", () => formModal(`Edit bus ${r.bus_number}`, defs(), r, v => api.patch(`/api/admin/buses/${r.id}`,
      { ...v, clear_route: v.route_id === null, clear_driver: v.driver_id === null, route_id: v.route_id ?? undefined, driver_id: v.driver_id ?? undefined }))),
    iconBtn("trash", "Delete", () => confirmDo(`Delete bus ${r.bus_number}? Consider setting it to inactive instead to keep its history.`, () => api.del(`/api/admin/buses/${r.id}`))),
  ]));
  title(p, "Buses", h("button", { class: "btn btn-primary", onclick: () => formModal("Add bus", defs(), { status: "active" }, v => api.post("/api/admin/buses", v)) }, icon("plus", 16), "Add bus"));
  p.append(h("div", { class: "toolbar" }, searchBox(draw)), list);
  draw();
}

async function routes(p: HTMLElement, id?: string) {
  if (id) return routeEditor(p, id === "new" ? null : Number(id));
  const rts = await api.get("/api/admin/routes");
  title(p, "Routes",
    h("button", { class: "btn", onclick: importDialog }, icon("upload", 16), "Import CSV / Excel"),
    h("a", { class: "btn btn-primary", href: "#/routes/new" }, icon("plus", 16), "Create route"));
  p.append(table(rts, [
    { label: "Code", get: r => routeChip(r.code, r.color) },
    { label: "Name", get: r => h("span", null, r.name, " ", demoBadge(r.is_demo)) },
    { label: "Stops", get: r => r.stop_count }, { label: "Length", get: r => `${r.length_km} km` },
    { label: "Status", get: r => h("span", { class: `badge badge-${r.status === "active" ? "ok" : r.status === "suspended" ? "warn" : "muted"}` }, r.status) },
    { label: "Verified", get: r => r.verified ? h("span", { class: "badge badge-ok", title: r.source }, "Verified") : h("span", { class: "badge badge-muted" }, "No") },
    { label: "Source", get: r => r.source },
  ], r => [h("a", { class: "icon-btn", href: `#/routes/${r.id}`, title: "Edit", "aria-label": "Edit" }, icon("edit", 16)),
    iconBtn("trash", "Delete", () => confirmDo(`Delete route ${r.code}? Buses on it become unassigned. Setting it to inactive keeps history.`, () => api.del(`/api/admin/routes/${r.id}`)))]));
}

async function routeEditor(p: HTMLElement, id: number | null) {
  const [allStops, existing] = await Promise.all([api.get("/api/admin/stops"), id ? api.get("/api/admin/routes").then((rs: any[]) => rs.find(r => r.id === id)) : null]);
  const r = existing || { code: "", name: "", color: "#D0102B", status: "active", avg_speed_kmh: 18, verified: false, source: "", description: "", stops: [], shape: [] };
  let order: number[] = r.stops.map((s: any) => s.id);
  const v = (name: string, attrs: any = {}) => h("input", { value: r[name] ?? "", ...attrs }) as HTMLInputElement;
  const code = v("code", { required: true, disabled: !!id }), name = v("name"), color = v("color", { type: "color" }), speed = v("avg_speed_kmh", { type: "number", step: "0.5" });
  const source = v("source", { placeholder: "e.g. PMA route notice, Oct 2026" });
  const status = h("select", null, ["active", "suspended", "inactive"].map(s => h("option", { value: s, selected: r.status === s }, s))) as HTMLSelectElement;
  const verified = h("input", { type: "checkbox", checked: r.verified }) as HTMLInputElement;
  const desc = h("textarea", { rows: 2 }) as HTMLTextAreaElement; desc.value = r.description || "";
  const shape = h("textarea", { rows: 3, placeholder: "[[31.47, 74.24], [31.48, 74.25], ...]  — leave empty to draw straight lines between stops" }) as HTMLTextAreaElement;
  shape.value = existing && r.shape.length && !samePts(r.shape, r.stops) ? JSON.stringify(r.shape) : "";
  const orderEl = h("div", { class: "stop-order" });
  const mapEl = h("div", { class: "fleet-map", style: { height: "360px" } });
  const addSel = h("select", null, h("option", { value: "" }, "Add a stop…")) as HTMLSelectElement;
  let mv: MapView | null = null;
  const drawOrder = () => {
    clear(orderEl);
    order.forEach((sid, i) => {
      const s = allStops.find((x: any) => x.id === sid);
      put(orderEl, h("div", { class: "item" }, h("span", { class: "n" }, String(i + 1)), h("span", { class: "name" }, s?.name || sid, i === 0 ? " (start)" : i === order.length - 1 ? " (end)" : ""),
        iconBtn("up", "Move up", () => { if (i) { [order[i - 1], order[i]] = [order[i], order[i - 1]]; drawOrder(); } }),
        iconBtn("down", "Move down", () => { if (i < order.length - 1) { [order[i + 1], order[i]] = [order[i], order[i + 1]]; drawOrder(); } }),
        iconBtn("x", "Remove", () => { order.splice(i, 1); drawOrder(); })));
    });
    clear(addSel).append(h("option", { value: "" }, "Add a stop…"), ...allStops.filter((s: any) => !order.includes(s.id)).map((s: any) => h("option", { value: s.id }, `${s.name} (${s.code})`)));
    const pts = order.map(sid => allStops.find((x: any) => x.id === sid)).filter(Boolean);
    if (mv) {
      mv.setStops(pts);
      let sh: any[] = [];
      try { sh = shape.value.trim() ? JSON.parse(shape.value) : []; } catch { /* invalid JSON shown on save */ }
      const line = sh.length >= 2 ? sh : pts.map((s: any) => [s.lat, s.lon]);
      mv.setRoutes(line.length >= 2 ? [{ id: 1, code: code.value, color: color.value, shape: line }] : []);
      if (line.length) mv.fit(line);
    }
  };
  addSel.addEventListener("change", () => { if (addSel.value) { order.push(Number(addSel.value)); drawOrder(); } });
  shape.addEventListener("change", drawOrder);
  const err = h("p", { class: "error-text", role: "alert" });
  title(p, id ? `Edit route ${r.code}` : "Create route", h("a", { class: "btn", href: "#/routes" }, "Back to routes"));
  p.append(h("div", { class: "split" },
    h("div", null,
      h("div", { class: "card" }, h("div", { class: "form-grid" }, field("Route code", code), field("Route name", name), field("Line colour", color), field("Average speed (km/h)", speed, "Used for timetable stop times and fallback ETAs"),
        field("Status", status), h("div", null, field("Data source", source, "Required to mark the route verified")),
        h("label", { class: "check full" }, verified, "Verified against an official source"), h("div", { class: "full" }, field("Description", desc)))),
      h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Stops in order"), orderEl, addSel,
        h("div", { style: { marginTop: "12px" } }, field("Road geometry (optional JSON)", shape, "Paste [lat, lon] points that follow the road. Stops are snapped onto this line."))),
      err,
      h("button", { class: "btn btn-primary", onclick: async () => {
        err.textContent = "";
        let sh: any = null;
        if (shape.value.trim()) { try { sh = JSON.parse(shape.value); } catch { err.textContent = "Road geometry must be valid JSON."; return; } }
        const body: any = { name: name.value, color: color.value, status: status.value, avg_speed_kmh: Number(speed.value), verified: verified.checked,
          source: source.value || null, description: desc.value || null, stop_ids: order, shape: sh ?? [] };
        try {
          if (id) await api.patch(`/api/admin/routes/${id}`, body); else await api.post("/api/admin/routes", { code: code.value, ...body });
          toast("Route saved", "ok"); location.hash = "#/routes";
        } catch (e: any) { err.textContent = e.message; }
      } }, "Save route")),
    h("div", null, mapEl, h("p", { class: "hint" }, "Preview of the route line and stops."))));
  mv = new MapView(mapEl, { center: cfg.map.center, zoom: cfg.map.zoom, tiles: cfg.map.tiles, attribution: cfg.map.attribution });
  drawOrder();
}

function samePts(shape: any[], stops: any[]) {
  return shape.length === stops.length && shape.every((p: any, i: number) => Math.abs(p[0] - stops[i].lat) < 1e-6 && Math.abs(p[1] - stops[i].lon) < 1e-6);
}

function importDialog() {
  const file = h("input", { type: "file", accept: ".csv,.xlsx" }) as HTMLInputElement;
  const source = h("input", { placeholder: "e.g. PMA Speedo feeder routes notice, Nov 2026", required: true }) as HTMLInputElement;
  const verified = h("input", { type: "checkbox" }) as HTMLInputElement;
  const out = h("div");
  const run = async (dry: boolean) => {
    if (!file.files?.[0]) { toast("Choose a file", "error"); return false; }
    const fd = new FormData(); fd.append("file", file.files[0]);
    try {
      const r = await api.upload(`/api/admin/import?dry_run=${dry}&verified=${verified.checked}&source=${encodeURIComponent(source.value)}`, fd);
      put(clear(out), h("p", null, h("strong", null, dry ? "Check result: " : "Import result: "), `${r.rows} rows, ${r.routes.length} routes, ${r.errors.length} errors`),
        r.errors.length ? h("ul", { class: "error-text" }, r.errors.slice(0, 15).map((e: any) => h("li", null, `${e.row ? `Row ${e.row}: ` : ""}${e.message}`))) : null,
        h("ul", null, r.routes.map((x: any) => h("li", null, `${x.action === "create" ? "New" : "Update"} ${x.code} — ${x.name} (${x.stops} stops)${x.schedule ? `, every ${x.schedule.headway_min} min ${x.schedule.first_departure}–${x.schedule.last_departure}` : ""}`))),
        r.applied ? h("p", { class: "badge badge-ok" }, "Imported") : null);
      if (r.applied) { toast("Routes imported", "ok"); }
    } catch (e: any) { put(clear(out), h("p", { class: "error-text" }, e.message)); }
    return false;
  };
  modal("Import routes from CSV or Excel", h("div", { class: "form" },
    h("p", { class: "hint" }, "One row per stop: route_code, route_name, stop_seq, stop_code, stop_name, lat, lon (+ optional colour, Urdu name and schedule columns). Only import data from official, verified sources."),
    h("button", { class: "btn btn-sm", onclick: () => download("/api/admin/import/template.csv", "speedo-route-import-template.csv") }, icon("download", 16), "Download template"),
    field("File", file), field("Source of this data", source), h("label", { class: "check" }, verified, "This data is verified against the official source"), out),
    [{ label: "Close", onClick: () => { route(); return true; } }, { label: "Check file", onClick: () => run(true) }, { label: "Import", kind: "btn-primary", onClick: () => run(false) }]);
}

async function download(path: string, filename: string) {
  const res = await fetch(API_BASE + path, { headers: { Authorization: `Bearer ${session.token}` } });
  if (!res.ok) return toast("Download failed", "error");
  const url = URL.createObjectURL(await res.blob());
  const a = h("a", { href: url, download: filename }); document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function stops(p: HTMLElement) {
  const rows = await api.get("/api/admin/stops");
  const defs: FieldDef[] = [{ name: "code", label: "Stop code", required: true }, { name: "name", label: "Name", required: true },
    { name: "name_ur", label: "Urdu name" }, { name: "status", label: "Status", type: "select", options: [["active", "Active"], ["closed", "Closed"]] },
    { name: "lat", label: "Latitude", type: "number", step: "0.000001", required: true }, { name: "lon", label: "Longitude", type: "number", step: "0.000001", required: true }];
  const list = h("div");
  const draw = (q = "") => put(clear(list), table(rows.filter((r: any) => !q || `${r.name} ${r.code}`.toLowerCase().includes(q)), [
    { label: "Code", get: r => r.code }, { label: "Name", get: r => h("span", null, r.name, " ", demoBadge(r.is_demo)) },
    { label: "Urdu", get: r => r.name_ur ? h("span", { class: "urdu", lang: "ur" }, r.name_ur) : "—" },
    { label: "Location", get: r => `${r.lat.toFixed(5)}, ${r.lon.toFixed(5)}` }, { label: "Routes", get: r => r.routes.join(", ") || "—" },
    { label: "Status", get: r => r.status },
  ], r => [iconBtn("edit", "Edit", () => formModal(`Edit stop ${r.name}`, defs, r, v => api.put(`/api/admin/stops/${r.id}`, v))),
    iconBtn("trash", "Delete", () => confirmDo(`Delete stop ${r.name}?`, () => api.del(`/api/admin/stops/${r.id}`)))]));
  title(p, "Stops", h("button", { class: "btn btn-primary", onclick: () => formModal("Add stop", defs, { status: "active" }, v => api.post("/api/admin/stops", v)) }, icon("plus", 16), "Add stop"));
  p.append(h("div", { class: "toolbar" }, searchBox(draw)), list);
  draw();
}

async function drivers(p: HTMLElement) {
  const [rows, bs] = await Promise.all([api.get("/api/admin/drivers"), api.get("/api/admin/buses")]);
  const busOpts: [any, string][] = [[null, "— No bus —"], ...bs.map((b: any) => [b.id, `${b.bus_number}${b.driver_name ? ` (driver: ${b.driver_name})` : ""}`] as [any, string])];
  title(p, "Drivers", h("button", { class: "btn btn-primary", onclick: () => formModal("Add driver", [
    { name: "name", label: "Full name", required: true }, { name: "phone", label: "Mobile number", required: true, hint: "Used to sign in, e.g. 03001234567" },
    { name: "email", label: "Email (optional)" }, { name: "password", label: "Initial password", type: "password", required: true, hint: "At least 8 characters" },
    { name: "employee_code", label: "Employee code", required: true }, { name: "license_no", label: "Licence no." },
    { name: "bus_id", label: "Assign bus", type: "select", options: busOpts, full: true }], {}, v => api.post("/api/admin/drivers", v)) }, icon("plus", 16), "Add driver"));
  p.append(table(rows, [
    { label: "Name", get: r => h("span", null, h("strong", null, r.name), " ", demoBadge(r.is_demo)) }, { label: "Employee", get: r => r.employee_code },
    { label: "Phone", get: r => r.phone }, { label: "Bus", get: r => r.bus_number ? h("span", null, r.bus_number, r.route_code ? ` · ${r.route_code}` : "") : "Unassigned" },
    { label: "Account", get: r => h("span", { class: `badge badge-${r.is_active ? "ok" : "muted"}` }, r.is_active ? "Active" : "Deactivated") },
    { label: "Location consent", get: r => r.location_consent_at ? `Given ${fmtAgo(r.location_consent_at)}` : "Not given" },
    { label: "Now", get: r => r.on_trip ? h("span", { class: "badge badge-ok" }, "On trip") : "Off duty" },
  ], r => [iconBtn("edit", "Edit", () => formModal(`Edit driver ${r.name}`, [
    { name: "name", label: "Full name" }, { name: "phone", label: "Mobile number" }, { name: "license_no", label: "Licence no." },
    { name: "bus_id", label: "Assigned bus", type: "select", options: busOpts },
    { name: "is_active", label: "Account active", type: "checkbox" }, { name: "new_password", label: "Reset password", type: "password", hint: "Leave empty to keep" }],
    r, v => api.patch(`/api/admin/drivers/${r.id}`, { ...v, bus_id: v.bus_id ?? undefined, clear_bus: v.bus_id === null && !!r.bus_id }))) ]));
}

async function fleet(p: HTMLElement) {
  title(p, "Live fleet", h("span", { id: "fleet-state", class: "badge" }, "Connecting…"));
  const mapEl = h("div", { class: "fleet-map" });
  const side = h("div");
  p.append(h("div", { class: "split" }, mapEl, side));
  const rts = await api.get("/api/admin/routes");
  const mv = new MapView(mapEl, { center: cfg.map.center, zoom: cfg.map.zoom, tiles: cfg.map.tiles, attribution: cfg.map.attribution });
  mv.setRoutes(rts.map((r: any) => ({ id: r.id, code: r.code, color: r.color, shape: r.shape })));
  mv.setStops(rts.flatMap((r: any) => r.stops));
  const pts = rts.flatMap((r: any) => r.shape);
  if (pts.length) mv.fit(pts);
  const buses = new Map<number, any>();
  let selected: number | null = null;
  const drawSide = () => {
    const list = [...buses.values()].sort((a, b) => a.bus_number.localeCompare(b.bus_number));
    const sel = selected ? buses.get(selected) : null;
    put(clear(side),
      sel ? h("div", { class: "card" },
        h("div", { class: "row-title" }, routeChip(sel.route_code || "—", sel.route_color), h("h2", null, sel.bus_number), demoBadge(sel.is_demo), statusBadge(sel.status)),
        h("div", { class: "kv" },
          h("div", null, h("span", null, "Driver"), h("strong", null, sel.driver ? `${sel.driver.name} (${sel.driver.employee_code})` : sel.trip_source === "simulator" ? "Simulator" : "—")),
          h("div", null, h("span", null, "Last GPS"), h("strong", null, fmtAgo(sel.last_gps_at))),
          h("div", null, h("span", null, "Position"), h("strong", null, sel.position ? `${sel.position.lat.toFixed(5)}, ${sel.position.lon.toFixed(5)}` : "—")),
          h("div", null, h("span", null, "GPS accuracy"), h("strong", null, sel.accuracy_m ? `${Math.round(sel.accuracy_m)} m` : "—")),
          h("div", null, h("span", null, "Trip"), h("strong", null, sel.trip_id ? `#${sel.trip_id} ${sel.direction} · ${sel.gps_points} fixes` : "No active trip")),
          h("div", null, h("span", null, "Next stop"), h("strong", null, sel.next_stop ? sel.next_stop.name : "—"))),
        sel.trip_id ? h("button", { class: "btn btn-sm", onclick: () => confirmDo(`End trip #${sel.trip_id} for ${sel.bus_number}? Location sharing for this trip stops.`,
          () => api.post(`/api/admin/trips/${sel.trip_id}/end`), "End trip") }, icon("stop", 14), "End trip") : null) : h("p", { class: "hint" }, "Select a bus on the map or in the list."),
      table(list, [
        { label: "Bus", get: b => h("a", { href: "javascript:void 0", onclick: () => { selected = b.id; if (b.position) mv.center([b.position.lat, b.position.lon], 15); drawSide(); } }, b.bus_number) },
        { label: "Route", get: b => b.route_code ? routeChip(b.route_code, b.route_color) : "—" },
        { label: "Status", get: b => statusBadge(b.status) }, { label: "GPS", get: b => fmtAgo(b.last_gps_at) },
      ]));
  };
  const redraw = debounce(drawSide, 300);
  mv.onBusClick = id => { selected = id; drawSide(); };
  feed = new LiveFeed({ ticket: async () => (await api.post("/api/admin/stream-ticket")).ticket }, {
    snapshot: list => { buses.clear(); list.forEach(b => buses.set(b.id, b)); mv.setBuses(list); drawSide(); },
    bus: b => { buses.set(b.id, b); mv.updateBus(b); redraw(); },
    state: s => { const el = document.getElementById("fleet-state"); if (el) { el.textContent = s === "live" ? "Live" : s; el.className = `badge badge-${s === "live" ? "ok" : "warn"}`; } },
  }, "/api/admin/fleet");
  feed.pollHeaders = () => ({ Accept: "application/json", Authorization: `Bearer ${session.token}` });
  feed.start();
}

async function schedules(p: HTMLElement) {
  const [rows, rts] = await Promise.all([api.get("/api/admin/schedules"), api.get("/api/admin/routes")]);
  const defs: FieldDef[] = [
    { name: "route_id", label: "Route", type: "select", options: rts.map((r: any) => [r.id, `${r.code} — ${r.name}`]), full: true },
    { name: "days", label: "Days", hint: "Comma-separated: MON,TUE,WED,THU,FRI,SAT,SUN", full: true },
    { name: "first_departure", label: "First departure", type: "time", required: true }, { name: "last_departure", label: "Last departure", type: "time", required: true },
    { name: "headway_min", label: "Every (minutes)", type: "number", required: true }, { name: "notes", label: "Notes" },
    { name: "valid_from", label: "Valid from (optional)", type: "date" }, { name: "valid_to", label: "Valid to (optional)", type: "date" },
  ];
  title(p, "Schedules", h("button", { class: "btn btn-primary", onclick: () => formModal("Add timetable", defs, { days: "MON,TUE,WED,THU,FRI,SAT,SUN", route_id: rts[0]?.id },
    v => api.post("/api/admin/schedules", v)) }, icon("plus", 16), "Add timetable"));
  p.append(h("p", { class: "hint" }, "Passengers who favourite a route are notified when its timetable changes. Holiday services: add a separate entry with valid-from/to dates and the right days."),
    table(rows, [
      { label: "Route", get: r => routeChip(r.route_code, rts.find((x: any) => x.id === r.route_id)?.color) }, { label: "Days", get: r => r.days.replaceAll(",", ", ") },
      { label: "First", get: r => r.first_departure }, { label: "Last", get: r => r.last_departure }, { label: "Every", get: r => `${r.headway_min} min` },
      { label: "Valid", get: r => r.valid_from || r.valid_to ? `${r.valid_from || "…"} – ${r.valid_to || "…"}` : "Ongoing" },
      { label: "Notes", get: r => h("span", null, r.notes || "", " ", demoBadge(r.is_demo)) },
    ], r => [iconBtn("edit", "Edit", () => formModal("Edit timetable", defs, r, v => api.put(`/api/admin/schedules/${r.id}`, v))),
      iconBtn("trash", "Delete", () => confirmDo("Delete this timetable entry?", () => api.del(`/api/admin/schedules/${r.id}`)))]));
}

async function alerts(p: HTMLElement) {
  const [rows, rts, sts] = await Promise.all([api.get("/api/admin/alerts"), api.get("/api/admin/routes"), api.get("/api/admin/stops")]);
  title(p, "Service alerts", h("button", { class: "btn btn-primary", onclick: () => formModal("Publish alert", [
    { name: "title", label: "Title", required: true, full: true }, { name: "body", label: "Details", type: "textarea", full: true },
    { name: "severity", label: "Type", type: "select", options: [["info", "Information"], ["delay", "Delay"], ["disruption", "Disruption"], ["suspension", "Suspension"], ["schedule_change", "Schedule change"]] },
    { name: "route_id", label: "Route", type: "select", options: [[null, "All routes"], ...rts.map((r: any) => [r.id, r.code] as [any, string])] },
    { name: "stop_id", label: "Stop (optional)", type: "select", options: [[null, "—"], ...sts.map((s: any) => [s.id, s.name] as [any, string])] },
    { name: "notify", label: "Notify passengers who follow this route/stop", type: "checkbox", full: true }],
    { severity: "info", notify: true }, async v => { const r = await api.post("/api/admin/alerts", v); toast(`Alert published · ${r.notified_users} passengers notified`, "ok"); }) }, icon("plus", 16), "Publish alert"));
  p.append(table(rows, [
    { label: "Title", get: r => h("strong", null, r.title) }, { label: "Type", get: r => r.severity }, { label: "Route", get: r => r.route_code || "All" },
    { label: "Stop", get: r => r.stop_name }, { label: "Since", get: r => fmtAgo(r.starts_at) },
    { label: "State", get: r => h("span", { class: `badge badge-${r.is_active ? "ok" : "muted"}` }, r.is_active ? "Active" : "Ended") },
  ], r => r.is_active ? [h("button", { class: "btn btn-sm", onclick: () => confirmDo(`End alert “${r.title}”?`, () => api.patch(`/api/admin/alerts/${r.id}`, { is_active: false }), "End alert") }, "End")] : []));
}

async function complaints(p: HTMLElement) {
  const qs = new URLSearchParams(location.hash.split("?")[1] || "");
  const status = qs.get("status") || "open";
  const driverId = qs.get("driver");
  const [rows, sum] = await Promise.all([
    api.get(`/api/admin/complaints?status=${status}${driverId ? `&driver_id=${driverId}` : ""}`), api.get("/api/admin/complaints/summary")]);
  const LBL: Record<string, string> = { new: "New", in_review: "Under review", resolved: "Resolved", rejected: "Closed" };
  const CLS: Record<string, string> = { new: "bad", in_review: "warn", resolved: "ok", rejected: "muted" };
  const link = (st: string, d: string | null = driverId) => `#/complaints?status=${st}${d ? `&driver=${d}` : ""}`;
  const sel = h("select", { "aria-label": "Show", onchange: (e: any) => { location.hash = link(e.target.value); } },
    [["open", "Open (new + under review)"], ["new", "New"], ["in_review", "Under review"], ["resolved", "Resolved"], ["rejected", "Closed"], ["all", "All"]]
      .map(([v, l]) => h("option", { value: v, selected: v === status }, l)));
  title(p, "Passenger complaints", sel);
  const m = (label: string, v: any, cls: string, st: string) => h("a", { class: `metric ${cls}`, href: link(st, null) }, h("span", null, label), h("strong", null, String(v)));
  const driverName = driverId ? sum.drivers.find((d: any) => String(d.driver_id) === driverId)?.driver_name || `#${driverId}` : null;

  const review = (r: any) => {
    const st = h("select", null, Object.entries(LBL).map(([v, l]) => h("option", { value: v, selected: v === r.status }, l))) as HTMLSelectElement;
    const note = h("textarea", { rows: 3, maxlength: 2000, placeholder: "Reply shown to the passenger (e.g. action taken)" }) as HTMLTextAreaElement;
    note.value = r.admin_note || "";
    const kv = (k: string, v: any) => v ? h("div", null, h("span", null, k), h("strong", null, v)) : null;
    modal(`Complaint ${r.ref_code}`, h("div", null,
      h("div", { class: "kv" }, kv("Bus", r.bus_number), kv("Route", r.route_code), kv("Driver", r.driver_name ? `${r.driver_name} (${r.driver_code})` : "Not known"),
        kv("Category", r.category_label), kv("When", new Date(r.incident_at).toLocaleString("en-PK", { timeZone: "Asia/Karachi" })), kv("Where", r.location),
        kv("Passenger", r.contact_name || "Anonymous"), kv("Phone", r.contact_phone), kv("Filed", fmtAgo(r.created_at))),
      h("p", { class: "complaint-text" }, r.description),
      field("Status", st), field("Reply to passenger", note, "Signed-in passengers get a notification when you save.")),
      [{ label: "Cancel", onClick: () => true }, { label: "Save", kind: "btn-primary", onClick: async () => {
        try { await api.patch(`/api/admin/complaints/${r.id}`, { status: st.value, admin_note: note.value.trim() || null }); toast("Complaint updated", "ok"); route(); }
        catch (e: any) { toast(e.message, "error"); return false; }
      } }]);
  };

  put(p,
    h("div", { class: "admin-grid" }, m("New", sum.by_status.new, "bad", "new"), m("Under review", sum.by_status.in_review, "warn", "in_review"),
      m("Resolved", sum.by_status.resolved, "ok", "resolved"), m("Closed", sum.by_status.rejected, "", "rejected")),
    driverName ? h("div", { class: "notice" }, icon("user", 18), h("span", null, `Showing complaints about driver ${driverName}. `, h("a", { href: link(status, null) }, "Show all drivers"))) : null,
    table(rows, [
      { label: "Ref", get: r => h("strong", null, r.ref_code) }, { label: "Filed", get: r => fmtAgo(r.created_at) },
      { label: "Bus", get: r => r.bus_number }, { label: "Route", get: r => r.route_code ? routeChip(r.route_code, r.route_color) : "—" },
      { label: "Driver", get: r => r.driver_name ? h("a", { href: link(status, String(r.driver_id)) }, r.driver_name) : h("span", { class: "muted" }, "Not known") },
      { label: "Problem", get: r => r.category_label },
      { label: "Details", get: r => h("span", { class: "clip", title: r.description }, r.description) },
      { label: "Status", get: r => h("span", { class: `badge badge-${CLS[r.status]}` }, LBL[r.status]) },
    ], r => [h("button", { class: "btn btn-sm", onclick: () => review(r) }, "Review")]),
    h("h3", null, "Drivers with most complaints (last 90 days)"),
    table(sum.drivers, [
      { label: "Driver", get: d => h("a", { href: link("all", String(d.driver_id)) }, h("strong", null, d.driver_name)) }, { label: "Employee", get: d => d.driver_code },
      { label: "Complaints", get: d => h("strong", null, String(d.total)) }, { label: "Open", get: d => String(d.open) }, { label: "Upheld", get: d => String(d.upheld) },
      { label: "Latest", get: d => fmtAgo(d.last_at) },
    ]),
    h("p", { class: "hint" }, "A complaint is linked to the driver who was on that bus's trip when it was filed (or the bus's assigned driver). Mark it Resolved when it was valid and action was taken, Closed when it couldn't be confirmed."));
}

async function reports(p: HTMLElement) {
  const today = new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Karachi" });
  const dateIn = h("input", { type: "date", value: today }) as HTMLInputElement;
  const out = h("div");
  const load = async () => {
    put(clear(out), loading());
    const r = await api.get(`/api/admin/reports/daily?date=${dateIn.value}`);
    const s = r.summary;
    const m = (label: string, v: any, cls = "") => h("div", { class: `metric ${cls}` }, h("span", null, label), h("strong", null, v === null ? "—" : String(v)));
    put(clear(out),
      h("div", { class: "admin-grid" }, m("Trips", s.trips), m("Completed", s.completed, "ok"), m("Still running", s.active), m("Interrupted", s.interrupted, "bad"),
        m("Delayed trips", s.delayed_trips, "warn"), m("Avg GPS availability", s.avg_gps_availability_pct === null ? null : `${s.avg_gps_availability_pct}%`), m("Offline events", s.offline_events, "bad"), m("Service alerts", s.service_alerts)),
      h("h3", null, "Route usage"), table(r.route_usage, [{ label: "Route", get: x => h("span", null, x.route_code, " ", demoBadge(x.is_demo)) }, { label: "Trips", get: x => x.trips },
        { label: "Delayed", get: x => x.delayed_trips }, { label: "Journey plans", get: x => x.journey_plans }, { label: "Tracking views", get: x => x.tracking_views }]),
      h("h3", null, "Bus activity"), table(r.bus_activity, [{ label: "Bus", get: x => x.bus_number }, { label: "Trips", get: x => x.trips },
        { label: "Active", get: x => `${x.active_min} min` }, { label: "Distance", get: x => `${x.distance_km} km` }, { label: "GPS fixes", get: x => x.gps_points }]),
      h("h3", null, "Trips"), table(r.trips, [{ label: "#", get: x => x.trip_id }, { label: "Bus", get: x => x.bus_number }, { label: "Route", get: x => x.route_code },
        { label: "Source", get: x => x.source }, { label: "Status", get: x => x.status }, { label: "Duration", get: x => `${x.duration_min} min` },
        { label: "GPS availability", get: x => `${x.gps_availability_pct}%` }, { label: "Max delay", get: x => `${x.max_delay_min} min` }, { label: "Offline", get: x => x.offline_events },
        { label: "Ended", get: x => x.end_reason }]),
      h("h3", null, "Service interruptions"),
      r.service_interruptions.alerts.length || r.service_interruptions.interrupted_trips.length ?
        h("ul", null, r.service_interruptions.alerts.map((a: any) => h("li", null, `Alert: ${a.title} (${a.severity})`)),
          r.service_interruptions.interrupted_trips.map((t: any) => h("li", null, `Trip #${t.trip_id} ${t.bus_number} interrupted: ${t.end_reason}`))) : h("p", { class: "muted" }, "None."));
  };
  title(p, "Reports", dateIn, h("button", { class: "btn", onclick: load }, "Show"),
    h("button", { class: "btn", onclick: () => download(`/api/admin/reports/daily?date=${dateIn.value}&format=csv`, `speedo-trips-${dateIn.value}.csv`) }, icon("download", 16), "Export CSV"));
  p.append(out);
  dateIn.addEventListener("change", load);
  await load();
}

async function settings(p: HTMLElement) {
  const s = await api.get("/api/admin/settings");
  title(p, "Settings");
  const row = (k: string, v: any) => h("tr", null, h("td", null, k), h("td", null, h("strong", null, String(v))));
  p.append(
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Operating mode"),
      h("p", null, s.mode === "demo" ? "SIMULATION MODE — simulated buses on sample routes." : "REAL-WORLD MODE — positions come only from authorised drivers or the configured GPS provider."),
      h("p", { class: "hint" }, "Settings are read-only here and come from environment variables on the server (see .env.example). Change SPEEDO_MODE and GPS_SOURCE to switch data sources.")),
    h("div", { class: "split" },
      h("table", { class: "table" }, h("tbody", null, row("Mode", s.mode), row("Environment", s.environment), row("GPS source", s.gps_source), row("GPS provider", s.gps_provider),
        row("Database", s.database), row("PostGIS", s.postgis ? "enabled" : "off"), row("Cache", s.cache), row("Push notifications", s.push_notifications),
        row("Migrations", s.migrations.join(", ")), row("GPS rows stored", s.gps_rows_stored))),
      h("table", { class: "table" }, h("tbody", null, Object.entries(s.tracking).map(([k, v]) => row(k.replaceAll("_", " "), v)),
        row("Service area", `${s.service_area.min_lat}–${s.service_area.max_lat}, ${s.service_area.min_lon}–${s.service_area.max_lon}`)))),
    h("p", null, h("a", { href: "/docs", target: "_blank", rel: "noopener" }, "API documentation (Swagger) ↗")));
}

boot();
export {};
