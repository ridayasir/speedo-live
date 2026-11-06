"use client";

import { Card, ErrorBox, PageHeader, SectionTitle, Spinner } from "../ui";
import { DataTable } from "./common";
import { API_URL } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";

interface AuditRow { id: number; user_id: number | null; action: string; entity: string; entity_id: string | null; created_at: string }

const LABELS: Record<string, string> = {
  data_source: "Data source (demo / driver / provider)",
  simulator_tick_seconds: "Simulator update interval (s)",
  gps_min_interval_seconds: "Minimum seconds between GPS fixes",
  gps_max_accuracy_m: "Reject GPS fixes less accurate than (m)",
  stale_after_seconds: "Mark GPS stale after (s)",
  offline_after_seconds: "Mark bus offline after (s)",
  interrupt_trip_after_seconds: "Interrupt silent trips after (s)",
  delay_threshold_minutes: "Delay threshold (min)",
  default_bus_speed_kmh: "Default bus speed for ETA (km/h)",
  gps_retention_days: "Keep GPS history for (days)",
  max_walk_m: "Max walk to a stop in journey planning (m)",
  fcm_configured: "Firebase push notifications configured",
  redis_configured: "Redis configured",
};

export function SettingsAdmin() {
  const s = useApi<Record<string, string | number | boolean>>("/api/admin/settings");
  const audit = useApi<AuditRow[]>("/api/admin/audit?limit=50");
  return (
    <div className="space-y-6">
      <PageHeader title="Settings" subtitle="Runtime settings come from server environment variables, so secrets never pass through the browser." />
      <Card className="p-5">
        <SectionTitle>System configuration</SectionTitle>
        {s.loading && <Spinner />}
        {s.error && <ErrorBox error={s.error} />}
        {s.data && (
          <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
            {Object.entries(s.data).map(([k, v]) => (
              <div key={k} className="flex justify-between border-b border-slate-100 py-1.5">
                <dt className="text-slate-600">{LABELS[k] || k}</dt>
                <dd className="font-medium text-slate-800">{typeof v === "boolean" ? (v ? "Yes" : "No") : String(v)}</dd>
              </div>
            ))}
          </dl>
        )}
        <p className="mt-4 text-xs text-slate-500">
          To switch from DEMO to real-world mode, set <code>DATA_SOURCE=driver</code> (driver apps only) or <code>DATA_SOURCE=provider</code> (approved GPS feed) on the API server and restart it.
          API documentation: <a className="text-brand-600 underline" href={`${API_URL}/docs`} target="_blank" rel="noreferrer">{API_URL}/docs</a>
        </p>
      </Card>
      <div>
        <SectionTitle>Recent admin activity</SectionTitle>
        <DataTable rows={audit.data || []} rowKey={(a) => a.id} empty="No admin activity yet." cols={[
          { h: "When", c: (a) => <span className="text-xs text-slate-500">{ago(a.created_at)}</span> },
          { h: "Action", c: (a) => <span className="capitalize">{a.action}</span> },
          { h: "Entity", c: (a) => `${a.entity}${a.entity_id && a.entity_id !== "None" ? ` #${a.entity_id}` : ""}` },
          { h: "Admin", c: (a) => (a.user_id ? `User ${a.user_id}` : "–") },
        ]} />
      </div>
    </div>
  );
}
