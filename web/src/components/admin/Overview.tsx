"use client";

import { Card, ErrorBox, PageHeader, SectionTitle, Spinner } from "../ui";
import MapView from "../MapView";
import { Stat } from "./common";
import { useApi, useLiveBuses } from "@/lib/hooks";
import type { Alert } from "@/lib/types";

interface OverviewData {
  demo_mode: boolean;
  total_buses: number;
  active_buses: number;
  inactive_buses: number;
  stale_or_offline: number;
  delayed_buses: number;
  total_routes: number;
  total_stops: number;
  total_drivers: number;
  active_drivers: number;
  ongoing_trips: number;
  passengers: number;
  alerts: Alert[];
}

export function Overview() {
  const { data, loading, error, reload } = useApi<OverviewData>("/api/admin/overview");
  const { buses } = useLiveBuses();
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox error={error} onRetry={reload} />;
  if (!data) return null;
  return (
    <div>
      <PageHeader title="Overview" subtitle="Network status right now" action={<button onClick={reload} className="text-sm text-brand-600">Refresh</button>} />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Total registered buses" value={data.total_buses} />
        <Stat label="Active buses" value={data.active_buses} tone="green" />
        <Stat label="Inactive buses" value={data.inactive_buses} tone="slate" />
        <Stat label="Stale / offline GPS" value={data.stale_or_offline} tone="amber" />
        <Stat label="Total routes" value={data.total_routes} />
        <Stat label="Total stops" value={data.total_stops} />
        <Stat label="Active drivers" value={`${data.active_drivers} / ${data.total_drivers}`} tone="green" />
        <Stat label="Ongoing trips" value={data.ongoing_trips} />
      </div>
      <div className="mt-6 grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2 h-[380px] overflow-hidden"><MapView buses={buses} /></Card>
        <Card className="p-5">
          <SectionTitle>Current service alerts</SectionTitle>
          {data.alerts.length === 0 && <p className="text-sm text-slate-500">No active alerts.</p>}
          <ul className="space-y-2">
            {data.alerts.map((a) => (
              <li key={a.id} className="rounded-xl border border-slate-100 p-3 text-sm">
                <span className={`mr-2 rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${a.severity === "disruption" ? "bg-red-100 text-red-700" : a.severity === "warning" ? "bg-amber-100 text-amber-700" : "bg-brand-50 text-brand-700"}`}>{a.severity}</span>
                <b>{a.title}</b>
                <p className="text-slate-600">{a.message}</p>
              </li>
            ))}
          </ul>
          <div className="mt-4 text-sm text-slate-500">Delayed buses: <b className="text-amber-700">{data.delayed_buses}</b> · Registered passengers: <b>{data.passengers}</b></div>
        </Card>
      </div>
    </div>
  );
}
