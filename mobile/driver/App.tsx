import "./src/lib/tracking"; // registers the background task before anything else
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { Alert, AppState, Linking, ScrollView, Text, View } from "react-native";
import { NavigationContainer, useFocusEffect } from "@react-navigation/native";
import { createBottomTabNavigator } from "@react-navigation/bottom-tabs";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { StatusBar } from "expo-status-bar";
import LiveMap from "./src/components/LiveMap";
import { Btn, Card, Demo, DemoBanner, ErrorText, Field, Loading, Muted, RouteChip, Section, StatusPill, Title, s } from "./src/components/ui";
import { api, loadToken, setToken } from "./src/lib/api";
import { ago, effectiveStatus, km } from "./src/lib/format";
import { C } from "./src/lib/theme";
import * as T from "./src/lib/tracking";
import type { BusState, RouteDetail, User } from "./src/lib/types";

interface TripOut { id: number; status: string; started_at: string; ended_at: string | null; route_code: string; route_name: string; bus_number: string; progress_m: number; route_length_m: number; max_delay_minutes: number; gps_points: number; end_reason: string | null }
interface DriverMe {
  driver: { id: number; full_name: string; phone: string | null; license_number: string; employee_code: string | null; location_consent_at: string | null };
  bus: { id: number; bus_number: string; status: string; registration_number: string | null } | null;
  route: RouteDetail | null;
  active_trip: TripOut | null;
  bus_state: BusState | null;
  demo_mode: boolean;
}

/* ---------------------------------------------------------------- shared state */
interface Ctx { me: DriverMe | null; reload: () => Promise<void>; tracking: boolean; setTracking: (v: boolean) => void; signOut: () => Promise<void> }
const DriverCtx = createContext<Ctx | null>(null);
const useDriver = () => useContext(DriverCtx)!;

