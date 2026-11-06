"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button, DemoBadge, ErrorBox, Input, Modal, PageHeader, Select, Spinner } from "../ui";
import { DataTable } from "./common";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { RouteSummary, Schedule } from "@/lib/types";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

export function SchedulesAdmin() {
  const [routeId, setRouteId] = useState("");
  const scheds = useApi<Schedule[]>(`/api/admin/schedules${routeId ? `?route_id=${routeId}` : ""}`);
  const routes = useApi<RouteSummary[]>("/api/routes?include_inactive=true");
  const [edit, setEdit] = useState<Schedule | "new" | null>(null);
  return (
    <div>
      <PageHeader title="Schedules" subtitle="Operating hours and frequency per route. Passengers following a route are notified of changes."
        action={<Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> Add schedule</Button>} />
      <div className="mb-3 max-w-sm">
        <Select value={routeId} onChange={(e) => setRouteId(e.target.value)} aria-label="Route filter">
          <option value="">All routes</option>
          {routes.data?.map((r) => <option key={r.id} value={r.id}>{r.code}: {r.name}</option>)}
        </Select>
      </div>
      {scheds.loading && !scheds.data && <Spinner />}
      {scheds.error && <ErrorBox error={scheds.error} onRetry={scheds.reload} />}
      <DataTable
        rows={scheds.data || []}
        rowKey={(s) => s.id}
        cols={[
          { h: "Route", c: (s) => <b>{s.route_code}</b> },
          { h: "Days", c: (s) => s.days.map((d) => d[0].toUpperCase() + d.slice(1)).join(", ") },
          { h: "First", c: (s) => s.first_departure },
          { h: "Last", c: (s) => s.last_departure },
          { h: "Every", c: (s) => `${s.frequency_minutes} min` },
          { h: "Notes", c: (s) => <span className="text-xs text-slate-500">{s.notes} {s.is_demo && <DemoBadge />}</span> },
          { h: "", c: (s) => <Button size="sm" variant="ghost" onClick={() => setEdit(s)}>Edit</Button>, className: "text-right" },
        ]}
      />
      {edit && <ScheduleForm s={edit === "new" ? null : edit} routes={routes.data || []} defaultRoute={routeId} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); scheds.reload(); }} />}
    </div>
  );
}

function ScheduleForm({ s, routes, defaultRoute, onClose, onSaved }: { s: Schedule | null; routes: RouteSummary[]; defaultRoute: string; onClose: () => void; onSaved: () => void }) {
  const [routeId, setRouteId] = useState(s ? String(s.route_id) : defaultRoute);
  const [days, setDays] = useState<string[]>(s?.days || DAYS.slice(0, 6));
  const [first, setFirst] = useState(s?.first_departure || "06:00");
  const [last, setLast] = useState(s?.last_departure || "22:00");
  const [freq, setFreq] = useState(String(s?.frequency_minutes || 15));
  const [notes, setNotes] = useState(s?.notes || "");
  const [err, setErr] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { route_id: Number(routeId), days: DAYS.filter((d) => days.includes(d)).join(","), first_departure: first, last_departure: last, frequency_minutes: Number(freq), notes: notes || null };
    try {
      if (s) await api(`/api/admin/schedules/${s.id}`, { method: "PUT", json: body });
      else await api("/api/admin/schedules", { method: "POST", json: body });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const del = async () => {
    if (!s || !confirm("Delete this schedule?")) return;
    await api(`/api/admin/schedules/${s.id}`, { method: "DELETE" });
    onSaved();
  };
  return (
    <Modal open onClose={onClose} title={s ? "Edit schedule" : "Add schedule"}>
      <form onSubmit={save} className="space-y-3">
        <Select label="Route" required value={routeId} onChange={(e) => setRouteId(e.target.value)}>
          <option value="">Choose route</option>
          {routes.map((r) => <option key={r.id} value={r.id}>{r.code}: {r.name}</option>)}
        </Select>
        <div>
          <span className="mb-1 block text-sm font-medium text-slate-600">Days of operation</span>
          <div className="flex flex-wrap gap-1.5">
            {DAYS.map((d) => (
              <button type="button" key={d} onClick={() => setDays((p) => (p.includes(d) ? p.filter((x) => x !== d) : [...p, d]))}
                className={`rounded-lg px-2.5 py-1 text-xs font-medium capitalize ${days.includes(d) ? "bg-brand-700 text-white" : "bg-slate-100 text-slate-600"}`}>{d}</button>
            ))}
          </div>
        </div>
        <div className="grid grid-cols-3 gap-3">
          <Input label="First departure" type="time" required value={first} onChange={(e) => setFirst(e.target.value)} />
          <Input label="Last departure" type="time" required value={last} onChange={(e) => setLast(e.target.value)} />
          <Input label="Every (min)" type="number" min={1} max={240} required value={freq} onChange={(e) => setFreq(e.target.value)} />
        </div>
        <Input label="Notes (e.g. holiday service)" value={notes} onChange={(e) => setNotes(e.target.value)} />
        {err && <ErrorBox error={err} />}
        <div className="flex justify-between pt-2">
          {s ? <Button type="button" variant="danger" onClick={del}>Delete</Button> : <span />}
          <Button type="submit" disabled={!routeId || days.length === 0}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}
