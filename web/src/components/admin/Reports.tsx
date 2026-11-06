"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { Card, ErrorBox, PageHeader, SectionTitle, Select, Spinner } from "../ui";
import { DataTable, Stat } from "./common";
import { download } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";
import type { Alert } from "@/lib/types";

interface TripRow { id: number; bus_number: string; route_code: string; started_at: string; status: string; max_delay_minutes: number; end_reason: string | null }
interface Report {
  daily_trips: { date: string; trips: number; completed: number; interrupted: number; delayed: number }[];
  bus_activity: { bus_number: string; trips: number; km: number; hours: number; gps_points: number; gps_availability_pct: number | null }[];
  route_usage: { route_code: string; route_name: string; trips: number; journeys: number; delayed_trips: number }[];
  delayed_trips: TripRow[];
  service_interruptions: { interrupted_trips: TripRow[]; alerts: Alert[] };
  summary: { trips: number; delayed: number; interrupted: number; alerts: number };
}

function Csv({ section, days }: { section: string; days: number }) {
  return (
    <button onClick={() => download(`/api/admin/reports/${section}.csv?days=${days}`, `${section}_${days}d.csv`)} className="inline-flex items-center gap-1 text-xs text-brand-600">
      <Download className="h-3.5 w-3.5" /> CSV
    </button>
  );
}

export function ReportsAdmin() {
  const [days, setDays] = useState(7);
  const { data, loading, error, reload } = useApi<Report>(`/api/admin/reports?days=${days}`);
  const maxTrips = Math.max(1, ...(data?.daily_trips.map((d) => d.trips) || [1]));
  return (
    <div>
      <PageHeader title="Reports" action={
        <Select value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Period" className="w-40">
          <option value={1}>Last 24 hours</option><option value={7}>Last 7 days</option><option value={30}>Last 30 days</option><option value={90}>Last 90 days</option>
        </Select>
      } />
      {loading && !data && <Spinner />}
      {error && <ErrorBox error={error} onRetry={reload} />}
      {data && (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="Trips" value={data.summary.trips} />
            <Stat label="Delayed trips" value={data.summary.delayed} tone="amber" />
            <Stat label="Interrupted trips" value={data.summary.interrupted} tone="red" />
            <Stat label="Service alerts" value={data.summary.alerts} tone="slate" />
          </div>
          <Card className="p-5">
            <SectionTitle action={<Csv section="daily_trips" days={days} />}>Daily trips</SectionTitle>
            <div className="space-y-1.5">
              {data.daily_trips.map((d) => (
                <div key={d.date} className="flex items-center gap-3 text-sm">
                  <span className="w-24 text-slate-500">{d.date}</span>
                  <div className="flex-1 h-5 rounded bg-slate-100 overflow-hidden flex">
                    <div className="h-full bg-brand-600" style={{ width: `${(d.completed / maxTrips) * 100}%` }} title={`${d.completed} completed`} />
                    <div className="h-full bg-red-400" style={{ width: `${(d.interrupted / maxTrips) * 100}%` }} title={`${d.interrupted} interrupted`} />
                    <div className="h-full bg-brand-200" style={{ width: `${((d.trips - d.completed - d.interrupted) / maxTrips) * 100}%` }} title="in progress" />
                  </div>
                  <span className="w-28 text-right text-xs text-slate-600">{d.trips} trips · {d.delayed} late</span>
                </div>
              ))}
              {data.daily_trips.length === 0 && <p className="text-sm text-slate-500">No trips in this period.</p>}
            </div>
            <p className="mt-2 text-xs text-slate-400">Dark blue: completed · red: interrupted · light: in progress</p>
          </Card>
          <div>
            <SectionTitle action={<Csv section="bus_activity" days={days} />}>Bus activity and GPS availability</SectionTitle>
            <DataTable rows={data.bus_activity} rowKey={(b) => b.bus_number} cols={[
              { h: "Bus", c: (b) => <b>{b.bus_number}</b> },
              { h: "Trips", c: (b) => b.trips },
              { h: "Distance", c: (b) => `${b.km} km` },
              { h: "Hours", c: (b) => b.hours },
              { h: "GPS fixes", c: (b) => b.gps_points },
              { h: "GPS availability", c: (b) => (b.gps_availability_pct != null ? `${b.gps_availability_pct}%` : "–") },
            ]} />
          </div>
          <div>
            <SectionTitle action={<Csv section="route_usage" days={days} />}>Route usage</SectionTitle>
            <DataTable rows={data.route_usage} rowKey={(r) => r.route_code} cols={[
              { h: "Route", c: (r) => <b>{r.route_code}</b> },
              { h: "Name", c: (r) => r.route_name },
              { h: "Trips", c: (r) => r.trips },
              { h: "Passenger journeys", c: (r) => r.journeys },
              { h: "Delayed trips", c: (r) => r.delayed_trips },
            ]} />
          </div>
          <div className="grid gap-5 lg:grid-cols-2">
            <div>
              <SectionTitle action={<Csv section="delayed_trips" days={days} />}>Delayed trips</SectionTitle>
              <DataTable rows={data.delayed_trips.slice(0, 50)} rowKey={(t) => t.id} empty="No delayed trips." cols={[
                { h: "Bus", c: (t) => t.bus_number }, { h: "Route", c: (t) => t.route_code },
                { h: "Started", c: (t) => ago(t.started_at) }, { h: "Max delay", c: (t) => `${Math.round(t.max_delay_minutes)} min` },
              ]} />
            </div>
            <div>
              <SectionTitle action={<Csv section="interrupted_trips" days={days} />}>Service interruptions</SectionTitle>
              <DataTable rows={data.service_interruptions.interrupted_trips.slice(0, 50)} rowKey={(t) => t.id} empty="No interrupted trips." cols={[
                { h: "Bus", c: (t) => t.bus_number }, { h: "Route", c: (t) => t.route_code },
                { h: "Started", c: (t) => ago(t.started_at) }, { h: "Reason", c: (t) => t.end_reason?.replace(/_/g, " ") || "–" },
              ]} />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
