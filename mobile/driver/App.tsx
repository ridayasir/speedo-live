// Speedo Live Driver — Android app for authorised bus drivers.
import "./src/tracking"; // registers the background location task at startup (must be top-level)
import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Alert, AppState, RefreshControl, ScrollView, Text, View } from "react-native";
import { StatusBar } from "expo-status-bar";
import { NavigationContainer, useFocusEffect } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import MapView, { Marker, Polyline, UrlTile } from "react-native-maps";
import { auth, fmtAgo, get, post } from "./src/api";
import { ensurePermissions, flush, getQueue, getStats, isTracking, startTracking, stopTracking, Stats } from "./src/tracking";
import { Badge, Button, C, Card, DemoBadge, ErrorText, Field, H, Loading, Muted, RouteChip, s, Section, StatusBadge } from "./src/ui";

type Ctx = { me: any; reload: () => Promise<void>; signOut: () => Promise<void> };
const MeCtx = createContext<Ctx>(null as any);
const useMe = () => useContext(MeCtx);

function useStats() {
  const [st, setSt] = useState<{ stats: Stats; queue: number; tracking: boolean } | null>(null);
  useFocusEffect(useCallback(() => {
    let on = true;
    const tick = async () => { const [stats, q, tracking] = await Promise.all([getStats(), getQueue(), isTracking()]); if (on) setSt({ stats, queue: q.length, tracking }); };
    tick(); const t = setInterval(tick, 2000);
    return () => { on = false; clearInterval(t); };
  }, []));
  return st;
}

function GpsGrid() {
  const st = useStats();
  if (!st) return <Loading />;
  const acc = st.stats.lastAccuracy;
  const cell = (label: string, value: string, warn = false) => (
    <View style={{ width: "48%", backgroundColor: C.bg, borderRadius: 12, padding: 10, marginBottom: 8 }}>
      <Muted>{label}</Muted><Text style={{ fontSize: 16, fontWeight: "700", color: warn ? C.warn : C.ink }}>{value}</Text>
    </View>
  );
  return (
    <View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between", marginTop: 12 }}>
        {cell("GPS sharing", st.tracking ? "On" : "Off")}
        {cell("Accuracy", acc ? `±${Math.round(acc)} m${acc > 50 ? " (weak)" : ""}` : "—", !!acc && acc > 50)}
        {cell("Last fix", fmtAgo(st.stats.lastFixAt))}
        {cell("Sent", String(st.stats.sent))}
        {cell("Waiting to send", String(st.queue), st.queue > 0)}
        {cell("Rejected", String(st.stats.rejected), st.stats.rejected > 0)}
      </View>
      <ErrorText text={st.stats.lastError} />
    </View>
  );
}

function Dashboard() {
  const { me, reload } = useMe();
  const [direction, setDirection] = useState<"outbound" | "inbound">("outbound");
  const [busy, setBusy] = useState(false);
  if (!me.bus) return <View style={[s.screen, s.pad]}><H>Salaam, {me.driver.name.split(" ")[0]}</H><Card><Muted>No bus is assigned to you. Contact your depot administrator.</Muted></Card></View>;
  const trip = me.trip;
  const start = async () => {
    setBusy(true);
    try {
      const problem = await ensurePermissions();
      if (problem) { Alert.alert("Location needed", problem); return; }
      await post("/api/driver/trips/start", { direction });
      await startTracking(me.settings.gps_interval_s);
      await reload();
    } catch (e: any) { Alert.alert("Couldn't start trip", e.message); } finally { setBusy(false); }
  };
  const end = () => Alert.alert("End trip?", "Location sharing will stop and passengers will no longer see this bus.", [
    { text: "Keep driving", style: "cancel" },
    { text: "End trip", style: "destructive", onPress: async () => {
      setBusy(true);
      try { await flush(); await post("/api/driver/trips/end", { reason: "completed" }); } catch (e: any) { Alert.alert(e.message); }
      await stopTracking(); await reload(); setBusy(false);
    } }]);
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad} refreshControl={<RefreshControl refreshing={false} onRefresh={reload} />}>
      <View style={[s.row, { justifyContent: "space-between" }]}><H>Salaam, {me.driver.name.split(" ")[0]}</H><DemoBadge show={me.driver.is_demo} /></View>
      <Card>
        <Text style={{ fontWeight: "800", color: trip ? C.ok : C.ink3, letterSpacing: 0.5 }}>{trip ? "● TRIP IN PROGRESS — SHARING LOCATION" : "OFF DUTY — LOCATION NOT SHARED"}</Text>
        <View style={[s.row, { marginTop: 10 }]}>{me.route && <RouteChip code={me.route.code} color={me.route.color} />}<Text style={[s.title, { fontSize: 20 }]}>Bus {me.bus.bus_number}</Text><DemoBadge show={me.bus.is_demo} /></View>
        <Muted>{me.route?.name || "No route assigned"}</Muted>
        {me.live && <View style={{ marginTop: 6 }}><StatusBadge status={me.live.status} /></View>}
        {!me.driver.location_consent_at ? <Consent /> : !trip ? <>
          <Section>Direction</Section>
          <View style={s.row}>
            {(["outbound", "inbound"] as const).map(d => <View key={d} style={{ flex: 1 }}><Button kind={direction === d ? "primary" : "plain"} title={`To ${d === "outbound" ? me.route?.last_stop : me.route?.first_stop}`} onPress={() => setDirection(d)} /></View>)}
          </View>
          {me.bus.status !== "active" && <Text style={{ color: C.warn }}>This bus is marked {me.bus.status} and cannot start a trip.</Text>}
          <Button kind="accent" title="▶  Start trip" onPress={start} disabled={busy || me.bus.status !== "active"} />
        </> : <>
          <GpsGrid />
          <Button kind="danger" title="■  End trip" onPress={end} disabled={busy} />
        </>}
      </Card>
    </ScrollView>
  );
}

