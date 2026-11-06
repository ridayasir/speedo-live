import type { BusState } from "./types";

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  return `${Math.round(s / 3600)} h ago`;
}

export function km(m: number | null | undefined): string {
  if (m == null) return "–";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

export function clock(iso: string): string {
  const d = new Date(iso);
  // Pakistan Standard Time is UTC+5 with no daylight saving
  const pk = new Date(d.getTime() + (5 * 60 + d.getTimezoneOffset()) * 60000);
  return `${String(pk.getHours()).padStart(2, "0")}:${String(pk.getMinutes()).padStart(2, "0")}`;
}

export function effectiveStatus(b: BusState, staleAfter = 60, offlineAfter = 300): BusState["status"] {
  if (b.status === "out_of_service") return b.status;
  if (!b.last_gps_at) return b.trip_id ? "offline" : b.status;
  const age = (Date.now() - new Date(b.last_gps_at).getTime()) / 1000;
  if (age > offlineAfter) return "offline";
  if (age > staleAfter) return "stale";
  return b.status;
}
