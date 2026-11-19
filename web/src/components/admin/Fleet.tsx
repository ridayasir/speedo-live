"use client";

import { useEffect, useState } from "react";
import MapView from "../MapView";
import { Button, Card, DemoBadge, ErrorBox, PageHeader, StatusPill, effectiveStatus } from "../ui";
import { api } from "@/lib/api";
import { ago, km, useLiveBuses } from "@/lib/hooks";
import type { BusState } from "@/lib/types";

interface FleetBus extends BusState {
  route_code: string | null;
  route_name: string | null;
  assigned_driver: { id: number; name: string; phone: string | null } | null;
  trip: { id: number; status: string; started_at: string; progress_m: number; route_length_m: number; gps_points: number; source: string } | null;
}

export function FleetAdmin() {
  const { buses: live, conn } = useLiveBuses();
  const [fleet, setFleet] = useState<Record<number, FleetBus>>({});
  const [selected, setSelected] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const load = () =>
    api<{ buses: FleetBus[] }>("/api/admin/fleet")
      .then((r) => setFleet(Object.fromEntries(r.buses.map((b) => [b.bus_id, b]))))
      .catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, []);
  // merge live positions with admin-only details
  const merged: FleetBus[] = live.map((b) => ({ ...(fleet[b.bus_id] || ({} as FleetBus)), ...b }));
  const sel = merged.find((b) => b.bus_id === selected);
  const endTrip = async (tripId: number) => {
    if (!confirm("End this trip now? The bus will stop showing as on route.")) return;
    await api(`/api/admin/trips/${tripId}/end`, { method: "POST" });
    load();
  };
  return (
    <div>
      <PageHeader title="Live fleet" subtitle={conn === "live" ? "Live updates connected" : "Reconnecting to live feed…"} />
      {err && <ErrorBox error={err} />}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2 h-[560px] overflow-hidden">
          <MapView buses={merged} selectedBusId={selected} onBusClick={(b) => setSelected(b.bus_id)} />
        </Card>
        <div className="space-y-3">
          {sel ? (
            <Card className="p-4 space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <h3 className="text-lg font-bold text-brand-900">{sel.bus_number} {sel.is_demo && <DemoBadge />}</h3>
                <button onClick={() => setSelected(null)} className="text-slate-400" aria-label="Close">✕</button>
              </div>
              <StatusPill status={effectiveStatus(sel)} />
              <dl className="grid grid-cols-2 gap-y-1.5 text-slate-600">
                <dt>Position</dt><dd className="text-right font-mono text-xs">{sel.lat?.toFixed(5)}, {sel.lng?.toFixed(5)}</dd>
                <dt>Route</dt><dd className="text-right">{sel.route_code || "–"}</dd>
                <dt>Driver</dt><dd className="text-right">{sel.assigned_driver?.name || (sel.is_demo ? "Simulated" : "–")}</dd>
                <dt>Driver phone</dt><dd className="text-right">{sel.assigned_driver?.phone || "–"}</dd>
                <dt>Last GPS</dt><dd className="text-right">{ago(sel.last_gps_at)}</dd>
                <dt>GPS link</dt><dd className="text-right capitalize">{sel.gps}</dd>
                <dt>Accuracy</dt><dd className="text-right">{sel.accuracy_m != null ? `${Math.round(sel.accuracy_m)} m` : "–"}</dd>
                <dt>Trip</dt><dd className="text-right">{sel.trip ? `#${sel.trip.id} (${sel.trip.source})` : "None"}</dd>
                {sel.trip && <><dt>Progress</dt><dd className="text-right">{km(sel.trip.progress_m)} / {km(sel.trip.route_length_m)}</dd></>}
                <dt>Next stop</dt><dd className="text-right">{sel.next_stop?.name || "–"}</dd>
                <dt>Delay</dt><dd className="text-right">{sel.delay_minutes != null ? `${Math.round(sel.delay_minutes)} min` : "–"}</dd>
              </dl>
              {sel.trip && <Button size="sm" variant="outline" onClick={() => endTrip(sel.trip!.id)}>End trip</Button>}
            </Card>
          ) : (
            <Card className="p-4 text-sm text-slate-500">Select a bus on the map or in the list.</Card>
          )}
          <Card className="max-h-[400px] overflow-y-auto scrollbar-thin divide-y divide-slate-100">
            {merged.sort((a, b) => a.bus_number.localeCompare(b.bus_number)).map((b) => (
              <button key={b.bus_id} onClick={() => setSelected(b.bus_id)} className={`flex w-full items-center justify-between px-4 py-2 text-left text-sm hover:bg-slate-50 ${b.bus_id === selected ? "bg-orange-50" : ""}`}>
                <span><b>{b.bus_number}</b> <span className="text-xs text-slate-400">{b.route_code}</span></span>
                <StatusPill status={effectiveStatus(b)} />
              </button>
            ))}
          </Card>
        </div>
      </div>
    </div>
  );
}
