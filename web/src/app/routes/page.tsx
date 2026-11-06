"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDownUp, Bus, Footprints, Repeat } from "lucide-react";
import MapView, { type MapRoute } from "@/components/MapView";
import { Button, Card, DemoBadge, Empty, ErrorBox, Input, SectionTitle, Spinner } from "@/components/ui";
import { PlaceInput, RouteChip, type Place } from "@/components/widgets";
import { api } from "@/lib/api";
import { km, saveRecent, useApi, useAuth, useGeolocation } from "@/lib/hooks";
import type { PlanLegRide, PlanOption, PlanResult, RouteDetail, RouteSummary, Stop } from "@/lib/types";

function parsePlace(v: string | null): Place | null {
  if (!v) return null;
  try {
    const p = JSON.parse(v);
    return typeof p.lat === "number" ? p : null;
  } catch {
    return null;
  }
}

function RoutesInner() {
  const params = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const geo = useGeolocation();
  const [from, setFrom] = useState<Place | null>(parsePlace(params.get("from")));
  const [to, setTo] = useState<Place | null>(parsePlace(params.get("to")));
  const [picking, setPicking] = useState<"from" | "to" | null>(null);
  const [result, setResult] = useState<PlanResult | null>(null);
  const [chosen, setChosen] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const routes = useApi<RouteDetail[]>("/api/routes?with_path=true");

  useEffect(() => {
    if (geo.pos && !from) setFrom({ label: "My location", lat: geo.pos.lat, lng: geo.pos.lng });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.pos]);

  const search = async (f = from, t = to) => {
    if (!f || !t) return setError("Choose a starting point and a destination.");
    setBusy(true);
    setError(null);
    try {
      const r = await api<PlanResult>("/api/plan", {
        method: "POST",
        json: {
          from_lat: f.lat, from_lng: f.lng, from_stop_id: f.stop_id, from_label: f.label,
          to_lat: t.lat, to_lng: t.lng, to_stop_id: t.stop_id, to_label: t.label,
        },
      });
      setResult(r);
      setChosen(0);
      saveRecent({ from: f, to: t, at: Date.now() });
      router.replace(`/routes/?from=${encodeURIComponent(JSON.stringify(f))}&to=${encodeURIComponent(JSON.stringify(t))}`, { scroll: false });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (from && to && params.get("from")) search(from, to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const option: PlanOption | undefined = result?.options[chosen];
  const routeById = useMemo(() => Object.fromEntries((routes.data || []).map((r) => [r.id, r])), [routes.data]);

  const mapRoutes: MapRoute[] = [];
  const stopsOnMap: Stop[] = [];
  const hl: number[] = [];
  if (option) {
    for (const leg of option.legs) {
      if (leg.type !== "ride") continue;
      const r = routeById[leg.route_id];
      const ids = new Set(leg.stops.map((s) => s.id));
      // draw only the ridden part of the route
      const seg = r ? sliceRoute(r, leg.board.id, leg.alight.id) : leg.stops.map((s) => [s.lat, s.lng] as [number, number]);
      mapRoutes.push({ id: leg.route_id, color: leg.color, path: seg });
      stopsOnMap.push(...leg.stops.filter((s) => ids.has(s.id)));
      hl.push(leg.board.id, leg.alight.id);
    }
  } else if (!result) {
    (routes.data || []).forEach((r) => mapRoutes.push({ id: r.id, color: r.color, path: r.path, dim: true }));
  }
  const points = [
    ...(from ? [{ lat: from.lat, lng: from.lng, label: from.label, kind: "origin" as const }] : []),
    ...(to ? [{ lat: to.lat, lng: to.lng, label: to.label, kind: "destination" as const }] : []),
  ];

  const startTracking = async (opt: PlanOption) => {
    const rides = opt.legs.filter((l): l is PlanLegRide => l.type === "ride");
    const ride = rides[0];
    if (!ride) return;
    if (user) {
      try {
        await api("/api/me/journeys", { method: "POST", json: { route_id: ride.route_id, from_stop_id: ride.board.id, to_stop_id: rides[rides.length - 1].alight.id } });
        await api("/api/me/watches", { method: "POST", json: { stop_id: ride.board.id, route_id: ride.route_id, minutes_before: user.notification_prefs?.arrival_minutes_before || 5 } });
      } catch {
        /* tracking still works without saving */
      }
    }
    router.push(`/stop/?id=${ride.board.id}&route=${ride.route_id}&tracking=1`);
  };

  const list = (routes.data || []).filter(
    (r) => !filter || r.name.toLowerCase().includes(filter.toLowerCase()) || r.code.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="flex flex-col lg:flex-row lg:h-[calc(100vh-4rem-2rem)]">
      <aside className="lg:w-[420px] lg:overflow-y-auto scrollbar-thin bg-surface p-4 space-y-4 order-2 lg:order-1">
        <Card className="p-4 space-y-3">
          <h1 className="text-lg font-bold text-brand-900">Plan your journey</h1>
          <PlaceInput value={from} onChange={setFrom} placeholder="Starting point (stop name)" icon="origin" onLocate={geo.locate} locating={geo.busy}
            onPickMap={() => setPicking(picking === "from" ? null : "from")} picking={picking === "from"} />
          <div className="flex justify-center -my-1">
            <button className="rounded-full border border-slate-200 bg-white p-1.5 text-slate-500 hover:bg-slate-50" aria-label="Swap" onClick={() => { setFrom(to); setTo(from); }}>
              <ArrowDownUp className="h-4 w-4" />
            </button>
          </div>
          <PlaceInput value={to} onChange={setTo} placeholder="Destination (stop name)" icon="destination"
            onPickMap={() => setPicking(picking === "to" ? null : "to")} picking={picking === "to"} />
          {picking && <p className="text-xs text-accent-600">Tap the map to set the {picking === "from" ? "starting point" : "destination"}.</p>}
          {geo.error && <p className="text-xs text-red-600">{geo.error}</p>}
          <Button className="w-full" onClick={() => search()} loading={busy}>Find routes</Button>
          {error && <ErrorBox error={error} />}
        </Card>

        {result && (
          <Card className="p-4">
            <SectionTitle action={<button className="text-sm text-brand-600" onClick={() => setResult(null)}>Clear</button>}>
              {result.options.length ? `${result.options.length} option${result.options.length > 1 ? "s" : ""}` : "No routes found"}
            </SectionTitle>
            {result.nearest_boarding_stop && (
              <p className="mb-3 text-xs text-slate-500">
                Nearest boarding stop: <b>{result.nearest_boarding_stop.name}</b> ({km(result.nearest_boarding_stop.walk_m)} walk).
                Destination stop: <b>{result.nearest_destination_stop?.name}</b>.
              </p>
            )}
            {result.options.length === 0 && (
              <Empty>No Speedo route connects these places within walking distance. Try a nearby major stop.</Empty>
            )}
            <div className="space-y-2">
              {result.options.map((o, i) => (
                <div
                  key={i}
                  role="button"
                  tabIndex={0}
                  onClick={() => setChosen(i)}
                  onKeyDown={(e) => e.key === "Enter" && setChosen(i)}
                  className={`rounded-xl border p-3 cursor-pointer ${i === chosen ? "border-brand-500 bg-brand-50/50" : "border-slate-100 bg-white hover:bg-slate-50"}`}
                >
                  <div className="flex items-center justify-between">
                    <div className="flex flex-wrap items-center gap-1.5">
                      {o.legs.filter((l) => l.type === "ride").map((l, k) =>
                        l.type === "ride" ? <RouteChip key={k} code={l.route_code} color={l.color} /> : null,
                      )}
                      {o.transfers > 0 && <span className="flex items-center gap-1 text-xs text-slate-500"><Repeat className="h-3 w-3" /> {o.transfers} transfer</span>}
                      {o.is_demo && <DemoBadge />}
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold text-brand-800">~{o.total_minutes} min</div>
                      <div className="text-[11px] text-slate-400">estimate incl. wait</div>
                    </div>
                  </div>
                  {i === chosen && (
                    <ol className="mt-3 space-y-2 border-l-2 border-slate-200 pl-3">
                      {o.legs.map((l, k) =>
                        l.type === "walk" ? (
                          <li key={k} className="flex items-center gap-2 text-sm text-slate-600">
                            <Footprints className="h-4 w-4 text-slate-400" /> Walk {km(l.distance_m)} (~{Math.round(l.minutes)} min) to {l.to.name}
                          </li>
                        ) : (
                          <li key={k} className="text-sm">
                            <div className="flex items-center gap-2 font-medium text-slate-800">
                              <Bus className="h-4 w-4 text-brand-600" /> Board {l.route_code} at {l.board.name}
                            </div>
                            <div className="ml-6 text-xs text-slate-500">
                              {l.stop_count} stop{l.stop_count === 1 ? "" : "s"} · {km(l.distance_m)} · ~{Math.round(l.minutes)} min · get off at <b>{l.alight.name}</b>
                            </div>
                            <details className="ml-6 mt-1 text-xs text-slate-500">
                              <summary className="cursor-pointer text-brand-600">All stops</summary>
                              <ol className="mt-1 list-decimal pl-4">
                                {l.stops.map((s) => <li key={s.id}>{s.name}</li>)}
                              </ol>
                            </details>
                          </li>
                        ),
                      )}
                    </ol>
                  )}
                  {i === chosen && (
                    <Button className="mt-3 w-full" variant="accent" onClick={(e) => { e.stopPropagation(); startTracking(o); }}>
                      Select route and start tracking
                    </Button>
                  )}
                </div>
              ))}
            </div>
            {!user && result.options.length > 0 && (
              <p className="mt-3 text-xs text-slate-500">
                <Link href="/profile/" className="text-brand-600 underline">Sign in</Link> to get a notification when your bus is approaching.
              </p>
            )}
          </Card>
        )}

        <Card className="p-4">
          <SectionTitle>All routes</SectionTitle>
          <Input placeholder="Filter routes" value={filter} onChange={(e) => setFilter(e.target.value)} />
          {routes.loading && <Spinner />}
          {routes.error && <ErrorBox error={routes.error} onRetry={routes.reload} />}
          <ul className="mt-3 space-y-2">
            {list.map((r: RouteSummary) => (
              <li key={r.id}>
                <Link href={`/route/?id=${r.id}`} className="flex items-center gap-3 rounded-xl border border-slate-100 bg-white px-3 py-2.5 hover:bg-slate-50">
                  <RouteChip code={r.code} color={r.color} />
                  <span className="flex-1 text-sm">{r.name}</span>
                  {r.is_demo && <DemoBadge />}
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </aside>
      <div className="h-[45vh] lg:h-full lg:flex-1 order-1 lg:order-2">
        <MapView
          routes={mapRoutes}
          stops={stopsOnMap}
          highlightStopIds={hl}
          points={points}
          fitKey={option ? `opt-${chosen}-${result?.origin.lat}` : points.length ? points.map((p) => p.lat).join() : undefined}
          onMapClick={(lat, lng) => {
            if (!picking) return;
            const p = { label: `Pinned (${lat.toFixed(4)}, ${lng.toFixed(4)})`, lat, lng };
            if (picking === "from") setFrom(p);
            else setTo(p);
            setPicking(null);
          }}
        />
      </div>
    </div>
  );
}

function sliceRoute(r: RouteDetail, boardId: number, alightId: number): [number, number][] {
  const a = r.stops.find((s) => s.id === boardId);
  const b = r.stops.find((s) => s.id === alightId);
  if (!a || !b || r.path.length < 2) return r.path;
  // walk the path accumulating distance
  const out: [number, number][] = [];
  let d = 0;
  const R = 6371000;
  const hav = (p: [number, number], q: [number, number]) => {
    const toR = Math.PI / 180;
    const dl = (q[0] - p[0]) * toR, dn = (q[1] - p[1]) * toR;
    const x = Math.sin(dl / 2) ** 2 + Math.cos(p[0] * toR) * Math.cos(q[0] * toR) * Math.sin(dn / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(x));
  };
  out.push([a.lat, a.lng]);
  for (let i = 1; i < r.path.length; i++) {
    d += hav(r.path[i - 1], r.path[i]);
    if (d > a.distance_m + 5 && d < b.distance_m - 5) out.push(r.path[i]);
  }
  out.push([b.lat, b.lng]);
  return out;
}

export default function RoutesPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <RoutesInner />
    </Suspense>
  );
}
