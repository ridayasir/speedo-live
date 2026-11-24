"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents, type MarkerProps } from "react-leaflet";
import { api } from "@/lib/api";
import { stopColor } from "@/lib/format";
import type { BusState, RouteDetail, Stop } from "@/lib/types";
import { effectiveStatus } from "./ui";

export interface MapRoute {
  id: number;
  color: string;
  path: [number, number][];
  code?: string;
  dim?: boolean;
  weight?: number;
  /** label shown on hover/tap (route code), so lines are not told apart by colour alone */
  label?: string;
}

/** A stop that matters for the planned trip, drawn with a lettered badge (not colour alone). */
export interface TripStop {
  id: number;
  lat: number;
  lng: number;
  name: string;
  role: "board" | "transfer" | "alight";
}

export interface MapProps {
  buses?: BusState[];
  routes?: MapRoute[];
  stops?: Stop[];
  highlightStopIds?: number[];
  selectedBusId?: number | null;
  onBusClick?: (b: BusState) => void;
  onStopClick?: (s: Stop) => void;
  onMapClick?: (lat: number, lng: number) => void;
  points?: { lat: number; lng: number; label: string; kind: "origin" | "destination" | "me" }[];
  fitKey?: string;
  className?: string;
  center?: [number, number];
  zoom?: number;
  /** walking parts of a trip, drawn dashed */
  walks?: [number, number][][];
  tripStops?: TripStop[];
  selectedStopId?: number | null;
  /** pan/zoom to this point whenever key changes */
  focus?: { lat: number; lng: number; key: string } | null;
}

const LAHORE: [number, number] = [31.5204, 74.3587];

// Buses take their route's colour (as on the map lines); only lost-signal and out-of-service buses are grey.
const STATUS_COLOR: Record<string, string> = {
  stale: "#94a3b8",
  offline: "#94a3b8",
  out_of_service: "#475569",
};

// stop id -> the routes that serve it, loaded once and shared by every map: stops take their route's colour,
// and a stop served by several routes (where people change buses) gets a dark ring and says so
type StopRoute = { id: number; code: string; color: string };
let stopRouteCache: Record<number, StopRoute[]> | null = null;
let stopRouteLoad: Promise<Record<number, StopRoute[]>> | null = null;
function useStopRoutes(): Record<number, StopRoute[]> {
  const [m, setM] = useState<Record<number, StopRoute[]>>(stopRouteCache || {});
  useEffect(() => {
    if (stopRouteCache) return;
    stopRouteLoad ??= api<RouteDetail[]>("/api/routes?with_path=true")
      .then((rs) => {
        const out: Record<number, StopRoute[]> = {};
        for (const r of rs) for (const st of r.stops || []) {
          (out[st.id] ??= []).some((x) => x.id === r.id) || out[st.id].push({ id: r.id, code: r.code, color: r.color });
        }
        return (stopRouteCache = out);
      })
      .catch(() => ({}));
    stopRouteLoad.then(setM);
  }, []);
  return m;
}

const BUS_RED = "#dc2626";
/** How long a bus takes to glide to its new position: about the time between two location updates. */
export const BUS_GLIDE_MS = 4800;

/**
 * A bus marker that drives smoothly from its last position to the new one instead of jumping, so buses are seen
 * moving between location updates. Very long jumps (a lost signal coming back) are not animated.
 */
function MovingMarker({ lat, lng, children, ...rest }: { lat: number; lng: number; children?: React.ReactNode } & Omit<MarkerProps, "position">) {
  const ref = useRef<L.Marker | null>(null);
  const first = useRef<[number, number]>([lat, lng]);
  useEffect(() => {
    const m = ref.current;
    if (!m) return;
    const from = m.getLatLng();
    const to = L.latLng(lat, lng);
    if (from.equals(to)) return;
    if (from.distanceTo(to) > 1500 || typeof requestAnimationFrame === "undefined") {
      m.setLatLng(to);
      return;
    }
    const t0 = performance.now();
    let raf = 0;
    const step = (t: number) => {
      const k = Math.min(1, (t - t0) / BUS_GLIDE_MS);
      m.setLatLng([from.lat + (to.lat - from.lat) * k, from.lng + (to.lng - from.lng) * k]);
      if (k < 1) raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf); // a newer position arrived: the next glide starts from here
  }, [lat, lng]);
  return <Marker ref={ref} position={first.current} {...rest}>{children}</Marker>;
}

