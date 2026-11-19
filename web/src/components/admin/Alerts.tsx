"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button, ErrorBox, Input, Modal, PageHeader, Select, Spinner } from "../ui";
import { DataTable } from "./common";
import { api } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";
import type { Alert, RouteSummary } from "@/lib/types";

export function AlertsAdmin() {
  const alerts = useApi<Alert[]>("/api/admin/alerts");
  const routes = useApi<RouteSummary[]>("/api/routes?include_inactive=true");
  const [edit, setEdit] = useState<Alert | "new" | null>(null);
  const code = (id: number | null) => routes.data?.find((r) => r.id === id)?.code || "All routes";
  return (
    <div>
      <PageHeader title="Service alerts" subtitle="Warnings and disruptions notify passengers who follow the route."
        action={<Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> New alert</Button>} />
      {alerts.loading && !alerts.data && <Spinner />}
      {alerts.error && <ErrorBox error={alerts.error} onRetry={alerts.reload} />}
      <DataTable
        rows={alerts.data || []}
        rowKey={(a) => a.id}
        cols={[
          { h: "Severity", c: (a) => <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${a.severity === "disruption" ? "bg-red-100 text-red-700" : a.severity === "warning" ? "bg-amber-100 text-amber-700" : "bg-brand-50 text-brand-700"}`}>{a.severity}</span> },
          { h: "Title", c: (a) => <span className="font-medium">{a.title}</span> },
          { h: "Route", c: (a) => code(a.route_id) },
          { h: "Active", c: (a) => (a.is_active ? "Yes" : "No") },
          { h: "Created", c: (a) => <span className="text-xs text-slate-500">{ago(a.created_at)}</span> },
          { h: "", c: (a) => <Button size="sm" variant="ghost" onClick={() => setEdit(a)}>Edit</Button>, className: "text-right" },
        ]}
      />
      {edit && <AlertForm a={edit === "new" ? null : edit} routes={routes.data || []} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); alerts.reload(); }} />}
    </div>
  );
}

function toLocal(iso: string | null) {
  if (!iso) return "";
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

function AlertForm({ a, routes, onClose, onSaved }: { a: Alert | null; routes: RouteSummary[]; onClose: () => void; onSaved: () => void }) {
  const [f, setF] = useState({
    route_id: a?.route_id ? String(a.route_id) : "", severity: a?.severity || "info", title: a?.title || "", message: a?.message || "",
    starts_at: toLocal(a?.starts_at || null), ends_at: toLocal(a?.ends_at || null), is_active: a ? a.is_active : true,
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = {
      route_id: f.route_id ? Number(f.route_id) : null, severity: f.severity, title: f.title, message: f.message, is_active: f.is_active,
      starts_at: f.starts_at ? new Date(f.starts_at).toISOString() : null, ends_at: f.ends_at ? new Date(f.ends_at).toISOString() : null,
    };
    try {
      if (a) await api(`/api/admin/alerts/${a.id}`, { method: "PATCH", json: body });
      else await api("/api/admin/alerts", { method: "POST", json: body });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const del = async () => {
    if (!a || !confirm("Delete this alert?")) return;
    await api(`/api/admin/alerts/${a.id}`, { method: "DELETE" });
    onSaved();
  };
  return (
    <Modal open onClose={onClose} title={a ? "Edit alert" : "New service alert"}>
      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Select label="Route" value={f.route_id} onChange={(e) => setF({ ...f, route_id: e.target.value })}>
            <option value="">All routes (network-wide)</option>
            {routes.map((r) => <option key={r.id} value={r.id}>{r.code}</option>)}
          </Select>
          <Select label="Severity" value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value as Alert["severity"] })}>
            <option value="info">Info</option><option value="warning">Warning</option><option value="disruption">Disruption</option>
          </Select>
        </div>
        <Input label="Title" required minLength={3} value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
        <label className="block text-sm"><span className="mb-1 block font-medium text-slate-600">Message</span>
          <textarea required minLength={3} rows={3} className="w-full rounded-xl border border-slate-200 p-2.5" value={f.message} onChange={(e) => setF({ ...f, message: e.target.value })} /></label>
        <div className="grid grid-cols-2 gap-3">
          <Input label="Starts (optional)" type="datetime-local" value={f.starts_at} onChange={(e) => setF({ ...f, starts_at: e.target.value })} />
          <Input label="Ends (optional)" type="datetime-local" value={f.ends_at} onChange={(e) => setF({ ...f, ends_at: e.target.value })} />
        </div>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} className="h-4 w-4 accent-brand-700" /> Active</label>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-between pt-2">
          {a ? <Button type="button" variant="danger" onClick={del}>Delete</Button> : <span />}
          <Button type="submit">{a ? "Save" : "Publish alert"}</Button>
        </div>
      </form>
    </Modal>
  );
}
