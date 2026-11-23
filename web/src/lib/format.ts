/** Distance for people: "350 m", "1.3 km". */
export function km(m: number | null | undefined): string {
  if (m == null) return "–";
  return m < 1000 ? `${Math.round(m)} m` : `${(m / 1000).toFixed(1)} km`;
}
