"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Card, DemoBadge, Empty, ErrorBox, PageHeader, Select, Spinner } from "@/components/ui";
import { RouteChip } from "@/components/widgets";
import { useApi } from "@/lib/hooks";
import type { Alert, RouteSummary, Schedule, Stop } from "@/lib/types";

interface TTRoute extends RouteSummary {
  schedules: Schedule[];
  operating_today: boolean;
  first_bus: string | null;
  last_bus: string | null;
  stops: { stop_id: number; name: string; offset_minutes: number; times: string[] }[];
  alerts: Alert[];
}

const DAY_LABEL: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

function upcoming(times: string[], n = 12) {
  const now = new Date().toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "Asia/Karachi" });
  const next = times.filter((t) => t >= now);
  return { next: next.slice(0, n), more: Math.max(0, next.length - n) };
}

function TimetableInner() {
  const p = useSearchParams();
  const [routeId, setRouteId] = useState(p.get("route") || "");
  const [stopId, setStopId] = useState(p.get("stop") || "");
  const allRoutes = useApi<RouteSummary[]>("/api/routes");
  const stops = useApi<Stop[]>("/api/stops?limit=500");
  const q = new URLSearchParams();
  if (routeId) q.set("route_id", routeId);
  if (stopId) q.set("stop_id", stopId);
  const tt = useApi<{ date: string; routes: TTRoute[] }>(`/api/timetable?${q.toString()}`);

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <PageHeader title="Bus timetable" subtitle={tt.data ? `Scheduled times for ${tt.data.date} (Pakistan time). Times are the timetable, not live tracking.` : undefined} />
      <Card className="p-4 mb-5 grid gap-3 sm:grid-cols-2">
        <Select label="Route" value={routeId} onChange={(e) => setRouteId(e.target.value)}>
          <option value="">All routes</option>
          {allRoutes.data?.map((r) => <option key={r.id} value={r.id}>{r.code}: {r.name}</option>)}
        </Select>
        <Select label="Stop" value={stopId} onChange={(e) => setStopId(e.target.value)}>
          <option value="">Major stops</option>
          {stops.data?.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </Select>
      </Card>
      {tt.loading && <Spinner />}
      {tt.error && <ErrorBox error={tt.error} onRetry={tt.reload} />}
      {tt.data && tt.data.routes.length === 0 && <Empty>No routes match this filter.</Empty>}
      <div className="space-y-5">
        {tt.data?.routes.map((r) => (
          <Card key={r.id} className="p-5">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <RouteChip code={r.code} color={r.color} />
                <h2 className="font-semibold text-slate-800">{r.name}</h2>
                {r.is_demo && <DemoBadge />}
              </div>
              <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${r.operating_today && r.status === "active" ? "bg-emerald-50 text-emerald-700" : "bg-red-50 text-red-700"}`}>
                {r.status !== "active" ? `Service ${r.status}` : r.operating_today ? "Operating today" : "No service today"}
              </span>
            </div>
            {r.alerts.map((a) => <p key={a.id} className="mt-2 rounded-lg bg-amber-50 p-2 text-xs text-amber-800"><b>{a.title}:</b> {a.message}</p>)}
            <div className="mt-3 grid gap-3 sm:grid-cols-3 text-sm">
              <div className="rounded-xl bg-surface p-3"><div className="text-xs text-slate-500">First bus</div><div className="text-lg font-bold text-brand-800">{r.first_bus || "–"}</div></div>
              <div className="rounded-xl bg-surface p-3"><div className="text-xs text-slate-500">Last bus</div><div className="text-lg font-bold text-brand-800">{r.last_bus || "–"}</div></div>
              <div className="rounded-xl bg-surface p-3">
                <div className="text-xs text-slate-500">Days and frequency</div>
                {r.schedules.map((s) => (
                  <div key={s.id} className="text-xs text-slate-700">
                    {s.days.map((d) => DAY_LABEL[d]).join(", ")}: {s.first_departure}–{s.last_departure}, every {s.frequency_minutes} min
                  </div>
                ))}
                {r.schedules.length === 0 && <div className="text-xs text-slate-500">No timetable published</div>}
              </div>
            </div>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs text-slate-500">
                    <th className="py-1 pr-4 font-medium">Stop</th>
                    <th className="py-1 font-medium">Next scheduled times</th>
                  </tr>
                </thead>
                <tbody>
                  {r.stops.map((s) => {
                    const u = upcoming(s.times);
                    return (
                      <tr key={s.stop_id} className="border-t border-slate-100 align-top">
                        <td className="py-2 pr-4 font-medium text-slate-700 whitespace-nowrap">{s.name}</td>
                        <td className="py-2">
                          <div className="flex flex-wrap gap-1.5">
                            {u.next.length === 0 && <span className="text-xs text-slate-400">No more departures today</span>}
                            {u.next.map((t, i) => <span key={i} className="rounded-md bg-brand-50 px-1.5 py-0.5 text-xs text-brand-800">{t}</span>)}
                            {u.more > 0 && <span className="text-xs text-slate-400">+{u.more} more</span>}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

export default function TimetablePage() {
  return <Suspense fallback={<Spinner />}><TimetableInner /></Suspense>;
}
