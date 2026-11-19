import { useEffect, useState } from "react";
import { Pressable, ScrollView, Switch, Text, View } from "react-native";
import { useNavigation } from "@react-navigation/native";
import type { NativeStackScreenProps } from "@react-navigation/native-stack";
import LiveMap from "../components/LiveMap";
import { Btn, Card, Demo, ErrorText, Field, Loading, Muted, RouteChip, Section, Title, s } from "../components/ui";
import { api } from "../lib/api";
import { ago, km } from "../lib/format";
import { useAuth, useFetch, useLiveBuses } from "../lib/hooks";
import { C } from "../lib/theme";
import type { NotificationPrefs, RouteDetail, RouteSummary, Schedule, Stop } from "../lib/types";
import type { RootStack } from "../../App";

/* ---------------------------------------------------------------- Route detail */
export function RouteScreen({ route, navigation }: NativeStackScreenProps<RootStack, "Route">) {
  const { id } = route.params;
  const { user } = useAuth();
  const r = useFetch<RouteDetail>(`/api/routes/${id}`);
  const { buses } = useLiveBuses([id]);
  const [fav, setFav] = useState(false);
  useEffect(() => {
    if (r.data) navigation.setOptions({ title: r.data.code });
    if (user) api<{ routes: RouteSummary[] }>("/api/me/favorites").then((f) => setFav(f.routes.some((x) => x.id === id))).catch(() => {});
  }, [r.data, user, id, navigation]);
  if (r.loading) return <Loading />;
  if (r.error || !r.data) return <ErrorText error={r.error || "Route not found"} onRetry={r.reload} />;
  const d = r.data;
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }}>
      <LiveMap height={240} lines={[{ id: d.id, color: d.color, path: d.path }]} stops={d.stops} buses={buses.filter((b) => b.route_id === id)} fitKey={`r${id}`}
        onStopPress={(sid) => navigation.navigate("Stop", { id: sid, routeId: id })}
        onBusPress={(bid) => navigation.navigate("Tabs", { screen: "LiveMap", params: { busId: bid, routeId: id } } as never)} />
      <View style={{ padding: 14 }}>
        <View style={s.row}><RouteChip code={d.code} color={d.color} />{d.is_demo && <Demo />}</View>
        <Text style={{ fontSize: 19, fontWeight: "800", color: C.brandDark, marginVertical: 6 }}>{d.name}</Text>
        <Muted>{d.stop_count} stops · {km(d.length_m)}{d.source_reference ? ` · Source: ${d.source_reference}` : ""}</Muted>
        <View style={[s.row, { gap: 8, marginVertical: 12 }]}>
          {user && <View style={{ flex: 1 }}><Btn small variant="outline" title={fav ? "★ Saved" : "☆ Save route"} onPress={async () => { await api(`/api/me/favorites/routes/${id}`, { method: fav ? "DELETE" : "PUT" }); setFav(!fav); }} /></View>}
          <View style={{ flex: 1 }}><Btn small title="Timetable" onPress={() => navigation.navigate("Timetable", { routeId: id })} /></View>
        </View>
        <Card>
          <Section>Stops</Section>
          {d.stops.map((st) => (
            <Pressable key={st.id} onPress={() => navigation.navigate("Stop", { id: st.id, routeId: id })} style={[s.row, { paddingVertical: 7 }]}>
              <View style={{ width: 10, height: 10, borderRadius: 5, borderWidth: 2, borderColor: d.color, marginRight: 10 }} />
              <Text style={{ flex: 1, fontWeight: st.is_major ? "700" : "400" }}>{st.name}</Text>
              <Muted>+{Math.round(st.offset_minutes)} min</Muted>
            </Pressable>
          ))}
        </Card>
      </View>
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- Timetable */
interface TTRoute extends RouteSummary { schedules: Schedule[]; operating_today: boolean; first_bus: string | null; last_bus: string | null; stops: { stop_id: number; name: string; times: string[] }[] }

