import { useEffect, useState } from "react";
import { FlatList, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import LiveMap from "../components/LiveMap";
import { Btn, Card, Demo, ErrorText, Loading, Muted, RouteChip, Section, s } from "../components/ui";
import { api } from "../lib/api";
import { effectiveStatus, km } from "../lib/format";
import { useAuth, useFetch, useLiveBuses, useMyLocation } from "../lib/hooks";
import { C } from "../lib/theme";
import type { Alert, RouteSummary, Stop } from "../lib/types";
import type { RootStack } from "../../App";

type Props = NativeStackScreenProps<RootStack, "Tabs">;

export default function HomeScreen({ navigation }: Props) {
  const { user } = useAuth();
  const { buses } = useLiveBuses();
  const loc = useMyLocation();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<{ stops: Stop[]; routes: RouteSummary[] } | null>(null);
  const popular = useFetch<RouteSummary[]>("/api/routes/popular?limit=5");
  const alerts = useFetch<Alert[]>("/api/alerts");
  const favs = useFetch<{ stops: Stop[]; routes: RouteSummary[] }>(user ? "/api/me/favorites" : null, [user?.id]);
  const nearby = useFetch<Stop[]>(loc.pos ? `/api/stops/nearby?lat=${loc.pos.lat}&lng=${loc.pos.lng}&radius_m=2000&limit=5` : null);

  useEffect(() => {
    loc.locate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (q.trim().length < 2) return setResults(null);
    const t = setTimeout(() => api(`/api/search?q=${encodeURIComponent(q.trim())}`).then(setResults).catch(() => setResults(null)), 250);
    return () => clearTimeout(t);
  }, [q]);

  const counts = buses.reduce((c, b) => {
    const st = effectiveStatus(b);
    if (st === "active") c.active++;
    else if (st === "delayed") c.delayed++;
    else if (st === "stale" || st === "offline") c.lost++;
    return c;
  }, { active: 0, delayed: 0, lost: 0 });

  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} keyboardShouldPersistTaps="handled">
      <LiveMap height={260} buses={buses} points={loc.pos ? [{ ...loc.pos, label: "You", kind: "me" }] : []} fitKey={loc.pos ? "me" : undefined}
        onBusPress={(id) => navigation.navigate("Tabs", { screen: "LiveMap", params: { busId: id } } as never)} />
      <View style={{ padding: 14, marginTop: -30 }}>
        <View style={[s.card, { padding: 4, paddingHorizontal: 12 }]}>
          <TextInput value={q} onChangeText={setQ} placeholder="Search a stop, route or bus" placeholderTextColor="#94a3b8" style={{ paddingVertical: 10, fontSize: 15 }} />
        </View>
        {results && (
          <Card>
            {results.stops.map((st) => (
              <Pressable key={`s${st.id}`} onPress={() => navigation.navigate("Stop", { id: st.id })} style={{ paddingVertical: 8 }}>
                <Text>📍 {st.name}</Text>
              </Pressable>
            ))}
            {results.routes.map((r) => (
              <Pressable key={`r${r.id}`} onPress={() => navigation.navigate("Route", { id: r.id })} style={[s.row, { paddingVertical: 8, gap: 8 }]}>
                <RouteChip code={r.code} color={r.color} /><Text style={{ flex: 1 }}>{r.name}</Text>
              </Pressable>
            ))}
            {!results.stops.length && !results.routes.length && <Muted>No matches.</Muted>}
          </Card>
        )}

        <View style={[s.row, { gap: 8, marginBottom: 12 }]}>
          <View style={{ flex: 1 }}><Btn title="Plan a journey" onPress={() => navigation.navigate("Tabs", { screen: "Explore" } as never)} /></View>
          <View style={{ flex: 1 }}><Btn title="Timetable" variant="outline" onPress={() => navigation.navigate("Timetable", {})} /></View>
        </View>

        {alerts.data?.slice(0, 2).map((a) => (
          <View key={a.id} style={{ backgroundColor: a.severity === "info" ? C.brandLight : C.amberBg, padding: 10, borderRadius: 12, marginBottom: 10 }}>
            <Text style={{ fontWeight: "700", color: C.brandDark }}>{a.title}</Text>
            <Text style={{ color: C.text, fontSize: 13 }}>{a.message}</Text>
          </View>
        ))}

        <Card>
          <Section>Live bus status</Section>
          <View style={[s.row, { gap: 8 }]}>
            {[["On route", counts.active, C.green, C.greenBg], ["Delayed", counts.delayed, C.amber, C.amberBg], ["No signal", counts.lost, C.muted, "#f1f5f9"]].map(([l, n, fg, bg]) => (
              <View key={l as string} style={{ flex: 1, backgroundColor: bg as string, borderRadius: 12, padding: 10, alignItems: "center" }}>
                <Text style={{ fontSize: 22, fontWeight: "800", color: fg as string }}>{n as number}</Text>
                <Text style={{ fontSize: 11, color: fg as string }}>{l as string}</Text>
              </View>
            ))}
          </View>
        </Card>

        <Card>
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <Section>Nearby stops</Section>
            <Text onPress={loc.locate} style={{ color: C.brand, fontWeight: "600" }}>{loc.busy ? "Locating…" : "Refresh"}</Text>
          </View>
          {loc.error && <ErrorText error={loc.error} onRetry={loc.locate} />}
          {nearby.loading && <Loading />}
          {nearby.data?.length === 0 && <Muted>No stops within 2 km of you.</Muted>}
          {nearby.data?.map((st) => (
            <Pressable key={st.id} onPress={() => navigation.navigate("Stop", { id: st.id })} style={[s.row, { paddingVertical: 8 }]}>
              <Text style={{ flex: 1 }}>📍 {st.name}</Text><Muted>{km(st.distance_m)}</Muted>
            </Pressable>
          ))}
        </Card>

        {user && (
          <Card>
            <Section>Favorite stops</Section>
            {favs.data?.stops.length === 0 && <Muted>Tap Save on a stop to add it here.</Muted>}
            {favs.data?.stops.map((st) => (
              <Pressable key={st.id} onPress={() => navigation.navigate("Stop", { id: st.id })} style={{ paddingVertical: 8 }}>
                <Text>⭐ {st.name}</Text>
              </Pressable>
            ))}
          </Card>
        )}

        <Card>
          <Section>Popular routes</Section>
          {popular.loading && <Loading />}
          {popular.error && <ErrorText error={popular.error} onRetry={popular.reload} />}
          <FlatList
            scrollEnabled={false}
            data={popular.data || []}
            keyExtractor={(r) => String(r.id)}
            renderItem={({ item: r }) => (
              <Pressable onPress={() => navigation.navigate("Route", { id: r.id })} style={[s.row, { paddingVertical: 8, gap: 8 }]}>
                <RouteChip code={r.code} color={r.color} />
                <Text style={{ flex: 1, fontSize: 13 }} numberOfLines={1}>{r.name}</Text>
                {r.is_demo && <Demo />}
              </Pressable>
            )}
          />
        </Card>
      </View>
    </ScrollView>
  );
}