function busIcon(b: BusState, selected: boolean) {
  const st = effectiveStatus(b);
  // every bus is Speedo red; only lost-signal / out-of-service buses are grey (the route is in the popup/list)
  const color = STATUS_COLOR[st] || BUS_RED;
  const ring = selected ? "3px solid #111827" : st === "delayed" ? "3px solid #f59e0b" : "2px solid white";
  const rot = b.heading ?? 0;
  const faded = st === "stale" || st === "offline";
  return L.divIcon({
    className: "",
    iconSize: [44, 44],
    iconAnchor: [22, 22],
    html: `
      <div style="position:relative;width:44px;height:44px;opacity:${faded ? 0.6 : 1}">
        ${!faded && b.heading != null ? `<div style="position:absolute;inset:0;transform:rotate(${rot}deg)"><div style="position:absolute;left:18px;top:-2px;width:0;height:0;border-left:4px solid transparent;border-right:4px solid transparent;border-bottom:8px solid ${color}"></div></div>` : ""}
        <div style="position:absolute;left:8px;top:8px;width:28px;height:28px;border-radius:9px;background:${color};
          border:${ring};box-shadow:0 2px 6px rgba(0,0,0,.3);
          display:flex;align-items:center;justify-content:center">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6v6"/><path d="M15 6v6"/><path d="M2 12h19.6"/><path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"/><circle cx="7" cy="18" r="2"/><path d="M9 18h5"/><circle cx="16" cy="18" r="2"/></svg>
        </div>
      </div>`,
  });
}

function pointIcon(kind: string) {
  const color = kind === "origin" ? "#16a34a" : kind === "destination" ? "#f59e0b" : "#2563eb";
  return L.divIcon({
    className: "",
    iconSize: [22, 22],
    iconAnchor: [11, 11],
    html: `<div style="width:22px;height:22px;border-radius:50%;background:${color};border:3px solid white;box-shadow:0 1px 5px rgba(0,0,0,.35)"></div>`,
  });
}

function Fit({ fitKey, routes, points, stops }: { fitKey?: string; routes?: MapRoute[]; points?: MapProps["points"]; stops?: Stop[] }) {
  const map = useMap();
  useEffect(() => {
    if (!fitKey) return;
    const coords: [number, number][] = [];
    routes?.filter((r) => !r.dim).forEach((r) => coords.push(...r.path));
    points?.forEach((p) => coords.push([p.lat, p.lng]));
    if (!coords.length) stops?.forEach((s) => coords.push([s.lat, s.lng]));
    if (coords.length > 1) map.fitBounds(L.latLngBounds(coords), { padding: [40, 40], maxZoom: 15 });
    else if (coords.length === 1) map.setView(coords[0], 15);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fitKey]);
  return null;
}

const ROLE = {
  board: { letter: "B", color: "#15803d", text: "Get on here" },
  transfer: { letter: "T", color: "#7c3aed", text: "Change bus here" },
  alight: { letter: "A", color: "#c2410c", text: "Get off here" },
} as const;

function tripStopIcon(role: TripStop["role"], selected: boolean) {
  const r = ROLE[role];
  const size = selected ? 30 : 24;
  return L.divIcon({
    className: "",
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    html: `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${r.color};color:white;font:700 ${selected ? 14 : 12}px/1 system-ui,sans-serif;display:flex;align-items:center;justify-content:center;border:${selected ? "3px solid #111827" : "2px solid white"};box-shadow:0 1px 5px rgba(0,0,0,.4)">${r.letter}</div>`,
  });
}

