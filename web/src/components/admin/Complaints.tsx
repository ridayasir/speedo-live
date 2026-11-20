"use client";

import { useState } from "react";
import { Button, Card, ErrorBox, Modal, PageHeader, Select, Spinner } from "../ui";
import { DataTable, Stat } from "./common";
import { RouteChip } from "../widgets";
import { api } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";
import type { AdminComplaint } from "@/lib/types";

interface Summary {
  by_status: Record<string, number>;
  open: number;
  drivers: { driver_id: number; driver_name: string; driver_code: string | null; total: number; open: number; upheld: number; last_at: string | null }[];
  buses: { bus_number: string; total: number }[];
  statuses: Record<string, string>;
}

const STATUS_STYLE: Record<string, string> = {
  new: "bg-sky-100 text-sky-700",
  in_review: "bg-amber-100 text-amber-700",
  resolved: "bg-emerald-100 text-emerald-700",
  rejected: "bg-slate-200 text-slate-600",
};
const STATUS_LABEL: Record<string, string> = { new: "Received", in_review: "Under review", resolved: "Resolved", rejected: "Closed" };

function StatusTag({ s }: { s: string }) {
  return <span className={`rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${STATUS_STYLE[s] || ""}`}>{STATUS_LABEL[s] || s}</span>;
}

