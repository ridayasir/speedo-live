import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { useNavigation } from "@react-navigation/native";
import LiveMap, { type MapLine } from "../components/LiveMap";
import { Btn, Card, Demo, ErrorText, Loading, Muted, RouteChip, Section, s } from "../components/ui";
import { api } from "../lib/api";
import { km } from "../lib/format";
import { useAuth, useFetch, useMyLocation } from "../lib/hooks";
import { C } from "../lib/theme";
import type { PlanLegRide, PlanResult, RouteDetail, Stop } from "../lib/types";

interface Place { label: string; lat: number; lng: number; stop_id?: number }

function PlaceField({ value, onChange, placeholder, dot }: { value: Place | null; onChange: (p: Place | null) => void; placeholder: string; dot: string }) {
  const [q, setQ] = useState(value?.label || "");
  const [res, setRes] = useState<Stop[]>([]);
  useEffect(() => setQ(value?.label || ""), [value]);
  useEffect(() => {
    if (q.trim().length < 2 || q === value?.label) return setRes([]);
    const t = setTimeout(() => api<Stop[]>(`/api/stops?q=${encodeURIComponent(q.trim())}&limit=6`).then(setRes).catch(() => setRes([])), 250);
    return () => clearTimeout(t);
  }, [q, value]);
  return (
    <View style={{ marginBottom: 8 }}>
      <View style={[s.row, { borderWidth: 1, borderColor: C.border, borderRadius: 12, paddingHorizontal: 10, backgroundColor: "#fff" }]}>
        <View style={{ width: 10, height: 10, borderRadius: 5, backgroundColor: dot, marginRight: 8 }} />
        <TextInput value={q} onChangeText={(t) => { setQ(t); if (!t) onChange(null); }} placeholder={placeholder} placeholderTextColor="#94a3b8" style={{ flex: 1, paddingVertical: 10, fontSize: 15 }} />
      </View>
      {res.map((st) => (
        <Pressable key={st.id} onPress={() => { onChange({ label: st.name, lat: st.lat, lng: st.lng, stop_id: st.id }); setRes([]); }} style={{ paddingVertical: 8, paddingHorizontal: 12, backgroundColor: "#fff", borderBottomWidth: 1, borderColor: "#f1f5f9" }}>
          <Text>📍 {st.name}</Text>
        </Pressable>
      ))}
    </View>
  );
}