/* ---------------------------------------------------------------- Login */
function Login({ onIn }: { onIn: () => void }) {
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ access_token: string; user: User }>("/api/auth/login", { method: "POST", json: { identifier: id.trim(), password: pw } });
      if (r.user.role !== "driver") throw new Error("This app is for Speedo drivers. Passengers should use the Speedo Live app.");
      await setToken(r.access_token);
      onIn();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <ScrollView contentContainerStyle={{ padding: 24, paddingTop: 60 }} style={{ backgroundColor: C.bg }} keyboardShouldPersistTaps="handled">
      <Title>Speedo Live Driver</Title>
      <Muted style={{ marginBottom: 20 }}>Sign in with the account your administrator gave you.</Muted>
      <Field label="Mobile number or email" autoCapitalize="none" value={id} onChangeText={setId} />
      <Field label="Password" secureTextEntry value={pw} onChangeText={setPw} />
      {err && <ErrorText error={err} />}
      <Btn title="Sign in" onPress={submit} loading={busy} />
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- Dashboard */
function Dashboard() {
  const { me, reload, tracking, setTracking } = useDriver();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [perm, setPerm] = useState<T.PermissionState | null>(null);
  useFocusEffect(useCallback(() => {
    reload();
    T.checkPermissions().then(setPerm);
  }, [reload]));
  if (!me) return <Loading />;
  const trip = me.active_trip;
  const interrupted = !!trip && !tracking;

  const start = () => {
    Alert.alert(
      "Share bus location?",
      `While this trip runs, the location of bus ${me.bus?.bus_number} is shared with passengers and stored for service records. Sharing stops when you end the trip.`,
      [{ text: "Cancel", style: "cancel" }, { text: "I agree, start", onPress: doStart }],
    );
  };
  const doStart = async () => {
    setBusy(true);
    setErr(null);
    try {
      let p = await T.requestPermissions();
      setPerm(p);
      if (!p.servicesEnabled) throw new Error("GPS is turned off. Turn on Location in your phone settings.");
      if (!p.foreground) throw new Error("Location permission is needed to share the bus position.");
      if (!p.background) {
        Alert.alert("Allow location all the time", "To keep sharing with the screen off, choose 'Allow all the time' for Speedo Live Driver.", [
          { text: "Open settings", onPress: () => Linking.openSettings() },
          { text: "Continue anyway" },
        ]);
      }
      const t = await api<TripOut>("/api/driver/trips/start", { method: "POST", json: { consent: true } });
      await T.startTracking(t.id);
      setTracking(true);
      await reload();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const end = () =>
    Alert.alert("End trip?", "Location sharing will stop.", [
      { text: "Cancel", style: "cancel" },
      {
        text: "End trip",
        style: "destructive",
        onPress: async () => {
          setBusy(true);
          try {
            await T.flush();
            await api(`/api/driver/trips/${trip!.id}/end`, { method: "POST", json: { reason: "completed" } });
          } catch (e) {
            setErr((e as Error).message);
          } finally {
            await T.stopTracking();
            setTracking(false);
            await reload();
            setBusy(false);
          }
        },
      },
    ]);

  const st = me.bus_state ? effectiveStatus(me.bus_state) : null;
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      <Card>
        <Muted>Driver</Muted>
        <Text style={{ fontSize: 20, fontWeight: "800", color: C.brandDark }}>{me.driver.full_name}</Text>
        <Muted>Licence {me.driver.license_number}{me.driver.employee_code ? ` · ${me.driver.employee_code}` : ""}</Muted>
      </Card>
      <Card>
        <View style={[s.row, { justifyContent: "space-between" }]}>
          <View>
            <Muted>Assigned bus</Muted>
            <Text style={{ fontSize: 22, fontWeight: "800" }}>{me.bus?.bus_number || "None"}</Text>
          </View>
          {st && <StatusPill status={st} />}
        </View>
        {me.route ? (
          <View style={[s.row, { gap: 8, marginTop: 8 }]}>
            <RouteChip code={me.route.code} color={me.route.color} />
            <Text style={{ flex: 1, fontSize: 13 }}>{me.route.name}</Text>
            {me.route.is_demo && <Demo />}
          </View>
        ) : <Muted>No route assigned. Contact your administrator.</Muted>}
      </Card>
      <Card style={{ borderColor: tracking ? C.green : C.border }}>
        <Section>Trip</Section>
        {trip ? (
          <>
            <Text style={{ fontWeight: "700", color: tracking ? C.green : C.amber }}>{tracking ? "● Trip in progress, sharing location" : "Trip interrupted: location is NOT being shared"}</Text>
            <Muted>Started {ago(trip.started_at)} · {km(trip.progress_m)} of {km(trip.route_length_m)}</Muted>
            {me.bus_state?.next_stop && <Muted>Next stop: {me.bus_state.next_stop.name} ({km(me.bus_state.next_stop.distance_m)})</Muted>}
          </>
        ) : <Muted>No active trip.</Muted>}
        <View style={{ marginTop: 12, gap: 8 }}>
          {!trip && <Btn title="Start Trip" variant="accent" onPress={start} loading={busy} disabled={!me.bus || !me.route} />}
          {interrupted && <Btn title="Resume sharing" variant="accent" onPress={doStart} loading={busy} />}
          {trip && <Btn title="End Trip" variant="danger" onPress={end} loading={busy} />}
        </View>
        {err && <ErrorText error={err} />}
      </Card>
      <Card>
        <Section>GPS connectivity</Section>
        <Muted>Location services: {perm?.servicesEnabled ? "on" : "OFF"}</Muted>
        <Muted>Permission: {perm?.foreground ? (perm.background ? "allowed all the time" : "only while app is open") : "not granted"}</Muted>
        <Muted>Last update received by server: {ago(me.bus_state?.last_gps_at)}</Muted>
      </Card>
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- My Route */
function MyRoute() {
  const { me, reload } = useDriver();
  useFocusEffect(useCallback(() => { reload(); }, [reload]));
  if (!me) return <Loading />;
  if (!me.route) return <View style={{ padding: 20 }}><Muted>No route assigned.</Muted></View>;
  const r = me.route;
  const progress = me.active_trip?.progress_m ?? -1;
  return (
    <View style={{ flex: 1, backgroundColor: C.bg }}>
      <LiveMap height={280} lines={[{ id: r.id, color: r.color, path: r.path }]} stops={r.stops} buses={me.bus_state ? [me.bus_state] : []} fitKey={`r${r.id}`} />
      <ScrollView contentContainerStyle={{ padding: 14 }}>
        <View style={[s.row, { gap: 8, marginBottom: 8 }]}><RouteChip code={r.code} color={r.color} /><Text style={{ fontWeight: "700", flex: 1 }}>{r.name}</Text></View>
        {r.stops.map((st) => {
          const passed = progress >= 0 && st.distance_m <= progress + 25;
          return (
            <View key={st.id} style={[s.row, { paddingVertical: 7, opacity: passed ? 0.45 : 1 }]}>
              <View style={{ width: 12, height: 12, borderRadius: 6, borderWidth: 2, borderColor: r.color, backgroundColor: passed ? r.color : "#fff", marginRight: 10 }} />
              <Text style={{ flex: 1, fontWeight: st.is_major ? "700" : "400" }}>{st.name}</Text>
              <Muted>+{Math.round(st.offset_minutes)} min</Muted>
            </View>
          );
        })}
      </ScrollView>
    </View>
  );
}

/* ---------------------------------------------------------------- GPS Status */
function GpsStatus() {
  const { tracking } = useDriver();
  const [stats, setStats] = useState<T.Stats | null>(null);
  const [perm, setPerm] = useState<T.PermissionState | null>(null);
  useEffect(() => {
    const load = () => { T.readStats().then(setStats); T.checkPermissions().then(setPerm); };
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  const rows: [string, string][] = [
    ["Sharing", tracking ? "Yes" : "No"],
    ["Location services", perm?.servicesEnabled ? "On" : "Off"],
    ["Background permission", perm?.background ? "Granted" : "Not granted"],
    ["Last GPS fix", ago(stats?.lastFixAt)],
    ["Accuracy", stats?.lastAccuracy != null ? `${Math.round(stats.lastAccuracy)} m` : "–"],
    ["Last sent to server", ago(stats?.lastSentAt)],
    ["Fixes sent", String(stats?.sent ?? 0)],
    ["Waiting to send (offline)", String(stats?.queued ?? 0)],
    ["Skipped: low accuracy", String(stats?.lowAccuracy ?? 0)],
    ["Rejected by server", String(stats?.rejected ?? 0)],
    ["Update interval", `${T.INTERVAL_MS / 1000} s`],
  ];
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      <Card>
        {rows.map(([k, v]) => (
          <View key={k} style={[s.row, { justifyContent: "space-between", paddingVertical: 6, borderBottomWidth: 1, borderColor: "#f1f5f9" }]}>
            <Text>{k}</Text><Text style={{ fontWeight: "700" }}>{v}</Text>
          </View>
        ))}
        {stats?.lastError && <ErrorText error={`Last problem: ${stats.lastError}`} />}
      </Card>
      {!perm?.servicesEnabled && <Btn title="Open location settings" onPress={() => Linking.openSettings()} />}
      <Muted style={{ marginTop: 10 }}>If the internet drops, fixes are kept on the phone (up to 1 hour) and sent when the connection returns.</Muted>
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- History */
function History() {
  const [trips, setTrips] = useState<TripOut[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useFocusEffect(useCallback(() => {
    api<TripOut[]>("/api/driver/trips").then(setTrips).catch((e) => setErr(e.message));
  }, []));
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      {err && <ErrorText error={err} />}
      {!trips && !err && <Loading />}
      {trips?.length === 0 && <Muted>No trips yet.</Muted>}
      {trips?.map((t) => (
        <Card key={t.id}>
          <View style={[s.row, { justifyContent: "space-between" }]}>
            <Text style={{ fontWeight: "700" }}>{t.route_code} · {t.bus_number}</Text>
            <Text style={{ color: t.status === "completed" ? C.green : t.status === "active" ? C.brand : C.amber, fontWeight: "600" }}>{t.status}</Text>
          </View>
          <Muted>{new Date(t.started_at).toLocaleString()} · {km(t.progress_m)} · {t.gps_points} GPS fixes</Muted>
          {t.max_delay_minutes >= 5 && <Muted>Max delay {Math.round(t.max_delay_minutes)} min</Muted>}
          {t.end_reason && t.status !== "completed" && <Muted>Reason: {t.end_reason.replace(/_/g, " ")}</Muted>}
        </Card>
      ))}
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- Profile */
function Profile() {
  const { me, signOut, tracking } = useDriver();
  const out = () => {
    if (tracking || me?.active_trip)
      return Alert.alert("Trip in progress", "End your trip on the Dashboard before logging out.");
    signOut();
  };
  return (
    <ScrollView style={{ flex: 1, backgroundColor: C.bg }} contentContainerStyle={{ padding: 14 }}>
      <Card>
        <Text style={{ fontSize: 20, fontWeight: "800" }}>{me?.driver.full_name}</Text>
        <Muted>{me?.driver.phone}</Muted>
        <Muted>Licence: {me?.driver.license_number}</Muted>
        <Muted>Location consent last given: {me?.driver.location_consent_at ? new Date(me.driver.location_consent_at).toLocaleString() : "never"}</Muted>
      </Card>
      <Card>
        <Section>Privacy</Section>
        <Muted>Your bus's location is shared only while a trip is running. Passengers see the bus number and position, never your name or phone number. GPS history is kept for a limited period for service reports.</Muted>
      </Card>
      <Btn title="Log out" variant="outline" onPress={out} />
    </ScrollView>
  );
}

/* ---------------------------------------------------------------- App */
const Tab = createBottomTabNavigator();
const ICONS: Record<string, string> = { Dashboard: "⌂", "My Route": "⇄", "GPS Status": "◉", "Trip History": "☰", Profile: "☺" };

export default function App() {
  const [signedIn, setSignedIn] = useState<boolean | null>(null);
  const [me, setMe] = useState<DriverMe | null>(null);
  const [tracking, setTracking] = useState(false);

  const reload = useCallback(async () => {
    try {
      setMe(await api<DriverMe>("/api/driver/me"));
      setTracking(await T.isTracking());
    } catch (e) {
      if ((e as { status?: number }).status === 401 || (e as { status?: number }).status === 403) setSignedIn(false);
    }
  }, []);

  useEffect(() => {
    loadToken().then((t) => setSignedIn(!!t));
  }, []);
  useEffect(() => {
    if (signedIn) reload();
  }, [signedIn, reload]);
  useEffect(() => {
    const sub = AppState.addEventListener("change", (s) => s === "active" && signedIn && (T.flush(), reload()));
    return () => sub.remove();
  }, [signedIn, reload]);

  const signOut = async () => {
    await T.stopTracking();
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    await setToken(null);
    setMe(null);
    setSignedIn(false);
  };

  return (
    <SafeAreaProvider>
      <SafeAreaView edges={["top"]} style={{ flex: 0, backgroundColor: me?.demo_mode ? C.accent : C.brand }} />
      <StatusBar style="light" />
      {signedIn === null ? <Loading /> : !signedIn ? (
        <Login onIn={() => setSignedIn(true)} />
      ) : (
        <DriverCtx.Provider value={{ me, reload, tracking, setTracking, signOut }}>
          <DemoBanner show={!!me?.demo_mode} />
          <SafeAreaProvider style={{ flex: 1 }}>
            <NavigationContainer>
              <Tab.Navigator screenOptions={({ route }) => ({
                headerStyle: { backgroundColor: C.brand }, headerTintColor: "#fff",
                tabBarActiveTintColor: C.brand,
                tabBarIcon: ({ color }) => <Text style={{ color, fontSize: 20 }}>{ICONS[route.name]}</Text>,
              })}>
                <Tab.Screen name="Dashboard" component={Dashboard} />
                <Tab.Screen name="My Route" component={MyRoute} />
                <Tab.Screen name="GPS Status" component={GpsStatus} />
                <Tab.Screen name="Trip History" component={History} />
                <Tab.Screen name="Profile" component={Profile} />
              </Tab.Navigator>
            </NavigationContainer>
          </SafeAreaProvider>
        </DriverCtx.Provider>
      )}
    </SafeAreaProvider>
  );
}
