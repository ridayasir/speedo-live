// Speedo Live — driver web app (browser version of the Android driver app).
// Shares GPS only while a trip is active, only for the driver's assigned bus.
import { Session, makeApi } from "./api.js";
import { $, clear, demoBadge, emptyState, errorBox, field, fmtAgo, h, icon, loading, modal, put, routeChip, statusBadge, toast } from "./dom.js";
import { MapView } from "./map.js";

const session = new Session("speedo.driver");
const api = makeApi(session, () => { stopGps(); render(); });
const QKEY = "speedo.driver.queue";
const main = () => $("#main");

const G = {
  me: null as any, cfg: null as any, watchId: null as number | null, lastSent: 0, lastFix: null as GeolocationPosition | null,
  sent: 0, rejected: 0, heartbeat: 0, lastStatus: Date.now(), error: "" as string, sending: false, wake: null as any, simTimer: 0, simChainage: 0, tab: "dashboard",
};

function queue(): any[] { try { return JSON.parse(localStorage.getItem(QKEY) || "[]"); } catch { return []; } }
function setQueue(q: any[]) { try { localStorage.setItem(QKEY, JSON.stringify(q.slice(-500))); } catch { /* storage full */ } }

async function boot() {
  G.cfg = await api.get("/api/config").catch(() => ({ demo: false, gps_interval_s: 5, map: { center: [31.52, 74.35], zoom: 12 } }));
  $("#demo-banner").hidden = true;
  window.addEventListener("hashchange", () => { G.tab = location.hash.slice(2) || "dashboard"; render(); });
  window.addEventListener("online", () => { toast("Back online — sending saved locations", "ok"); flush(); });
  window.addEventListener("offline", () => toast("No internet. Locations are saved and will be sent when you're back online.", "error", 6000));
  G.tab = location.hash.slice(2) || "dashboard";
  render();
}

async function render() {
  const m = clear(main());
  if (!session.token) return renderLogin(m);
  put(m, loading());
  try {
    G.me = await api.get("/api/driver/me");
  } catch (e: any) {
    return put(clear(m), errorBox(e, render));
  }
  // resume sharing after reload/crash if a trip is still active
  if (G.me.trip && G.watchId === null && !G.simTimer && G.me.driver.location_consent_at) startGps();
  clear(m);
  const tabs: Record<string, () => any> = { dashboard, route: myRoute, gps: gpsStatus, history, profile };
  await (tabs[G.tab] || dashboard)();
  renderNav();
}

function renderNav() {
  const nav = clear($("#driver-nav"));
  nav.hidden = !session.token;
  for (const [id, label, ic] of [["dashboard", "Dashboard", "home"], ["route", "My Route", "route"], ["gps", "GPS Status", "signal"], ["history", "Trips", "clock"], ["profile", "Profile", "user"]]) {
    put(nav, h("a", { href: `#/${id}`, class: G.tab === id ? "active" : "" }, icon(ic), label));
  }
}

function renderLogin(m: HTMLElement) {
  const id = h("input", { autocomplete: "username", inputmode: "tel", placeholder: "03001234567 or email", required: true }) as HTMLInputElement;
  const pw = h("input", { type: "password", autocomplete: "current-password", required: true }) as HTMLInputElement;
  const err = h("p", { class: "error-text", role: "alert" });
  renderNav();
  put(m, h("div", { class: "login-wrap" }, h("div", { class: "card login-card" },
    h("img", { class: "login-cover", src: "img/bus-2.jpg", alt: "Speedo bus in Lahore" }),
    h("h2", null, "Driver sign in"), h("p", { class: "muted" }, "For authorised Speedo drivers only."),
    h("form", { class: "form", onsubmit: async (e: Event) => {
      e.preventDefault(); err.textContent = "";
      try {
        const r = await api.post("/api/auth/login", { identifier: id.value, password: pw.value });
        if (r.user.role !== "driver") { err.textContent = "This account is not a driver account."; return; }
        session.set(r.token, r.user); render();
      } catch (e2: any) { err.textContent = e2.message; }
    } }, field("Phone or email", id), field("Password", pw), err, h("button", { class: "btn btn-primary btn-block big-btn", type: "submit" }, "Sign in")),
    G.cfg?.demo ? h("p", { class: "hint" }, "Test account: driver@speedo.demo / Demo@12345") : null)));
}

