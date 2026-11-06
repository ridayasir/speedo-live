import { ActivityIndicator, Pressable, StyleSheet, Text, TextInput, View, type TextInputProps, type ViewStyle } from "react-native";
import { C, STATUS } from "../lib/theme";

export function Card({ children, style }: { children: React.ReactNode; style?: ViewStyle }) {
  return <View style={[s.card, style]}>{children}</View>;
}

export function Title({ children }: { children: React.ReactNode }) {
  return <Text style={s.title}>{children}</Text>;
}

export function Section({ children }: { children: React.ReactNode }) {
  return <Text style={s.section}>{children}</Text>;
}

export function Muted({ children, style }: { children: React.ReactNode; style?: object }) {
  return <Text style={[s.muted, style]}>{children}</Text>;
}

export function Btn({ title, onPress, variant = "primary", loading, disabled, small }: {
  title: string; onPress: () => void; variant?: "primary" | "accent" | "outline" | "danger"; loading?: boolean; disabled?: boolean; small?: boolean;
}) {
  const bg = variant === "primary" ? C.brand : variant === "accent" ? C.accent : variant === "danger" ? C.red : "#fff";
  const fg = variant === "outline" ? C.text : "#fff";
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      disabled={disabled || loading}
      style={({ pressed }) => [s.btn, small && s.btnSmall, { backgroundColor: bg, opacity: disabled ? 0.5 : pressed ? 0.85 : 1 }, variant === "outline" && s.outline]}
    >
      {loading ? <ActivityIndicator color={fg} /> : <Text style={[s.btnText, { color: fg }]}>{title}</Text>}
    </Pressable>
  );
}

export function Field({ label, ...rest }: TextInputProps & { label?: string }) {
  return (
    <View style={{ marginBottom: 10 }}>
      {label && <Text style={s.label}>{label}</Text>}
      <TextInput placeholderTextColor="#94a3b8" style={s.input} {...rest} />
    </View>
  );
}

export function Demo() {
  return <Text style={s.demo}>DEMO</Text>;
}

export function DemoBanner({ show }: { show: boolean }) {
  if (!show) return null;
  return (
    <View style={s.banner}>
      <Text style={s.bannerText}>DEMO MODE: buses, routes and times are simulated sample data, not real Speedo services.</Text>
    </View>
  );
}

export function StatusPill({ status }: { status: string }) {
  const st = STATUS[status] || { label: status, color: C.muted, bg: "#f1f5f9" };
  return (
    <View style={[s.pill, { backgroundColor: st.bg }]}>
      <Text style={{ color: st.color, fontSize: 11, fontWeight: "600" }}>{st.label}</Text>
    </View>
  );
}

export function RouteChip({ code, color }: { code: string; color: string }) {
  return <Text style={[s.chip, { backgroundColor: color }]}>{code}</Text>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <View style={{ padding: 20, alignItems: "center" }}>
      <ActivityIndicator color={C.brand} />
      <Muted style={{ marginTop: 6 }}>{label}</Muted>
    </View>
  );
}

export function ErrorText({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <View style={s.error}>
      <Text style={{ color: C.red, flex: 1 }}>{error}</Text>
      {onRetry && <Text onPress={onRetry} style={{ color: C.red, fontWeight: "700" }}>Retry</Text>}
    </View>
  );
}

export const s = StyleSheet.create({
  card: { backgroundColor: C.card, borderRadius: 16, padding: 14, marginBottom: 12, borderWidth: 1, borderColor: "#eef1f5", shadowColor: "#000", shadowOpacity: 0.05, shadowRadius: 6, elevation: 1 },
  title: { fontSize: 22, fontWeight: "800", color: C.brandDark, marginBottom: 8 },
  section: { fontSize: 15, fontWeight: "700", color: C.text, marginBottom: 8 },
  muted: { color: C.muted, fontSize: 13 },
  btn: { borderRadius: 12, paddingVertical: 12, paddingHorizontal: 16, alignItems: "center", justifyContent: "center" },
  btnSmall: { paddingVertical: 7, paddingHorizontal: 12 },
  outline: { borderWidth: 1, borderColor: C.border },
  btnText: { fontWeight: "700", fontSize: 14 },
  label: { fontSize: 13, color: C.muted, marginBottom: 4, fontWeight: "600" },
  input: { borderWidth: 1, borderColor: C.border, borderRadius: 12, paddingHorizontal: 12, paddingVertical: 10, backgroundColor: "#fff", color: C.text, fontSize: 15 },
  demo: { backgroundColor: C.accent, color: "#fff", fontSize: 9, fontWeight: "800", paddingHorizontal: 4, paddingVertical: 1, borderRadius: 4, overflow: "hidden", marginLeft: 6 },
  banner: { backgroundColor: C.accent, paddingHorizontal: 12, paddingVertical: 6 },
  bannerText: { color: "#fff", fontSize: 12, fontWeight: "600" },
  pill: { borderRadius: 99, paddingHorizontal: 8, paddingVertical: 2, alignSelf: "flex-start" },
  chip: { color: "#fff", fontWeight: "800", fontSize: 11, paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, overflow: "hidden", alignSelf: "flex-start" },
  error: { flexDirection: "row", backgroundColor: C.redBg, padding: 10, borderRadius: 12, marginVertical: 6 },
  row: { flexDirection: "row", alignItems: "center" },
});
