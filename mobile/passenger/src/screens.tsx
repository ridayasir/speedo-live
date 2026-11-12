// Passenger screens: Home, Explore, Live Map, Favorites, Profile + detail screens.
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Alert, FlatList, Modal, Pressable, RefreshControl, ScrollView, Switch, Text, TextInput, View } from "react-native";
import MapView, { Marker, Polyline, UrlTile } from "react-native-maps";
import * as Location from "expo-location";
import { useFocusEffect, useNavigation } from "@react-navigation/native";
import { auth, del, fmtAgo, fmtDist, fmtEta, get, liveBuses, post, put } from "./api";
import { Badge, Button, C, Card, DemoBadge, ErrorText, Field, H, Loading, Muted, RouteChip, s, Section, StatusBadge } from "./ui";

const LAHORE = { latitude: 31.5204, longitude: 74.3587, latitudeDelta: 0.18, longitudeDelta: 0.18 };
type Place = { label: string; lat: number; lon: number; stop_id?: number };

function useApi<T>(path: string | null, deps: any[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    if (!path) return;
    setLoading(true);
    try { setData(await get<T>(path)); setError(null); } catch (e: any) { setError(e.message); } finally { setLoading(false); }
  }, [path, ...deps]);
  useEffect(() => { load(); }, [load]);
  return { data, error, loading, reload: load };
}

function useAuth() {
  const [, force] = useState(0);
  useEffect(() => { const off = auth.subscribe(() => force(x => x + 1)); return () => { off(); }; }, []);
  return auth.user;
}

export function DemoBanner() {
  const { data } = useApi<any>("/api/config");
  if (!data?.demo) return null;
  return <View style={s.demoBanner}><Text style={s.demoText}>DEMO MODE · simulated buses on sample routes, not real Speedo data</Text></View>;
}

function NetworkMap({ buses, routes, stops, highlight, onBus, onStop, style, region }: any) {
  return (
    <MapView style={style || { height: 300 }} initialRegion={region || LAHORE} mapType="none" showsUserLocation>
      <UrlTile urlTemplate="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maximumZ={19} flipY={false} />
      {(routes || []).map((r: any) => (
        <Polyline key={`r${r.id}`} coordinates={r.shape.map((p: number[]) => ({ latitude: p[0], longitude: p[1] }))}
          strokeColor={r.color} strokeWidth={highlight && highlight !== r.id ? 2 : 5} />
      ))}
      {(stops || []).map((st: any) => (
        <Marker key={`s${st.id}`} coordinate={{ latitude: st.lat, longitude: st.lon }} title={st.name} pinColor="navy" onCalloutPress={() => onStop?.(st.id)} />
      ))}
      {[...(buses?.values?.() || [])].filter((b: any) => b.position).map((b: any) => (
        <Marker key={`b${b.id}`} coordinate={{ latitude: b.position.lat, longitude: b.position.lon }} title={`Bus ${b.bus_number}`}
          description={`${b.route_code} · ${b.status}${b.next_stop ? ` · next ${b.next_stop.name} ${fmtEta(b.next_stop.eta_s)}` : ""}`}
          pinColor={["stale", "offline"].includes(b.status) ? "gray" : b.route_color || C.blue} onCalloutPress={() => onBus?.(b.id)} />
      ))}
    </MapView>
  );
}

function useNetwork() {
  const [routes, setRoutes] = useState<any[]>([]);
  useEffect(() => {
    (async () => {
      try {
        const list = await get<any[]>("/api/routes");
        setRoutes(await Promise.all(list.map(r => get(`/api/routes/${r.id}`))));
      } catch { /* offline */ }
    })();
  }, []);
  return routes;
}

function useLive(routeId?: number) {
  const [buses, setBuses] = useState<Map<number, any>>(new Map());
  useFocusEffect(useCallback(() => liveBuses(setBuses, routeId), [routeId]));
  return buses;
}