// ------------------------------------------------------------- GPS sharing
function startGps() {
  if (!("geolocation" in navigator)) { G.error = "This device has no GPS / location service."; return; }
  G.error = "";
  G.watchId = navigator.geolocation.watchPosition(onFix, onGpsError, { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
  // watchPosition may go quiet while the bus is standing still; ask for a fresh fix so the
  // server keeps receiving genuine positions (a stopped bus must not look like lost GPS).
  clearInterval(G.heartbeat);
  G.heartbeat = window.setInterval(() => {
    if (G.watchId === null) return;
    if (Date.now() - G.lastSent > G.cfg.gps_interval_s * 1000 * 1.5)
      navigator.geolocation.getCurrentPosition(onFix, onGpsError, { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
    if (Date.now() - G.lastStatus > 15000) refreshStatus();
  }, G.cfg.gps_interval_s * 1000);
  (navigator as any).wakeLock?.request("screen").then((w: any) => (G.wake = w)).catch(() => {});
}

function stopGps() {
  if (G.watchId !== null) navigator.geolocation.clearWatch(G.watchId);
  G.watchId = null;
  clearInterval(G.simTimer); G.simTimer = 0;
  clearInterval(G.heartbeat); G.heartbeat = 0;
  G.wake?.release?.(); G.wake = null;
}

function onGpsError(e: GeolocationPositionError) {
  G.error = e.code === 1 ? "Location permission denied. Allow location for this site in your browser settings."
    : e.code === 2 ? "GPS signal unavailable. Make sure location/GPS is switched on." : "GPS is taking too long to respond.";
  refreshLive();
}

function onFix(pos: GeolocationPosition) {
  G.lastFix = pos; G.error = "";
  const now = Date.now();
  if (now - G.lastSent < G.cfg.gps_interval_s * 1000 - 300) { refreshLive(); return; }
  G.lastSent = now;
  enqueue({ lat: pos.coords.latitude, lon: pos.coords.longitude, accuracy_m: Math.round(pos.coords.accuracy),
    speed_mps: pos.coords.speed !== null && pos.coords.speed >= 0 ? pos.coords.speed : null,
    heading: pos.coords.heading !== null && !Number.isNaN(pos.coords.heading) ? pos.coords.heading : null,
    recorded_at: new Date(pos.timestamp).toISOString() });
}

function enqueue(point: any) {
  setQueue([...queue(), point]);
  flush();
}

async function flush() {
  if (G.sending || !navigator.onLine) { refreshLive(); return; }
  const q = queue();
  if (!q.length) return;
  G.sending = true;
  try {
    const batch = q.slice(0, 100);
    const r = batch.length === 1 ? await api.post("/api/driver/location", batch[0]) : await api.post("/api/driver/location/batch", { points: batch });
    G.sent += r.accepted; G.rejected += r.rejected.length;
    if (r.rejected.length) G.error = `Some GPS points were rejected: ${[...new Set(r.rejected.map((x: any) => x.reason.replaceAll("_", " ")))].join(", ")}`;
    setQueue(queue().slice(batch.length));
  } catch (e: any) {
    if (e.code === "no_active_trip" || e.code === "trip_not_active") { setQueue([]); stopGps(); toast("Your trip was ended. Location sharing stopped.", "info"); render(); }
    else if (e.status === 429) { /* keep queue, slow down */ }
    else if (e.status >= 400 && e.status < 500 && e.status !== 401) { setQueue(queue().slice(1)); G.error = e.message; }
    else G.error = navigator.onLine ? e.message : "Offline — locations saved on this phone";
  } finally {
    G.sending = false;
    refreshLive();
    if (queue().length && navigator.onLine) setTimeout(flush, 2000);
  }
}

// DEMO only: drive along the route without moving the phone.
function simulate() {
  const route = G.me.route;
  if (!route?.shape?.length) return;
  const pts: [number, number][] = route.shape;
  const cum = [0];
  for (let i = 1; i < pts.length; i++) cum.push(cum[i - 1] + dist(pts[i - 1], pts[i]));
  const total = cum[cum.length - 1];
  const dir = G.me.trip?.direction || "outbound";
  G.simChainage = Math.min(G.simChainage, total);
  G.simTimer = window.setInterval(() => {
    G.simChainage = Math.min(total, G.simChainage + 6 * G.cfg.gps_interval_s);
    const c = dir === "outbound" ? G.simChainage : total - G.simChainage;
    let i = 1; while (i < cum.length - 1 && cum[i] < c) i++;
    const t = (c - cum[i - 1]) / Math.max(1, cum[i] - cum[i - 1]);
    const lat = pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]), lon = pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]);
    G.lastFix = { coords: { latitude: lat, longitude: lon, accuracy: 10, speed: 6, heading: null }, timestamp: Date.now() } as any;
    enqueue({ lat, lon, accuracy_m: 10, speed_mps: 6, recorded_at: new Date().toISOString() });
  }, G.cfg.gps_interval_s * 1000);
}

