/** Distance for people: "350 m", "1.3 km". */
export function km(m: number | null | undefined): string {
  if (m == null) return "–";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}

// every stop has its own colour (the same on every map and list), so neighbouring stops are easy to tell apart
const STOP_PALETTE = ["#e11d48", "#2563eb", "#16a34a", "#d97706", "#7c3aed", "#0891b2", "#db2777", "#65a30d",
  "#ea580c", "#4f46e5", "#0d9488", "#a21caf"];
export const stopColor = (id: number) => STOP_PALETTE[Math.abs(id) % STOP_PALETTE.length];
