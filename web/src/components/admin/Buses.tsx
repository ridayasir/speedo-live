"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button, DemoBadge, ErrorBox, Input, Modal, PageHeader, Select, Spinner, StatusPill, effectiveStatus } from "../ui";
import { DataTable, nullIfEmpty, useForm } from "./common";
import { api } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";
import type { BusState, RouteSummary } from "@/lib/types";

interface AdminBus {
  id: number;
  bus_number: string;
  registration_number: string | null;
  capacity: number | null;
  status: string;
  route_id: number | null;
  route_code: string | null;
  gps_device_id: string | null;
  is_demo: boolean;
  driver: { id: number; name: string } | null;
  last_gps_at: string | null;
  live: BusState;
}
interface DriverLite { id: number; full_name: string; assigned_bus: { id: number } | null }

export function BusesAdmin() {
  const buses = useApi<AdminBus[]>("/api/admin/buses");
  const routes = useApi<RouteSummary[]>("/api/routes?include_inactive=true");
  const drivers = useApi<DriverLite[]>("/api/admin/drivers");
  const [edit, setEdit] = useState<AdminBus | "new" | null>(null);
  const [q, setQ] = useState("");
  if (buses.loading && !buses.data) return <Spinner />;
  const rows = (buses.data || []).filter((b) => !q || b.bus_number.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <PageHeader title="Buses" subtitle={`${buses.data?.length ?? 0} registered`} action={<Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> Add bus</Button>} />
      {buses.error && <ErrorBox error={buses.error} onRetry={buses.reload} />}
      <div className="mb-3 max-w-xs"><Input placeholder="Search bus number" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <DataTable
        rows={rows}
        rowKey={(b) => b.id}
        cols={[
          { h: "Bus", c: (b) => <span className="font-semibold">{b.bus_number} {b.is_demo && <DemoBadge />}</span> },
          { h: "Registration", c: (b) => b.registration_number || "–" },
          { h: "Route", c: (b) => b.route_code || <span className="text-slate-400">Unassigned</span> },
          { h: "Driver", c: (b) => b.driver?.name || <span className="text-slate-400">–</span> },
          { h: "Fleet status", c: (b) => <span className="capitalize">{b.status.replace(/_/g, " ")}</span> },
          { h: "Live", c: (b) => <StatusPill status={effectiveStatus(b.live)} /> },
          { h: "GPS", c: (b) => <span className="text-xs text-slate-500">{ago(b.last_gps_at)}</span> },
          { h: "", c: (b) => <Button size="sm" variant="ghost" onClick={() => setEdit(b)}>Edit</Button>, className: "text-right" },
        ]}
      />
      {edit && (
        <BusForm
          bus={edit === "new" ? null : edit}
          routes={routes.data || []}
          drivers={drivers.data || []}
          onClose={() => setEdit(null)}
          onSaved={() => { setEdit(null); buses.reload(); drivers.reload(); }}
        />
      )}
    </div>
  );
}

function BusForm({ bus, routes, drivers, onClose, onSaved }: { bus: AdminBus | null; routes: RouteSummary[]; drivers: DriverLite[]; onClose: () => void; onSaved: () => void }) {
  const { v, set } = useForm({
    bus_number: bus?.bus_number || "",
    registration_number: bus?.registration_number || "",
    capacity: bus?.capacity ? String(bus.capacity) : "",
    status: bus?.status || "active",
    route_id: bus?.route_id ? String(bus.route_id) : "",
    gps_device_id: bus?.gps_device_id || "",
    driver_id: bus?.driver ? String(bus.driver.id) : "",
  });
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    const body = {
      bus_number: v.bus_number.trim(),
      registration_number: nullIfEmpty(v.registration_number),
      capacity: v.capacity ? Number(v.capacity) : null,
      status: v.status,
      route_id: v.route_id ? Number(v.route_id) : null,
      gps_device_id: nullIfEmpty(v.gps_device_id),
    };
    try {
      if (bus) await api(`/api/admin/buses/${bus.id}`, { method: "PATCH", json: { ...body, driver_id: v.driver_id ? Number(v.driver_id) : 0 } });
      else {
        const created = await api<{ id: number }>("/api/admin/buses", { method: "POST", json: body });
        if (v.driver_id) await api(`/api/admin/buses/${created.id}`, { method: "PATCH", json: { driver_id: Number(v.driver_id) } });
      }
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const deactivate = async (hard: boolean) => {
    if (!bus) return;
    if (hard && !confirm(`Permanently delete ${bus.bus_number} and its trip history? This cannot be undone.`)) return;
    try {
      await api(`/api/admin/buses/${bus.id}?hard=${hard}`, { method: "DELETE" });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <Modal open onClose={onClose} title={bus ? `Edit ${bus.bus_number}` : "Add bus"}>
      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Bus number" required value={v.bus_number} onChange={set("bus_number")} />
          <Input label="Registration no." value={v.registration_number} onChange={set("registration_number")} />
          <Input label="Capacity" type="number" min={1} value={v.capacity} onChange={set("capacity")} />
          <Select label="Status" value={v.status} onChange={set("status")}>
            <option value="active">Active</option>
            <option value="inactive">Inactive</option>
            <option value="maintenance">Maintenance</option>
            <option value="out_of_service">Out of service</option>
          </Select>
        </div>
        <Select label="Assigned route" value={v.route_id} onChange={set("route_id")}>
          <option value="">No route</option>
          {routes.map((r) => <option key={r.id} value={r.id}>{r.code}: {r.name}</option>)}
        </Select>
        <Select label="Assigned driver" value={v.driver_id} onChange={set("driver_id")}>
          <option value="">No driver</option>
          {drivers.map((d) => (
            <option key={d.id} value={d.id}>
              {d.full_name}{d.assigned_bus && d.assigned_bus.id !== bus?.id ? " (has another bus)" : ""}
            </option>
          ))}
        </Select>
        <Input label="GPS device ID (for an external GPS provider)" value={v.gps_device_id} onChange={set("gps_device_id")} />
        {err && <ErrorBox error={err} />}
        <div className="flex flex-wrap justify-between gap-2 pt-2">
          <div className="flex gap-2">
            {bus && <Button type="button" variant="outline" onClick={() => deactivate(false)}>Deactivate</Button>}
            {bus && <Button type="button" variant="danger" onClick={() => deactivate(true)}>Delete</Button>}
          </div>
          <Button type="submit" loading={busy}>Save</Button>
        </div>
      </form>
    </Modal>
  );
}
