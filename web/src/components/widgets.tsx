"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { Bus, Clock, LocateFixed, MapPin, Navigation, Radio, Search } from "lucide-react";
import { api } from "@/lib/api";
import { ago, clock, km, useApi } from "@/lib/hooks";
import type { Arrivals, BusState, RouteSummary, Stop } from "@/lib/types";
import { DemoBadge, Empty, ErrorBox, Spinner, StatusPill, effectiveStatus } from "./ui";
import clsx from "./clsx";

export interface Place {
  label: string;
  lat: number;
  lng: number;
  stop_id?: number;
}

/* ------------------------------------------------------------------ place / stop search */
export function PlaceInput({
  value, onChange, placeholder, onLocate, locating, icon = "origin", onPickMap, picking,
}: {
  value: Place | null;
  onChange: (p: Place | null) => void;
  placeholder: string;
  onLocate?: () => void;
  locating?: boolean;
  icon?: "origin" | "destination";
  onPickMap?: () => void;
  picking?: boolean;
}) {
  const [q, setQ] = useState(value?.label || "");
  const [results, setResults] = useState<Stop[]>([]);
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => setQ(value?.label || ""), [value]);
  useEffect(() => {
    if (!open || q.trim().length < 2 || q === value?.label) {
      setResults([]);
      return;
    }
    const t = setTimeout(() => {
      api<Stop[]>(`/api/stops?q=${encodeURIComponent(q.trim())}&limit=8`).then(setResults).catch(() => setResults([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q, open, value]);
  useEffect(() => {
    const h = (e: MouseEvent) => box.current && !box.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  return (
    <div ref={box} className="relative">
      <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 focus-within:border-brand-500 focus-within:ring-2 focus-within:ring-brand-100">
        <span className={clsx("h-2.5 w-2.5 shrink-0 rounded-full", icon === "origin" ? "bg-emerald-500" : "bg-accent-500")} />
        <input
          className="w-full bg-transparent py-2.5 text-sm outline-none"
          placeholder={placeholder}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            if (!e.target.value) onChange(null);
          }}
          onFocus={() => setOpen(true)}
          aria-label={placeholder}
        />
        {onLocate && (
          <button type="button" onClick={onLocate} className="text-brand-600 hover:text-brand-800 p-1" title="Use my location" aria-label="Use my location">
            <LocateFixed className={clsx("h-4 w-4", locating && "animate-pulse")} />
          </button>
        )}
        {onPickMap && (
          <button type="button" onClick={onPickMap} className={clsx("p-1", picking ? "text-accent-500" : "text-brand-600 hover:text-brand-800")} title="Pick on map" aria-label="Pick on map">
            <MapPin className="h-4 w-4" />
          </button>
        )}
      </div>
      {open && results.length > 0 && (
        <ul className="absolute z-[1500] mt-1 w-full overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          {results.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-brand-50"
                onClick={() => {
                  onChange({ label: s.name, lat: s.lat, lng: s.lng, stop_id: s.id });
                  setOpen(false);
                }}
              >
                <MapPin className="h-4 w-4 text-brand-500" />
                <span className="flex-1">{s.name}</span>
                {s.is_demo && <DemoBadge />}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function GlobalSearch() {
  const [q, setQ] = useState("");
  const [res, setRes] = useState<{ stops: Stop[]; routes: RouteSummary[]; buses: { id: number; bus_number: string }[] } | null>(null);
  useEffect(() => {
    if (q.trim().length < 2) return setRes(null);
    const t = setTimeout(() => api<typeof res>(`/api/search?q=${encodeURIComponent(q.trim())}`).then(setRes).catch(() => setRes(null)), 200);
    return () => clearTimeout(t);
  }, [q]);
  const empty = res && !res.stops.length && !res.routes.length && !res.buses.length;
  return (
    <div className="relative">
      <div className="flex items-center gap-2 rounded-2xl bg-white px-4 shadow-card border border-slate-100">
        <Search className="h-5 w-5 text-slate-400" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search a bus stop, route or bus number"
          className="w-full bg-transparent py-3.5 text-sm outline-none"
          aria-label="Search"
        />
      </div>
      {res && (
        <div className="absolute z-[1500] mt-2 w-full rounded-2xl border border-slate-200 bg-white p-2 shadow-lg">
          {empty && <Empty>No stops, routes or buses match “{q}”.</Empty>}
          {res.stops.map((s) => (
            <Link key={`s${s.id}`} href={`/stop/?id=${s.id}`} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-brand-50">
              <MapPin className="h-4 w-4 text-brand-500" /> <span className="flex-1">{s.name}</span>
              <span className="text-xs text-slate-400">Stop</span>
            </Link>
          ))}
          {res.routes.map((r) => (
            <Link key={`r${r.id}`} href={`/route/?id=${r.id}`} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-brand-50">
              <span className="h-3 w-3 rounded-full" style={{ background: r.color }} /> <span className="flex-1">{r.name}</span>
              <span className="text-xs text-slate-400">Route</span>
            </Link>
          ))}
          {res.buses.map((b) => (
            <Link key={`b${b.id}`} href={`/live/?bus=${b.id}`} className="flex items-center gap-2 rounded-xl px-3 py-2 text-sm hover:bg-brand-50">
              <Bus className="h-4 w-4 text-brand-500" /> <span className="flex-1">{b.bus_number}</span>
              <span className="text-xs text-slate-400">Bus</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ route chip */
export function RouteChip({ code, color, className }: { code: string; color: string; className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-lg px-2 py-0.5 text-xs font-bold text-white", className)} style={{ background: color }}>
      {code}
    </span>
  );
}

/* ------------------------------------------------------------------ bus card */
export function BusRow({ b, routeCode, color, onClick, selected }: { b: BusState; routeCode?: string; color?: string; onClick?: () => void; selected?: boolean }) {
  const st = effectiveStatus(b);
  return (
    <button
      onClick={onClick}
      className={clsx(
        "flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition",
        selected ? "border-accent-400 bg-orange-50" : "border-slate-100 bg-white hover:bg-slate-50",
      )}
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-700 text-white">
        <Bus className="h-4 w-4" />
      </span>
      <span className="flex-1 min-w-0">
        <span className="flex flex-wrap items-center gap-1.5">
          <span className="font-semibold text-slate-800 whitespace-nowrap">{b.bus_number}</span>
          {routeCode && <RouteChip code={routeCode} color={color || "#173693"} className="whitespace-nowrap" />}
        </span>
        <span className="block truncate text-xs text-slate-500">
          {b.next_stop ? `Next: ${b.next_stop.name} · ${km(b.next_stop.distance_m)}` : "No active trip"}
        </span>
      </span>
      <span className="text-right">
        <StatusPill status={st} />
        <span className="mt-0.5 block text-[11px] text-slate-400">GPS {ago(b.last_gps_at)}</span>
      </span>
    </button>
  );
}

/* ------------------------------------------------------------------ bus detail */
interface BusDetail extends BusState {
  route: RouteSummary | null;
  upcoming_stops: { stop_id: number; name: string; distance_m: number; minutes: number | null; kind: string }[];
}

export function BusDetailPanel({ bus, onClose }: { bus: BusState; onClose?: () => void }) {
  const { data, loading, error, reload } = useApi<BusDetail>(`/api/buses/${bus.bus_id}`, [bus.last_gps_at]);
  const st = effectiveStatus(bus);
  const live = st === "active" || st === "delayed";
  return (
    <div>
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <h3 className="text-lg font-bold text-brand-900">Bus {bus.bus_number}</h3>
            {bus.is_demo && <DemoBadge />}
          </div>
          {data?.route && <p className="text-sm text-slate-500">{data.route.name}</p>}
        </div>
        {onClose && (
          <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Close">
            ✕
          </button>
        )}
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-surface p-2">
          <div className="text-[11px] text-slate-500">Status</div>
          <div className="mt-1"><StatusPill status={st} /></div>
        </div>
        <div className="rounded-xl bg-surface p-2">
          <div className="text-[11px] text-slate-500">Speed</div>
          <div className="font-semibold text-slate-800">{live && bus.speed_kmh != null ? `${Math.round(bus.speed_kmh)} km/h` : "–"}</div>
        </div>
        <div className="rounded-xl bg-surface p-2">
          <div className="text-[11px] text-slate-500">Last GPS</div>
          <div className="font-semibold text-slate-800">{ago(bus.last_gps_at)}</div>
        </div>
      </div>
      {st === "stale" && (
        <p className="mt-3 rounded-xl bg-slate-100 p-2 text-xs text-slate-600">
          No GPS update for over a minute. The marker shows the last known position; the bus may have moved.
        </p>
      )}
      {bus.delay_minutes != null && bus.delay_minutes >= 5 && live && (
        <p className="mt-3 rounded-xl bg-amber-50 p-2 text-xs text-amber-700">Running about {Math.round(bus.delay_minutes)} min behind schedule.</p>
      )}
      <h4 className="mt-4 mb-2 text-sm font-semibold text-slate-700">Upcoming stops</h4>
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && data.upcoming_stops.length === 0 && <Empty>No upcoming stops (bus is not on an active trip).</Empty>}
      <ol className="space-y-1">
        {data?.upcoming_stops.slice(0, 8).map((s, i) => (
          <li key={s.stop_id}>
            <Link href={`/stop/?id=${s.stop_id}`} className="flex items-center gap-3 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50">
              <span className={clsx("h-2.5 w-2.5 rounded-full border-2", i === 0 ? "border-accent-500 bg-accent-500" : "border-brand-600 bg-white")} />
              <span className="flex-1">{s.name}</span>
              <span className="text-xs text-slate-400">{km(s.distance_m)}</span>
              <span className="w-16 text-right font-semibold text-brand-700">
                {s.minutes != null && live ? (s.minutes <= 0 ? "Now" : `${s.minutes} min`) : "–"}
              </span>
            </Link>
          </li>
        ))}
      </ol>
    </div>
  );
}

/* ------------------------------------------------------------------ arrivals */
export function ArrivalsList({ stopId, routeId, compact }: { stopId: number; routeId?: number; compact?: boolean }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 15000);
    return () => clearInterval(t);
  }, []);
  const { data, loading, error, reload } = useApi<Arrivals>(`/api/stops/${stopId}/arrivals${routeId ? `?route_id=${routeId}` : ""}`, [tick]);
  if (loading && !data) return <Spinner label="Checking arrivals…" />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  const live = data.live.slice(0, compact ? 3 : 8);
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-emerald-700">
          <Radio className="h-3.5 w-3.5" /> Live GPS estimates
        </div>
        {live.length === 0 && <p className="text-sm text-slate-500">No bus with a current GPS signal is heading here right now.</p>}
        <ul className="space-y-1.5">
          {live.map((a) => (
            <li key={a.trip_id} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-white px-3 py-2">
              <Bus className="h-4 w-4 text-brand-600" />
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                  {a.bus_number} <span className="text-xs font-normal text-slate-500 truncate">{a.route_code}</span>
                  {a.is_demo && <DemoBadge />}
                </div>
                <div className="text-xs text-slate-500">
                  {km(a.distance_m)} away · GPS {ago(a.last_gps_at)}
                </div>
              </div>
              <div className="text-right">
                <div className="text-lg font-bold text-brand-700">{a.minutes <= 0 ? "Now" : `${a.minutes} min`}</div>
                <div className="text-[11px] text-slate-400">{clock(a.eta)}</div>
              </div>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="mb-1.5 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
          <Clock className="h-3.5 w-3.5" /> Scheduled (timetable, not live)
        </div>
        {data.scheduled.length === 0 && <p className="text-sm text-slate-500">No more scheduled departures today.</p>}
        <div className="flex flex-wrap gap-2">
          {data.scheduled.slice(0, compact ? 4 : 6).map((a, i) => (
            <span key={i} className="rounded-lg bg-slate-100 px-2.5 py-1 text-xs text-slate-600">
              <b>{a.route_code}</b> {clock(a.eta)} <span className="text-slate-400">({a.minutes} min)</span>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function NavLinkCard({ href, icon: Icon, title, text }: { href: string; icon: typeof Navigation; title: string; text: string }) {
  return (
    <Link href={href} className="flex items-center gap-3 rounded-xl2 border border-slate-100 bg-white p-4 shadow-card hover:border-brand-200">
      <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-50 text-brand-700">
        <Icon className="h-5 w-5" />
      </span>
      <span>
        <span className="block font-semibold text-slate-800">{title}</span>
        <span className="block text-xs text-slate-500">{text}</span>
      </span>
    </Link>
  );
}
