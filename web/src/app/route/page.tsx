"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Clock, Radio } from "lucide-react";
import FavoriteButton from "@/components/FavoriteButton";
import MapView from "@/components/MapView";
import { Card, DemoBadge, Empty, ErrorBox, SectionTitle, Spinner } from "@/components/ui";
import { BusRow, RouteChip } from "@/components/widgets";
import { km, useApi, useLiveBuses } from "@/lib/hooks";
import type { RouteDetail } from "@/lib/types";

function RouteInner() {
  const id = Number(useSearchParams().get("id"));
  const router = useRouter();
  const { data: r, loading, error, reload } = useApi<RouteDetail>(id ? `/api/routes/${id}` : null);
  const { buses } = useLiveBuses({ routeIds: id ? [id] : [] });
  if (!id) return <div className="p-6"><ErrorBox error="No route selected." /></div>;
  if (loading) return <Spinner />;
  if (error || !r) return <div className="p-6"><ErrorBox error={error || "Route not found"} onRetry={reload} /></div>;
  const onRoute = buses.filter((b) => b.route_id === r.id);
  return (
    <div className="mx-auto max-w-7xl px-4 py-6 space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <RouteChip code={r.code} color={r.color} className="text-sm" />
            {r.is_demo && <DemoBadge />}
            {r.status !== "active" && <span className="rounded-md bg-red-50 px-2 py-0.5 text-xs text-red-700">{r.status}</span>}
          </div>
          <h1 className="mt-2 text-2xl font-bold text-brand-900">{r.name}</h1>
          <p className="text-sm text-slate-500">
            {r.stop_count} stops · {km(r.length_m)}{r.fare_pkr ? ` · Rs ${r.fare_pkr}` : ""}
          </p>
          {r.source_reference && <p className="text-xs text-slate-400 mt-1">Source: {r.source_reference}</p>}
        </div>
        <div className="flex gap-2">
          <FavoriteButton kind="routes" id={r.id} />
          <Link href={`/live/?route=${r.id}`} className="inline-flex items-center gap-1.5 rounded-xl bg-brand-700 px-3 py-1.5 text-sm text-white hover:bg-brand-800">
            <Radio className="h-4 w-4" /> Track live
          </Link>
          <Link href={`/timetable/?route=${r.id}`} className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50">
            <Clock className="h-4 w-4" /> Timetable
          </Link>
        </div>
      </div>
      {r.alerts?.map((a) => (
        <div key={a.id} className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-sm text-amber-800"><b>{a.title}.</b> {a.message}</div>
      ))}
      <div className="grid gap-5 lg:grid-cols-5">
        <Card className="lg:col-span-3 h-[420px] overflow-hidden">
          <MapView routes={[{ id: r.id, color: r.color, path: r.path }]} stops={r.stops} buses={onRoute} fitKey={`r${r.id}`}
            onStopClick={(s) => router.push(`/stop/?id=${s.id}&route=${r.id}`)} />
        </Card>
        <div className="lg:col-span-2 space-y-5">
          <Card className="p-4">
            <SectionTitle>Buses on this route</SectionTitle>
            {onRoute.length === 0 && <Empty>No buses are reporting on this route right now.</Empty>}
            <div className="space-y-2">
              {onRoute.map((b) => <BusRow key={b.bus_id} b={b} onClick={() => router.push(`/live/?route=${r.id}&bus=${b.bus_id}`)} />)}
            </div>
          </Card>
          <Card className="p-4">
            <SectionTitle>Stops</SectionTitle>
            <ol className="relative ml-2 border-l-2" style={{ borderColor: r.color }}>
              {r.stops.map((s, i) => (
                <li key={s.id} className="ml-4 py-1.5">
                  <span className="absolute -left-[7px] mt-1.5 h-3 w-3 rounded-full border-2 bg-white" style={{ borderColor: r.color }} />
                  <Link href={`/stop/?id=${s.id}&route=${r.id}`} className="flex items-center justify-between text-sm hover:text-brand-700">
                    <span className={i === 0 || i === r.stops.length - 1 || s.is_major ? "font-semibold" : ""}>{s.name}</span>
                    <span className="text-xs text-slate-400">+{Math.round(s.offset_minutes)} min</span>
                  </Link>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      </div>
    </div>
  );
}

export default function RoutePage() {
  return <Suspense fallback={<Spinner />}><RouteInner /></Suspense>;
}
