"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { Flag, History, LocateFixed, MapPin, Navigation, Radio, Star } from "lucide-react";
import MapView from "@/components/MapView";
import { Button, Card, Empty, ErrorBox, SectionTitle, Spinner, effectiveStatus } from "@/components/ui";
import { GlobalSearch, NavLinkCard, PlaceInput, RouteChip, findPlace, type Place, type VoiceJourney } from "@/components/widgets";
import { speak, type VoiceLang } from "@/lib/voice";
import { km, loadRecent, useApi, useAuth, useGeolocation, useLiveBuses, type RecentSearch } from "@/lib/hooks";
import type { Alert, RouteDetail, RouteSummary, Stop } from "@/lib/types";

function WhereTo() {
  const router = useRouter();
  const [dest, setDest] = useState<Place | null>(null);
  const [voiceMsg, setVoiceMsg] = useState<{ text: string; error?: boolean } | null>(null);
  const go = (p: Place | null = dest) => {
    if (p) router.push(`/routes/?from=me&to=${encodeURIComponent(JSON.stringify(p))}`);
  };
  // "Main Model Town mein hoon, mujhe Liberty Chowk jana hai": find both places, then plan and read out the answer
  const voiceJourney = async (j: VoiceJourney, lang: VoiceLang) => {
    setVoiceMsg({ text: j.from ? `Finding “${j.from}” and “${j.to}”…` : `Finding “${j.to}”…` });
    const [from, to] = await Promise.all([j.from ? findPlace(j.from) : Promise.resolve(null), findPlace(j.to)]);
    const missing = !to ? j.to : j.from && !from ? j.from : null;
    if (missing) {
      setVoiceMsg({ text: `We could not find “${missing}”. Please say it again or type it.`, error: true });
      speak(`Sorry, we could not find ${missing}. Please try again.`, `معاف کیجیے، ${missing} نہیں ملا۔ دوبارہ بولیں۔`, lang);
      return;
    }
    const f = from ? encodeURIComponent(JSON.stringify(from)) : "me";
    router.push(`/routes/?from=${f}&to=${encodeURIComponent(JSON.stringify(to))}&say=${lang}`);
  };
  return (
    <Card className="p-4 md:p-5">
      <h2 className="text-lg font-bold text-brand-900 md:text-xl">Where do you want to go?</h2>
      <p className="mb-3 text-sm text-slate-500">
        Type a stop or any place in Lahore, or tap the mic and say it (English or Urdu). We find the Speedo stop nearest
        to you and the bus that takes you there.
      </p>
      <div className="flex flex-col gap-2 sm:flex-row">
        <div className="flex-1">
          <PlaceInput value={dest} onChange={setDest} onSubmit={go} allowPlaces icon="destination" onVoiceJourney={voiceJourney}
            placeholder="e.g. Liberty Chowk, Emporium Mall, Jinnah Hospital" />
          {voiceMsg && (
            <p className={`mt-2 text-sm ${voiceMsg.error ? "text-red-700" : "text-brand-700"}`} role="status">{voiceMsg.text}</p>
          )}
        </div>
        <Button onClick={() => go()} disabled={!dest} className="sm:w-44">
          <Navigation className="h-4 w-4" /> Find my bus
        </Button>
      </div>
      <p className="mt-2 text-xs text-slate-400">Uses your phone&apos;s location to find the nearest stop. Press Enter to search places.</p>
      <p className="mt-1 text-xs text-slate-500">
        🎤 Try saying: <i>“Main Model Town mein hoon, mujhe Liberty Chowk jana hai”</i> and we will tell you which stop to go to.
      </p>
    </Card>
  );
}