// ------------------------------------------------------------------ Home
export function HomeScreen() {
  const nav = useNavigation<any>();
  const buses = useLive();
  const [me, setMe] = useState<[number, number] | null>(null);
  const [from, setFrom] = useState<Place | null>(null);
  const [to, setTo] = useState<Place | null>(null);
  const center = me || [31.5204, 74.3587];
  const near = useApi<any[]>(`/api/stops?lat=${center[0]}&lon=${center[1]}&radius_m=3000&limit=5`, [me]);
  const routes = useApi<any[]>("/api/routes");
  const user = useAuth();
  const favs = useApi<any>(user ? "/api/me/favorites" : null, [user]);
  const counts = useMemo(() => {
    const l = [...buses.values()];
    return { active: l.filter(b => b.status === "active").length, delayed: l.filter(b => b.status === "delayed").length, stale: l.filter(b => ["stale", "offline"].includes(b.status)).length };
  }, [buses]);

  const locate = async () => {
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== "granted") return Alert.alert("Location", "Allow location to see stops near you.");
    const p = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.Balanced });
    setMe([p.coords.latitude, p.coords.longitude]);
    setFrom({ label: "My location", lat: p.coords.latitude, lon: p.coords.longitude });
  };

  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={false} onRefresh={() => { near.reload(); routes.reload(); }} />}>
      <H>Where are you going?</H>
      <Muted>Your Bus, Your Route, Your Time.</Muted>
      <Card style={{ marginTop: 12 }}>
        <PlacePicker label="From" value={from} onChange={setFrom} onLocate={locate} />
        <PlacePicker label="To" value={to} onChange={setTo} />
        <Button title="Find my bus" onPress={() => from && to ? nav.navigate("Plan", { from, to }) : Alert.alert("Choose start and destination")} />
      </Card>
      <Section>Live bus status</Section>
      <View style={[s.row, { gap: 8 }]}>
        {[["on the move", counts.active, C.ok], ["delayed", counts.delayed, C.warn], ["no recent GPS", counts.stale, C.ink3]].map(([l, n, c]: any) => (
          <Card key={l} style={{ flex: 1 }} onPress={() => nav.navigate("Live Map")}><Text style={{ fontSize: 24, fontWeight: "800", color: c }}>{n}</Text><Muted>{l}</Muted></Card>
        ))}
      </View>
      <View style={[s.row, { justifyContent: "space-between" }]}><Section>Nearby stops</Section><Pressable onPress={locate}><Text style={{ color: C.blue, fontWeight: "700" }}>Use my location</Text></Pressable></View>
      {!me && <Muted>Showing stops near central Lahore.</Muted>}
      {near.loading ? <Loading /> : (near.data || []).map(st => <StopRow key={st.id} stop={st} extra={`${fmtDist(st.distance_m)} away`} />)}
      {favs.data?.stops?.length ? <><Section>Favorite stops</Section>{favs.data.stops.map((st: any) => <StopRow key={st.id} stop={st} />)}</> : null}
      <Section>Popular routes</Section>
      {(routes.data || []).map(r => <RouteCard key={r.id} route={r} />)}
      <ErrorText text={near.error || routes.error} />
    </ScrollView>
  );
}

function PlacePicker({ label, value, onChange, onLocate }: { label: string; value: Place | null; onChange: (p: Place) => void; onLocate?: () => void }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const stops = useApi<any[]>(open ? `/api/stops?limit=100${q ? `&q=${encodeURIComponent(q)}` : ""}` : null, [q, open]);
  return (
    <View style={{ marginBottom: 10 }}>
      <Text style={s.label}>{label}</Text>
      <Pressable style={[s.input, { justifyContent: "center" }]} onPress={() => setOpen(true)} accessibilityRole="button" accessibilityLabel={`${label}: ${value?.label || "choose"}`}>
        <Text style={{ color: value ? C.ink : C.ink3 }}>{value?.label || "Choose a stop"}</Text>
      </Pressable>
      <Modal visible={open} animationType="slide" onRequestClose={() => setOpen(false)}>
        <View style={[s.screen, s.pad]}>
          <H>{label}</H>
          <TextInput style={s.input} placeholder="Search stops" value={q} onChangeText={setQ} autoFocus />
          {onLocate && <Button kind="plain" title="📍 My current location" onPress={() => { setOpen(false); onLocate(); }} />}
          <FlatList data={stops.data || []} keyExtractor={i => String(i.id)} renderItem={({ item }) => (
            <Card onPress={() => { onChange({ label: item.name, lat: item.lat, lon: item.lon, stop_id: item.id }); setOpen(false); }}>
              <Text style={s.title}>{item.name}</Text><View style={s.row}>{item.routes.map((r: any) => <RouteChip key={r.id} code={r.code} color={r.color} />)}</View>
            </Card>)} />
          <Button kind="plain" title="Cancel" onPress={() => setOpen(false)} />
        </View>
      </Modal>
    </View>
  );
}