function Consent() {
  const { reload } = useMe();
  return (
    <View style={{ marginTop: 12, backgroundColor: "#FFF4EC", borderRadius: 12, padding: 12 }}>
      <Text style={s.title}>Location sharing consent</Text>
      <Muted>While a trip is active, this app sends your bus's GPS location every few seconds so passengers can see where the bus is. Location is only shared during trips you start and stops when you end the trip or sign out. Trip locations are kept for a limited time for service reports.</Muted>
      <Button title="I agree — enable location sharing" onPress={async () => { await post("/api/driver/consent", { accepted: true }); await reload(); }} />
    </View>
  );
}

function MyRoute() {
  const { me } = useMe();
  const r = me.route;
  if (!r) return <View style={[s.screen, s.pad]}><Muted>No route assigned.</Muted></View>;
  const mid = r.stops[Math.floor(r.stops.length / 2)];
  return (
    <ScrollView style={s.screen}>
      <MapView style={{ height: 280 }} mapType="none" showsUserLocation initialRegion={{ latitude: mid.lat, longitude: mid.lon, latitudeDelta: 0.14, longitudeDelta: 0.14 }}>
        <UrlTile urlTemplate="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maximumZ={19} />
        <Polyline coordinates={r.shape.map((p: number[]) => ({ latitude: p[0], longitude: p[1] }))} strokeColor={r.color} strokeWidth={5} />
        {r.stops.map((st: any) => <Marker key={st.id} coordinate={{ latitude: st.lat, longitude: st.lon }} title={st.name} pinColor="navy" />)}
      </MapView>
      <View style={s.pad}>
        <View style={s.row}><RouteChip code={r.code} color={r.color} /><Text style={s.title}>{r.name}</Text></View>
        <Section>Stops</Section>
        {r.stops.map((st: any, i: number) => <Card key={st.id}><Text style={s.title}>{i + 1}. {st.name}</Text>{st.name_ur ? <Muted>{st.name_ur}</Muted> : null}</Card>)}
      </View>
    </ScrollView>
  );
}

function GpsStatus() {
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>GPS status</H>
      <Card><GpsGrid /><Button kind="plain" title="Send saved locations now" onPress={() => flush()} /></Card>
      <Card>
        <Text style={s.title}>Troubleshooting</Text>
        <Muted>• Turn on Location / GPS in phone settings.{"\n"}• Allow location “all the time” for Speedo Live Driver.{"\n"}• Turn off battery optimisation for this app so Android doesn't stop tracking.{"\n"}• Weak accuracy (over 50 m)? Move away from tall buildings or flyovers.{"\n"}• No internet? Locations are stored on the phone and sent automatically later.</Muted>
      </Card>
    </ScrollView>
  );
}

function History() {
  const [rows, setRows] = useState<any[] | null>(null);
  useFocusEffect(useCallback(() => { get("/api/driver/trips?limit=30").then(setRows).catch(() => setRows([])); }, []));
  if (!rows) return <Loading />;
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>Trip history</H>
      {rows.map(t => (
        <Card key={t.id}>
          <View style={[s.row, { justifyContent: "space-between" }]}><Text style={s.title}>{t.route_code} · {t.bus_number} · {t.direction}</Text>
            <Badge text={t.status} fg={t.status === "completed" ? C.ok : C.ink2} bg={t.status === "completed" ? C.okBg : "#EEF1F5"} /></View>
          <Muted>{new Date(t.started_at).toLocaleString()} · {(t.distance_m / 1000).toFixed(1)} km · {t.gps_points} GPS fixes</Muted>
        </Card>
      ))}
      {!rows.length && <Muted>No trips yet.</Muted>}
    </ScrollView>
  );
}