function dist(a: [number, number], b: [number, number]) {
  const R = 6371000, toR = Math.PI / 180;
  const x = (b[1] - a[1]) * toR * Math.cos((a[0] + b[0]) / 2 * toR), y = (b[0] - a[0]) * toR;
  return Math.sqrt(x * x + y * y) * R;
}

async function refreshStatus() {
  G.lastStatus = Date.now();
  try {
    const me = await api.get("/api/driver/me");
    G.me.live = me.live;
    const el = document.getElementById("drv-status");
    if (el && me.live) put(clear(el), statusBadge(me.live.status));
  } catch { /* offline: keep last */ }
}

function refreshLive() {
  const el = document.getElementById("gps-live");
  if (el) put(clear(el), gpsGrid());
}

function gpsGrid() {
  const f = G.lastFix, acc = f ? Math.round(f.coords.accuracy) : null;
  const q = queue().length;
  return put(h("div"),
    h("div", { class: "gps-grid" },
      h("div", null, h("span", null, "GPS"), h("strong", null, G.simTimer ? "Simulated" : G.watchId !== null ? (f ? "Receiving" : "Searching…") : "Off")),
      h("div", null, h("span", null, "Accuracy"), h("strong", { style: { color: acc && acc > 50 ? "var(--warn)" : "" } }, acc ? `±${acc} m${acc > 50 ? " (weak)" : ""}` : "—")),
      h("div", null, h("span", null, "Last fix"), h("strong", null, f ? fmtAgo(new Date(f.timestamp).toISOString()) : "—")),
      h("div", null, h("span", null, "Internet"), h("strong", null, navigator.onLine ? "Connected" : "Offline")),
      h("div", null, h("span", null, "Sent"), h("strong", null, String(G.sent))),
      h("div", null, h("span", null, "Waiting to send"), h("strong", { style: { color: q ? "var(--warn)" : "" } }, String(q)))),
    G.error ? h("p", { class: "warn-text" }, icon("alert", 14), " ", G.error) : null);
}

// ------------------------------------------------------------------ tabs
async function dashboard() {
  const m = main(), me = G.me;
  put(m, h("div", { class: "driver-main" },
    h("div", { class: "panel-head" }, h("h2", null, `Salaam, ${me.driver.name.split(" ")[0]}`), h("div", { class: "spacer" }), demoBadge(me.driver.is_demo)),
    !me.bus ? h("div", { class: "card" }, emptyState("No bus is assigned to you yet. Please contact your depot administrator.", "bus")) : tripCard()));
}