export function ComplaintsAdmin() {
  const [filter, setFilter] = useState("open");
  const [driverId, setDriverId] = useState<number | null>(null);
  const q = new URLSearchParams({ status: filter, ...(driverId ? { driver_id: String(driverId) } : {}) });
  const list = useApi<AdminComplaint[]>(`/api/admin/complaints?${q.toString()}`);
  const summary = useApi<Summary>("/api/admin/complaints/summary");
  const [open, setOpen] = useState<AdminComplaint | null>(null);
  const reload = () => { list.reload(); summary.reload(); };
  const driverName = driverId ? summary.data?.drivers.find((d) => d.driver_id === driverId)?.driver_name : null;
  const s = summary.data?.by_status || {};

  return (
    <div className="space-y-6">
      <PageHeader title="Driver reports" subtitle="Passenger complaints about buses and drivers, filed with the bus number." />
      <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
        <Stat label="Open" value={summary.data?.open ?? "–"} tone="red" />
        <Stat label="Received" value={s.new ?? "–"} tone="brand" />
        <Stat label="Under review" value={s.in_review ?? "–"} tone="amber" />
        <Stat label="Resolved" value={s.resolved ?? "–"} tone="green" />
        <Stat label="Closed" value={s.rejected ?? "–"} tone="slate" />
      </div>

      <div>
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <Select value={filter} onChange={(e) => setFilter(e.target.value)} aria-label="Status filter" className="w-auto">
            <option value="open">Open (received + under review)</option>
            <option value="all">All</option>
            <option value="new">Received</option>
            <option value="in_review">Under review</option>
            <option value="resolved">Resolved</option>
            <option value="rejected">Closed</option>
          </Select>
          {driverId && (
            <Button size="sm" variant="ghost" onClick={() => setDriverId(null)}>Driver: {driverName} ✕</Button>
          )}
        </div>
        {list.loading && !list.data && <Spinner />}
        {list.error && <ErrorBox error={list.error} onRetry={list.reload} />}
        <DataTable
          rows={list.data || []}
          rowKey={(c) => c.id}
          empty="No reports here."
          cols={[
            { h: "Reference", c: (c) => <span className="font-mono text-xs font-semibold">{c.ref_code}</span> },
            { h: "Bus", c: (c) => <span className="font-medium">{c.bus_number}</span> },
            { h: "Route", c: (c) => (c.route_code ? <RouteChip code={c.route_code} color={c.route_color || "#b91c1c"} className="max-w-[11rem]" /> : "–") },
            { h: "Problem", c: (c) => c.category_label },
            { h: "Driver", c: (c) => c.driver_name || <span className="text-slate-400">not known</span> },
            { h: "Status", c: (c) => <StatusTag s={c.status} /> },
            { h: "Reported", c: (c) => <span className="text-xs text-slate-500">{ago(c.created_at)}</span> },
            { h: "", c: (c) => <Button size="sm" variant="ghost" onClick={() => setOpen(c)}>Open</Button>, className: "text-right" },
          ]}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card className="p-5">
          <h3 className="mb-1 font-semibold text-slate-800">Drivers with the most reports</h3>
          <p className="mb-3 text-xs text-slate-500">Last 90 days. Click a driver to see their reports.</p>
          {(summary.data?.drivers || []).length === 0 ? <p className="text-sm text-slate-500">No reports linked to a driver yet.</p> : (
            <table className="w-full text-sm">
              <thead className="text-left text-xs uppercase text-slate-500"><tr><th className="py-1">Driver</th><th>Total</th><th>Open</th><th>Upheld</th></tr></thead>
              <tbody>
                {summary.data!.drivers.map((d) => (
                  <tr key={d.driver_id} className="border-t border-slate-100">
                    <td className="py-1.5">
                      <button className="text-left font-medium text-brand-700 hover:underline" onClick={() => { setDriverId(d.driver_id); setFilter("all"); }}>
                        {d.driver_name}
                      </button>
                      {d.driver_code && <span className="ml-1 text-xs text-slate-400">{d.driver_code}</span>}
                    </td>
                    <td className="font-semibold">{d.total}</td><td>{d.open}</td><td>{d.upheld}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
        <Card className="p-5">
          <h3 className="mb-1 font-semibold text-slate-800">Buses with the most reports</h3>
          <p className="mb-3 text-xs text-slate-500">Last 90 days.</p>
          {(summary.data?.buses || []).length === 0 ? <p className="text-sm text-slate-500">No reports yet.</p> : (
            <ul className="divide-y divide-slate-100 text-sm">
              {summary.data!.buses.map((b) => (
                <li key={b.bus_number} className="flex justify-between py-1.5"><span className="font-medium">{b.bus_number}</span><span className="font-semibold">{b.total}</span></li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      {open && <ComplaintModal c={open} onClose={() => setOpen(null)} onSaved={() => { setOpen(null); reload(); }} />}
    </div>
  );
}

function ComplaintModal({ c, onClose, onSaved }: { c: AdminComplaint; onClose: () => void; onSaved: () => void }) {
  const [status, setStatus] = useState(c.status);
  const [note, setNote] = useState(c.admin_note || "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/admin/complaints/${c.id}`, { method: "PATCH", json: { status, admin_note: note } });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const row = (k: string, v: React.ReactNode) => (
    <div className="flex gap-3 py-1 text-sm"><span className="w-28 shrink-0 text-slate-500">{k}</span><span className="text-slate-800">{v}</span></div>
  );
  return (
    <Modal open onClose={onClose} title={`Report ${c.ref_code}`}>
      <div className="divide-y divide-slate-100">
        {row("Bus", <>{c.bus_number} {c.route_name && <span className="text-slate-500">· {c.route_name}</span>}</>)}
        {row("Driver", c.driver_name ? `${c.driver_name}${c.driver_code ? ` (${c.driver_code})` : ""}` : "Not known (no driver on this bus)")}
        {row("Problem", c.category_label)}
        {row("When", new Date(c.incident_at).toLocaleString("en-PK", { timeZone: "Asia/Karachi" }))}
        {c.location && row("Where", c.location)}
        {row("Reported by", c.filed_by ? `${c.filed_by.name}${c.filed_by.email ? ` · ${c.filed_by.email}` : ""}` : (c.contact_name || "Anonymous"))}
        {c.contact_phone && row("Phone", c.contact_phone)}
      </div>
      <p className="mt-3 whitespace-pre-line rounded-xl bg-surface p-3 text-sm text-slate-700">{c.description}</p>
      <div className="mt-4 space-y-3">
        <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value as AdminComplaint["status"])}>
          <option value="new">Received</option>
          <option value="in_review">Under review</option>
          <option value="resolved">Resolved (complaint upheld)</option>
          <option value="rejected">Closed (no action)</option>
        </Select>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">Reply to the passenger</span>
          <textarea rows={3} maxLength={2000} value={note} onChange={(e) => setNote(e.target.value)}
            placeholder="Shown to the passenger with their reference code"
            className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
        </label>
        {c.filed_by && <p className="text-xs text-slate-500">The passenger is signed in and gets a notification when you save a change.</p>}
        {error && <ErrorBox error={error} />}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button onClick={save} loading={busy}>Save</Button>
        </div>
      </div>
    </Modal>
  );
}