function Focus({ focus }: { focus?: MapProps["focus"] }) {
  const map = useMap();
  useEffect(() => {
    if (focus) map.setView([focus.lat, focus.lng], Math.max(map.getZoom(), 16), { animate: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focus?.key]);
  return null;
}

function ClickHandler({ onMapClick }: { onMapClick?: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onMapClick?.(e.latlng.lat, e.latlng.lng) });
  return null;
}

export default function LeafletMap(props: MapProps) {
  const { buses = [], routes = [], stops = [], highlightStopIds = [], selectedBusId, onBusClick, onStopClick, onMapClick, points = [],
    walks = [], tripStops = [], selectedStopId = null } = props;
  const tripIds = useMemo(() => new Set(tripStops.map((t) => t.id)), [tripStops]);
  const stopRoutes = useStopRoutes();
  const hl = useMemo(() => new Set(highlightStopIds), [highlightStopIds]);
  return (
    <MapContainer
      center={props.center || LAHORE}
      zoom={props.zoom || 12}
      className={props.className || "h-full w-full"}
      scrollWheelZoom
      attributionControl
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />
      <ClickHandler onMapClick={onMapClick} />
      <Fit fitKey={props.fitKey} routes={routes} points={points} stops={stops} />
      <Focus focus={props.focus} />
      {routes.map((r) => (
        <Polyline
          key={`r-${r.id}`}
          positions={r.path}
          pathOptions={{ color: r.color, weight: r.weight ?? (r.dim ? 3 : 6), opacity: r.dim ? 0.35 : 0.85 }}
        >
          {r.label && <Tooltip sticky>{r.label}</Tooltip>}
        </Polyline>
      ))}
      {walks.map((w, i) => (
        <Polyline key={`w-${i}`} positions={w} pathOptions={{ color: "#334155", weight: 4, opacity: 0.9, dashArray: "2 9", lineCap: "round" }}>
          <Tooltip sticky>Walk (straight line, estimate)</Tooltip>
        </Polyline>
      ))}
      {stops.filter((s) => !tripIds.has(s.id)).map((s) => {
        const rs = stopRoutes[s.id] || [];
        const change = rs.length > 1;
        const sel = s.id === selectedStopId, lit = hl.has(s.id);
        const r = sel ? 9 : lit ? 8 : change ? 6.5 : 5;
        return (
          <Fragment key={`s-${s.id}`}>
            {change && (
              <CircleMarker center={[s.lat, s.lng]} radius={r + 3} interactive={false}
                pathOptions={{ color: "#111827", weight: 2, fillOpacity: 0 }} />
            )}
            <CircleMarker
              center={[s.lat, s.lng]}
              radius={r}
              pathOptions={{ color: sel ? "#111827" : lit ? "#f59e0b" : "white", fillColor: stopColor(s.id), fillOpacity: 1, weight: lit || sel ? 4 : 2 }}
              eventHandlers={{ click: () => onStopClick?.(s) }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                {s.name}
                {rs.length > 0 && (
                  <span style={{ display: "block", fontSize: 11, color: "#475569" }}>
                    {change ? `Change here · ${rs.length} routes: ` : "Route: "}
                    {rs.slice(0, 4).map((x) => x.code).join(", ")}{rs.length > 4 ? "…" : ""}
                  </span>
                )}
              </Tooltip>
            </CircleMarker>
          </Fragment>
        );
      })}
      {tripStops.map((t) => (
        <Marker key={`t-${t.role}-${t.id}`} position={[t.lat, t.lng]} icon={tripStopIcon(t.role, t.id === selectedStopId)}
          zIndexOffset={t.id === selectedStopId ? 900 : 500}
          eventHandlers={{ click: () => onStopClick?.({ id: t.id, name: t.name, lat: t.lat, lng: t.lng } as Stop) }}>
          <Tooltip direction="top" offset={[0, -12]}>{ROLE[t.role].text}: {t.name}</Tooltip>
        </Marker>
      ))}
      {points.map((p, i) => (
        <Marker key={`p-${i}`} position={[p.lat, p.lng]} icon={pointIcon(p.kind)}>
          <Tooltip permanent={p.kind !== "me"} direction="top" offset={[0, -10]}>{p.label}</Tooltip>
        </Marker>
      ))}
      {buses
        .filter((b) => b.lat != null && b.lng != null)
        .map((b) => (
          <MovingMarker
            key={`b-${b.bus_id}`}
            lat={b.lat as number}
            lng={b.lng as number}
            icon={busIcon(b, b.bus_id === selectedBusId)}
            eventHandlers={{ click: () => onBusClick?.(b) }}
            zIndexOffset={b.bus_id === selectedBusId ? 1000 : 0}
          >
            {!onBusClick && (
              <Popup>
                <b>{b.bus_number}</b>
                {b.next_stop && <div>Next: {b.next_stop.name}</div>}
              </Popup>
            )}
          </MovingMarker>
        ))}
    </MapContainer>
  );
}
