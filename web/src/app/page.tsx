"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { History, LocateFixed, MapPin, Navigation, Radio, Star } from "lucide-react";
import MapView from "@/components/MapView";
import { Button, Card, DemoBadge, Empty, ErrorBox, SectionTitle, Spinner, effectiveStatus } from "@/components/ui";
import { GlobalSearch, NavLinkCard, RouteChip } from "@/components/widgets";
import { km, loadRecent, useApi, useAuth, useGeolocation, useLiveBuses, type RecentSearch } from "@/lib/hooks";
import type { Alert, RouteSummary, Stop } from "@/lib/types";

export default function Home() {
  const { user } = useAuth();
  const geo = useGeolocation();
  const { buses, conn } = useLiveBuses();
  const popular = useApi<RouteSummary[]>("/api/routes/popular?limit=6");
  const alerts = useApi<Alert[]>("/api/alerts");
  const favs = useApi<{ stops: Stop[]; routes: RouteSummary[] }>(user ? "/api/me/favorites" : null, [user?.id]);
  const nearby = useApi<Stop[]>(geo.pos ? `/api/stops/nearby?lat=${geo.pos.lat}&lng=${geo.pos.lng}&radius_m=2000&limit=5` : null);
  const [recent, setRecent] = useState<RecentSearch[]>([]);
  useEffect(() => setRecent(loadRecent()), []);

  const counts = useMemo(() => {
    const c = { active: 0, delayed: 0, lost: 0 };
    for (const b of buses) {
      const s = effectiveStatus(b);
      if (s === "active") c.active++;
      else if (s === "delayed") c.delayed++;
      else if (s === "stale" || s === "offline") c.lost++;
    }
    return c;
  }, [buses]);

  return (
    <div>
      <section className="relative">
        <div className="h-[42vh] min-h-[280px] md:h-[52vh] w-full">
          <MapView buses={buses} points={geo.pos ? [{ ...geo.pos, label: "You", kind: "me" }] : []} fitKey={geo.pos ? "me" : undefined} />
        </div>
        <div className="absolute inset-x-0 -bottom-6 z-[1000]">
          <div className="mx-auto max-w-3xl px-4">
            <GlobalSearch />
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-4 pt-12 pb-8 space-y-6">
        <div className="grid gap-3 sm:grid-cols-3">
          <NavLinkCard href="/routes/" icon={Navigation} title="Plan a journey" text="Find the right Speedo route" />
          <NavLinkCard href="/live/" icon={Radio} title="Track buses live" text="See buses moving on the map" />
          <NavLinkCard href="/timetable/" icon={History} title="Timetables" text="First and last bus, stop times" />
        </div>

        {alerts.data && alerts.data.length > 0 && (
          <div className="space-y-2">
            {alerts.data.slice(0, 3).map((a) => (
              <div
                key={a.id}
                className={`rounded-xl border p-3 text-sm ${a.severity === "disruption" ? "border-red-200 bg-red-50 text-red-800" : a.severity === "warning" ? "border-amber-200 bg-amber-50 text-amber-800" : "border-brand-100 bg-brand-50 text-brand-800"}`}
              >
                <b>{a.title}.</b> {a.message}
              </div>
            ))}
          </div>
        )}

        <div className="grid gap-6 lg:grid-cols-3">
          <Card className="p-5">
            <SectionTitle>Live bus status</SectionTitle>
            <div className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-xl bg-emerald-50 p-3"><div className="text-2xl font-bold text-emerald-700">{counts.active}</div><div className="text-xs text-emerald-700">On route</div></div>
              <div className="rounded-xl bg-amber-50 p-3"><div className="text-2xl font-bold text-amber-700">{counts.delayed}</div><div className="text-xs text-amber-700">Delayed</div></div>
              <div className="rounded-xl bg-slate-100 p-3"><div className="text-2xl font-bold text-slate-600">{counts.lost}</div><div className="text-xs text-slate-600">No signal</div></div>
            </div>
            <p className="mt-3 text-xs text-slate-500">
              Connection: {conn === "live" ? "live updates" : conn === "connecting" ? "connecting…" : "reconnecting, showing last known data"}
            </p>
          </Card>

          <Card className="p-5">
            <SectionTitle
              action={
                <Button size="sm" variant="ghost" onClick={geo.locate} loading={geo.busy}>
                  <LocateFixed className="h-4 w-4" /> {geo.pos ? "Refresh" : "Use my location"}
                </Button>
              }
            >
              Nearby stops
            </SectionTitle>
            {geo.error && <ErrorBox error={geo.error} />}
            {!geo.pos && !geo.error && <Empty>Share your location to see the closest stops.</Empty>}
            {nearby.loading && <Spinner />}
            {nearby.data && nearby.data.length === 0 && <Empty>No stops within 2 km.</Empty>}
            <ul className="space-y-1">
              {nearby.data?.map((s) => (
                <li key={s.id}>
                  <Link href={`/stop/?id=${s.id}`} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-slate-50">
                    <MapPin className="h-4 w-4 text-brand-500" /> <span className="flex-1">{s.name}</span>
                    <span className="text-xs text-slate-400">{km(s.distance_m)}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>

          <Card className="p-5">
            <SectionTitle action={<Link href="/favorites/" className="text-sm text-brand-600">All</Link>}>Favorite stops</SectionTitle>
            {!user && (
              <Empty>
                <Link href="/profile/" className="text-brand-600 underline">Sign in</Link> to save favorite stops and routes.
              </Empty>
            )}
            {user && favs.data && favs.data.stops.length === 0 && <Empty>Tap the star on any stop to add it here.</Empty>}
            <ul className="space-y-1">
              {favs.data?.stops.slice(0, 5).map((s) => (
                <li key={s.id}>
                  <Link href={`/stop/?id=${s.id}`} className="flex items-center gap-2 rounded-lg px-2 py-2 text-sm hover:bg-slate-50">
                    <Star className="h-4 w-4 fill-accent-400 text-accent-500" /> {s.name}
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>

        <div className="grid gap-6 lg:grid-cols-2">
          <Card className="p-5">
            <SectionTitle action={<Link href="/routes/" className="text-sm text-brand-600">All routes</Link>}>Popular routes</SectionTitle>
            {popular.loading && <Spinner />}
            {popular.error && <ErrorBox error={popular.error} onRetry={popular.reload} />}
            <ul className="space-y-2">
              {popular.data?.map((r) => (
                <li key={r.id}>
                  <Link href={`/route/?id=${r.id}`} className="flex items-center gap-3 rounded-xl border border-slate-100 px-3 py-2.5 hover:bg-slate-50">
                    <RouteChip code={r.code} color={r.color} />
                    <span className="flex-1 text-sm text-slate-700">{r.name}</span>
                    {r.is_demo && <DemoBadge />}
                    <span className="text-xs text-slate-400">{r.stop_count} stops</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
          <Card className="p-5">
            <SectionTitle>Recently searched</SectionTitle>
            {recent.length === 0 && <Empty>Your recent journey searches will appear here.</Empty>}
            <ul className="space-y-2">
              {recent.map((r, i) => (
                <li key={i}>
                  <Link
                    href={`/routes/?from=${encodeURIComponent(JSON.stringify(r.from))}&to=${encodeURIComponent(JSON.stringify(r.to))}`}
                    className="flex items-center gap-3 rounded-xl border border-slate-100 px-3 py-2.5 text-sm hover:bg-slate-50"
                  >
                    <History className="h-4 w-4 text-slate-400" />
                    <span className="flex-1 truncate">{r.from.label} → {r.to.label}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </Card>
        </div>
      </div>
    </div>
  );
}
