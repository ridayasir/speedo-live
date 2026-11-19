"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { Button, ErrorBox, Input, Modal, PageHeader, Select, Spinner } from "../ui";
import { DataTable, nullIfEmpty, useForm } from "./common";
import { api } from "@/lib/api";
import { ago, useApi } from "@/lib/hooks";
import type { RouteSummary } from "@/lib/types";

interface AdminDriver {
  id: number;
  full_name: string;
  email: string | null;
  phone: string | null;
  license_number: string;
  employee_code: string | null;
  is_active: boolean;
  assigned_bus: { id: number; bus_number: string; route_id: number | null } | null;
  location_consent_at: string | null;
  active_trip_id: number | null;
}
interface BusLite { id: number; bus_number: string; route_id: number | null; driver: { id: number } | null }

export function DriversAdmin() {
  const drivers = useApi<AdminDriver[]>("/api/admin/drivers");
  const buses = useApi<BusLite[]>("/api/admin/buses");
  const routes = useApi<RouteSummary[]>("/api/routes?include_inactive=true");
  const [edit, setEdit] = useState<AdminDriver | "new" | null>(null);
  if (drivers.loading && !drivers.data) return <Spinner />;
  const routeCode = (id: number | null | undefined) => routes.data?.find((r) => r.id === id)?.code;
  return (
    <div>
      <PageHeader title="Drivers" subtitle="Driver accounts can only share the location of their assigned bus." action={<Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> Add driver</Button>} />
      {drivers.error && <ErrorBox error={drivers.error} onRetry={drivers.reload} />}
      <DataTable
        rows={drivers.data || []}
        rowKey={(d) => d.id}
        cols={[
          { h: "Name", c: (d) => <span className="font-medium">{d.full_name}</span> },
          { h: "Phone", c: (d) => d.phone || "–" },
          { h: "Licence", c: (d) => <span className="font-mono text-xs">{d.license_number}</span> },
          { h: "Bus", c: (d) => d.assigned_bus?.bus_number || <span className="text-slate-400">–</span> },
          { h: "Route", c: (d) => routeCode(d.assigned_bus?.route_id) || "–" },
          { h: "Trip", c: (d) => d.active_trip_id ? <span className="text-emerald-700 font-medium">On trip</span> : <span className="text-slate-400">Off duty</span> },
          { h: "Consent", c: (d) => <span className="text-xs text-slate-500">{d.location_consent_at ? ago(d.location_consent_at) : "not yet"}</span> },
          { h: "Account", c: (d) => d.is_active ? "Active" : <span className="text-red-600">Deactivated</span> },
          { h: "", c: (d) => <Button size="sm" variant="ghost" onClick={() => setEdit(d)}>Edit</Button>, className: "text-right" },
        ]}
      />
      {edit && (
        <DriverForm driver={edit === "new" ? null : edit} buses={buses.data || []} routes={routes.data || []}
          onClose={() => setEdit(null)} onSaved={() => { setEdit(null); drivers.reload(); buses.reload(); }} />
      )}
    </div>
  );
}

function DriverForm({ driver, buses, routes, onClose, onSaved }: { driver: AdminDriver | null; buses: BusLite[]; routes: RouteSummary[]; onClose: () => void; onSaved: () => void }) {
  const currentBus = buses.find((b) => b.id === driver?.assigned_bus?.id);
  const { v, set } = useForm({
    full_name: driver?.full_name || "",
    email: driver?.email || "",
    phone: driver?.phone || "",
    license_number: driver?.license_number || "",
    employee_code: driver?.employee_code || "",
    password: "",
    bus_id: driver?.assigned_bus ? String(driver.assigned_bus.id) : "",
    route_id: currentBus?.route_id ? String(currentBus.route_id) : "",
    is_active: driver ? driver.is_active : true,
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      if (driver) {
        await api(`/api/admin/drivers/${driver.id}`, {
          method: "PATCH",
          json: {
            full_name: v.full_name, phone: nullIfEmpty(v.phone) ?? undefined, license_number: v.license_number,
            employee_code: nullIfEmpty(v.employee_code), is_active: v.is_active, bus_id: v.bus_id ? Number(v.bus_id) : 0,
            route_id: v.route_id && v.bus_id ? Number(v.route_id) : undefined, password: v.password || undefined,
          },
        });
      } else {
        const d = await api<{ id: number }>("/api/admin/drivers", {
          method: "POST",
          json: { full_name: v.full_name, email: nullIfEmpty(v.email), phone: v.phone.replace(/[\s-]/g, ""), password: v.password,
            license_number: v.license_number, employee_code: nullIfEmpty(v.employee_code), bus_id: v.bus_id ? Number(v.bus_id) : null },
        });
        if (v.route_id && v.bus_id) await api(`/api/admin/drivers/${d.id}`, { method: "PATCH", json: { route_id: Number(v.route_id) } });
      }
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  return (
    <Modal open onClose={onClose} title={driver ? `Edit ${driver.full_name}` : "Add driver"}>
      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Full name" required value={v.full_name} onChange={set("full_name")} />
          <Input label="Mobile (login)" required={!driver} value={v.phone} onChange={set("phone")} placeholder="03xx xxxxxxx" />
          {!driver && <Input label="Email (optional)" type="email" value={v.email} onChange={set("email")} />}
          <Input label="Licence number" required value={v.license_number} onChange={set("license_number")} />
          <Input label="Employee code" value={v.employee_code} onChange={set("employee_code")} />
          <Input label={driver ? "New password (optional)" : "Password"} type="password" minLength={8} required={!driver} value={v.password} onChange={set("password")} />
        </div>
        <Select label="Assigned bus" value={v.bus_id} onChange={set("bus_id")}>
          <option value="">No bus</option>
          {buses.map((b) => (
            <option key={b.id} value={b.id}>{b.bus_number}{b.driver && b.driver.id !== driver?.id ? " (has a driver)" : ""}</option>
          ))}
        </Select>
        <Select label="Route for that bus" value={v.route_id} onChange={set("route_id")} disabled={!v.bus_id}>
          <option value="">Keep current</option>
          {routes.map((r) => <option key={r.id} value={r.id}>{r.code}: {r.name}</option>)}
        </Select>
        {driver && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={!!v.is_active} onChange={set("is_active")} className="h-4 w-4 accent-brand-700" /> Account active
          </label>
        )}
        {err && <ErrorBox error={err} />}
        <div className="flex justify-end pt-2"><Button type="submit">Save</Button></div>
      </form>
    </Modal>
  );
}
