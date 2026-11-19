"use client";

import { Suspense, useMemo, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import MapView from "@/components/MapView";
import { Card, Empty, Select, Spinner, effectiveStatus } from "@/components/ui";
import { BusDetailPanel, BusRow } from "@/components/widgets";
import { useApi, useLiveBuses } from "@/lib/hooks";
import type { RouteDetail } from "@/lib/types";

function LiveInner() {
  const params = useSearchParams();
  const router = useRouter();
  const routeParam = params.get("route");
  const busParam = params.get("bus");
  const [routeId, setRouteId] = useState<number | null>(routeParam ? Number(routeParam) : null);
  const [selected, setSelected] = useState<number | null>(busParam ? Number(busParam) : null);
  const [statusFilter, setStatusFilter] = useState("all");
  const routes = useApi<RouteDetail[]>("/api/routes?with_path=true");
  const { buses, conn } = useLiveBuses();

  useEffect(() => {
    const q = new URLSearchParams();
    if (routeId) q.set("route", String(routeId));
    if (selected) q.set("bus", String(selected));
    router.replace(`/live/${q.toString() ? "?" + q.toString() : ""}`, { scroll: false });
  }, [routeId, selected, router]);

  const routeById = useMemo(() => Object.fromEntries((routes.data || []).map((r) => [r.id, r])), [routes.data]);
  const shown = buses
    .filter((b) => !routeId || b.route_id === routeId)
    .filter((b) => statusFilter === "all" || effectiveStatus(b) === statusFilter)
    .sort((a, b) => a.bus_number.localeCompare(b.bus_number));
  const sel = buses.find((b) => b.bus_id === selected) || null;
  const mapRoutes = (routes.data || [])
    .filter((r) => !routeId || r.id === routeId || (sel && sel.route_id === r.id))
    .map((r) => ({ id: r.id, color: r.color, path: r.path, dim: !!routeId && r.id !== routeId && !(sel && sel.route_id === r.id) }));
  const focusRoute = routeId ? routeById[routeId] : sel?.route_id ? routeById[sel.route_id] : null;

  return (
    <div className="flex flex-col md:flex-row md:h-[calc(100vh-4rem-2rem)]">
      <div className="h-[55vh] md:h-full md:flex-1 relative">
        <MapView
          buses={shown}
          routes={mapRoutes}
          stops={focusRoute?.stops || []}
          selectedBusId={selected}
          onBusClick={(b) => setSelected(b.bus_id)}
          onStopClick={(s) => router.push(`/stop/?id=${s.id}`)}
          fitKey={routeId ? `r${routeId}` : undefined}
        />
        <div className="absolute left-3 top-3 z-[1000] rounded-full bg-white/95 px-3 py-1 text-xs shadow-card">
          <span className={`mr-1.5 inline-block h-2 w-2 rounded-full ${conn === "live" ? "bg-emerald-500 animate-pulse" : "bg-slate-400"}`} />
          {conn === "live" ? "Live updates" : conn === "connecting" ? "Connecting…" : "Reconnecting (showing last known data)"}
        </div>
      </div>
      <aside className="md:w-[380px] md:border-l border-slate-200 bg-surface md:overflow-y-auto scrollbar-thin p-4 space-y-4">
        {sel ? (
          <Card className="p-4">
            <BusDetailPanel bus={sel} onClose={() => setSelected(null)} />
          </Card>
        ) : null}
        <Card className="p-4 space-y-3">
          <h1 className="text-lg font-bold text-brand-900">Live Tracking</h1>
          <div className="grid grid-cols-2 gap-2">
            <Select value={routeId ?? ""} onChange={(e) => setRouteId(e.target.value ? Number(e.target.value) : null)} aria-label="Filter by route">
              <option value="">All routes</option>
              {routes.data?.map((r) => (
                <option key={r.id} value={r.id}>{r.code}</option>
              ))}
            </Select>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Filter by status">
              <option value="all">Any status</option>
              <option value="active">On route</option>
              <option value="delayed">Delayed</option>
              <option value="stale">GPS signal lost</option>
              <option value="offline">Offline</option>
              <option value="idle">Not on a trip</option>
              <option value="out_of_service">Out of service</option>
            </Select>
          </div>
          {routeId && routeById[routeId] && <p className="text-sm text-slate-600">{routeById[routeId].name}</p>}
          {conn === "connecting" && buses.length === 0 && <Spinner label="Connecting to live feed…" />}
          {conn !== "connecting" && shown.length === 0 && <Empty>No buses match these filters.</Empty>}
          <div className="space-y-2">
            {shown.map((b) => (
              <BusRow
                key={b.bus_id}
                b={b}
                routeCode={b.route_id ? routeById[b.route_id]?.code : undefined}
                color={b.route_id ? routeById[b.route_id]?.color : undefined}
                selected={b.bus_id === selected}
                onClick={() => setSelected(b.bus_id)}
              />
            ))}
          </div>
        </Card>
      </aside>
    </div>
  );
}

export default function LivePage() {
  return (
    <Suspense fallback={<Spinner />}>
      <LiveInner />
    </Suspense>
  );
}
