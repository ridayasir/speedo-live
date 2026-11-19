import { useEffect, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import LiveMap from "../components/LiveMap";
import { Btn, Card, Demo, ErrorText, Loading, Muted, RouteChip, Section, s } from "../components/ui";
import { api } from "../lib/api";
import { ago, clock, km } from "../lib/format";
import { useAuth, useFetch, useLiveBuses } from "../lib/hooks";
import { C } from "../lib/theme";
import type { Alert, Arrivals, RouteSummary, Stop } from "../lib/types";
import type { RootStack } from "../../App";

type Props = NativeStackScreenProps<RootStack, "Stop">;
type StopDetail = Stop & { routes: RouteSummary[]; alerts: Alert[] };

export default function StopScreen({ route, navigation }: Props) {
  const { id, routeId: initialRoute, tracking } = route.params;
  const { user } = useAuth();
  const [routeId, setRouteId] = useState<number | undefined>(initialRoute);
  const [tick, setTick] = useState(0);
  const [fav, setFav] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const stop = useFetch<StopDetail>(`/api/stops/${id}`);
  const arr = useFetch<Arrivals>(`/api/stops/${id}/arrivals${routeId ? `?route_id=${routeId}` : ""}`, [tick]);
  const { buses } = useLiveBuses(stop.data ? (routeId ? [routeId] : stop.data.routes.map((r) => r.id)) : [-1]);

  useEffect(() => {
    const t = setInterval(() => setTick((x) => x + 1), 15000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (stop.data) navigation.setOptions({ title: stop.data.name });
    if (user) api<{ stops: Stop[] }>("/api/me/favorites").then((f) => setFav(f.stops.some((x) => x.id === id))).catch(() => {});
  }, [stop.data, user, id, navigation]);

  if (stop.loading) return <Loading />;
  if (stop.error || !stop.data) return <ErrorText error={stop.error || "Stop not found"} onRetry={stop.reload} />;
  const st = stop.data;

  const toggleFav = async () => {
    await api(`/api/me/favorites/stops/${id}`, { method: fav ? "DELETE" : "PUT" });
    setFav(!fav);
  };
  const watch = async () => {
    try {
      await api("/api/me/watches", { method: "POST", json: { stop_id: id, route_id: routeId || st.routes[0].id, minutes_before: user?.notification_prefs?.arrival_minutes_before || 5 } });
      setMsg("We'll notify you when a bus is a few minutes away.");
    } catch (e) {
      setMsg((e as Error).message);
    }
  };

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }}>
      <LiveMap height={200} stops={[st]} buses={buses} fitKey={`s${id}`} />
      <View style={{ padding: 14 }}>
        <View style={[s.row, { marginBottom: 8 }]}>
          <Text style={{ fontSize: 20, fontWeight: "800", color: C.brandDark, flex: 1 }}>{st.name}</Text>
          {st.is_demo && <Demo />}
        </View>
        {tracking && <Muted style={{ marginBottom: 8 }}>Tracking your bus to this stop.{user ? " You'll be notified as it approaches." : ""}</Muted>}
        {user && (
          <View style={[s.row, { gap: 8, marginBottom: 10 }]}>
            <View style={{ flex: 1 }}><Btn small variant="outline" title={fav ? "★ Saved" : "☆ Save stop"} onPress={toggleFav} /></View>
            <View style={{ flex: 1 }}><Btn small variant="accent" title="Notify me" onPress={watch} /></View>
          </View>
        )}
        {msg && <Muted style={{ marginBottom: 8 }}>{msg}</Muted>}
        {st.alerts.map((a) => (
          <View key={a.id} style={{ backgroundColor: C.amberBg, padding: 10, borderRadius: 12, marginBottom: 8 }}>
            <Text style={{ fontWeight: "700" }}>{a.title}</Text><Text>{a.message}</Text>
          </View>
        ))}
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ marginBottom: 10 }} contentContainerStyle={{ gap: 6 }}>
          <Pressable onPress={() => setRouteId(undefined)} style={[chip, !routeId && chipOn]}><Text style={{ color: !routeId ? "#fff" : C.text }}>All</Text></Pressable>
          {st.routes.map((r) => (
            <Pressable key={r.id} onPress={() => setRouteId(r.id)} style={[chip, routeId === r.id && chipOn]}><Text style={{ color: routeId === r.id ? "#fff" : C.text }}>{r.code}</Text></Pressable>
          ))}
        </ScrollView>
        <Card>
          <Section>Live GPS estimates</Section>
          {arr.loading && !arr.data && <Loading />}
          {arr.error && <ErrorText error={arr.error} onRetry={arr.reload} />}
          {arr.data?.live.length === 0 && <Muted>No bus with a current GPS signal is heading here right now.</Muted>}
          {arr.data?.live.slice(0, 6).map((a) => (
            <View key={a.trip_id} style={[s.row, { paddingVertical: 8, borderBottomWidth: 1, borderColor: "#f1f5f9" }]}>
              <View style={{ flex: 1 }}>
                <View style={s.row}><Text style={{ fontWeight: "700" }}>{a.bus_number}</Text><Muted>  {a.route_code}</Muted>{a.is_demo && <Demo />}</View>
                <Muted>{km(a.distance_m)} away · GPS {ago(a.last_gps_at)}</Muted>
              </View>
              <View style={{ alignItems: "flex-end" }}>
                <Text style={{ fontSize: 20, fontWeight: "800", color: C.brand }}>{a.minutes <= 0 ? "Now" : `${a.minutes} min`}</Text>
                <Muted>{clock(a.eta)}</Muted>
              </View>
            </View>
          ))}
        </Card>
        <Card>
          <Section>Scheduled (timetable, not live)</Section>
          {arr.data?.scheduled.length === 0 && <Muted>No more scheduled departures today.</Muted>}
          <View style={[s.row, { flexWrap: "wrap", gap: 6 }]}>
            {arr.data?.scheduled.map((a, i) => (
              <Text key={i} style={{ backgroundColor: "#f1f5f9", borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4, fontSize: 12 }}>
                {a.route_code} {clock(a.eta)} ({a.minutes} min)
              </Text>
            ))}
          </View>
        </Card>
        <Card>
          <Section>Routes at this stop</Section>
          {st.routes.map((r) => (
            <Pressable key={r.id} onPress={() => navigation.navigate("Route", { id: r.id })} style={[s.row, { gap: 8, paddingVertical: 6 }]}>
              <RouteChip code={r.code} color={r.color} /><Text style={{ flex: 1, fontSize: 13 }}>{r.name}</Text>
            </Pressable>
          ))}
        </Card>
      </View>
    </ScrollView>
  );
}

const chip = { borderWidth: 1, borderColor: C.border, backgroundColor: "#fff", borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6 };
const chipOn = { backgroundColor: C.brand, borderColor: C.brand };
