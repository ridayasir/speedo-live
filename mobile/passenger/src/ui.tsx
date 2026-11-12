// Shared look & feel: deep blue, white, orange accent, rounded cards.
import React from "react";
import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, ViewStyle } from "react-native";

export const C = {
  blue: "#0B3B8C", blue50: "#EBF1FB", orange: "#F97316", bg: "#F4F6FA", card: "#FFFFFF", ink: "#0F1B2D", ink2: "#44526A",
  ink3: "#6B7890", line: "#E2E7EF", ok: "#0F8A4B", okBg: "#E6F6ED", warn: "#B45309", warnBg: "#FEF3E2", bad: "#C2261C", badBg: "#FDECEA",
};

export const STATUS: Record<string, { label: string; fg: string; bg: string }> = {
  active: { label: "On the move", fg: C.ok, bg: C.okBg },
  delayed: { label: "Delayed", fg: C.warn, bg: C.warnBg },
  stale: { label: "GPS weak", fg: C.ink3, bg: "#EEF1F5" },
  offline: { label: "Offline", fg: C.bad, bg: C.badBg },
  out_of_service: { label: "Out of service", fg: C.bad, bg: C.badBg },
  not_in_service: { label: "Not in service", fg: C.ink3, bg: "#EEF1F5" },
};

export function Badge({ text, fg = C.ink2, bg = "#EEF1F5" }: { text: string; fg?: string; bg?: string }) {
  return <View style={[s.badge, { backgroundColor: bg }]}><Text style={[s.badgeText, { color: fg }]}>{text}</Text></View>;
}
export const StatusBadge = ({ status }: { status: string }) => { const x = STATUS[status] || STATUS.not_in_service; return <Badge text={x.label} fg={x.fg} bg={x.bg} />; };
export const DemoBadge = ({ show = true }: { show?: boolean }) => show ? <Badge text="DEMO" fg="#fff" bg={C.orange} /> : null;
export const RouteChip = ({ code, color }: { code: string; color?: string | null }) => (
  <View style={[s.chip, { backgroundColor: color || C.blue }]}><Text style={s.chipText}>{code}</Text></View>
);

export function Card({ children, style, onPress }: { children: React.ReactNode; style?: ViewStyle; onPress?: () => void }) {
  const body = <View style={[s.card, style]}>{children}</View>;
  return onPress ? <Pressable onPress={onPress} style={({ pressed }) => ({ opacity: pressed ? 0.8 : 1 })} accessibilityRole="button">{body}</Pressable> : body;
}

export function Button({ title, onPress, kind = "primary", disabled }: { title: string; onPress: () => void; kind?: "primary" | "accent" | "plain" | "danger"; disabled?: boolean }) {
  const bg = kind === "primary" ? C.blue : kind === "accent" ? C.orange : kind === "danger" ? C.bad : "#fff";
  return (
    <Pressable onPress={onPress} disabled={disabled} accessibilityRole="button"
      style={({ pressed }) => [s.btn, { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.85 : 1, borderWidth: kind === "plain" ? 1 : 0 }]}>
      <Text style={[s.btnText, { color: kind === "plain" ? C.ink : "#fff" }]}>{title}</Text>
    </Pressable>
  );
}

export function Field(props: React.ComponentProps<typeof TextInput> & { label: string }) {
  return (
    <View style={{ marginBottom: 12 }}>
      <Text style={s.label}>{props.label}</Text>
      <TextInput placeholderTextColor={C.ink3} {...props} style={[s.input, props.style]} accessibilityLabel={props.label} />
    </View>
  );
}

export const H = ({ children }: { children: React.ReactNode }) => <Text style={s.h}>{children}</Text>;
export const Section = ({ children }: { children: React.ReactNode }) => <Text style={s.section}>{children}</Text>;
export const Muted = ({ children }: { children: React.ReactNode }) => <Text style={s.muted}>{children}</Text>;
export const Loading = () => <View style={{ padding: 24 }}><ActivityIndicator color={C.blue} /></View>;
export const ErrorText = ({ text }: { text?: string | null }) => text ? <Text style={{ color: C.bad, marginVertical: 6 }}>{text}</Text> : null;

export const s = StyleSheet.create({
  screen: { flex: 1, backgroundColor: C.bg },
  pad: { padding: 16 },
  card: { backgroundColor: C.card, borderRadius: 14, padding: 14, marginBottom: 10, shadowColor: "#0F1B2D", shadowOpacity: 0.06, shadowRadius: 8, shadowOffset: { width: 0, height: 2 }, elevation: 2 },
  badge: { borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2, alignSelf: "flex-start" },
  badgeText: { fontSize: 11, fontWeight: "700" },
  chip: { borderRadius: 7, paddingHorizontal: 8, paddingVertical: 2 },
  chipText: { color: "#fff", fontWeight: "800", fontSize: 12 },
  btn: { minHeight: 48, borderRadius: 12, alignItems: "center", justifyContent: "center", paddingHorizontal: 16, marginVertical: 6, borderColor: C.line },
  btnText: { fontWeight: "700", fontSize: 16 },
  label: { fontSize: 12, fontWeight: "700", color: C.ink2, marginBottom: 4 },
  input: { borderWidth: 1, borderColor: "#D3DAE5", borderRadius: 10, paddingHorizontal: 12, minHeight: 46, backgroundColor: "#fff", color: C.ink, fontSize: 15 },
  h: { fontSize: 22, fontWeight: "800", color: C.blue, marginBottom: 8 },
  section: { fontSize: 12, fontWeight: "800", color: C.ink2, letterSpacing: 0.6, textTransform: "uppercase", marginTop: 16, marginBottom: 8 },
  muted: { color: C.ink3, fontSize: 13 },
  row: { flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" },
  title: { fontSize: 16, fontWeight: "700", color: C.ink },
  demoBanner: { backgroundColor: C.orange, paddingVertical: 6, paddingHorizontal: 12 },
  demoText: { color: "#fff", fontSize: 12, fontWeight: "600" },
});