function StopRow({ stop, extra }: { stop: any; extra?: string }) {
  const nav = useNavigation<any>();
  return (
    <Card onPress={() => nav.navigate("Stop", { id: stop.id, name: stop.name })}>
      <Text style={s.title}>{stop.name} {stop.name_ur ? <Text style={s.muted}>{stop.name_ur}</Text> : null}</Text>
      <View style={[s.row, { marginTop: 4 }]}>{(stop.routes || []).map((r: any) => <RouteChip key={r.id} code={r.code} color={r.color} />)}{extra ? <Muted>{extra}</Muted> : null}</View>
    </Card>
  );
}

function RouteCard({ route }: { route: any }) {
  const nav = useNavigation<any>();
  return (
    <Card onPress={() => nav.navigate("Route", { id: route.id, name: route.code })} style={{ borderLeftWidth: 5, borderLeftColor: route.color }}>
      <View style={s.row}><RouteChip code={route.code} color={route.color} /><DemoBadge show={route.is_demo} />{route.verified && <Badge text="Verified" fg={C.ok} bg={C.okBg} />}</View>
      <Text style={[s.title, { marginTop: 4 }]}>{route.name}</Text>
      <Muted>{route.stop_count} stops · {route.length_km} km · {route.active_buses ?? 0} live buses</Muted>
    </Card>
  );
}

// --------------------------------------------------------------- Explore
export function ExploreScreen() {
  const routes = useApi<any[]>("/api/routes");
  const nav = useNavigation<any>();
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={routes.loading} onRefresh={routes.reload} />}>
      <H>Routes</H>
      {(routes.data || []).map(r => <RouteCard key={r.id} route={r} />)}
      <Button kind="plain" title="Timetables" onPress={() => nav.navigate("Timetable", { routeId: routes.data?.[0]?.id })} />
      <ErrorText text={routes.error} />
    </ScrollView>
  );
}

export function RouteScreen({ route: navRoute }: any) {
  const { id } = navRoute.params;
  const nav = useNavigation<any>();
  const r = useApi<any>(`/api/routes/${id}`);
  const buses = useLive(id);
  if (!r.data) return r.error ? <View style={s.pad}><ErrorText text={r.error} /></View> : <Loading />;
  const d = r.data;
  return (
    <ScrollView style={s.screen}>
      <NetworkMap routes={[d]} stops={d.stops} buses={buses} onBus={(b: number) => nav.navigate("Bus", { id: b })} onStop={(sid: number) => nav.navigate("Stop", { id: sid })}
        region={{ latitude: d.stops[Math.floor(d.stops.length / 2)].lat, longitude: d.stops[Math.floor(d.stops.length / 2)].lon, latitudeDelta: 0.12, longitudeDelta: 0.12 }} />
      <View style={s.pad}>
        <View style={s.row}><RouteChip code={d.code} color={d.color} /><DemoBadge show={d.is_demo} /><FavButton kind="routes" id={id} /></View>
        <Text style={[s.title, { fontSize: 18, marginVertical: 6 }]}>{d.name}</Text>
        <Muted>{d.stop_count} stops · {d.length_km} km · source: {d.source || "not specified"}</Muted>
        {d.alerts.map((a: any) => <Card key={a.id} style={{ backgroundColor: C.warnBg, marginTop: 8 }}><Text style={s.title}>{a.title}</Text>{a.body ? <Muted>{a.body}</Muted> : null}</Card>)}
        <Button kind="plain" title="Timetable" onPress={() => nav.navigate("Timetable", { routeId: id })} />
        <Section>Stops</Section>
        {d.stops.map((st: any, i: number) => {
          const here = [...buses.values()].filter(b => b.next_stop?.id === st.id);
          return (
            <Card key={st.id} onPress={() => nav.navigate("Stop", { id: st.id, name: st.name })}>
              <Text style={s.title}>{i + 1}. {st.name}</Text>
              {here.map(b => <Muted key={b.id}>🚌 {b.bus_number} arriving in {fmtEta(b.next_stop.eta_s)}</Muted>)}
            </Card>
          );
        })}
      </View>
    </ScrollView>
  );
}