export default function ExploreScreen() {
  const nav = useNavigation<any>();
  const { user } = useAuth();
  const loc = useMyLocation();
  const [from, setFrom] = useState<Place | null>(null);
  const [to, setTo] = useState<Place | null>(null);
  const [picking, setPicking] = useState<"from" | "to" | null>(null);
  const [res, setRes] = useState<PlanResult | null>(null);
  const [chosen, setChosen] = useState(0);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const routes = useFetch<RouteDetail[]>("/api/routes?with_path=true");

  useEffect(() => {
    if (loc.pos && !from) setFrom({ label: "My location", ...loc.pos });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loc.pos]);

  const search = async () => {
    if (!from || !to) return setErr("Choose a starting point and a destination.");
    setBusy(true);
    setErr(null);
    try {
      const r = await api<PlanResult>("/api/plan", { method: "POST", json: {
        from_lat: from.lat, from_lng: from.lng, from_stop_id: from.stop_id, from_label: from.label,
        to_lat: to.lat, to_lng: to.lng, to_stop_id: to.stop_id, to_label: to.label } });
      setRes(r);
      setChosen(0);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const opt = res?.options[chosen];
  const rides = (opt?.legs.filter((l) => l.type === "ride") || []) as PlanLegRide[];
  const lines: MapLine[] = opt
    ? rides.map((l) => ({ id: l.route_id, color: l.color, path: l.stops.map((x) => [x.lat, x.lng] as [number, number]) }))
    : (routes.data || []).map((r) => ({ id: r.id, color: r.color, path: r.path, dim: true }));
  const points = [
    ...(from ? [{ lat: from.lat, lng: from.lng, label: from.label, kind: "origin" as const }] : []),
    ...(to ? [{ lat: to.lat, lng: to.lng, label: to.label, kind: "destination" as const }] : []),
  ];

  const startTracking = async () => {
    if (!rides.length) return;
    if (user) {
      await api("/api/me/journeys", { method: "POST", json: { route_id: rides[0].route_id, from_stop_id: rides[0].board.id, to_stop_id: rides[rides.length - 1].alight.id } }).catch(() => {});
      await api("/api/me/watches", { method: "POST", json: { stop_id: rides[0].board.id, route_id: rides[0].route_id, minutes_before: user.notification_prefs?.arrival_minutes_before || 5 } }).catch(() => {});
    }
    nav.navigate("Stop", { id: rides[0].board.id, routeId: rides[0].route_id, tracking: true });
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} keyboardShouldPersistTaps="handled">
      <LiveMap height={240} lines={lines} points={points} stops={rides.flatMap((l) => l.stops)} fitKey={opt ? `o${chosen}${res?.origin.lat}` : points.map((p) => p.lat).join()}
        onMapPress={(lat, lng) => {
          if (!picking) return;
          const p = { label: `Pinned point`, lat, lng };
          if (picking === "from") setFrom(p);
          else setTo(p);
          setPicking(null);
        }} />
      <View style={{ padding: 14 }}>
        <Card>
          <Section>Plan your journey</Section>
          <PlaceField value={from} onChange={setFrom} placeholder="Starting stop" dot="#16a34a" />
          <PlaceField value={to} onChange={setTo} placeholder="Destination stop" dot={C.accent} />
          <View style={[s.row, { gap: 12, marginBottom: 10, flexWrap: "wrap" }]}>
            <Text onPress={loc.locate} style={{ color: C.brand, fontWeight: "600" }}>{loc.busy ? "Locating…" : "◎ Use my location"}</Text>
            <Text onPress={() => setPicking("from")} style={{ color: picking === "from" ? C.accent : C.brand, fontWeight: "600" }}>Pick start on map</Text>
            <Text onPress={() => setPicking("to")} style={{ color: picking === "to" ? C.accent : C.brand, fontWeight: "600" }}>Pick destination on map</Text>
          </View>
          {picking && <Muted>Tap the map above.</Muted>}
          {loc.error && <ErrorText error={loc.error} />}
          <Btn title="Find routes" onPress={search} loading={busy} />
          {err && <ErrorText error={err} />}
        </Card>

        {res && (
          <Card>
            <Section>{res.options.length ? `${res.options.length} option(s)` : "No routes found"}</Section>
            {res.nearest_boarding_stop && <Muted>Nearest boarding stop: {res.nearest_boarding_stop.name} ({km(res.nearest_boarding_stop.walk_m)} walk)</Muted>}
            {res.options.length === 0 && <Muted>No Speedo route connects these places within walking distance.</Muted>}
            {res.options.map((o, i) => (
              <Pressable key={i} onPress={() => setChosen(i)} style={{ borderWidth: 1, borderColor: i === chosen ? C.brand : C.border, borderRadius: 12, padding: 10, marginTop: 8 }}>
                <View style={[s.row, { gap: 6 }]}>
                  {(o.legs.filter((l) => l.type === "ride") as PlanLegRide[]).map((l, k) => <RouteChip key={k} code={l.route_code} color={l.color} />)}
                  {o.is_demo && <Demo />}
                  <View style={{ flex: 1 }} />
                  <Text style={{ fontSize: 18, fontWeight: "800", color: C.brandDark }}>~{o.total_minutes} min</Text>
                </View>
                {o.transfers > 0 && <Muted>{o.transfers} transfer</Muted>}
                {i === chosen && o.legs.map((l, k) => (
                  <Text key={k} style={{ marginTop: 6, fontSize: 13 }}>
                    {l.type === "walk"
                      ? `🚶 Walk ${km(l.distance_m)} (~${Math.round(l.minutes)} min) to ${l.to.name}`
                      : `🚌 ${l.route_code}: board at ${l.board.name}, ${l.stop_count} stops (~${Math.round(l.minutes)} min), get off at ${l.alight.name}`}
                  </Text>
                ))}
              </Pressable>
            ))}
            {opt && <View style={{ marginTop: 10 }}><Btn title="Select route and start tracking" variant="accent" onPress={startTracking} /></View>}
          </Card>
        )}

        <Card>
          <Section>All routes</Section>
          {routes.loading && <Loading />}
          {routes.data?.map((r) => (
            <Pressable key={r.id} onPress={() => nav.navigate("Route", { id: r.id })} style={[s.row, { gap: 8, paddingVertical: 8 }]}>
              <RouteChip code={r.code} color={r.color} />
              <Text style={{ flex: 1, fontSize: 13 }} numberOfLines={1}>{r.name}</Text>
            </Pressable>
          ))}
        </Card>
      </View>
    </ScrollView>
  );
}
