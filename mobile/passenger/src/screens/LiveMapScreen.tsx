import { useEffect, useMemo, useState } from "react";
import { Pressable, ScrollView, Text, View } from "react-native";
import { useNavigation, useRoute } from "@react-navigation/native";
import LiveMap from "../components/LiveMap";
import { Card, Demo, Loading, Muted, RouteChip, StatusPill, s } from "../components/ui";
import { ago, effectiveStatus, km } from "../lib/format";
import { useFetch, useLiveBuses } from "../lib/hooks";
import { C } from "../lib/theme";
import type { BusState, RouteDetail } from "../lib/types";

interface BusDetail extends BusState {
  upcoming_stops: { stop_id: number; name: string; distance_m: number; minutes: number | null }[];
}

export default function LiveMapScreen() {
  const nav = useNavigation<any>();
  const route = useRoute<any>();
  const [routeId, setRouteId] = useState<number | null>(route.params?.routeId ?? null);
  const [sel, setSel] = useState<number | null>(route.params?.busId ?? null);
  useEffect(() => {
    if (route.params?.busId) setSel(route.params.busId);
    if (route.params?.routeId) setRouteId(route.params.routeId);
  }, [route.params]);
  const routes = useFetch<RouteDetail[]>("/api/routes?with_path=true");
  const { buses, conn } = useLiveBuses();
  const byId = useMemo(() => Object.fromEntries((routes.data || []).map((r) => [r.id, r])), [routes.data]);
  const shown = buses.filter((b) => !routeId || b.route_id === routeId).sort((a, b) => a.bus_number.localeCompare(b.bus_number));
  const bus = buses.find((b) => b.bus_id === sel);
  const detail = useFetch<BusDetail>(sel ? `/api/buses/${sel}` : null, [bus?.last_gps_at]);
  const focus = routeId ? byId[routeId] : bus?.route_id ? byId[bus.route_id] : undefined;
  const st = bus ? effectiveStatus(bus) : null;
  const live = st === "active" || st === "delayed";

  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <View style={{ height: "52%" }}>
        <LiveMap
          buses={shown}
          lines={(routes.data || []).filter((r) => !routeId || r.id === routeId).map((r) => ({ id: r.id, color: r.color, path: r.path, dim: !focus || r.id !== focus.id }))}
          stops={focus?.stops || []}
          selectedBusId={sel}
          fitKey={routeId ? `r${routeId}` : undefined}
          onBusPress={setSel}
          onStopPress={(id) => nav.navigate("Stop", { id })}
        />
        <View style={{ position: "absolute", top: 10, left: 10, backgroundColor: "#fff", borderRadius: 99, paddingHorizontal: 10, paddingVertical: 4 }}>
          <Text style={{ fontSize: 12 }}>{conn === "live" ? "● Live updates" : "Reconnecting…"}</Text>
        </View>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flexGrow: 0, paddingVertical: 8 }} contentContainerStyle={{ paddingHorizontal: 12, gap: 6 }}>
        <Pressable onPress={() => setRouteId(null)} style={[chip, !routeId && chipOn]}><Text style={{ color: !routeId ? "#fff" : C.text, fontSize: 12 }}>All</Text></Pressable>
        {routes.data?.map((r) => (
          <Pressable key={r.id} onPress={() => setRouteId(r.id)} style={[chip, routeId === r.id && chipOn]}>
            <Text style={{ color: routeId === r.id ? "#fff" : C.text, fontSize: 12 }}>{r.code}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <ScrollView style={{ flex: 1, paddingHorizontal: 12 }}>
        {bus && (
          <Card style={{ borderColor: C.accent }}>
            <View style={[s.row, { justifyContent: "space-between" }]}>
              <View style={s.row}><Text style={{ fontSize: 18, fontWeight: "800", color: C.brandDark }}>Bus {bus.bus_number}</Text>{bus.is_demo && <Demo />}</View>
              <Text onPress={() => setSel(null)} style={{ color: C.muted, fontSize: 18 }}>✕</Text>
            </View>
            {bus.route_id && byId[bus.route_id] && <Muted>{byId[bus.route_id].name}</Muted>}
            <View style={[s.row, { gap: 10, marginTop: 8 }]}>
              <StatusPill status={st!} />
              <Muted>GPS {ago(bus.last_gps_at)}</Muted>
              {live && bus.speed_kmh != null && <Muted>{Math.round(bus.speed_kmh)} km/h</Muted>}
            </View>
            {st === "stale" && <Muted style={{ marginTop: 6 }}>No GPS update for over a minute. Showing last known position.</Muted>}
            <Text style={{ fontWeight: "700", marginTop: 10, marginBottom: 4 }}>Upcoming stops</Text>
            {detail.loading && !detail.data && <Loading />}
            {detail.data?.upcoming_stops.length === 0 && <Muted>Not on an active trip.</Muted>}
            {detail.data?.upcoming_stops.slice(0, 6).map((u) => (
              <Pressable key={u.stop_id} onPress={() => nav.navigate("Stop", { id: u.stop_id })} style={[s.row, { paddingVertical: 5 }]}>
                <Text style={{ flex: 1 }}>{u.name}</Text>
                <Muted>{km(u.distance_m)}  </Muted>
                <Text style={{ fontWeight: "700", color: C.brand, width: 60, textAlign: "right" }}>{live && u.minutes != null ? (u.minutes <= 0 ? "Now" : `${u.minutes} min`) : "–"}</Text>
              </Pressable>
            ))}
          </Card>
        )}
        {shown.map((b) => (
          <Pressable key={b.bus_id} onPress={() => setSel(b.bus_id)}>
            <Card style={{ paddingVertical: 10 }}>
              <View style={[s.row, { gap: 8 }]}>
                <Text style={{ fontWeight: "700" }}>{b.bus_number}</Text>
                {b.route_id && byId[b.route_id] && <RouteChip code={byId[b.route_id].code} color={byId[b.route_id].color} />}
                <View style={{ flex: 1 }} />
                <StatusPill status={effectiveStatus(b)} />
              </View>
              <Muted>{b.next_stop ? `Next: ${b.next_stop.name} · ${km(b.next_stop.distance_m)}` : "No active trip"}</Muted>
            </Card>
          </Pressable>
        ))}
        {conn !== "connecting" && shown.length === 0 && <Muted>No buses on this route right now.</Muted>}
      </ScrollView>
    </View>
  );
}

const chip = { borderWidth: 1, borderColor: C.border, backgroundColor: "#fff", borderRadius: 99, paddingHorizontal: 12, paddingVertical: 6 };
const chipOn = { backgroundColor: C.brand, borderColor: C.brand };
