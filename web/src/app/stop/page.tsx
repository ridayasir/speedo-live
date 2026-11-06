"use client";

import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { BellRing } from "lucide-react";
import FavoriteButton from "@/components/FavoriteButton";
import MapView from "@/components/MapView";
import { Button, Card, DemoBadge, ErrorBox, SectionTitle, Spinner } from "@/components/ui";
import { ArrivalsList, RouteChip } from "@/components/widgets";
import { api } from "@/lib/api";
import { useApi, useAuth, useLiveBuses } from "@/lib/hooks";
import type { Alert, RouteSummary, Stop } from "@/lib/types";

type StopDetail = Stop & { routes: (RouteSummary & { sequence: number })[]; alerts: Alert[] };

function StopInner() {
  const p = useSearchParams();
  const id = Number(p.get("id"));
  const routeParam = p.get("route") ? Number(p.get("route")) : undefined;
  const tracking = p.get("tracking") === "1";
  const { user } = useAuth();
  const [routeId, setRouteId] = useState<number | undefined>(routeParam);
  const [watchMsg, setWatchMsg] = useState<string | null>(null);
  const { data: s, loading, error, reload } = useApi<StopDetail>(id ? `/api/stops/${id}` : null);
  const { buses } = useLiveBuses({ routeIds: s ? (routeId ? [routeId] : s.routes.map((r) => r.id)) : [] });
  if (!id) return <div className="p-6"><ErrorBox error="No stop selected." /></div>;
  if (loading) return <Spinner />;
  if (error || !s) return <div className="p-6"><ErrorBox error={error || "Stop not found"} onRetry={reload} /></div>;

  const watch = async () => {
    const rid = routeId || s.routes[0]?.id;
    if (!rid) return;
    try {
      await api("/api/me/watches", { method: "POST", json: { stop_id: s.id, route_id: rid, minutes_before: user?.notification_prefs?.arrival_minutes_before || 5 } });
      setWatchMsg("We'll notify you when a bus is a few minutes away (for the next 3 hours).");
    } catch (e) {
      setWatchMsg((e as Error).message);
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Bus stop</p>
          <h1 className="text-2xl font-bold text-brand-900 flex items-center gap-2">{s.name} {s.is_demo && <DemoBadge />}</h1>
          {s.name_ur && <p className="text-slate-500" dir="rtl">{s.name_ur}</p>}
        </div>
        <div className="flex gap-2">
          <FavoriteButton kind="stops" id={s.id} />
          {user && (
            <Button size="sm" variant="accent" onClick={watch}><BellRing className="h-4 w-4" /> Notify me</Button>
          )}
        </div>
      </div>
      {tracking && (
        <div className="rounded-xl border border-brand-200 bg-brand-50 p-3 text-sm text-brand-800">
          Tracking your bus to this stop. {user ? "You'll get a notification as it approaches." : "Sign in to receive an approach notification."}
        </div>
      )}
      {watchMsg && <div className="rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{watchMsg}</div>}
      {s.alerts.map((a) => (
        <div key={a.id} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><b>{a.title}.</b> {a.message}</div>
      ))}
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3 space-y-5">
          <Card className="p-4">
            <SectionTitle>Arrivals</SectionTitle>
            <div className="mb-3 flex flex-wrap gap-2">
              <button onClick={() => setRouteId(undefined)} className={`rounded-lg px-2.5 py-1 text-xs ${!routeId ? "bg-brand-700 text-white" : "bg-slate-100 text-slate-600"}`}>All routes</button>
              {s.routes.map((r) => (
                <button key={r.id} onClick={() => setRouteId(r.id)} className={`rounded-lg px-2.5 py-1 text-xs ${routeId === r.id ? "bg-brand-700 text-white" : "bg-slate-100 text-slate-600"}`}>{r.code}</button>
              ))}
            </div>
            <ArrivalsList stopId={s.id} routeId={routeId} />
          </Card>
          <Card className="p-4">
            <SectionTitle>Routes serving this stop</SectionTitle>
            <ul className="space-y-2">
              {s.routes.map((r) => (
                <li key={r.id}>
                  <Link href={`/route/?id=${r.id}`} className="flex items-center gap-3 rounded-xl border border-slate-100 px-3 py-2 hover:bg-slate-50">
                    <RouteChip code={r.code} color={r.color} /> <span className="text-sm">{r.name}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <Card className="lg:col-span-2 h-[420px] overflow-hidden">
          <MapView stops={[s]} highlightStopIds={[s.id]} buses={buses} center={[s.lat, s.lng]} zoom={14} />
        </Card>
      </div>
    </div>
  );
}

export default function StopPage() {
  return <Suspense fallback={<Spinner />}><StopInner /></Suspense>;
}