function FavButton({ kind, id }: { kind: "routes" | "stops"; id: number }) {
  const user = useAuth();
  const nav = useNavigation<any>();
  const favs = useApi<any>(user ? "/api/me/favorites" : null, [user]);
  const on = !!favs.data?.[kind]?.some((x: any) => x.id === id);
  return (
    <Pressable accessibilityRole="button" accessibilityLabel={on ? "Remove favorite" : "Add favorite"} onPress={async () => {
      if (!user) return nav.navigate("Profile");
      try { on ? await del(`/api/me/favorites/${kind}/${id}`) : await post(`/api/me/favorites/${kind}`, { id }); favs.reload(); } catch (e: any) { Alert.alert(e.message); }
    }}><Text style={{ fontSize: 22, color: on ? C.orange : C.ink3 }}>{on ? "★" : "☆"}</Text></Pressable>
  );
}

export function StopScreen({ route: navRoute }: any) {
  const { id } = navRoute.params;
  const nav = useNavigation<any>();
  const st = useApi<any>(`/api/stops/${id}`);
  const [tick, setTick] = useState(0);
  const arr = useApi<any>(`/api/stops/${id}/arrivals`, [tick]);
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), 15000); return () => clearInterval(t); }, []);
  const user = useAuth();
  const watch = async (routeId: number, busId?: number) => {
    if (!user) return nav.navigate("Profile");
    try { await post("/api/me/watches", { route_id: routeId, stop_id: id, bus_id: busId ?? null, lead_min: 5 }); Alert.alert("Alert set", "We'll notify you about 5 minutes before the bus arrives."); }
    catch (e: any) { Alert.alert(e.message); }
  };
  if (!st.data) return <Loading />;
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={arr.loading} onRefresh={arr.reload} />}>
      <View style={[s.row, { justifyContent: "space-between" }]}><H>{st.data.name}</H><FavButton kind="stops" id={id} /></View>
      <View style={s.row}>{st.data.routes.map((r: any) => <RouteChip key={r.id} code={r.code} color={r.color} />)}<DemoBadge show={st.data.is_demo} /></View>
      <Section>Live arrivals</Section>
      {(arr.data?.live || []).length ? arr.data.live.map((a: any) => (
        <Card key={`${a.bus_id}`} onPress={() => nav.navigate("Bus", { id: a.bus_id })}>
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <View style={s.row}><RouteChip code={a.route_code} color={a.route_color} /><Text style={s.title}>Bus {a.bus_number}</Text><DemoBadge show={a.is_demo} /></View>
            <Text style={{ fontSize: 18, fontWeight: "800", color: C.blue }}>{fmtEta(a.eta_s)}</Text>
          </View>
          <Muted>towards {a.towards} · {fmtDist(a.distance_m)} away · GPS {fmtAgo(a.last_gps_at)}</Muted>
          <Pressable onPress={() => watch(a.route_id, a.bus_id)}><Text style={{ color: C.blue, fontWeight: "700", marginTop: 6 }}>🔔 Notify me</Text></Pressable>
        </Card>
      )) : <Muted>No buses with live GPS are approaching right now.</Muted>}
      <Section>Timetable estimates</Section>
      {(arr.data?.scheduled || []).map((x: any, i: number) => (
        <Card key={i}><View style={s.row}><RouteChip code={x.route_code} color={x.route_color} /><Badge text="Scheduled" /><Text style={s.title}>{x.minutes <= 0 ? "Due" : `${x.minutes} min`}</Text></View>
          <Muted>towards {x.towards} · from the timetable, not live GPS</Muted></Card>
      ))}
      <ErrorText text={arr.error} />
    </ScrollView>
  );
}