export default function Home() {
  const { user } = useAuth();
  const geo = useGeolocation();
  const { buses, conn } = useLiveBuses();
  const popular = useApi<RouteSummary[]>("/api/routes/popular?limit=6");
  const alerts = useApi<Alert[]>("/api/alerts");
  const network = useApi<RouteDetail[]>("/api/routes?with_path=true");
  const networkLines = useMemo(() => (network.data || []).map((r) => ({ id: r.id, color: r.color, path: r.path, weight: 4 })), [network.data]);
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
      <div className="mx-auto max-w-7xl px-4 pt-4 pb-4">
        <section className="grid gap-3 md:grid-cols-3" aria-label="Speedo buses in Lahore">
          <div className="relative overflow-hidden rounded-xl2 shadow-card md:col-span-2">
            <img
              src="/images/speedo-fleet-minar-e-pakistan.webp"
              fetchPriority="high"
              alt="A row of red Speedo buses near Minar-e-Pakistan, Lahore"
              className="h-56 w-full object-cover md:h-72"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-black/15 to-transparent" />
            <div className="absolute bottom-0 p-5 text-white">
              <h2 className="text-xl font-bold md:text-2xl">Your Bus, Your Route, Your Time.</h2>
              <p className="text-sm text-white/85">Lahore&apos;s red Speedo buses, live on your phone.</p>
            </div>
          </div>
          <Link href="/routes/" className="group relative block overflow-hidden rounded-xl2 shadow-card">
            <img
              src="/images/speedo-buses-depot.jpg"
              alt="Red Speedo feeder buses F199, F178 and F190 parked side by side"
              className="h-56 w-full object-cover transition-transform duration-300 group-hover:scale-[1.03] md:h-72"
            />
            <div className="absolute inset-0 bg-gradient-to-t from-black/75 via-transparent to-transparent" />
            <div className="absolute bottom-0 p-5 text-white">
              <h2 className="text-lg font-bold">{network.data ? `${network.data.length} Speedo routes` : "Speedo routes"}</h2>
              <p className="text-sm text-white/85">See every route and stop &rarr;</p>
            </div>
          </Link>
        </section>
      </div>

      <div className="mx-auto max-w-7xl px-4 pb-4">
        <WhereTo />
      </div>

      <section className="relative">
        <div className="h-[42vh] min-h-[280px] md:h-[52vh] w-full">
          <MapView buses={buses} routes={networkLines} points={geo.pos ? [{ ...geo.pos, label: "You", kind: "me" }] : []} fitKey={geo.pos ? "me" : undefined} />
        </div>
        <div className="absolute inset-x-0 -bottom-6 z-[1000]">
          <div className="mx-auto max-w-3xl px-4">
            <GlobalSearch />
          </div>
        </div>
      </section>

      <div className="mx-auto max-w-7xl px-4 pt-12 pb-8 space-y-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <NavLinkCard href="/routes/" icon={Navigation} title="Plan a journey" text="Find the right Speedo route" />
          <NavLinkCard href="/live/" icon={Radio} title="Track buses live" text="See buses moving on the map" />
          <NavLinkCard href="/timetable/" icon={History} title="Timetables" text="First and last bus, stop times" />
          <NavLinkCard href="/report/" icon={Flag} title="Report a driver" text="Rash driving, rude behaviour, skipped stops" />
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

        <div className="grid gap-6 lg:grid-cols-2 [&>*]:min-w-0">
          <Card className="p-5">
            <SectionTitle action={<Link href="/routes/" className="text-sm text-brand-600">All routes</Link>}>Popular routes</SectionTitle>
            {popular.loading && <Spinner />}
            {popular.error && <ErrorBox error={popular.error} onRetry={popular.reload} />}
            <ul className="space-y-2">
              {popular.data?.map((r) => (
                <li key={r.id}>
                  <Link href={`/route/?id=${r.id}`} className="flex items-center gap-3 rounded-xl border border-slate-100 px-3 py-2.5 hover:bg-slate-50">
                    <RouteChip code={r.code} color={r.color} className="max-w-[10rem]" />
                    <span className="min-w-0 flex-1 truncate text-sm text-slate-700">{r.name}</span>
                    <span className="shrink-0 text-xs text-slate-400">{r.stop_count} stops</span>
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
