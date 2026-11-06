/**
 * Background GPS for an active trip.
 *
 * - Runs as an Android foreground service (persistent notification) so tracking continues with the
 *   screen off, and stops the moment the trip ends.
 * - Every fix is time-stamped on the device. Fixes that cannot be sent (no internet) are queued and
 *   sent in order once the connection returns; the server drops duplicates and anything over 1 hour old.
 * - Fixes worse than MAX_ACCURACY_M are not sent, and are counted so the driver can see poor GPS.
 */
import AsyncStorage from "@react-native-async-storage/async-storage";
import * as Location from "expo-location";
import * as TaskManager from "expo-task-manager";
import { api, loadToken } from "./api";

export const TASK = "speedo-driver-location";
export const INTERVAL_MS = 5000;
const MAX_ACCURACY_M = 100;
const QUEUE_KEY = "speedo.queue";
const TRIP_KEY = "speedo.trip";
const STATS_KEY = "speedo.stats";
const MAX_QUEUE = 720; // ~1 hour at 5 s

export interface Fix { lat: number; lng: number; recorded_at: string; accuracy_m?: number; speed_mps?: number; heading?: number }
export interface Stats {
  lastFixAt?: string;
  lastAccuracy?: number;
  lastSentAt?: string;
  lastError?: string;
  sent: number;
  rejected: number;
  lowAccuracy: number;
  queued: number;
}

async function getStats(): Promise<Stats> {
  try {
    return { sent: 0, rejected: 0, lowAccuracy: 0, queued: 0, ...JSON.parse((await AsyncStorage.getItem(STATS_KEY)) || "{}") };
  } catch {
    return { sent: 0, rejected: 0, lowAccuracy: 0, queued: 0 };
  }
}
async function setStats(p: Partial<Stats>) {
  const s = await getStats();
  await AsyncStorage.setItem(STATS_KEY, JSON.stringify({ ...s, ...p }));
}
export const readStats = getStats;

async function readQueue(): Promise<Fix[]> {
  try {
    return JSON.parse((await AsyncStorage.getItem(QUEUE_KEY)) || "[]");
  } catch {
    return [];
  }
}

export async function currentTripId(): Promise<number | null> {
  const v = await AsyncStorage.getItem(TRIP_KEY);
  return v ? Number(v) : null;
}

/** Send queued fixes. Returns true if the queue is empty afterwards. */
export async function flush(): Promise<boolean> {
  const tripId = await currentTripId();
  let queue = await readQueue();
  if (!tripId || !queue.length) return true;
  await loadToken();
  while (queue.length) {
    const batch = queue.slice(0, 100);
    try {
      const r = await api<{ accepted: number; rejected: unknown[]; duplicates: number }>(`/api/driver/trips/${tripId}/locations`, {
        method: "POST",
        json: { points: batch },
      });
      const s = await getStats();
      queue = queue.slice(batch.length);
      await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
      await setStats({ sent: s.sent + r.accepted, rejected: s.rejected + r.rejected.length, lastSentAt: new Date().toISOString(), lastError: undefined, queued: queue.length });
    } catch (e) {
      const status = (e as { status?: number }).status;
      if (status === 409 || status === 404 || status === 403) {
        // trip ended or bus reassigned elsewhere: stop sharing immediately
        await stopTracking();
        await setStats({ lastError: (e as Error).message });
        return false;
      }
      await setStats({ lastError: (e as Error).message, queued: queue.length });
      return false;
    }
  }
  return true;
}

TaskManager.defineTask(TASK, async ({ data, error }) => {
  if (error) {
    await setStats({ lastError: error.message });
    return;
  }
  const { locations } = (data || {}) as { locations?: Location.LocationObject[] };
  if (!locations?.length) return;
  const s = await getStats();
  let low = 0;
  const fixes: Fix[] = [];
  for (const l of locations) {
    const acc = l.coords.accuracy ?? undefined;
    if (acc != null && acc > MAX_ACCURACY_M) {
      low++;
      continue;
    }
    fixes.push({
      lat: l.coords.latitude,
      lng: l.coords.longitude,
      recorded_at: new Date(l.timestamp).toISOString(),
      accuracy_m: acc,
      speed_mps: l.coords.speed != null && l.coords.speed >= 0 ? l.coords.speed : undefined,
      heading: l.coords.heading != null && l.coords.heading >= 0 ? l.coords.heading : undefined,
    });
  }
  const last = locations[locations.length - 1];
  const queue = [...(await readQueue()), ...fixes].slice(-MAX_QUEUE);
  await AsyncStorage.setItem(QUEUE_KEY, JSON.stringify(queue));
  await setStats({ lowAccuracy: s.lowAccuracy + low, lastFixAt: new Date(last.timestamp).toISOString(), lastAccuracy: last.coords.accuracy ?? undefined, queued: queue.length });
  await flush();
});

export type PermissionState = { foreground: boolean; background: boolean; servicesEnabled: boolean };

export async function checkPermissions(): Promise<PermissionState> {
  const [fg, bg, services] = await Promise.all([
    Location.getForegroundPermissionsAsync(),
    Location.getBackgroundPermissionsAsync(),
    Location.hasServicesEnabledAsync(),
  ]);
  return { foreground: fg.status === "granted", background: bg.status === "granted", servicesEnabled: services };
}

export async function requestPermissions(): Promise<PermissionState> {
  const fg = await Location.requestForegroundPermissionsAsync();
  if (fg.status === "granted") await Location.requestBackgroundPermissionsAsync();
  return checkPermissions();
}

export async function startTracking(tripId: number) {
  await AsyncStorage.setItem(TRIP_KEY, String(tripId));
  await AsyncStorage.setItem(STATS_KEY, JSON.stringify({ sent: 0, rejected: 0, lowAccuracy: 0, queued: 0 }));
  if (await Location.hasStartedLocationUpdatesAsync(TASK)) return;
  await Location.startLocationUpdatesAsync(TASK, {
    accuracy: Location.Accuracy.BestForNavigation,
    timeInterval: INTERVAL_MS,
    distanceInterval: 0,
    deferredUpdatesInterval: INTERVAL_MS,
    pausesUpdatesAutomatically: false,
    showsBackgroundLocationIndicator: true,
    foregroundService: {
      notificationTitle: "Speedo Live: sharing bus location",
      notificationBody: "Your bus's location is shared with passengers until you end the trip.",
      notificationColor: "#173693",
      killServiceOnDestroy: false,
    },
  });
}

export async function stopTracking() {
  if (await Location.hasStartedLocationUpdatesAsync(TASK).catch(() => false)) {
    await Location.stopLocationUpdatesAsync(TASK);
  }
  await AsyncStorage.multiRemove([TRIP_KEY, QUEUE_KEY]);
}

export async function isTracking(): Promise<boolean> {
  return Location.hasStartedLocationUpdatesAsync(TASK).catch(() => false);
}