export function BusScreen({ route: navRoute }: any) {
  const { id } = navRoute.params;
  const buses = useLive();
  const [tick, setTick] = useState(0);
  const b = useApi<any>(`/api/buses/${id}`, [tick]);
  useEffect(() => { const t = setInterval(() => setTick(x => x + 1), 10000); return () => clearInterval(t); }, []);
  const live = buses.get(id) || b.data;
  if (!live) return <Loading />;
  const pos = live.position;
  return (
    <ScrollView style={s.screen}>
      {pos ? <NetworkMap buses={new Map([[id, live]])} region={{ latitude: pos.lat, longitude: pos.lon, latitudeDelta: 0.03, longitudeDelta: 0.03 }} /> : null}
      <View style={s.pad}>
        <View style={s.row}><RouteChip code={live.route_code || "—"} color={live.route_color} /><Text style={[s.title, { fontSize: 20 }]}>Bus {live.bus_number}</Text><DemoBadge show={live.is_demo} /></View>
        <View style={[s.row, { marginVertical: 8 }]}><StatusBadge status={live.status} /><Muted>Last GPS {fmtAgo(live.last_gps_at)}</Muted></View>
        {["stale", "offline"].includes(live.status) && <Text style={{ color: C.warn }}>No recent GPS from this bus. Its position may be out of date and ETAs are paused.</Text>}
        <Section>Upcoming stops</Section>
        {(b.data?.upcoming_stops || []).map((u: any) => (
          <Card key={u.stop_id}><View style={[s.row, { justifyContent: "space-between" }]}><Text style={s.title}>{u.name}</Text><Text style={{ fontWeight: "800", color: C.blue }}>{fmtEta(u.eta_s)}</Text></View>
            <Muted>{fmtDist(u.distance_m)}</Muted></Card>
        ))}
      </View>
    </ScrollView>
  );
}

export function PlanScreen({ route: navRoute }: any) {
  const { from, to } = navRoute.params as { from: Place; to: Place };
  const nav = useNavigation<any>();
  const [plan, setPlan] = useState<any>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    const p = (x: Place) => x.stop_id ? { stop_id: x.stop_id, label: x.label } : { lat: x.lat, lon: x.lon, label: x.label };
    post("/api/journeys/plan", { origin: p(from), destination: p(to) }).then(setPlan).catch(e => setErr(e.message));
  }, []);
  if (err) return <View style={s.pad}><ErrorText text={err} /></View>;
  if (!plan) return <Loading />;
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>{from.label} → {to.label}</H>
      {!plan.options.length && <Muted>{plan.message}</Muted>}
      {plan.options.map((o: any, i: number) => (
        <Card key={i}>
          <View style={s.row}><Text style={{ fontSize: 22, fontWeight: "800", color: C.blue }}>{o.total_min} min</Text><Muted>{o.type === "transfer" ? "1 transfer" : "Direct"} · {fmtDist(o.walk_m)} walk</Muted></View>
          {o.legs.map((l: any, j: number) => l.kind === "ride" ? (
            <View key={j} style={{ borderLeftWidth: 4, borderLeftColor: l.route.color, paddingLeft: 10, marginTop: 8 }}>
              <View style={s.row}><RouteChip code={l.route.code} color={l.route.color} /><Text style={s.title}>Board at {l.board.name}</Text></View>
              <Muted>Towards {l.towards} · {l.stop_count} stops · {Math.round(l.ride_min)} min · get off at {l.alight.name}</Muted>
              <Muted>{l.next_bus.method === "live" ? `Next bus ${l.next_bus.bus_number}: ${fmtEta(l.next_bus.eta_s)} (live)` : l.next_bus.method === "scheduled" ? `Next scheduled in ${fmtEta(l.next_bus.eta_s)}` : l.next_bus.note}</Muted>
            </View>
          ) : l.kind === "transfer" ? <Muted key={j}>⇄ Change at {l.at}</Muted> : l.distance_m > 30 ? <Muted key={j}>🚶 Walk {fmtDist(l.distance_m)} to {l.to}</Muted> : null)}
          <Button title="Start tracking" onPress={async () => {
            const ride = o.legs.find((l: any) => l.kind === "ride");
            if (auth.user) post("/api/me/watches", { route_id: ride.route.id, stop_id: ride.board.id, lead_min: 5 }).catch(() => {});
            ride.next_bus.bus_id ? nav.navigate("Bus", { id: ride.next_bus.bus_id }) : nav.navigate("Stop", { id: ride.board.id });
          }} />
        </Card>
      ))}
    </ScrollView>
  );
}

