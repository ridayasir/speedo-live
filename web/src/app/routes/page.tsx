"use client";

import Link from "next/link";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { ArrowDownUp, Bus, ExternalLink, Footprints, Info, LocateFixed, Repeat } from "lucide-react";
import MapView, { type MapRoute, type TripStop } from "@/components/MapView";
import { Button, Card, Empty, ErrorBox, Input, SectionTitle, Spinner } from "@/components/ui";
import { NextBus, PlaceInput, RouteChip, walkingDirectionsUrl, type Place } from "@/components/widgets";
import { VoiceTripPanel, useVoiceTrip } from "@/components/VoiceTrip";
import VoiceGuide from "@/components/VoiceGuide";
import { journeySpeech, loadTrip, saveTrip, tripKey } from "@/lib/journey";
import { speak, type VoiceLang } from "@/lib/voice";
import { api } from "@/lib/api";
import { km, saveRecent, useApi, useAuth, useGeolocation, useMeta } from "@/lib/hooks";
import type { PlanLegRide, PlanOption, PlanPreference, PlanResult, RouteDetail, RouteSummary, Stop } from "@/lib/types";

function parsePlace(v: string | null): Place | null {
  if (!v) return null;
  try {
    const p = JSON.parse(v);
    return typeof p.lat === "number" ? p : null;
  } catch {
    return null;
  }
}

const PREFS: { id: PlanPreference; label: string }[] = [
  { id: "fastest", label: "Fastest (estimate)" },
  { id: "fewer_transfers", label: "Fewer changes" },
  { id: "less_walking", label: "Less walking" },
];


