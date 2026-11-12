// Speedo Live — passenger web app (single page, hash routing).
import { ApiError, LiveFeed, Session, makeApi, recent } from "./api.js";
import { $, clear, put, debounce, demoBadge, emptyState, errorBox, field, fmtAgo, fmtClock, fmtDist, fmtEta, h, icon, loading, modal, routeChip, STATUS, statusBadge, toast } from "./dom.js";
import { MapView } from "./map.js";
const session = new Session("speedo.passenger");
const api = makeApi(session, () => { toast("Your session ended. Please sign in again.", "info"); renderNav(); });
const S = {
    cfg: null, routes: [], routeDetail: new Map(), stops: [], buses: new Map(), me: null, feed: null, view: "",
    busListeners: new Set(), pickTarget: null,
};
let map;
const panel = () => $("#panel");
// ---------------------------------------------------------------- boot
async function boot() {
    try {
        [S.cfg, S.routes, S.stops] = await Promise.all([api.get("/api/config"), api.get("/api/routes"), api.get("/api/stops?limit=100")]);
    }
    catch (e) {
        put(clear(panel()), errorBox(e, () => location.reload()));
        return;
    }
    $("#demo-banner").hidden = true;
    map = new MapView($("#map"), { center: S.cfg.map.center, zoom: S.cfg.map.zoom, tiles: S.cfg.map.tiles, attribution: S.cfg.map.attribution });
    map.onStopClick = id => go(`#/stop/${id}`);
    map.onBusClick = id => go(`#/bus/${id}`);
    map.onPick = p => {
        if (S.pickTarget) {
            const t = S.pickTarget;
            S.pickTarget = null;
            document.body.classList.remove("picking");
            t({ label: `Map point ${p[0].toFixed(4)}, ${p[1].toFixed(4)}`, lat: p[0], lon: p[1] });
        }
    };
    await loadRouteShapes();
    map.fit([...S.routeDetail.values()].flatMap(d => d.shape));
    S.feed = new LiveFeed({}, {
        snapshot: list => { S.buses = new Map(list.map((b) => [b.id, b])); map.setBuses(list); S.busListeners.forEach(f => list.forEach(f)); },
        bus: b => { S.buses.set(b.id, b); map.updateBus(b); S.busListeners.forEach(f => f(b)); },
        alert: a => toast(`Service alert: ${a.title}`, "info", 6000),
        state: st => setFeedState(st),
    }, "/api/buses", (S.cfg.gps_interval_s || 5) * 1000);
    S.feed.start();
    renderNav();
    window.addEventListener("hashchange", route);
    route();
}
async function loadRouteShapes() {
    const details = await Promise.all(S.routes.map(r => api.get(`/api/routes/${r.id}`).catch(() => null)));
    details.filter(Boolean).forEach((d) => S.routeDetail.set(d.id, d));
    showNetwork();
}
function showNetwork(highlight = null) {
    map.setRoutes([...S.routeDetail.values()].map(d => ({ id: d.id, code: d.code, color: d.color, shape: d.shape })), highlight);
    map.setStops(S.stops);
    map.setOverlay([], []);
}
function setFeedState(st) {
    const el = $("#feed-state");
    const label = { live: "Live", connecting: "Connecting…", reconnecting: "Reconnecting…", polling: "Live (polling)", offline: "Offline" };
    el.textContent = label[st] || st;
    el.className = `feed-state fs-${st}`;
}
function go(hash) { if (location.hash === hash)
    route();
else
    location.hash = hash; }
