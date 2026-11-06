"use client";

import "leaflet/dist/leaflet.css";
import L from "leaflet";
import { useEffect, useMemo } from "react";
import { CircleMarker, MapContainer, Marker, Polyline, Popup, TileLayer, Tooltip, useMap, useMapEvents } from "react-leaflet";
import type { BusState, Stop } from "@/lib/types";
import { effectiveStatus } from "./ui";

export interface MapRoute {
  id: number;
  color: string;
  path: [number, number][];
  code?: string;
  dim?: boolean;
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
}

const LAHORE: [number, number] = [31.5204, 74.3587];

const STATUS_COLOR: Record<string, string> = {
  active: "#173693",
  delayed: "#d97706",
  stale: "#94a3b8",
  offline: "#94a3b8",
  idle: "#0284c7",
  out_of_service: "#dc2626",
};

function busIcon(b: BusState, selected: boolean) {
  const st = effectiveStatus(b);
  const color = STATUS_COLOR[st] || "#173693";
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
          border:${selected ? "3px solid #f97316" : "2px solid white"};box-shadow:0 2px 6px rgba(0,0,0,.3);
          display:flex;align-items:center;justify-content:center">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6v6"/><path d="M15 6v6"/><path d="M2 12h19.6"/><path d="M18 18h3s.5-1.7.8-2.8c.1-.4.2-.8.2-1.2 0-.4-.1-.8-.2-1.2l-1.4-5C20.1 6.8 19.1 6 18 6H4a2 2 0 0 0-2 2v10h3"/><circle cx="7" cy="18" r="2"/><path d="M9 18h5"/><circle cx="16" cy="18" r="2"/></svg>
        </div>
        ${b.is_demo ? `<div style="position:absolute;right:-2px;top:0;background:#f97316;color:white;font:700 7px/1 sans-serif;padding:2px 3px;border-radius:4px">DEMO</div>` : ""}
      </div>`,
  });
}

function pointIcon(kind: string) {
  const color = kind === "origin" ? "#16a34a" : kind === "destination" ? "#f97316" : "#2563eb";
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

function ClickHandler({ onMapClick }: { onMapClick?: (lat: number, lng: number) => void }) {
  useMapEvents({ click: (e) => onMapClick?.(e.latlng.lat, e.latlng.lng) });
  return null;
}

export default function LeafletMap(props: MapProps) {
  const { buses = [], routes = [], stops = [], highlightStopIds = [], selectedBusId, onBusClick, onStopClick, onMapClick, points = [] } = props;
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
      {routes.map((r) => (
        <Polyline
          key={`r-${r.id}`}
          positions={r.path}
          pathOptions={{ color: r.color, weight: r.dim ? 3 : 6, opacity: r.dim ? 0.35 : 0.85 }}
        />
      ))}
      {stops.map((s) => (
        <CircleMarker
          key={`s-${s.id}`}
          center={[s.lat, s.lng]}
          radius={hl.has(s.id) ? 8 : 5}
          pathOptions={{ color: hl.has(s.id) ? "#f97316" : "#173693", fillColor: "white", fillOpacity: 1, weight: hl.has(s.id) ? 4 : 2.5 }}
          eventHandlers={{ click: () => onStopClick?.(s) }}
        >
          <Tooltip direction="top" offset={[0, -6]}>{s.name}</Tooltip>
        </CircleMarker>
      ))}
      {points.map((p, i) => (
        <Marker key={`p-${i}`} position={[p.lat, p.lng]} icon={pointIcon(p.kind)}>
          <Tooltip permanent={p.kind !== "me"} direction="top" offset={[0, -10]}>{p.label}</Tooltip>
        </Marker>
      ))}
      {buses
        .filter((b) => b.lat != null && b.lng != null)
        .map((b) => (
          <Marker
            key={`b-${b.bus_id}`}
            position={[b.lat as number, b.lng as number]}
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
          </Marker>
        ))}
    </MapContainer>
  );
}