function tripCard() {
  const me = G.me, trip = me.trip;
  const dirSel = h("select", null, h("option", { value: "outbound" }, `Towards ${me.route?.last_stop || "end"}`), h("option", { value: "inbound" }, `Towards ${me.route?.first_stop || "start"}`)) as HTMLSelectElement;
  const card = h("div", { class: "trip-card" },
    h("div", { class: `trip-state ${trip ? "on" : ""}` }, trip ? "● Trip in progress — sharing location" : "Off duty — location not shared"),
    h("div", { class: "row-title", style: { justifyContent: "center", margin: "10px 0" } }, me.route ? routeChip(me.route.code, me.route.color) : null, h("h2", null, `Bus ${me.bus.bus_number}`), demoBadge(me.bus.is_demo)),
    h("div", { class: "muted" }, me.route ? me.route.name : "No route assigned"),
    me.live ? h("div", { id: "drv-status", style: { marginTop: "8px" } }, statusBadge(me.live.status)) : null);
  if (!me.driver.location_consent_at) {
    put(card, h("div", { class: "notice", style: { textAlign: "left", marginTop: "14px" } }, icon("alert", 18),
      h("div", null, h("strong", null, "Location sharing consent"), h("p", null, "While a trip is active, this app sends your bus's GPS location every few seconds so passengers can see where the bus is. Location is only shared during trips you start, and stops when you end the trip or sign out. Trip locations are kept for a limited time for service reports."))),
      h("button", { class: "btn btn-primary big-btn", onclick: async () => { await api.post("/api/driver/consent", { accepted: true }); toast("Thank you", "ok"); render(); } }, "I agree — enable location sharing"));
    return card;
  }
  if (!trip) {
    put(card, h("div", { style: { textAlign: "left", marginTop: "14px" } }, field("Direction", dirSel)),
      me.bus.status !== "active" ? h("p", { class: "warn-text" }, `This bus is marked ${me.bus.status}. It cannot start a trip.`) : null,
      h("button", { class: "btn btn-accent big-btn", disabled: me.bus.status !== "active", onclick: async () => {
        try {
          await api.post("/api/driver/trips/start", { direction: dirSel.value });
          G.sent = 0; G.rejected = 0; G.simChainage = 0; setQueue([]);
          startGps(); toast("Trip started. Keep this screen open while driving.", "ok"); render();
        } catch (e: any) { toast(e.message, "error"); }
      } }, icon("play", 20), "Start trip"));
  } else {
    put(card, h("div", { id: "gps-live" }, gpsGrid()),
      h("p", { class: "hint" }, "Keep this page open and the screen on. For reliable background tracking use the Speedo Live Driver Android app."),
      me.bus.is_demo && G.cfg.demo ? h("button", { class: "btn btn-sm", style: { marginTop: "8px" }, onclick: () => {
        if (G.simTimer) { clearInterval(G.simTimer); G.simTimer = 0; startGps(); toast("Using real GPS again", "info"); }
        else { stopGps(); simulate(); toast("Simulating a drive along the route", "info"); }
        refreshLive();
      } }, G.simTimer ? "Use real GPS" : "Simulate driving") : null,
      h("button", { class: "btn btn-danger big-btn", onclick: () => modal("End trip?", h("p", null, "Location sharing will stop and passengers will no longer see this bus."), [
        { label: "Keep driving", onClick: () => true },
        { label: "End trip", kind: "btn-danger", onClick: async () => {
          await flush().catch(() => {});
          try { await api.post("/api/driver/trips/end", { reason: "completed" }); } catch (e: any) { toast(e.message, "error"); }
          stopGps(); setQueue([]); toast("Trip ended", "ok"); render();
        } }]) }, icon("stop", 20), "End trip"));
  }
  return card;
}

async function myRoute() {
  const r = G.me.route;
  const m = main();
  if (!r) return put(m, h("div", { class: "driver-main" }, emptyState("No route assigned.", "route")));
  const mapEl = h("div", { class: "mini-map" });
  put(m, h("div", { class: "driver-main" },
    h("div", { class: "panel-head" }, routeChip(r.code, r.color), h("h2", null, r.name)),
    mapEl,
    h("ol", { class: "timeline" }, r.stops.map((s: any, i: number) => h("li", null, s.name, s.name_ur ? h("span", { class: "urdu", lang: "ur" }, s.name_ur) : null,
      i === 0 ? h("span", { class: "badge" }, "Start") : i === r.stops.length - 1 ? h("span", { class: "badge" }, "End") : null)))));
  const mv = new MapView(mapEl, { center: G.cfg.map.center, zoom: 12, tiles: G.cfg.map.tiles, attribution: G.cfg.map.attribution });
  mv.setRoutes([{ id: r.id, code: r.code, color: r.color, shape: r.shape }]);
  mv.setStops(r.stops);
  mv.fit(r.shape);
  if (G.lastFix) mv.setUser([G.lastFix.coords.latitude, G.lastFix.coords.longitude]);
}

