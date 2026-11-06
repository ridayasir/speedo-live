export const C = {
  brand: "#173693",
  brandDark: "#0c1d52",
  brandLight: "#eef4ff",
  accent: "#f97316",
  bg: "#f4f6fa",
  card: "#ffffff",
  text: "#0f172a",
  muted: "#64748b",
  border: "#e2e8f0",
  green: "#047857",
  greenBg: "#ecfdf5",
  amber: "#b45309",
  amberBg: "#fffbeb",
  red: "#b91c1c",
  redBg: "#fef2f2",
};

export const STATUS: Record<string, { label: string; color: string; bg: string }> = {
  active: { label: "On route", color: C.green, bg: C.greenBg },
  delayed: { label: "Delayed", color: C.amber, bg: C.amberBg },
  stale: { label: "GPS signal lost", color: C.muted, bg: "#f1f5f9" },
  offline: { label: "Offline", color: C.muted, bg: "#f1f5f9" },
  idle: { label: "Not on a trip", color: "#0369a1", bg: "#f0f9ff" },
  out_of_service: { label: "Out of service", color: C.red, bg: C.redBg },
};
