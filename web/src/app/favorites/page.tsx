"use client";

import Link from "next/link";
import { MapPin, Star, Trash2 } from "lucide-react";
import { Card, DemoBadge, Empty, ErrorBox, PageHeader, SectionTitle, Spinner } from "@/components/ui";
import { ArrivalsList, RouteChip } from "@/components/widgets";
import { api } from "@/lib/api";
import { useApi, useAuth } from "@/lib/hooks";
import type { RouteSummary, Stop } from "@/lib/types";

export default function FavoritesPage() {
  const { user, ready } = useAuth();
  const favs = useApi<{ routes: RouteSummary[]; stops: Stop[] }>(user ? "/api/me/favorites" : null, [user?.id]);
  if (!ready) return <Spinner />;
  if (!user)
    return (
      <div className="mx-auto max-w-3xl px-4 py-10">
        <Card className="p-8 text-center">
          <Star className="mx-auto h-10 w-10 text-accent-500" />
          <h1 className="mt-3 text-xl font-bold text-brand-900">Save your stops and routes</h1>
          <p className="mt-1 text-sm text-slate-500">Sign in to keep favorites and see their next buses at a glance.</p>
          <Link href="/profile/" className="mt-4 inline-block rounded-xl bg-brand-700 px-4 py-2 text-sm text-white">Sign in or create account</Link>
        </Card>
      </div>
    );
  const remove = async (kind: "routes" | "stops", id: number) => {
    await api(`/api/me/favorites/${kind}/${id}`, { method: "DELETE" });
    favs.reload();
  };
  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <PageHeader title="Favorites" />
      {favs.loading && <Spinner />}
      {favs.error && <ErrorBox error={favs.error} onRetry={favs.reload} />}
      {favs.data && (
        <div className="grid gap-5 lg:grid-cols-2">
          <div className="space-y-4">
            <SectionTitle>Stops</SectionTitle>
            {favs.data.stops.length === 0 && <Card className="p-4"><Empty>No favorite stops yet. Open a stop and tap Save.</Empty></Card>}
            {favs.data.stops.map((s) => (
              <Card key={s.id} className="p-4">
                <div className="mb-3 flex items-center justify-between">
                  <Link href={`/stop/?id=${s.id}`} className="flex items-center gap-2 font-semibold text-slate-800 hover:text-brand-700">
                    <MapPin className="h-4 w-4 text-brand-500" /> {s.name} {s.is_demo && <DemoBadge />}
                  </Link>
                  <button onClick={() => remove("stops", s.id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Remove ${s.name}`}>
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <ArrivalsList stopId={s.id} compact />
              </Card>
            ))}
          </div>
          <div className="space-y-4">
            <SectionTitle>Routes</SectionTitle>
            {favs.data.routes.length === 0 && <Card className="p-4"><Empty>No favorite routes yet. You get delay and disruption alerts for routes you save.</Empty></Card>}
            {favs.data.routes.map((r) => (
              <Card key={r.id} className="flex items-center gap-3 p-4">
                <RouteChip code={r.code} color={r.color} />
                <Link href={`/route/?id=${r.id}`} className="flex-1 text-sm font-medium text-slate-700 hover:text-brand-700">{r.name}</Link>
                <Link href={`/live/?route=${r.id}`} className="text-sm text-brand-600">Live</Link>
                <button onClick={() => remove("routes", r.id)} className="rounded-lg p-1.5 text-slate-400 hover:bg-red-50 hover:text-red-600" aria-label={`Remove ${r.code}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              </Card>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