export function TimetableScreen({ route: navRoute }: any) {
  const routes = useApi<any[]>("/api/routes");
  const [routeId, setRouteId] = useState<number | undefined>(navRoute.params?.routeId);
  const rid = routeId ?? routes.data?.[0]?.id;
  const t = useApi<any>(rid ? `/api/timetable?route_id=${rid}` : null, [rid]);
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>Timetable</H>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        {(routes.data || []).map(r => <Pressable key={r.id} onPress={() => setRouteId(r.id)} style={{ marginRight: 6, opacity: r.id === rid ? 1 : 0.5 }}><RouteChip code={r.code} color={r.color} /></Pressable>)}
      </ScrollView>
      {t.data ? <>
        {t.data.schedules.some((x: any) => x.is_demo) && <Text style={{ color: C.orange, marginTop: 8 }}>Demonstration timetable, not official.</Text>}
        <Card style={{ marginTop: 10 }}>
          <Text style={s.title}>{t.data.operates_today ? "Operating today" : "No service today"}</Text>
          <Muted>First {t.data.first_departure || "—"} · Last {t.data.last_departure || "—"} · {t.data.trips_today} departures</Muted>
          {t.data.schedules.map((x: any) => <Muted key={x.id}>{x.days.replaceAll(",", " ")} · every {x.headway_min} min</Muted>)}
        </Card>
        {["outbound", "inbound"].map(dir => (
          <View key={dir}><Section>{t.data.directions[dir].from} → {t.data.directions[dir].to}</Section>
            {t.data.directions[dir].stops.map((x: any) => <View key={x.stop_id} style={[s.row, { justifyContent: "space-between", paddingVertical: 6 }]}>
              <Text style={{ flex: 1 }}>{x.name}</Text><Muted>{x.first || "—"} – {x.last || "—"}</Muted></View>)}
          </View>
        ))}
      </> : <Loading />}
    </ScrollView>
  );
}

// -------------------------------------------------------------- Live map
export function LiveMapScreen() {
  const nav = useNavigation<any>();
  const routes = useNetwork();
  const buses = useLive();
  const list = [...buses.values()].sort((a, b) => a.bus_number.localeCompare(b.bus_number));
  return (
    <View style={s.screen}>
      <NetworkMap style={{ flex: 1 }} routes={routes} stops={routes.flatMap(r => r.stops)} buses={buses}
        onBus={(id: number) => nav.navigate("Bus", { id })} onStop={(id: number) => nav.navigate("Stop", { id })} />
      <FlatList style={{ maxHeight: 220 }} contentContainerStyle={{ padding: 10 }} data={list} keyExtractor={b => String(b.id)} renderItem={({ item }) => (
        <Card onPress={() => nav.navigate("Bus", { id: item.id })}>
          <View style={[s.row, { justifyContent: "space-between" }]}><View style={s.row}><RouteChip code={item.route_code} color={item.route_color} /><Text style={s.title}>{item.bus_number}</Text></View><StatusBadge status={item.status} /></View>
          <Muted>{item.next_stop ? `Next: ${item.next_stop.name} · ${fmtEta(item.next_stop.eta_s)}` : ""} · GPS {fmtAgo(item.last_gps_at)}</Muted>
        </Card>)} />
    </View>
  );
}

// ------------------------------------------------------------- Favorites
export function FavoritesScreen() {
  const user = useAuth();
  const nav = useNavigation<any>();
  const favs = useApi<any>(user ? "/api/me/favorites" : null, [user]);
  useFocusEffect(useCallback(() => { favs.reload(); }, [user]));
  if (!user) return <View style={[s.screen, s.pad]}><H>Favorites</H><Muted>Sign in to save routes and stops.</Muted><Button title="Sign in" onPress={() => nav.navigate("Profile")} /></View>;
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>Favorites</H>
      <Section>Routes</Section>
      {(favs.data?.routes || []).map((r: any) => <RouteCard key={r.id} route={r} />)}
      <Section>Stops</Section>
      {(favs.data?.stops || []).map((st: any) => <StopRow key={st.id} stop={st} />)}
      {!favs.loading && !favs.data?.routes?.length && !favs.data?.stops?.length && <Muted>Tap ☆ on a route or stop to save it here.</Muted>}
    </ScrollView>
  );
}