async function gpsStatus() {
  put(main(), h("div", { class: "driver-main" }, h("h2", null, "GPS status"),
    h("div", { class: "card" }, h("div", { id: "gps-live" }, gpsGrid())),
    h("div", { class: "card" }, h("h3", { style: { marginTop: 0 } }, "Troubleshooting"),
      h("ul", null, h("li", null, "Turn on Location / GPS in your phone settings."), h("li", null, "Allow location for this app or website."),
        h("li", null, "If accuracy is weak (over 50 m), move away from tall buildings or flyovers."),
        h("li", null, "No internet? Locations are stored on the phone and sent automatically later.")),
      h("button", { class: "btn btn-sm", onclick: () => { flush(); refreshLive(); } }, "Send saved locations now"))));
}

async function history() {
  const rows = await api.get("/api/driver/trips?limit=30");
  put(main(), h("div", { class: "driver-main" }, h("h2", null, "Trip history"),
    rows.length ? h("div", { class: "list", style: { marginTop: "12px" } }, rows.map((t: any) => h("div", { class: "list-row" }, icon("bus", 18),
      h("div", { class: "row-main" }, h("strong", null, `${t.route_code} · ${t.bus_number} · ${t.direction}`),
        h("div", { class: "row-sub" }, `${new Date(t.started_at).toLocaleString("en-PK", { timeZone: "Asia/Karachi" })} · ${(t.distance_m / 1000).toFixed(1)} km · ${t.gps_points} GPS fixes`)),
      h("span", { class: `badge badge-${t.status === "completed" ? "ok" : t.status === "active" ? "warn" : "muted"}` }, t.status)))) : emptyState("No trips yet.", "clock")));
}

async function profile() {
  const d = G.me.driver;
  put(main(), h("div", { class: "driver-main" }, h("h2", null, "Profile"),
    h("div", { class: "card" }, h("div", { class: "kv" },
      h("div", null, h("span", null, "Name"), h("strong", null, d.name)), h("div", null, h("span", null, "Employee code"), h("strong", null, d.employee_code)),
      h("div", null, h("span", null, "Phone"), h("strong", null, d.phone || "—")), h("div", null, h("span", null, "Licence"), h("strong", null, d.license_no || "—")),
      h("div", null, h("span", null, "Bus"), h("strong", null, G.me.bus?.bus_number || "Unassigned")),
      h("div", null, h("span", null, "Location consent"), h("strong", null, d.location_consent_at ? `Given ${fmtAgo(d.location_consent_at)}` : "Not given")))),
    d.location_consent_at ? h("button", { class: "btn btn-block", onclick: () => modal("Withdraw consent?", h("p", null, "You won't be able to start trips until you agree again. Any active trip will end."), [
      { label: "Cancel", onClick: () => true },
      { label: "Withdraw", kind: "btn-danger", onClick: async () => { await api.post("/api/driver/consent", { accepted: false }); stopGps(); render(); } }]) }, "Withdraw location consent") : null,
    h("button", { class: "btn btn-block", style: { marginTop: "10px" }, onclick: async () => {
      if (G.me.trip && !confirm("You have an active trip. Signing out will end it. Continue?")) return;
      await flush().catch(() => {});
      try { await api.post("/api/auth/logout"); } catch { /* ignore */ }
      stopGps(); session.clear(); setQueue([]); location.hash = "#/dashboard"; render();
    } }, icon("logout", 18), "Sign out")));
}

boot();
export {};
