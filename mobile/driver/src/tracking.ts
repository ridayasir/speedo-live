// Background GPS sharing for the driver app.
// - Runs as an Android foreground service (persistent notification) only while a trip is active.
// - Every fix is queued on the phone first, then sent in batches, so nothing is lost offline.
// - The server validates trip, bus assignment, coordinates, timestamps, accuracy and duplicates.
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import * as SecureStore from "expo-secure-store";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { API_URL } from "./api";

export const TASK = "speedo-driver-location";
const QUEUE = "speedo.driver.queue";
const STATS = "speedo.driver.stats";
let flushing = false;

export type Stats = { sent: number; rejected: number; lastFixAt: string | null; lastAccuracy: number | null; lastError: string | null; lastLat?: number; lastLon?: number };

export async function getQueue(): Promise<any[]> { return JSON.parse((await AsyncStorage.getItem(QUEUE)) || "[]"); }
async function setQueue(q: any[]) { await AsyncStorage.setItem(QUEUE, JSON.stringify(q.slice(-1000))); }
export async function getStats(): Promise<Stats> {
  return { sent: 0, rejected: 0, lastFixAt: null, lastAccuracy: null, lastError: null, ...JSON.parse((await AsyncStorage.getItem(STATS)) || "{}") };
}
async function patchStats(p: Partial<Stats>) { await AsyncStorage.setItem(STATS, JSON.stringify({ ...(await getStats()), ...p })); }

TaskManager.defineTask(TASK, async ({ data, error }: any) => {
  if (error) { await patchStats({ lastError: error.message }); return; }
  const locations: Location.LocationObject[] = data?.locations || [];
  if (!locations.length) return;
  const points = locations.map(l => ({
    lat: l.coords.latitude, lon: l.coords.longitude,
    accuracy_m: l.coords.accuracy ?? null,
    speed_mps: l.coords.speed !== null && l.coords.speed! >= 0 ? l.coords.speed : null,
    heading: l.coords.heading !== null && l.coords.heading! >= 0 ? l.coords.heading : null,
    recorded_at: new Date(l.timestamp).toISOString(),
  }));
  const last = locations[locations.length - 1];
  await patchStats({ lastFixAt: new Date(last.timestamp).toISOString(), lastAccuracy: last.coords.accuracy ?? null, lastLat: last.coords.latitude, lastLon: last.coords.longitude });
  await setQueue([...(await getQueue()), ...points]);
  await flush();
});

/** Send queued fixes. Safe to call from the UI or the background task. */
export async function flush(): Promise<void> {
  if (flushing) return;
  flushing = true;
  try {
    const token = await SecureStore.getItemAsync("speedo.token");
    if (!token) return;
    for (let i = 0; i < 10; i++) {
      const q = await getQueue();
      if (!q.length) break;
      const batch = q.slice(0, 100);
      let res: Response;
      try {
        res = await fetch(`${API_URL}/api/driver/location/batch`, { method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` }, body: JSON.stringify({ points: batch }) });
      } catch {
        await patchStats({ lastError: "No internet — locations saved on the phone" });
        break;  // keep the queue; retry on the next fix
      }
      const body = await res.json().catch(() => null);
      if (res.ok) {
        const st = await getStats();
        await patchStats({ sent: st.sent + body.accepted, rejected: st.rejected + body.rejected.length,
          lastError: body.rejected.length ? `Rejected: ${[...new Set(body.rejected.map((r: any) => r.reason))].join(", ")}` : null });
        await setQueue((await getQueue()).slice(batch.length));
      } else if (res.status === 409 || res.status === 403) {
        // trip ended elsewhere / bus reassigned: stop sharing immediately
        await setQueue([]);
        await patchStats({ lastError: body?.error?.message || "Trip is no longer active" });
        await stopTracking();
        break;
      } else if (res.status === 422) {
        await setQueue((await getQueue()).slice(batch.length));  // malformed batch: drop it
        await patchStats({ lastError: body?.error?.message || "Invalid GPS data" });
      } else {
        await patchStats({ lastError: body?.error?.message || `Server error ${res.status}` });
        break;
      }
    }
  } finally {
    flushing = false;
  }
}

export async function ensurePermissions(): Promise<string | null> {
  if (!(await Location.hasServicesEnabledAsync())) return "Location (GPS) is turned off. Turn it on in your phone settings.";
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status !== "granted") return "Location permission is required to share the bus position during trips.";
  const bg = await Location.requestBackgroundPermissionsAsync();
  if (bg.status !== "granted") return "Choose “Allow all the time” so tracking continues when the screen is off.";
  return null;
}

export async function startTracking(intervalS: number) {
  if (await Location.hasStartedLocationUpdatesAsync(TASK)) return;
  await AsyncStorage.setItem(STATS, JSON.stringify({ sent: 0, rejected: 0, lastFixAt: null, lastAccuracy: null, lastError: null }));
  await Location.startLocationUpdatesAsync(TASK, {
    accuracy: Location.Accuracy.BestForNavigation,
    timeInterval: intervalS * 1000,
    distanceInterval: 0,               // keep reporting while stopped so a waiting bus doesn't look offline
    deferredUpdatesInterval: intervalS * 1000,
    pausesUpdatesAutomatically: false,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: "Speedo Live: trip in progress",
      notificationBody: "Sharing your bus location with passengers. End the trip to stop.",
      notificationColor: "#0B3B8C",
      killServiceOnDestroy: false,
    },
  });
}

export async function stopTracking() {
  if (await Location.hasStartedLocationUpdatesAsync(TASK)) await Location.stopLocationUpdatesAsync(TASK);
}

export async function isTracking() {
  return Location.hasStartedLocationUpdatesAsync(TASK);
}