// --------------------------------------------------------------- Profile
export function ProfileScreen({ registerPush }: { registerPush: () => Promise<void> }) {
  const user = useAuth();
  if (!user) return <AuthForm />;
  return <Account registerPush={registerPush} />;
}

function AuthForm() {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ identifier: "", name: "", email: "", phone: "", password: "" });
  const [err, setErr] = useState<string | null>(null);
  const submit = async () => {
    setErr(null);
    try {
      const r = mode === "login" ? await post("/api/auth/login", { identifier: f.identifier, password: f.password })
        : await post("/api/auth/register", { name: f.name, email: f.email || null, phone: f.phone || null, password: f.password });
      await auth.set(r.token, r.user);
    } catch (e: any) { setErr(e.message); }
  };
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} keyboardShouldPersistTaps="handled">
      <H>{mode === "login" ? "Sign in" : "Create account"}</H>
      <Muted>Find routes and track buses without an account. Sign in for favorites, history and arrival alerts.</Muted>
      <View style={{ height: 12 }} />
      {mode === "login" ? <Field label="Email or phone" autoCapitalize="none" value={f.identifier} onChangeText={v => setF({ ...f, identifier: v })} /> : <>
        <Field label="Full name" value={f.name} onChangeText={v => setF({ ...f, name: v })} />
        <Field label="Email" autoCapitalize="none" keyboardType="email-address" value={f.email} onChangeText={v => setF({ ...f, email: v })} />
        <Field label="Mobile number" keyboardType="phone-pad" placeholder="03001234567" value={f.phone} onChangeText={v => setF({ ...f, phone: v })} />
      </>}
      <Field label="Password" secureTextEntry value={f.password} onChangeText={v => setF({ ...f, password: v })} />
      <ErrorText text={err} />
      <Button title={mode === "login" ? "Sign in" : "Create account"} onPress={submit} />
      <Button kind="plain" title={mode === "login" ? "New here? Create an account" : "I already have an account"} onPress={() => setMode(mode === "login" ? "register" : "login")} />
    </ScrollView>
  );
}

function Account({ registerPush }: { registerPush: () => Promise<void> }) {
  const prefs = useApi<any>("/api/me/notification-preferences");
  const inbox = useApi<any>("/api/me/notifications?limit=20");
  const hist = useApi<any[]>("/api/me/history?limit=10");
  const [p, setP] = useState<any>(null);
  useEffect(() => { if (prefs.data) setP(prefs.data); }, [prefs.data]);
  useEffect(() => { registerPush().catch(() => {}); }, []);
  const save = async (next: any) => { setP(next); const { user_id, ...body } = next; try { await put("/api/me/notification-preferences", body); } catch (e: any) { Alert.alert(e.message); } };
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={inbox.loading} onRefresh={inbox.reload} />}>
      <H>{auth.user.name}</H>
      <Muted>{auth.user.email || auth.user.phone}</Muted>
      <Section>Notifications</Section>
      {p && [["approaching", "Bus approaching my stop"], ["delays", "Delays on favorite routes"], ["disruptions", "Service disruptions"], ["schedule_changes", "Timetable changes"]].map(([k, l]) => (
        <View key={k} style={[s.row, { justifyContent: "space-between", paddingVertical: 6 }]}><Text>{l}</Text><Switch value={p[k]} onValueChange={v => save({ ...p, [k]: v })} trackColor={{ true: C.blue }} /></View>
      ))}
      <Section>Inbox</Section>
      {(inbox.data?.items || []).map((n: any) => <Card key={n.id}><Text style={s.title}>{n.title}</Text><Muted>{n.body} · {fmtAgo(n.created_at)}</Muted></Card>)}
      {!inbox.data?.items?.length && <Muted>No notifications yet.</Muted>}
      <Section>Journey history</Section>
      {(hist.data || []).map((x: any) => <Card key={x.id}><Text style={s.title}>{x.origin_label} → {x.dest_label}</Text><Muted>{x.route_codes} · {fmtAgo(x.created_at)}</Muted></Card>)}
      <Button kind="plain" title="Sign out" onPress={async () => { try { await post("/api/auth/logout"); } catch { /* ignore */ } await auth.clear(); }} />
    </ScrollView>
  );
}