function parseHash() {
    const [path, qs] = (location.hash.slice(1) || "/home").split("?");
    return { parts: path.split("/").filter(Boolean), q: new URLSearchParams(qs || "") };
}
const NAV = [
    { id: "home", label: "Home", icon: "home", hash: "#/home" },
    { id: "live", label: "Live Tracking", short: "Live Map", icon: "bus", hash: "#/live" },
    { id: "routes", label: "Routes", short: "Explore", icon: "route", hash: "#/routes" },
    { id: "timetable", label: "Timetable", icon: "clock", hash: "#/timetable", desktopOnly: true },
    { id: "favorites", label: "Favorites", icon: "star", hash: "#/favorites" },
    { id: "complain", label: "Report a driver", short: "Report", icon: "flag", hash: "#/complain" },
    { id: "profile", label: "Profile", icon: "user", hash: "#/profile" },
];
function renderNav() {
    const nav = clear($("#nav"));
    for (const n of NAV) {
        put(nav, h("a", { href: n.hash, class: `nav-item ${n.desktopOnly ? "desktop-only" : ""} ${S.view === n.id ? "active" : ""}`,
            "aria-current": S.view === n.id ? "page" : null }, icon(n.icon), h("span", { class: "lg" }, n.label), h("span", { class: "sm" }, n.short || n.label)));
    }
    const u = session.user;
    $("#user-chip").textContent = u ? u.name.split(" ")[0] : "Sign in";
}
async function route() {
    const { parts, q } = parseHash();
    const [view, id] = parts;
    S.busListeners.clear();
    map?.follow(null);
    S.pickTarget = null;
    document.body.classList.remove("picking");
    const viewMap = { stop: "home", bus: "live", plan: "home" };
    S.view = viewMap[view] || view || "home";
    renderNav();
    document.body.dataset.view = view || "home";
    const p = clear(panel());
    p.scrollTop = 0;
    try {
        switch (view) {
            case "live": return viewLive(p, q);
            case "bus": return await viewBus(p, Number(id));
            case "routes": return id ? await viewRoute(p, Number(id)) : viewRoutes(p);
            case "stop": return await viewStop(p, Number(id));
            case "plan": return await viewPlan(p, q);
            case "timetable": return await viewTimetable(p, q);
            case "favorites": return await viewFavorites(p);
            case "profile": return await viewProfile(p, q);
            case "complain": return await viewComplain(p, q);
            default: return viewHome(p);
        }
    }
    catch (e) {
        put(p, errorBox(e, route));
    }
    finally {
        map?.resize();
    }
}
// ------------------------------------------------------------ components
function header(title, back, ...extra) {
    return h("div", { class: "panel-head" }, back ? h("a", { href: back, class: "icon-btn", "aria-label": "Back" }, icon("back")) : null, h("h2", null, title), h("div", { class: "spacer" }), ...extra);
}
function busRow(b) {
    return h("a", { href: `#/bus/${b.id}`, class: "list-row" }, h("div", { class: "row-main" }, h("div", { class: "row-title" }, routeChip(b.route_code || "—", b.route_color), h("strong", null, b.bus_number), demoBadge(b.is_demo)), h("div", { class: "row-sub" }, b.next_stop ? `Next: ${b.next_stop.name} · ${fmtEta(b.next_stop.eta_s)}` : (STATUS[b.status]?.hint || ""), b.last_gps_at ? ` · GPS ${fmtAgo(b.last_gps_at)}` : "")), statusBadge(b.status));
}
function stopRow(s, extra) {
    return h("a", { href: `#/stop/${s.id}`, class: "list-row" }, h("div", { class: "row-main" }, h("div", { class: "row-title" }, icon("pin", 16), h("strong", null, s.name), s.name_ur ? h("span", { class: "urdu", lang: "ur" }, s.name_ur) : null), h("div", { class: "row-sub" }, (s.routes || []).map((r) => routeChip(r.code, r.color)), extra ? h("span", null, extra) : null)), icon("chevron", 18));
}
function routeCard(r) {
    return h("a", { href: `#/routes/${r.id}`, class: "route-card", style: { borderLeftColor: r.color } }, h("div", { class: "row-title" }, routeChip(r.code, r.color), demoBadge(r.is_demo), r.verified ? h("span", { class: "badge badge-ok" }, "Verified") : null), h("div", { class: "route-name" }, r.name), h("div", { class: "row-sub" }, `${r.stop_count} stops · ${r.length_km} km · `, h("strong", null, `${r.active_buses} live bus${r.active_buses === 1 ? "" : "es"}`)));
}
function placeLabel(p) { return p ? p.label : ""; }
function encodePlace(p) { return p.stop_id ? `stop:${p.stop_id}` : `ll:${p.lat.toFixed(5)},${p.lon.toFixed(5)}:${encodeURIComponent(p.label)}`; }
function decodePlace(v) {
    if (!v)
        return null;
    if (v.startsWith("stop:")) {
        const s = S.stops.find(x => x.id === Number(v.slice(5)));
        return s ? { label: s.name, lat: s.lat, lon: s.lon, stop_id: s.id } : null;
    }
    const m = v.match(/^ll:([-\d.]+),([-\d.]+):?(.*)$/);
    return m ? { lat: Number(m[1]), lon: Number(m[2]), label: decodeURIComponent(m[3] || "Selected point") } : null;
}
function locate() {
    return new Promise((resolve, reject) => {
        if (!navigator.geolocation)
            return reject(new Error("Location is not available on this device"));
        navigator.geolocation.getCurrentPosition(p => { S.me = [p.coords.latitude, p.coords.longitude]; map.setUser(S.me); resolve(S.me); }, e => reject(new Error(e.code === 1 ? "Location permission was denied" : "Couldn't get your location")), { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
    });
}
/** Text box that suggests stops, "my location" and "pick on map". */
function placeInput(label, initial, onChange) {
    let value = initial;
    const input = h("input", { type: "text", placeholder: "Stop name, or choose below", autocomplete: "off", value: placeLabel(initial),
        role: "combobox", "aria-expanded": "false", "aria-autocomplete": "list" });
    const list = h("div", { class: "suggest", role: "listbox", hidden: true });
    const set = (p) => { value = p; input.value = placeLabel(p); list.hidden = true; input.setAttribute("aria-expanded", "false"); onChange(p); };
    const show = () => {
        const qv = input.value.trim().toLowerCase();
        const matches = S.stops.filter(s => !qv || s.name.toLowerCase().includes(qv) || (s.name_ur && s.name_ur.includes(input.value.trim()))).slice(0, 7);
        put(clear(list), h("button", { type: "button", class: "suggest-item", onclick: async () => {
                try {
                    const me = await locate();
                    set({ label: "My location", lat: me[0], lon: me[1] });
                }
                catch (e) {
                    toast(e.message, "error");
                }
            } }, icon("locate", 16), "My current location"), h("button", { type: "button", class: "suggest-item", onclick: () => {
                list.hidden = true;
                S.pickTarget = set;
                document.body.classList.add("picking");
                toast("Tap the map to choose a point", "info");
            } }, icon("map", 16), "Choose on map"), ...matches.map(s => h("button", { type: "button", class: "suggest-item", role: "option", onclick: () => set({ label: s.name, lat: s.lat, lon: s.lon, stop_id: s.id }) }, icon("pin", 16), s.name, h("span", { class: "muted" }, (s.routes || []).map((r) => r.code).join(", ")))), matches.length ? null : h("div", { class: "suggest-empty" }, "No stop matches. Try “choose on map”."));
        list.hidden = false;
        input.setAttribute("aria-expanded", "true");
    };
    input.addEventListener("focus", show);
    input.addEventListener("input", debounce(() => { value = null; show(); }, 120));
    input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; if (!value && input.value)
        input.value = ""; }, 200));
    return h("div", { class: "place-input" }, field(label, input), list);
}
function searchCard(from = null, to = null) {
    let a = from, b = to;
    const submit = () => {
        if (!a || !b)
            return toast("Choose where you're starting and where you want to go", "error");
        go(`#/plan?from=${encodeURIComponent(encodePlace(a))}&to=${encodeURIComponent(encodePlace(b))}`);
    };
    const fromEl = placeInput("From", a, p => (a = p));
    const toEl = placeInput("To", b, p => (b = p));
    return h("form", { class: "search-card", onsubmit: (e) => { e.preventDefault(); submit(); } }, h("div", { class: "search-fields" }, fromEl, toEl), h("button", { class: "btn btn-primary btn-block", type: "submit" }, icon("search", 18), "Find my bus"));
}
// ------------------------------------------------------------------ views
async function viewHome(p) {
    showNetwork();
    put(p, h("div", { class: "hero hero-photo" }, h("div", { class: "hero-slides", "aria-hidden": "true" }, h("img", { src: "img/bus-1.webp", alt: "" }), h("img", { src: "img/bus-2.jpg", alt: "" })), h("div", { class: "hero-text" }, h("span", { class: "hero-kicker" }, "Speedo · Lahore"), h("h1", null, "Where are you going?"), h("p", null, "Your Bus, Your Route, Your Time."))), searchCard(S.me ? { label: "My location", lat: S.me[0], lon: S.me[1] } : null, null));
    const stats = h("div", { class: "stat-row" });
    const drawStats = () => {
        const live = [...S.buses.values()];
        const count = (...st) => live.filter(b => st.includes(b.status)).length;
        put(clear(stats), h("a", { class: "stat", href: "#/live" }, h("strong", null, String(count("active"))), h("span", null, "on the move")), h("a", { class: "stat warn", href: "#/live" }, h("strong", null, String(count("delayed"))), h("span", null, "delayed")), h("a", { class: "stat muted", href: "#/live" }, h("strong", null, String(count("stale", "offline"))), h("span", null, "no recent GPS")));
    };
    drawStats();
    S.busListeners.add(debounce(drawStats, 500));
    put(p, h("section", { class: "section" }, h("h3", null, "Live bus status"), stats));
    const nearbySec = h("section", { class: "section" }, h("div", { class: "section-head" }, h("h3", null, "Nearby stops"), h("button", { class: "btn btn-sm", onclick: async () => {
            try {
                await locate();
                route();
            }
            catch (e) {
                toast(e.message, "error");
            }
        } }, icon("locate", 16), S.me ? "Refresh" : "Use my location")));
    const center = S.me || S.cfg.map.center;
    const near = await api.get(`/api/stops?lat=${center[0]}&lon=${center[1]}&radius_m=3000&limit=4`);
    put(nearbySec, S.me ? null : h("p", { class: "hint" }, "Showing stops near central Lahore. Share your location for stops near you."), near.length ? h("div", { class: "list" }, near.map((s) => stopRow(s, `${fmtDist(s.distance_m)} away`))) : emptyState("No stops within 3 km."));
    put(p, nearbySec);
    const rec = recent.list();
    if (rec.length)
        put(p, h("section", { class: "section" }, h("h3", null, "Recent searches"), h("div", { class: "list" }, rec.map((r) => h("a", { class: "list-row", href: `#/plan?from=${encodeURIComponent(r.from.code)}&to=${encodeURIComponent(r.to.code)}` }, h("div", { class: "row-main" }, h("div", { class: "row-title" }, icon("clock", 16), h("span", null, `${r.from.label} → ${r.to.label}`))), icon("chevron", 18))))));
    if (session.token) {
        try {
            const fav = await api.get("/api/me/favorites");
            if (fav.stops.length)
                put(p, h("section", { class: "section" }, h("h3", null, "Favorite stops"), h("div", { class: "list" }, fav.stops.map((s) => stopRow({ ...s, routes: S.stops.find(x => x.id === s.id)?.routes })))));
        }
        catch { /* not critical */ }
    }
    put(p, h("section", { class: "section" }, h("h3", null, "Popular routes"), h("div", { class: "cards" }, [...S.routes].sort((a, b) => b.active_buses - a.active_buses).map(routeCard))));
}
function viewLive(p, q) {
    const filter = q.get("route") ? Number(q.get("route")) : null;
    showNetwork(filter);
    const list = h("div", { class: "list" });
    const chips = h("div", { class: "chips" }, h("a", { class: `chip ${filter ? "" : "active"}`, href: "#/live" }, "All routes"), S.routes.map(r => h("a", { class: `chip ${filter === r.id ? "active" : ""}`, href: `#/live?route=${r.id}` }, routeChip(r.code, r.color))));
    const draw = () => {
        const buses = [...S.buses.values()].filter(b => !filter || b.route_id === filter);
        const order = ["active", "delayed", "stale", "offline", "out_of_service"];
        buses.sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || a.bus_number.localeCompare(b.bus_number));
        put(clear(list), ...(buses.length ? buses.map(busRow) : [emptyState("No buses are running on this route right now.", "bus")]));
    };
    draw();
    const redraw = debounce(draw, 400);
    S.busListeners.add(() => { if (S.view === "live")
        redraw(); });
    if (filter) {
        const d = S.routeDetail.get(filter);
        if (d)
            map.fit(d.shape);
    }
    put(p, header("Live tracking", undefined, h("span", { id: "feed-state-copy", class: "muted" })), chips, h("p", { class: "hint" }, "Tap a bus to follow it. Grey buses haven't sent GPS recently — their position may be out of date."), list, legend());
}
function legend() {
    return h("details", { class: "legend" }, h("summary", null, "What do the statuses mean?"), h("ul", null, Object.entries(STATUS).filter(([k]) => k !== "not_in_service").map(([k, v]) => h("li", null, statusBadge(k), ` ${v.hint}`))));
}
async function viewBus(p, id) {
    put(p, loading());
    let follow = true;
    const body = h("div");
    const setFollow = (on) => {
        follow = on;
        map.follow(on ? id : null);
        followBtn.setAttribute("aria-pressed", String(on));
        followBtn.textContent = on ? "Following" : "Follow bus";
    };
    const followBtn = h("button", { class: "btn btn-sm", "aria-pressed": "true", onclick: () => setFollow(!follow) }, "Following");
    map.onFollowEnd = () => setFollow(false);
    let first = true;
    let busNumber = "";
    const draw = async () => {
        const b = await api.get(`/api/buses/${id}`);
        busNumber = b.bus_number;
        showNetwork(b.route_id);
        if (first && b.position) {
            first = false;
            map.center([b.position.lat, b.position.lon], 15);
            if (follow)
                map.follow(id);
        }
        put(clear(body), h("div", { class: "bus-hero", style: { borderColor: b.route_color || "#D0102B" } }, h("div", { class: "row-title" }, routeChip(b.route_code || "—", b.route_color), h("h2", null, `Bus ${b.bus_number}`), demoBadge(b.is_demo)), h("div", { class: "muted" }, b.route_name || "No route assigned"), h("div", { class: "kv" }, h("div", null, h("span", null, "Status"), statusBadge(b.status)), h("div", null, h("span", null, "Last GPS update"), h("strong", null, fmtAgo(b.last_gps_at))), h("div", null, h("span", null, "Speed"), h("strong", null, b.position ? `${b.position.speed_kmh} km/h` : "—")), h("div", null, h("span", null, "Delay"), h("strong", null, b.delay_min >= 1 ? `${Math.round(b.delay_min)} min` : "On time")), b.direction ? h("div", null, h("span", null, "Heading to"), h("strong", null, b.upcoming_stops?.length ? b.upcoming_stops[b.upcoming_stops.length - 1].name : "—")) : null), b.position?.low_accuracy ? h("p", { class: "warn-text" }, "GPS accuracy is low right now; the marker may be slightly off.") : null, ["stale", "offline"].includes(b.status) ? h("p", { class: "warn-text" }, STATUS[b.status].hint + ". ETAs are paused until GPS returns.") : null), h("h3", null, "Upcoming stops"), b.upcoming_stops?.length ? h("ol", { class: "timeline" }, b.upcoming_stops.map((s, i) => h("li", { class: i === 0 ? "next" : "" }, h("a", { href: `#/stop/${s.stop_id}` }, s.name), h("span", { class: "eta" }, fmtEta(s.eta_s)), h("span", { class: "muted" }, ` ${fmtDist(s.distance_m)} · ~${fmtClock(s.eta_at)}`)))) :
            emptyState(b.status === "out_of_service" ? "This bus is out of service." : "No live arrival times right now.", "clock"), h("p", { class: "hint" }, "Live ETAs use the bus's GPS, distance along the route, recent speed and typical speeds. They're estimates."));
    };
    await draw();
    put(clear(p), header("Bus", "#/live", followBtn), body, h("a", { class: "btn btn-block report-link", href: `#/complain?bus=${encodeURIComponent(busNumber)}` }, icon("flag", 18), "Report this bus or its driver"));
    const refresh = debounce(() => draw().catch(() => { }), 800);
    S.busListeners.add(b => { if (b.id === id)
        refresh(); });
}
function viewRoutes(p) {
    showNetwork();
    map.fit([...S.routeDetail.values()].flatMap(d => d.shape));
    put(p, header("Routes"), null, h("div", { class: "cards" }, S.routes.map(routeCard)), h("a", { class: "btn btn-block", href: "#/timetable" }, icon("clock", 18), "Open timetables"));
}
async function viewRoute(p, id) {
    const r = await api.get(`/api/routes/${id}`);
    S.routeDetail.set(id, r);
    showNetwork(id);
    map.fit(r.shape);
    const favBtn = await favButton("routes", id);
    const stopsEl = h("ol", { class: "timeline route-stops" });
    const draw = () => {
        const buses = [...S.buses.values()].filter(b => b.route_id === id && b.position);
        put(clear(stopsEl), ...r.stops.map((s, i) => {
            const here = buses.filter(b => b.next_stop?.id === s.id);
            return h("li", null, h("a", { href: `#/stop/${s.id}` }, s.name), s.name_ur ? h("span", { class: "urdu", lang: "ur" }, ` ${s.name_ur}`) : null, i === 0 ? h("span", { class: "badge" }, "Start") : i === r.stops.length - 1 ? h("span", { class: "badge" }, "End") : null, here.map((b) => h("a", { class: "bus-pill", href: `#/bus/${b.id}` }, icon("bus", 14), `${b.bus_number} · ${fmtEta(b.next_stop.eta_s)}`)));
        }));
    };
    draw();
    S.busListeners.add(debounce(draw, 500));
    put(p, header(r.code, "#/routes", favBtn), h("div", { class: "route-hero", style: { borderLeftColor: r.color } }, h("div", { class: "row-title" }, routeChip(r.code, r.color), demoBadge(r.is_demo), r.verified ? h("span", { class: "badge badge-ok", title: r.source }, "Verified") : null), h("h2", null, r.name), h("div", { class: "muted" }, `${r.stop_count} stops · ${r.length_km} km · source: ${r.source || "not specified"}`)), r.alerts.length ? h("div", { class: "alerts" }, r.alerts.map(alertBox)) : null, h("div", { class: "btn-row" }, h("a", { class: "btn btn-primary", href: `#/live?route=${id}` }, icon("bus", 18), "Track buses"), h("a", { class: "btn", href: `#/timetable?route=${id}` }, icon("clock", 18), "Timetable")), h("h3", null, "Stops"), stopsEl);
}
function alertBox(a) {
    return h("div", { class: `alert alert-${a.severity}` }, icon("alert", 18), h("div", null, h("strong", null, a.title), a.body ? h("p", null, a.body) : null));
}
async function favButton(kind, id) {
    let on = false;
    if (session.token) {
        try {
            const f = await api.get("/api/me/favorites");
            on = f[kind].some((x) => x.id === id);
        }
        catch { /* ignore */ }
    }
    const btn = h("button", { class: `icon-btn fav ${on ? "on" : ""}`, "aria-pressed": String(on), "aria-label": "Favorite", title: "Save to favorites" }, icon("star"));
    btn.addEventListener("click", async () => {
        if (!session.token) {
            toast("Sign in to save favorites", "info");
            return go("#/profile?next=" + encodeURIComponent(location.hash));
        }
        try {
            if (on)
                await api.del(`/api/me/favorites/${kind}/${id}`);
            else
                await api.post(`/api/me/favorites/${kind}`, { id });
            on = !on;
            btn.classList.toggle("on", on);
            btn.setAttribute("aria-pressed", String(on));
            toast(on ? "Saved to favorites" : "Removed from favorites", "ok");
        }
        catch (e) {
            toast(e.message, "error");
        }
    });
    return btn;
}
async function viewStop(p, id) {
    const s = await api.get(`/api/stops/${id}`);
    map.setOverlay([], [{ p: [s.lat, s.lon], label: s.name, kind: "stop" }]);
    map.center([s.lat, s.lon], 15);
    const box = h("div", null, loading());
    const draw = async () => {
        const a = await api.get(`/api/stops/${id}/arrivals`);
        clear(box);
        put(box, h("h3", null, "Live arrivals"), a.live.length ? h("div", { class: "list" }, a.live.map((x) => h("div", { class: "arrival" }, h("div", { class: "eta-big" }, fmtEta(x.eta_s)), h("div", { class: "row-main" }, h("div", { class: "row-title" }, routeChip(x.route_code, x.route_color), h("a", { href: `#/bus/${x.bus_id}` }, h("strong", null, `Bus ${x.bus_number}`)), demoBadge(x.is_demo), x.delay_min >= 1 ? h("span", { class: "badge badge-warn" }, `${Math.round(x.delay_min)} min late`) : null), h("div", { class: "row-sub" }, `towards ${x.towards} · ${fmtDist(x.distance_m)} away · GPS ${fmtAgo(x.last_gps_at)} · ~${fmtClock(x.eta_at)}`)), h("button", { class: "icon-btn", title: "Notify me", "aria-label": `Notify me when bus ${x.bus_number} approaches`, onclick: () => watchDialog(x.route_id, id, s.name, x.bus_id) }, icon("bell"))))) :
            h("p", { class: "muted" }, "No buses with live GPS are approaching this stop right now."), h("h3", null, "Timetable estimates"), a.scheduled.length ? h("div", { class: "list" }, a.scheduled.map((x) => h("div", { class: "arrival sched" }, h("div", { class: "eta-big" }, x.minutes <= 0 ? "Due" : `${x.minutes} min`), h("div", { class: "row-main" }, h("div", { class: "row-title" }, routeChip(x.route_code, x.route_color), h("span", { class: "badge badge-muted" }, "Scheduled")), h("div", { class: "row-sub" }, `towards ${x.towards} · ${fmtClock(x.arrival)} from the timetable, not live GPS`))))) :
            h("p", { class: "muted" }, "No more scheduled services today."));
    };
    await draw();
    const timer = setInterval(() => { if (location.hash.startsWith(`#/stop/${id}`))
        draw().catch(() => { });
    else
        clearInterval(timer); }, 15000);
    put(p, header(s.name, "#/home", await favButton("stops", id)), s.name_ur ? h("p", { class: "urdu big", lang: "ur" }, s.name_ur) : null, h("div", { class: "row-sub" }, s.routes.map((r) => h("a", { href: `#/routes/${r.id}` }, routeChip(r.code, r.color))), demoBadge(s.is_demo)), s.alerts.length ? h("div", { class: "alerts" }, s.alerts.map(alertBox)) : null, box, h("div", { class: "btn-row" }, h("a", { class: "btn", href: `#/plan?from=${encodeURIComponent("stop:" + id)}` }, icon("route", 18), "Plan from here"), h("button", { class: "btn", onclick: () => watchDialog(s.routes[0]?.id, id, s.name) }, icon("bell", 18), "Notify me")));
}
function watchDialog(routeId, stopId, stopName, busId) {
    if (!session.token) {
        toast("Sign in to get arrival notifications", "info");
        return go("#/profile?next=" + encodeURIComponent(location.hash));
    }
    const routes = S.stops.find(s => s.id === stopId)?.routes || [];
    const sel = h("select", null, routes.map((r) => h("option", { value: r.id, selected: r.id === routeId }, r.code)));
    const lead = h("select", null, [2, 5, 10, 15].map(m => h("option", { value: m, selected: m === 5 }, `${m} minutes before`)));
    modal(`Notify me at ${stopName}`, h("div", null, field("Route", sel), field("Alert me", lead), h("p", { class: "hint" }, busId ? "We'll alert you about this specific bus." : "We'll alert you about the next bus on this route. Active for 2 hours."), S.cfg.push_enabled ? null : h("p", { class: "hint" }, "Alerts appear in your Profile inbox. Phone push needs the Android app.")), [{ label: "Cancel", onClick: () => true }, { label: "Set alert", kind: "btn-primary", onClick: async () => {
                try {
                    await api.post("/api/me/watches", { route_id: Number(sel.value), stop_id: stopId, bus_id: busId ?? null, lead_min: Number(lead.value) });
                    toast("Alert set. We'll let you know when the bus is close.", "ok");
                }
                catch (e) {
                    toast(e.message, "error");
                    return false;
                }
            } }]);
}
async function viewPlan(p, q) {
    const from = decodePlace(q.get("from")), to = decodePlace(q.get("to"));
    put(p, header("Plan a journey", "#/home"), searchCard(from, to));
    if (!from || !to)
        return;
    const results = h("div", null, loading("Finding routes…"));
    put(p, results);
    let plan;
    try {
        plan = await api.post("/api/journeys/plan", { origin: { stop_id: from.stop_id ?? null, lat: from.stop_id ? null : from.lat, lon: from.stop_id ? null : from.lon, label: from.label },
            destination: { stop_id: to.stop_id ?? null, lat: to.stop_id ? null : to.lat, lon: to.stop_id ? null : to.lon, label: to.label } });
    }
    catch (e) {
        put(clear(results), errorBox(e));
        return;
    }
    recent.add({ from: { label: from.label, code: encodePlace(from) }, to: { label: to.label, code: encodePlace(to) } });
    clear(results);
    const ends = [{ p: [from.lat, from.lon], label: from.label, kind: "from" }, { p: [to.lat, to.lon], label: to.label, kind: "to" }];
    if (!plan.options.length) {
        map.setOverlay([], ends);
        put(results, emptyState(plan.message || "No route found.", "route"), plan.origin_stops.length ? h("p", { class: "hint" }, `Nearest stop to your start: ${plan.origin_stops[0].name} (${fmtDist(plan.origin_stops[0].distance_m)})`) : null);
        return;
    }
    const drawOption = (opt) => {
        const lines = [];
        let prev = [from.lat, from.lon];
        for (const l of opt.legs) {
            if (l.kind === "ride") {
                lines.push({ color: "#94A3B8", points: [prev, [l.board.lat, l.board.lon]], dashed: true });
                lines.push({ color: l.route.color, points: l.stops.map((s) => [s.lat, s.lon]) });
                prev = [l.alight.lat, l.alight.lon];
            }
        }
        lines.push({ color: "#94A3B8", points: [prev, [to.lat, to.lon]], dashed: true });
        map.setOverlay(lines, ends);
        map.fit(lines.flatMap(l => l.points));
    };
    showNetwork();
    drawOption(plan.options[0]);
    put(results, h("p", { class: "hint" }, `Nearest boarding stop: ${plan.origin_stops[0].name} (${fmtDist(plan.origin_stops[0].distance_m)} walk)`));
    plan.options.forEach((opt, idx) => {
        const card = h("div", { class: `option ${idx === 0 ? "selected" : ""}`, tabindex: 0 }, h("div", { class: "option-head" }, h("strong", { class: "total" }, `${opt.total_min} min`), h("span", null, opt.route_codes.map((c) => routeChip(c, opt.legs.find((l) => l.route?.code === c)?.route.color))), h("span", { class: "muted" }, opt.type === "transfer" ? "1 transfer" : "Direct", ` · ${fmtDist(opt.walk_m)} walking`)), h("ol", { class: "legs" }, opt.legs.map((l) => legItem(l))), h("div", { class: "btn-row" }, h("button", { class: "btn btn-primary", onclick: (e) => { e.stopPropagation(); startJourney(opt, from, to); } }, icon("play", 16), "Start tracking")));
        card.addEventListener("click", () => { results.querySelectorAll(".option").forEach(o => o.classList.remove("selected")); card.classList.add("selected"); drawOption(opt); });
        put(results, card);
    });
}
function legItem(l) {
    if (l.kind === "walk")
        return l.distance_m < 30 ? null : h("li", { class: "leg walk" }, icon("walk", 18), `Walk ${fmtDist(l.distance_m)} (${Math.round(l.walk_min)} min) to ${l.to}`);
    if (l.kind === "transfer")
        return h("li", { class: "leg transfer" }, icon("swap", 18), `Change buses at ${l.at}`);
    const nb = l.next_bus;
    const next = nb.method === "live" ? h("span", { class: "badge badge-ok" }, `Next bus ${nb.bus_number}: ${fmtEta(nb.eta_s)} (live)`) :
        nb.method === "scheduled" ? h("span", { class: "badge badge-muted" }, `Next scheduled: ${fmtEta(nb.eta_s)}`) :
            h("span", { class: "badge badge-bad" }, nb.note || "No service");
    return h("li", { class: "leg ride", style: { borderLeftColor: l.route.color } }, h("div", { class: "row-title" }, routeChip(l.route.code, l.route.color), h("strong", null, `Board at ${l.board.name}`), demoBadge(l.route.is_demo)), h("div", { class: "row-sub" }, `Towards ${l.towards} · ${l.stop_count} stops · ${Math.round(l.ride_min)} min · get off at `, h("strong", null, l.alight.name)), next, h("details", null, h("summary", null, "All stops"), h("ol", { class: "mini-stops" }, l.stops.map((s) => h("li", null, s.name)))));
}
async function startJourney(opt, from, to) {
    const ride = opt.legs.find((l) => l.kind === "ride");
    if (session.token) {
        try {
            await api.post("/api/me/history", { origin_label: from.label.slice(0, 160), dest_label: to.label.slice(0, 160), route_codes: opt.route_codes.join(",") });
            await api.post("/api/me/watches", { route_id: ride.route.id, stop_id: ride.board.id, lead_min: 5, bus_id: ride.next_bus.bus_id ?? null });
            toast("Tracking started. We'll alert you ~5 min before the bus arrives.", "ok");
        }
        catch { /* not fatal */ }
    }
    go(ride.next_bus.bus_id ? `#/bus/${ride.next_bus.bus_id}` : `#/stop/${ride.board.id}`);
}
async function viewTimetable(p, q) {
    showNetwork();
    const routeId = Number(q.get("route") || S.routes[0]?.id);
    const stopId = q.get("stop") ? Number(q.get("stop")) : null;
    const date = q.get("date") || new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Karachi" });
    const detail = S.routeDetail.get(routeId);
    const rsel = h("select", { onchange: (e) => go(`#/timetable?route=${e.target.value}&date=${date}`) }, S.routes.map(r => h("option", { value: r.id, selected: r.id === routeId }, `${r.code} — ${r.name}`)));
    const ssel = h("select", { onchange: (e) => go(`#/timetable?route=${routeId}&date=${date}${e.target.value ? `&stop=${e.target.value}` : ""}`) }, h("option", { value: "" }, "All major stops"), (detail?.stops || []).map((s) => h("option", { value: s.id, selected: s.id === stopId }, s.name)));
    const dsel = h("input", { type: "date", value: date, onchange: (e) => go(`#/timetable?route=${routeId}&date=${e.target.value}${stopId ? `&stop=${stopId}` : ""}`) });
    put(p, header("Timetable"), h("div", { class: "filters" }, field("Route", rsel), field("Stop", ssel), field("Date", dsel)));
    if (!routeId)
        return put(p, emptyState("No routes yet."));
    const t = await api.get(`/api/timetable?route_id=${routeId}&date=${date}${stopId ? `&stop_id=${stopId}` : ""}`);
    if (detail) {
        showNetwork(routeId);
        map.fit(detail.shape);
    }
    put(p, t.schedules.some((s) => s.is_demo) ? h("div", { class: "notice" }, icon("alert", 18), "Demonstration timetable — not an official Speedo schedule.") : null, t.alerts.length ? h("div", { class: "alerts" }, t.alerts.map(alertBox)) : null, h("div", { class: "kv" }, h("div", null, h("span", null, "Service on this date"), h("strong", null, t.operates_today ? "Operating" : "No service")), h("div", null, h("span", null, "First departure"), h("strong", null, t.first_departure || "—")), h("div", null, h("span", null, "Last departure"), h("strong", null, t.last_departure || "—")), h("div", null, h("span", null, "Departures"), h("strong", null, String(t.trips_today)))), h("h3", null, "Service pattern"), h("table", { class: "table" }, h("thead", null, h("tr", null, ["Days", "First", "Last", "Every", "Valid", "Notes"].map(x => h("th", null, x)))), h("tbody", null, t.schedules.map((s) => h("tr", null, h("td", null, s.days.replaceAll(",", ", ")), h("td", null, s.first_departure), h("td", null, s.last_departure), h("td", null, `${s.headway_min} min`), h("td", null, s.valid_from || s.valid_to ? `${s.valid_from || "…"} – ${s.valid_to || "…"}` : "Ongoing"), h("td", null, s.notes || ""))))));
    if (t.stop_times) {
        const name = detail?.stops.find((s) => s.id === stopId)?.name;
        for (const dir of ["outbound", "inbound"]) {
            const times = t.stop_times[dir];
            put(p, h("h3", null, `${name}: towards ${t.directions[dir].to}`), times.length ? h("div", { class: "times" }, times.map(x => h("span", null, x))) : h("p", { class: "muted" }, "No departures."));
        }
    }
    else {
        for (const dir of ["outbound", "inbound"]) {
            const d = t.directions[dir];
            put(p, h("h3", null, `${d.from} → ${d.to}`), h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Stop"), h("th", null, "From start"), h("th", null, "First"), h("th", null, "Last"))), h("tbody", null, d.stops.map((s) => h("tr", null, h("td", null, h("a", { href: `#/timetable?route=${routeId}&date=${date}&stop=${s.stop_id}` }, s.name)), h("td", null, `${Math.round(s.offset_min)} min`), h("td", null, s.first || "—"), h("td", null, s.last || "—"))))));
        }
    }
    put(p, h("p", { class: "hint" }, "Stop times are estimated from the route's average speed; live ETAs are shown on stop pages."));
}
async function viewFavorites(p) {
    showNetwork();
    put(p, header("Favorites"));
    if (!session.token) {
        put(p, emptyState("Sign in to save your favorite routes and stops.", "star"), h("a", { class: "btn btn-primary btn-block", href: "#/profile?next=%23%2Ffavorites" }, "Sign in"));
        return;
    }
    const f = await api.get("/api/me/favorites");
    put(p, h("h3", null, "Routes"), f.routes.length ? h("div", { class: "cards" }, f.routes.map((r) => routeCard({ ...r, active_buses: S.routes.find(x => x.id === r.id)?.active_buses ?? 0 }))) :
        h("p", { class: "muted" }, "Tap ☆ on a route to save it."));
    put(p, h("h3", null, "Stops"));
    if (!f.stops.length)
        return put(p, h("p", { class: "muted" }, "Tap ☆ on a stop to save it."));
    for (const s of f.stops) {
        const a = await api.get(`/api/stops/${s.id}/arrivals`).catch(() => ({ live: [], scheduled: [] }));
        const next = a.live[0] ? `${a.live[0].route_code} bus ${a.live[0].bus_number} in ${fmtEta(a.live[0].eta_s)}` :
            a.scheduled[0] ? `${a.scheduled[0].route_code} scheduled in ${a.scheduled[0].minutes} min` : "No upcoming buses";
        put(p, stopRow({ ...s, routes: S.stops.find(x => x.id === s.id)?.routes }, next));
    }
}
async function viewProfile(p, q) {
    showNetwork();
    if (!session.token)
        return authForms(p, q.get("next"));
    const [me, prefs, inbox, hist, comps] = await Promise.all([api.get("/api/me"), api.get("/api/me/notification-preferences"),
        api.get("/api/me/notifications?limit=20"), api.get("/api/me/history?limit=10"), api.get("/api/me/complaints").catch(() => [])]);
    api.post("/api/me/notifications/read").catch(() => { });
    const name = h("input", { value: me.name, maxlength: 120 });
    const phone = h("input", { value: me.phone || "", placeholder: "03001234567", inputmode: "tel" });
    const prefBox = (key, label) => {
        const cb = h("input", { type: "checkbox", checked: prefs[key] });
        cb.addEventListener("change", () => { prefs[key] = cb.checked; savePrefs(); });
        return h("label", { class: "check" }, cb, label);
    };
    const lead = h("select", { onchange: (e) => { prefs.approaching_lead_min = Number(e.target.value); savePrefs(); } }, [2, 3, 5, 10, 15].map(m => h("option", { value: m, selected: prefs.approaching_lead_min === m }, `${m} min`)));
    const savePrefs = debounce(async () => {
        try {
            const { user_id, ...body } = prefs;
            await api.put("/api/me/notification-preferences", body);
            toast("Preferences saved", "ok");
        }
        catch (e) {
            toast(e.message, "error");
        }
    }, 300);
    put(p, header("Profile", undefined, h("button", { class: "btn btn-sm", onclick: async () => {
            try {
                await api.post("/api/auth/logout");
            }
            catch { /* ignore */ }
            session.clear();
            renderNav();
            go("#/home");
            toast("Signed out", "ok");
        } }, icon("logout", 16), "Sign out")), h("section", { class: "section" }, h("h3", null, "Your details"), h("form", { class: "form", onsubmit: async (e) => {
            e.preventDefault();
            try {
                const u = await api.patch("/api/me", { name: name.value, phone: phone.value || null });
                session.set(session.token, u);
                renderNav();
                toast("Profile updated", "ok");
            }
            catch (err) {
                toast(err.message, "error");
            }
        } }, field("Name", name), field("Phone", phone), h("p", { class: "muted" }, me.email || ""), h("button", { class: "btn", type: "submit" }, "Save"))), h("section", { class: "section" }, h("h3", null, "Notifications"), prefBox("approaching", "Bus approaching my stop"), h("div", { class: "indent" }, "Alert me ", lead, " before arrival"), prefBox("delays", "Delays on my favorite routes"), prefBox("disruptions", "Service disruptions"), prefBox("schedule_changes", "Timetable changes"), S.cfg.push_enabled ? null : h("p", { class: "hint" }, "Phone push notifications use the Speedo Live Android app. Here, alerts appear in your inbox below.")), h("section", { class: "section" }, h("h3", null, `Inbox${inbox.unread ? ` (${inbox.unread} new)` : ""}`), inbox.items.length ? h("div", { class: "list" }, inbox.items.map((n) => h("div", { class: `list-row notif ${n.read_at ? "" : "unread"}` }, icon(n.kind === "delay" ? "clock" : n.kind === "disruption" ? "alert" : "bell", 18), h("div", { class: "row-main" }, h("strong", null, n.title), h("div", { class: "row-sub" }, n.body || "", " · ", fmtAgo(n.created_at)))))) :
        h("p", { class: "muted" }, "No notifications yet.")), h("section", { class: "section" }, h("div", { class: "section-head" }, h("h3", null, "Journey history"), hist.length ? h("button", { class: "btn btn-sm", onclick: async () => { await api.del("/api/me/history"); route(); } }, "Clear") : null), hist.length ? h("div", { class: "list" }, hist.map((x) => h("div", { class: "list-row" }, icon("clock", 16), h("div", { class: "row-main" }, h("strong", null, `${x.origin_label} → ${x.dest_label}`), h("div", { class: "row-sub" }, `${x.route_codes || ""} · ${fmtAgo(x.created_at)}`))))) :
        h("p", { class: "muted" }, "Journeys you plan will appear here.")), h("section", { class: "section" }, h("div", { class: "section-head" }, h("h3", null, "My complaints"), h("a", { class: "btn btn-sm", href: "#/complain" }, icon("flag", 16), "New complaint")), comps.length ? h("div", { class: "list" }, comps.map(complaintCard)) : h("p", { class: "muted" }, "Complaints you file while signed in appear here.")));
}
// ------------------------------------------------------------ complaints
const COMPLAINT_REFS = "speedo.complaints";
function savedRefs() { try {
    return JSON.parse(localStorage.getItem(COMPLAINT_REFS) || "[]");
}
catch {
    return [];
} }
function saveRef(ref) { try {
    localStorage.setItem(COMPLAINT_REFS, JSON.stringify([ref, ...savedRefs().filter(r => r !== ref)].slice(0, 10)));
}
catch { /* private mode */ } }
const C_STATUS = { new: "muted", in_review: "warn", resolved: "ok", rejected: "bad" };
function complaintCard(c) {
    return h("div", { class: "complaint-card" }, h("div", { class: "row-title" }, h("strong", null, c.ref_code), h("span", { class: `badge badge-${C_STATUS[c.status]}` }, c.status_label), h("span", { class: "spacer" }), h("span", { class: "muted" }, fmtAgo(c.created_at))), h("div", { class: "row-sub" }, icon("bus", 14), ` Bus ${c.bus_number}`, c.route_code ? ` · ${c.route_code}` : "", ` · ${c.category_label}`), h("p", { class: "complaint-text" }, c.description), c.reply ? h("div", { class: "complaint-reply" }, h("strong", null, "Speedo team: "), c.reply) : null);
}
/** "Now" in Pakistan time, formatted for <input type=datetime-local>. */
function localNow() { return new Date(Date.now() + 5 * 3600 * 1000).toISOString().slice(0, 16); }
async function viewComplain(p, q) {
    showNetwork();
    const [cats, fleet] = await Promise.all([api.get("/api/complaints/categories"), api.get("/api/buses?include_idle=true").catch(() => [])]);
    const busList = h("datalist", { id: "bus-numbers" }, fleet.map((b) => h("option", { value: b.bus_number }, b.route_code || "")));
    const stopList = h("datalist", { id: "stop-names" }, S.stops.map(s => h("option", { value: s.name })));
    const norm = (v) => v.toUpperCase().replace(/[^A-Z0-9]/g, "");
    const findBus = (v) => { const n = norm(v); return n ? fleet.find((b) => norm(b.bus_number) === n) : null; };
    const busIn = h("input", { list: "bus-numbers", required: true, autocomplete: "off", placeholder: "e.g. SP-101", value: q.get("bus") || "",
        maxlength: 32, class: "upper" });
    const busInfo = h("div", { class: "bus-match", "aria-live": "polite" });
    const showBus = () => {
        const b = findBus(busIn.value);
        put(clear(busInfo), !busIn.value.trim() ? null : b ? h("span", { class: "ok-text" }, "✓ Bus found", b.route_code ? [" on route ", routeChip(b.route_code, b.route_color)] : "")
            : h("span", { class: "muted" }, "Not in our list yet. Check the number painted on the front or side of the bus."));
    };
    busIn.addEventListener("input", showBus);
    showBus();
    let category = "";
    const catBox = h("div", { class: "cat-grid", role: "radiogroup", "aria-label": "What happened?" });
    for (const c of cats) {
        const b = h("button", { type: "button", class: "cat", role: "radio", "aria-checked": "false" }, c.label);
        b.addEventListener("click", () => { category = c.id; catBox.querySelectorAll(".cat").forEach(x => x.setAttribute("aria-checked", String(x === b))); });
        catBox.append(b);
    }
    const when = h("input", { type: "datetime-local", value: localNow(), max: localNow() });
    const where = h("input", { list: "stop-names", maxlength: 160, placeholder: "Stop or place (optional)" });
    const desc = h("textarea", { rows: 5, required: true, minlength: 10, maxlength: 2000, placeholder: "Tell us what happened…" });
    const count = h("small", { class: "muted counter" }, "0 / 2000");
    desc.addEventListener("input", () => { count.textContent = `${desc.value.length} / 2000`; });
    const u = session.user;
    const cname = h("input", { maxlength: 120, autocomplete: "name", value: u?.name || "" });
    const cphone = h("input", { inputmode: "tel", autocomplete: "tel", placeholder: "03001234567", value: u?.phone || "" });
    const err = h("p", { class: "error-text", role: "alert" });
    const submit = h("button", { class: "btn btn-primary btn-block", type: "submit" }, icon("flag", 18), "Submit complaint");
    const formBox = h("div");
    const checkIn = h("input", { placeholder: "SPC-XXXXXX", maxlength: 16, class: "upper", "aria-label": "Reference number" });
    const checkOut = h("div");
    const check = async (ref) => {
        put(clear(checkOut), loading());
        try {
            put(clear(checkOut), complaintCard(await api.get(`/api/complaints/${encodeURIComponent(ref.trim())}`)));
        }
        catch (e) {
            put(clear(checkOut), h("p", { class: "error-text" }, e.status === 404 ? "No complaint found with that reference number." : e.message));
        }
    };
    const recentRefs = h("div", { class: "chips" });
    const drawChecks = () => put(clear(recentRefs), savedRefs().map(r => h("button", { class: "chip", type: "button", onclick: () => { checkIn.value = r; check(r); } }, r)));
    drawChecks();
    const form = h("form", { class: "form", onsubmit: async (e) => {
            e.preventDefault();
            err.textContent = "";
            if (!category) {
                err.textContent = "Choose what happened.";
                return;
            }
            submit.disabled = true;
            try {
                const c = await api.post("/api/complaints", { bus_number: busIn.value.trim(), category, description: desc.value.trim(),
                    location: where.value.trim() || null, incident_at: when.value || null,
                    contact_name: cname.value.trim() || null, contact_phone: cphone.value.trim() || null });
                saveRef(c.ref_code);
                put(clear(formBox), h("div", { class: "complaint-done" }, h("div", { class: "done-icon" }, icon("flag", 28)), h("h3", null, "Complaint received"), h("p", null, `Thank you. The Speedo team will review your complaint about bus ${c.bus_number}.`), h("div", { class: "ref-box" }, h("span", null, "Your reference number"), h("strong", null, c.ref_code), h("button", { class: "btn btn-sm", type: "button", onclick: () => navigator.clipboard?.writeText(c.ref_code).then(() => toast("Copied", "ok")) }, icon("copy", 14), "Copy")), h("p", { class: "hint" }, "Keep this number to check the status below. Your contact details are only seen by the Speedo team, never by the driver."), h("button", { class: "btn", type: "button", onclick: () => route() }, "File another complaint")));
                formBox.scrollIntoView({ behavior: "smooth" });
                drawChecks();
            }
            catch (e2) {
                err.textContent = e2.message;
            }
            finally {
                submit.disabled = false;
            }
        } }, h("div", null, field("Bus number", busIn, "Written on the front and side of every Speedo bus"), busInfo), h("fieldset", { class: "plain" }, h("legend", null, "What happened?"), catBox), h("div", { class: "form-2" }, field("When", when), field("Where", where)), h("div", null, field("Details", desc, "Describe what happened. Please don't include other people's personal details."), count), h("details", { class: "contact-box", open: !!u }, h("summary", null, "Your contact (optional)"), h("div", { class: "form-2" }, field("Name", cname), field("Mobile number", cphone)), h("p", { class: "hint" }, "Lets the Speedo team follow up with you. Never shared with the driver.")), err, submit);
    put(formBox, form);
    put(p, header("Report a driver"), h("div", { class: "report-intro" }, icon("flag", 22), h("div", null, h("strong", null, "Had a problem on a Speedo bus?"), h("p", null, "Enter the bus number and tell us what happened: rash driving, rude behaviour, overcharging or anything else. Every complaint is reviewed by the Speedo team."), h("p", { class: "urdu", lang: "ur", dir: "rtl" }, "بس نمبر لکھیں اور ڈرائیور کے خلاف اپنی شکایت درج کریں۔"))), formBox, busList, stopList, h("section", { class: "section" }, h("h3", null, "Check a complaint"), h("form", { class: "inline-form", onsubmit: (e) => { e.preventDefault(); if (checkIn.value.trim())
            check(checkIn.value); } }, checkIn, h("button", { class: "btn", type: "submit" }, "Check")), recentRefs, checkOut), h("p", { class: "hint" }, "Emergency? Call 15 (Police) or 1122 (Rescue)."));
}
function authForms(p, next) {
    let mode = "login";
    const box = h("div");
    const draw = () => {
        const ident = h("input", { autocomplete: "username", required: true, placeholder: "you@example.com or 03001234567" });
        const name = h("input", { autocomplete: "name", required: true, minlength: 2 });
        const email = h("input", { type: "email", autocomplete: "email", placeholder: "Optional if you give a phone" });
        const phone = h("input", { inputmode: "tel", autocomplete: "tel", placeholder: "03001234567" });
        const pw = h("input", { type: "password", required: true, minlength: mode === "register" ? 8 : 1, autocomplete: mode === "login" ? "current-password" : "new-password" });
        const err = h("p", { class: "error-text", role: "alert" });
        const submit = h("button", { class: "btn btn-primary btn-block", type: "submit" }, mode === "login" ? "Sign in" : "Create account");
        const form = h("form", { class: "form", onsubmit: async (e) => {
                e.preventDefault();
                err.textContent = "";
                submit.disabled = true;
                try {
                    const res = mode === "login" ? await api.post("/api/auth/login", { identifier: ident.value, password: pw.value })
                        : await api.post("/api/auth/register", { name: name.value, email: email.value || null, phone: phone.value || null, password: pw.value });
                    if (res.user.role !== "passenger")
                        toast(`Signed in as ${res.user.role}. Use the ${res.user.role} app for ${res.user.role} tools.`, "info", 6000);
                    session.set(res.token, res.user);
                    renderNav();
                    toast(`Welcome, ${res.user.name.split(" ")[0]}!`, "ok");
                    go(next || "#/home");
                }
                catch (e2) {
                    err.textContent = e2.message;
                }
                finally {
                    submit.disabled = false;
                }
            } }, mode === "register" ? [field("Full name", name), field("Email", email), field("Mobile number", phone, "Email or phone is required")] : field("Email or phone", ident), field("Password", pw, mode === "register" ? "At least 8 characters with letters and numbers" : undefined), err, submit);
        put(clear(box), h("div", { class: "tabs", role: "tablist" }, h("button", { role: "tab", class: mode === "login" ? "active" : "", "aria-selected": String(mode === "login"), onclick: () => { mode = "login"; draw(); } }, "Sign in"), h("button", { role: "tab", class: mode === "register" ? "active" : "", "aria-selected": String(mode === "register"), onclick: () => { mode = "register"; draw(); } }, "Create account")), form, S.cfg.demo ? h("p", { class: "hint" }, "Demo account: passenger@speedo.demo / Demo@12345") : null);
    };
    draw();
    put(p, header("Your account"), h("p", { class: "muted" }, "You can find routes and track buses without an account. Sign in to save favorites, keep journey history and get arrival alerts."), box);
}
window.addEventListener("online", () => toast("Back online", "ok"));
window.addEventListener("offline", () => toast("You're offline. Showing last known information.", "error", 6000));
boot();
void ApiError;