function Profile() {
  const { me, reload, signOut } = useMe();
  const d = me.driver;
  return (
    <ScrollView style={s.screen} contentContainerStyle={s.pad}>
      <H>{d.name}</H>
      <Card>
        <Muted>Employee code</Muted><Text style={s.title}>{d.employee_code}</Text>
        <Muted>Phone</Muted><Text style={s.title}>{d.phone || "—"}</Text>
        <Muted>Bus</Muted><Text style={s.title}>{me.bus?.bus_number || "Unassigned"}</Text>
        <Muted>Location consent</Muted><Text style={s.title}>{d.location_consent_at ? `Given ${fmtAgo(d.location_consent_at)}` : "Not given"}</Text>
      </Card>
      {d.location_consent_at && <Button kind="plain" title="Withdraw location consent" onPress={() => Alert.alert("Withdraw consent?", "Any active trip will end and you can't start trips until you agree again.", [
        { text: "Cancel", style: "cancel" },
        { text: "Withdraw", style: "destructive", onPress: async () => { await post("/api/driver/consent", { accepted: false }); await stopTracking(); await reload(); } }])} />}
      <Button kind="plain" title="Sign out" onPress={() => Alert.alert("Sign out?", me.trip ? "Your active trip will end." : "", [{ text: "Cancel", style: "cancel" }, { text: "Sign out", onPress: signOut }])} />
    </ScrollView>
  );
}

function Login({ onDone }: { onDone: () => void }) {
  const [id, setId] = useState(""); const [pw, setPw] = useState(""); const [err, setErr] = useState<string | null>(null);
  return (
    <ScrollView style={s.screen} contentContainerStyle={[s.pad, { paddingTop: 60 }]} keyboardShouldPersistTaps="handled">
      <H>Driver sign in</H>
      <Muted>For authorised Speedo drivers only.</Muted>
      <View style={{ height: 16 }} />
      <Field label="Phone or email" value={id} onChangeText={setId} autoCapitalize="none" keyboardType="phone-pad" />
      <Field label="Password" value={pw} onChangeText={setPw} secureTextEntry />
      <ErrorText text={err} />
      <Button title="Sign in" onPress={async () => {
        setErr(null);
        try {
          const r = await post("/api/auth/login", { identifier: id, password: pw });
          if (r.user.role !== "driver") return setErr("This account is not a driver account.");
          await auth.set(r.token); onDone();
        } catch (e: any) { setErr(e.message); }
      }} />
    </ScrollView>
  );
}

const Tab = createBottomTabNavigator();
const ic = (g: string) => ({ color }: { color: string }) => <Text style={{ fontSize: 20, color }}>{g}</Text>;

export default function App() {
  const [me, setMe] = useState<any>(undefined);
  const [cfg, setCfg] = useState<any>(null);
  const reload = useCallback(async () => {
    if (!auth.token) { setMe(null); return; }
    try {
      const m = await get("/api/driver/me");
      setMe(m);
      // trip active on the server but tracking stopped (phone restarted / app killed): resume it
      if (m.trip && m.driver.location_consent_at && !(await isTracking()) && !(await ensurePermissions())) await startTracking(m.settings.gps_interval_s);
      if (!m.trip && (await isTracking())) await stopTracking();
    } catch (e: any) {
      if (e.status === 401 || e.status === 403) { await auth.clear(); setMe(null); } else setMe((x: any) => x ?? null);
    }
  }, []);
  const signOut = useCallback(async () => {
    await flush();
    try { await post("/api/auth/logout"); } catch { /* offline: token expires anyway */ }
    await stopTracking(); await auth.clear(); setMe(null);
  }, []);
  useEffect(() => { auth.load().then(reload); get("/api/config").then(setCfg).catch(() => {}); }, []);
  useEffect(() => { const sub = AppState.addEventListener("change", st => { if (st === "active") { reload(); flush(); } }); return () => sub.remove(); }, []);
  if (me === undefined) return <View style={{ flex: 1, backgroundColor: C.blue }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style="light" />
      <SafeAreaView style={{ flex: 1, backgroundColor: C.blue }} edges={["top"]}>
        {cfg?.demo && <View style={s.demoBanner}><Text style={s.demoText}>DEMO MODE · demo buses and routes, not for real service</Text></View>}
        {!me ? <Login onDone={reload} /> : (
          <MeCtx.Provider value={{ me, reload, signOut }}>
            <NavigationContainer>
              <Tab.Navigator screenOptions={{ tabBarActiveTintColor: C.blue, headerStyle: { backgroundColor: C.blue }, headerTintColor: "#fff" }}>
                <Tab.Screen name="Dashboard" component={Dashboard} options={{ tabBarIcon: ic("⌂") }} />
                <Tab.Screen name="My Route" component={MyRoute} options={{ tabBarIcon: ic("⤳") }} />
                <Tab.Screen name="GPS Status" component={GpsStatus} options={{ tabBarIcon: ic("📡") }} />
                <Tab.Screen name="Trip History" component={History} options={{ tabBarIcon: ic("🕘"), tabBarLabel: "Trips" }} />
                <Tab.Screen name="Profile" component={Profile} options={{ tabBarIcon: ic("◉") }} />
              </Tab.Navigator>
            </NavigationContainer>
          </MeCtx.Provider>
        )}
      </SafeAreaView>
    </SafeAreaProvider>
  );
}