function RoutesInner() {
  const params = useSearchParams();
  // ?say=en-IN|ur-PK: the trip was asked for by voice, so read the answer aloud
  // (a ref, so the answer is read out once even if two searches start together)
  const sayRef = useRef<VoiceLang | null>(
    params.get("say") === "ur-PK" ? "ur-PK" : params.get("say") === "en-IN" ? "en-IN" : null,
  );
  const router = useRouter();
  const { user } = useAuth();
  const geo = useGeolocation();
  // ?from=me: start from the passenger's current location (asked for on arrival)
  const fromMe = params.get("from") === "me";
  const [from, setFrom] = useState<Place | null>(fromMe ? null : parsePlace(params.get("from")));
  const [autoRun, setAutoRun] = useState(fromMe);
  const [to, setTo] = useState<Place | null>(parsePlace(params.get("to")));
  const [picking, setPicking] = useState<"from" | "to" | null>(null);
  const [result, setResult] = useState<PlanResult | null>(null);
  const [chosen, setChosen] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // set when the shown trip comes from this phone's saved copy (no internet), with the time it was planned
  const [savedAt, setSavedAt] = useState<number | null>(null);
  const [filter, setFilter] = useState("");
  const routes = useApi<RouteDetail[]>("/api/routes?with_path=true");

  useEffect(() => {
    if (fromMe) geo.locate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!geo.pos) return;
    const me = { label: "My location", lat: geo.pos.lat, lng: geo.pos.lng };
    if (!from || autoRun) setFrom(me);
    if (autoRun && to) {
      setAutoRun(false);
      search(me, to);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [geo.pos]);

  const [prefer, setPrefer] = useState<PlanPreference>("fastest");
  const meta = useMeta();
  const search = async (f = from, t = to, pref: PlanPreference = prefer) => {
    if (!f || !t) return setError("Choose a starting point and a destination.");
    setBusy(true);
    setError(null);
    const key = tripKey(f, t, pref);
    try {
      const r = await api<PlanResult>("/api/plan", {
        method: "POST",
        json: {
          from_lat: f.lat, from_lng: f.lng, from_stop_id: f.stop_id, from_label: f.label,
          to_lat: t.lat, to_lng: t.lng, to_stop_id: t.stop_id, to_label: t.label, prefer: pref,
        },
      });
      setResult(r);
      setChosen(0);
      setSavedAt(null);
      saveTrip(key, r);
      const sayLang = sayRef.current;
      if (sayLang) {
        sayRef.current = null;
        const answer = journeySpeech(r.options[0], r).summary;
        speak(answer.en, answer.ur, sayLang);
      }
      saveRecent({ from: f, to: t, at: Date.now() });
      router.replace(`/routes/?from=${encodeURIComponent(JSON.stringify(f))}&to=${encodeURIComponent(JSON.stringify(t))}`, { scroll: false });
    } catch (e) {
      // no internet (or server down): show this trip from the phone's saved copy, clearly dated
      const saved = loadTrip(key);
      if (saved) {
        setResult(saved.result);
        setChosen(0);
        setSavedAt(saved.at);
      } else {
        const offline = typeof navigator !== "undefined" && !navigator.onLine;
        setError(offline ? "No internet connection, and this trip is not saved on this phone. Connect and try again." : (e as Error).message);
      }
    } finally {
      setBusy(false);
    }
  };

  // a spoken sentence with both places, said into either box (ambiguous names are asked about first)
  const trip = useVoiceTrip((f, t, lang) => {
    setError(null);
    setTo(t);
    sayRef.current = lang;
    if (f) {
      setFrom(f);
      search(f, t);
    } else if (geo.pos) {
      const me = { label: "My location", lat: geo.pos.lat, lng: geo.pos.lng };
      setFrom(me);
      search(me, t);
    } else {
      setAutoRun(true);
      geo.locate();
    }
  });

  useEffect(() => {
    if (from && to && params.get("from") && !fromMe) search(from, to);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const option: PlanOption | undefined = result?.options[chosen];
  // list <-> map: tapping a stop in the list focuses the map; tapping a trip marker highlights the list item
  const [selStop, setSelStop] = useState<number | null>(null);
  const [focus, setFocus] = useState<{ lat: number; lng: number; key: string } | null>(null);
  const [openLegs, setOpenLegs] = useState<Set<number>>(new Set());
  useEffect(() => {
    setSelStop(null);
    setOpenLegs(new Set());
  }, [chosen, result]);
  const focusStop = (st: { id: number; lat: number; lng: number }) => {
    setSelStop(st.id);
    setFocus({ lat: st.lat, lng: st.lng, key: `${st.id}-${Date.now()}` });
  };
  const fromMap = (st: { id: number }) => {
    if (!option) return;
    setSelStop(st.id);
    const k = option.legs.findIndex((l) => l.type === "ride" && l.stops.some((x) => x.id === st.id));
    if (k >= 0) setOpenLegs((o) => new Set(o).add(k));
    setTimeout(() => document.getElementById(`tl-${st.id}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }), 50);
  };
  const routeById = useMemo(() => Object.fromEntries((routes.data || []).map((r) => [r.id, r])), [routes.data]);

  const mapRoutes: MapRoute[] = [];
  const stopsOnMap: Stop[] = [];
  const hl: number[] = [];
  const walks: [number, number][][] = [];
  const tripStops: TripStop[] = [];
  if (option) {
    const rideLegs = option.legs.filter((l): l is PlanLegRide => l.type === "ride");
    rideLegs.forEach((leg, k) => {
      const add = (st: Stop, role: TripStop["role"]) => {
        if (!tripStops.some((t) => t.id === st.id)) tripStops.push({ id: st.id, lat: st.lat, lng: st.lng, name: st.name, role });
      };
      add(leg.board, k === 0 ? "board" : "transfer");
      add(leg.alight, k === rideLegs.length - 1 ? "alight" : "transfer");
    });
    for (const leg of option.legs) {
      if (leg.type === "walk") {
        walks.push([[leg.from.lat, leg.from.lng], [leg.to.lat, leg.to.lng]]);
        continue;
      }
      const r = routeById[leg.route_id];
      const ids = new Set(leg.stops.map((s) => s.id));
      // draw only the ridden part of the route
      const seg = r ? sliceRoute(r, leg.board.id, leg.alight.id) : leg.stops.map((s) => [s.lat, s.lng] as [number, number]);
      mapRoutes.push({ id: leg.route_id, color: leg.color, path: seg, label: `${leg.route_code}${leg.towards ? ` → ${leg.towards}` : ""}` });
      // a transfer stop ends one ride and starts the next: show it once
      stopsOnMap.push(...leg.stops.filter((s) => ids.has(s.id) && !stopsOnMap.some((m) => m.id === s.id)));
      hl.push(leg.board.id, leg.alight.id);
    }
  } else if (!result) {
    // network view: every route in its own colour
    (routes.data || []).forEach((r) => mapRoutes.push({ id: r.id, color: r.color, path: r.path, weight: 4 }));
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
          <PlaceInput value={from} onChange={setFrom} placeholder="Starting point (stop or any place)" allowPlaces icon="origin" onLocate={geo.locate} locating={geo.busy}
            onVoiceJourney={trip.start}
            onPickMap={() => setPicking(picking === "from" ? null : "from")} picking={picking === "from"} />
          <div className="flex justify-center -my-1">
            <button className="rounded-full border border-slate-200 bg-white p-1.5 text-slate-500 hover:bg-slate-50" aria-label="Swap" onClick={() => { setFrom(to); setTo(from); }}>
              <ArrowDownUp className="h-4 w-4" />
            </button>
          </div>
          <PlaceInput value={to} onChange={setTo} placeholder="Destination (stop or any place)" allowPlaces icon="destination" onVoiceJourney={trip.start}
            onPickMap={() => setPicking(picking === "to" ? null : "to")} picking={picking === "to"} />
          <VoiceTripPanel trip={trip} />
          <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Route preference">
            {PREFS.map((p) => (
              <button key={p.id} type="button" role="radio" aria-checked={prefer === p.id}
                onClick={() => { setPrefer(p.id); if (from && to) search(from, to, p.id); }}
                className={`rounded-full border px-2.5 py-1 text-xs font-medium ${prefer === p.id ? "border-brand-600 bg-brand-600 text-white" : "border-slate-200 bg-white text-slate-700 hover:border-brand-400"}`}>
                {prefer === p.id ? "✓ " : ""}{p.label}
              </button>
            ))}
          </div>
          {picking && <p className="text-xs text-accent-600">Tap the map to set the {picking === "from" ? "starting point" : "destination"}.</p>}
          {geo.busy && autoRun && <p className="flex items-center gap-1 text-xs text-brand-700"><LocateFixed className="h-3.5 w-3.5 animate-pulse" /> Finding your location…</p>}
          {geo.error && <p className="text-xs text-red-600">{geo.error}. Type your starting point instead.</p>}
          <Button className="w-full" onClick={() => search()} loading={busy}>Find routes</Button>
          {error && <ErrorBox error={error} />}
        </Card>

        {result && (
          <Card className="p-4">
            <SectionTitle action={<button className="text-sm text-brand-600" onClick={() => setResult(null)}>Clear</button>}>
              {result.options.length ? (result.options.length > 1 ? `Best trip + ${result.options.length - 1} other${result.options.length > 2 ? "s" : ""}` : "Best trip")
                : result.status === "outside_coverage" ? "Outside the Speedo area"
                : result.status === "data_unavailable" ? "Route data unavailable" : "No connection found"}
            </SectionTitle>
            {savedAt && (
              <p role="status" className="mb-2 rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs text-white">
                Saved trip from {new Date(savedAt).toLocaleString("en-PK", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}{" "}
                (no internet). Routes may have changed since; check again when you are online.
              </p>
            )}
            {option && (() => {
              const ride = option.legs.find((l): l is PlanLegRide => l.type === "ride");
              const walk = option.legs[0]?.type === "walk" ? option.legs[0] : null;
              if (!ride) return null;
              return (
                <div className="mb-3 rounded-xl border border-brand-100 bg-brand-50/60 p-3">
                  <div className="text-xs font-semibold uppercase tracking-wide text-brand-700">Your stop for this trip</div>
                  <div className="mt-0.5 text-base font-bold text-brand-900">{ride.board.name}</div>
                  <div className="text-xs text-slate-600">
                    {walk ? `${km(walk.distance_m)} away in a straight line · about ${Math.max(1, Math.round(walk.minutes))} min walk (estimate)` : "You are at the stop"}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <NextBus stopId={ride.board.id} routeId={ride.route_id} />
                    {walk && (
                      <a href={walkingDirectionsUrl(walk.from, ride.board)} target="_blank" rel="noreferrer"
                        className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-0.5 text-[11px] font-semibold text-brand-700 shadow-sm hover:bg-brand-50">
                        <Footprints className="h-3 w-3" /> Walking directions <ExternalLink className="h-3 w-3" />
                      </a>
                    )}
                  </div>
                  <div className="mt-2"><VoiceGuide trip={journeySpeech(option, result)} /></div>
                </div>
              );
            })()}
            {result.warnings?.map((w) => (
              <p key={w.code} className="mb-2 flex items-start gap-1.5 rounded-lg bg-amber-50 px-2.5 py-1.5 text-xs text-amber-800">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {w.message}
              </p>
            ))}
            {result.options.length > 0 && (
              <p className="mb-2 text-[11px] text-slate-500">
                Trip times are estimates from the route timetable. Walking is measured in a straight line.
                {meta?.demo_mode ? ` ${meta.notice}` : ""}
              </p>
            )}
            {result.options.length === 0 && result.status === "outside_coverage" && (
              <Empty>Speedo buses run in Lahore only. Choose a starting point and destination inside Lahore.</Empty>
            )}
            {result.options.length === 0 && result.status === "data_unavailable" && (
              <Empty>The route data could not be loaded right now. Please try again in a few minutes.</Empty>
            )}
            {result.options.length === 0 && (result.status ?? "no_route") === "no_route" && (
              <Empty>
                No Speedo connection found within {km(result.search_limits?.max_walk_m ?? 1500)} walking of these places and
                up to {result.search_limits?.max_transfers ?? 2} changes. There may still be a way: try a nearby main stop,
                or a different starting point.
              </Empty>
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
                      {o.recommended && <span className="rounded-full bg-emerald-50 px-2 py-0.5 text-[10px] font-bold uppercase text-emerald-700">Recommended</span>}
                      {o.transfers > 0 ? (
                        <span className="flex items-center gap-1 text-xs text-slate-500"><Repeat className="h-3 w-3" /> {o.transfers} change{o.transfers > 1 ? "s" : ""}</span>
                      ) : (
                        <span className="text-xs text-slate-500">No change</span>
                      )}
                      <span className="text-xs text-slate-500">· {km(o.walk_m)} walk</span>
                    </div>
                    <div className="text-right">
                      <div className="text-lg font-bold text-brand-800">~{o.total_minutes} min</div>
                      <div className="text-[11px] text-slate-400">timetable estimate incl. wait</div>
                      <div className="text-[11px] text-slate-400">Fare: {o.fare_pkr != null ? `Rs ${o.fare_pkr}` : "not available"}</div>
                    </div>
                  </div>
                  {i === chosen && (
                    <ol className="mt-3 space-y-2 border-l-2 border-slate-200 pl-3">
                      {o.legs.map((l, k) =>
                        l.type === "walk" ? (
                          <li key={k} className="text-sm text-slate-600">
                            <div className="flex items-center gap-2">
                              <Footprints className="h-4 w-4 text-slate-400" />
                              {l.transfer ? (
                                <span><b className="text-violet-700">Change bus:</b> walk {km(l.distance_m)} straight-line (~{Math.max(1, Math.round(l.minutes))} min, estimate) to {l.to.name}</span>
                              ) : (
                                <span>Walk {km(l.distance_m)} straight-line (~{Math.max(1, Math.round(l.minutes))} min, estimate) to {l.to.name}</span>
                              )}
                            </div>
                            <a href={walkingDirectionsUrl(l.from, l.to)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
                              className="ml-6 inline-flex items-center gap-1 text-xs text-brand-600 hover:underline">
                              Walking directions <ExternalLink className="h-3 w-3" />
                            </a>
                          </li>
                        ) : (
                          <li key={k} className="text-sm">
                            <button type="button" id={i === chosen ? `tl-${l.board.id}` : undefined}
                              onClick={(e) => { e.stopPropagation(); focusStop(l.board); }}
                              className={`flex w-full items-center gap-2 rounded-lg text-left font-medium text-slate-800 ${selStop === l.board.id ? "bg-amber-100 ring-2 ring-amber-400" : "hover:bg-slate-50"}`}>
                              <Bus className="h-4 w-4 shrink-0 text-brand-600" />
                              <span><span className={`mr-1 inline-flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold text-white ${k === o.legs.findIndex((x) => x.type === "ride") ? "bg-green-700" : "bg-violet-600"}`}>{k === o.legs.findIndex((x) => x.type === "ride") ? "B" : "T"}</span>
                                Board {l.route_code} at {l.board.name}</span>
                            </button>
                            {l.towards && <div className="ml-6 text-xs font-medium text-brand-700">Bus going towards {l.towards}</div>}
                            <div className="ml-6 text-xs text-slate-500">
                              {l.stop_count} stop{l.stop_count === 1 ? "" : "s"} · {km(l.distance_m)} · ~{Math.round(l.minutes)} min (timetable) · get off at{" "}
                              <button type="button" id={i === chosen ? `tl-${l.alight.id}` : undefined}
                                onClick={(e) => { e.stopPropagation(); focusStop(l.alight); }}
                                className={`rounded px-0.5 font-bold text-slate-800 ${selStop === l.alight.id ? "bg-amber-100 ring-2 ring-amber-400" : "hover:bg-slate-100"}`}>
                                {l.alight.name}
                              </button>
                            </div>
                            <div className="ml-6 mt-1"><NextBus stopId={l.board.id} routeId={l.route_id} /></div>
                            <div className="ml-6 mt-1 text-xs text-slate-500">
                              <button type="button" className="text-brand-600 hover:underline" aria-expanded={openLegs.has(k)}
                                onClick={(e) => { e.stopPropagation(); setOpenLegs((s0) => { const n = new Set(s0); if (n.has(k)) n.delete(k); else n.add(k); return n; }); }}>
                                {openLegs.has(k) ? "Hide stops" : `All ${l.stops.length} stops (incl. where you get on and off)`}
                              </button>
                              {openLegs.has(k) && (
                                <ol className="mt-1 space-y-0.5">
                                  {l.stops.map((st, n) => {
                                    const end = n === 0 || n === l.stops.length - 1;
                                    return (
                                      <li key={st.id}>
                                        <button type="button" id={i === chosen && !end ? `tl-${st.id}` : undefined}
                                          onClick={(e) => { e.stopPropagation(); focusStop(st); }}
                                          className={`flex w-full items-center gap-2 rounded px-1 py-0.5 text-left ${selStop === st.id ? "bg-amber-100 font-semibold text-slate-900" : "hover:bg-slate-50"} ${end ? "font-semibold text-slate-800" : ""}`}>
                                          <span className="w-5 shrink-0 text-right text-slate-400">{n + 1}.</span>
                                          <span className="min-w-0 flex-1 truncate">{st.name}</span>
                                          {n === 0 && <span className="text-[10px] uppercase text-green-700">get on</span>}
                                          {n === l.stops.length - 1 && <span className="text-[10px] uppercase text-orange-700">get off</span>}
                                        </button>
                                      </li>
                                    );
                                  })}
                                </ol>
                              )}
                            </div>
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
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      </aside>
      <div className="relative h-[45vh] lg:h-full lg:flex-1 order-1 lg:order-2">
        <MapView
          routes={mapRoutes}
          stops={stopsOnMap}
          highlightStopIds={hl}
          points={points}
          walks={walks}
          tripStops={tripStops}
          selectedStopId={selStop}
          focus={focus}
          onStopClick={fromMap}
          fitKey={option ? `opt-${chosen}-${result?.origin.lat}` : points.length ? points.map((p) => p.lat).join() : undefined}
          onMapClick={(lat, lng) => {
            if (!picking) return;
            const p = { label: `Pinned (${lat.toFixed(4)}, ${lng.toFixed(4)})`, lat, lng };
            if (picking === "from") setFrom(p);
            else setTo(p);
            setPicking(null);
          }}
        />
        {option && (
          <div className="pointer-events-none absolute bottom-2 left-2 z-[1000] max-w-[calc(100%-1rem)] rounded-lg bg-white/95 px-2.5 py-1.5 text-[11px] text-slate-700 shadow">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span><b className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-green-700 text-[10px] text-white">B</b> Get on</span>
              <span><b className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-violet-600 text-[10px] text-white">T</b> Change</span>
              <span><b className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-orange-700 text-[10px] text-white">A</b> Get off</span>
              <span><span className="tracking-widest text-slate-600">•••</span> Walk (straight line)</span>
            </div>
            <div className="mt-0.5 text-slate-500">Bus lines are drawn from the route data and may be approximate.</div>
          </div>
        )}
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