export function TimetableScreen({ route }: NativeStackScreenProps<RootStack, "Timetable">) {
  const routeId = route.params?.routeId;
  const tt = useFetch<{ date: string; routes: TTRoute[] }>(`/api/timetable${routeId ? `?route_id=${routeId}` : ""}`);
  const now = new Date(Date.now() + (5 * 60 + new Date().getTimezoneOffset()) * 60000);
  const hhmm = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      <Muted style={{ marginBottom: 10 }}>Scheduled times for today (Pakistan time). These are the timetable, not live tracking.</Muted>
      {tt.loading && <Loading />}
      {tt.error && <ErrorText error={tt.error} onRetry={tt.reload} />}
      {tt.data?.routes.map((r) => (
        <Card key={r.id}>
          <View style={[s.row, { gap: 6 }]}><RouteChip code={r.code} color={r.color} />{r.is_demo && <Demo />}</View>
          <Text style={{ fontWeight: "700", marginVertical: 4 }}>{r.name}</Text>
          <Muted>{r.operating_today ? `First ${r.first_bus} · Last ${r.last_bus}` : "No service today"}</Muted>
          {r.schedules.map((sc) => <Muted key={sc.id}>{sc.days.join(", ")}: every {sc.frequency_minutes} min</Muted>)}
          {r.stops.map((st) => (
            <View key={st.stop_id} style={{ marginTop: 8 }}>
              <Text style={{ fontWeight: "600", fontSize: 13 }}>{st.name}</Text>
              <Text style={{ color: C.brand, fontSize: 12 }}>{st.times.filter((t) => t >= hhmm).slice(0, 8).join("  ") || "No more today"}</Text>
            </View>
          ))}
        </Card>
      ))}
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- Favorites */
export function FavoritesScreen() {
  const nav = useNavigation<any>();
  const { user } = useAuth();
  const f = useFetch<{ stops: Stop[]; routes: RouteSummary[] }>(user ? "/api/me/favorites" : null, [user?.id]);
  useEffect(() => nav.addListener("focus", f.reload), [nav, f.reload]);
  if (!user)
    return (
      <View style={{ flex: 1, padding: 20, justifyContent: "center", backgroundColor: C.bg }}>
        <Title>Favorites</Title>
        <Muted>Sign in on the Profile tab to save stops and routes and get delay alerts for them.</Muted>
        <View style={{ marginTop: 12 }}><Btn title="Go to Profile" onPress={() => nav.navigate("Profile")} /></View>
      </View>
    );
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      {f.loading && <Loading />}
      <Card>
        <Section>Stops</Section>
        {f.data?.stops.length === 0 && <Muted>No favorite stops yet.</Muted>}
        {f.data?.stops.map((st) => (
          <Pressable key={st.id} onPress={() => nav.navigate("Stop", { id: st.id })} style={{ paddingVertical: 8 }}><Text>⭐ {st.name}</Text></Pressable>
        ))}
      </Card>
      <Card>
        <Section>Routes</Section>
        {f.data?.routes.length === 0 && <Muted>No favorite routes yet.</Muted>}
        {f.data?.routes.map((r) => (
          <Pressable key={r.id} onPress={() => nav.navigate("Route", { id: r.id })} style={[s.row, { gap: 8, paddingVertical: 8 }]}>
            <RouteChip code={r.code} color={r.color} /><Text style={{ flex: 1, fontSize: 13 }}>{r.name}</Text>
          </Pressable>
        ))}
      </Card>
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- Profile */
interface Note { id: number; title: string; body: string; created_at: string; read_at: string | null }

export function ProfileScreen() {
  const { user, login, register, logout, refresh } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [f, setF] = useState({ id: "", pw: "", name: "", contact: "" });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const notes = useFetch<Note[]>(user ? "/api/me/notifications" : null, [user?.id]);
  const hist = useFetch<{ id: number; created_at: string; route: RouteSummary | null; from_stop: Stop | null; to_stop: Stop | null }[]>(user ? "/api/me/journeys" : null, [user?.id]);

  if (!user) {
    const submit = async () => {
      setBusy(true);
      setErr(null);
      try {
        if (mode === "login") await login(f.id.trim(), f.pw);
        else await register({ full_name: f.name.trim(), password: f.pw, ...(f.contact.includes("@") ? { email: f.contact.trim() } : { phone: f.contact.replace(/[\s-]/g, "") }) });
      } catch (e) {
        setErr((e as Error).message);
      } finally {
        setBusy(false);
      }
    };
    return (
      <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 20 }} keyboardShouldPersistTaps="handled">
        <Title>{mode === "login" ? "Sign in" : "Create account"}</Title>
        <Muted style={{ marginBottom: 14 }}>Route search and tracking work without an account. Sign in for favorites and bus alerts.</Muted>
        {mode === "login" ? (
          <>
            <Field label="Email or phone" autoCapitalize="none" value={f.id} onChangeText={(t) => setF({ ...f, id: t })} />
            <Field label="Password" secureTextEntry value={f.pw} onChangeText={(t) => setF({ ...f, pw: t })} />
          </>
        ) : (
          <>
            <Field label="Full name" value={f.name} onChangeText={(t) => setF({ ...f, name: t })} />
            <Field label="Email or mobile number" autoCapitalize="none" value={f.contact} onChangeText={(t) => setF({ ...f, contact: t })} />
            <Field label="Password (min 8)" secureTextEntry value={f.pw} onChangeText={(t) => setF({ ...f, pw: t })} />
          </>
        )}
        {err && <ErrorText error={err} />}
        <Btn title={mode === "login" ? "Sign in" : "Create account"} onPress={submit} loading={busy} />
        <Text onPress={() => setMode(mode === "login" ? "register" : "login")} style={{ color: C.brand, textAlign: "center", marginTop: 14, fontWeight: "600" }}>
          {mode === "login" ? "New here? Create an account" : "Have an account? Sign in"}
        </Text>
      </ScrollView>
    );
  }

  const prefs = user.notification_prefs;
  const setPref = async (p: Partial<NotificationPrefs>) => {
    await api("/api/me/notification-preferences", { method: "PUT", json: p });
    await refresh();
  };
  const labels: [keyof NotificationPrefs, string][] = [["bus_approaching", "My bus is approaching"], ["delays", "Delays on favorite routes"], ["disruptions", "Service disruptions"], ["schedule_changes", "Timetable changes"]];
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      <Card>
        <Text style={{ fontSize: 20, fontWeight: "800", color: C.brandDark }}>{user.full_name}</Text>
        <Muted>{user.email || user.phone}</Muted>
        <View style={{ marginTop: 10 }}><Btn small variant="outline" title="Log out" onPress={logout} /></View>
      </Card>
      <Card>
        <Section>Notifications</Section>
        {labels.map(([k, l]) => (
          <View key={k} style={[s.row, { justifyContent: "space-between", paddingVertical: 4 }]}>
            <Text>{l}</Text>
            <Switch value={!!prefs[k]} onValueChange={(v) => setPref({ [k]: v })} trackColor={{ true: C.brand }} />
          </View>
        ))}
        <View style={[s.row, { justifyContent: "space-between", paddingVertical: 4 }]}>
          <Text>Minutes before arrival</Text>
          <View style={[s.row, { gap: 4 }]}>
            {[3, 5, 10].map((m) => (
              <Text key={m} onPress={() => setPref({ arrival_minutes_before: m })} style={{ paddingHorizontal: 10, paddingVertical: 4, borderRadius: 8, overflow: "hidden", backgroundColor: prefs.arrival_minutes_before === m ? C.brand : "#f1f5f9", color: prefs.arrival_minutes_before === m ? "#fff" : C.text }}>{m}</Text>
            ))}
          </View>
        </View>
      </Card>
      <Card>
        <Section>Inbox</Section>
        {notes.data?.length === 0 && <Muted>No notifications yet.</Muted>}
        {notes.data?.slice(0, 15).map((n) => (
          <View key={n.id} style={{ paddingVertical: 6, borderBottomWidth: 1, borderColor: "#f1f5f9" }}>
            <Text style={{ fontWeight: n.read_at ? "400" : "700" }}>{n.title}</Text>
            <Muted>{n.body} · {ago(n.created_at)}</Muted>
          </View>
        ))}
      </Card>
      <Card>
        <Section>Journey history</Section>
        {hist.data?.length === 0 && <Muted>Journeys you track appear here.</Muted>}
        {hist.data?.map((j) => (
          <View key={j.id} style={[s.row, { gap: 8, paddingVertical: 6 }]}>
            {j.route && <RouteChip code={j.route.code} color={j.route.color} />}
            <Text style={{ flex: 1, fontSize: 13 }}>{j.from_stop?.name} → {j.to_stop?.name}</Text>
            <Muted>{ago(j.created_at)}</Muted>
          </View>
        ))}
      </Card>
    </ScrollView>
  );
}
