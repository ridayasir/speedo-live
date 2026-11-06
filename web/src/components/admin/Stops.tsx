"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import MapView from "../MapView";
import { Button, Card, DemoBadge, ErrorBox, Input, Modal, PageHeader, Spinner } from "../ui";
import { DataTable, nullIfEmpty, useForm } from "./common";
import { api } from "@/lib/api";
import { useApi } from "@/lib/hooks";
import type { Stop } from "@/lib/types";

type AdminStop = Stop & { route_count: number };

export function StopsAdmin() {
  const stops = useApi<AdminStop[]>("/api/admin/stops");
  const [edit, setEdit] = useState<AdminStop | "new" | null>(null);
  const [q, setQ] = useState("");
  if (stops.loading && !stops.data) return <Spinner />;
  const rows = (stops.data || []).filter((s) => !q || s.name.toLowerCase().includes(q.toLowerCase()) || s.code.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <PageHeader title="Bus stops" subtitle={`${stops.data?.length ?? 0} stops`} action={<Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> Add stop</Button>} />
      {stops.error && <ErrorBox error={stops.error} onRetry={stops.reload} />}
      <div className="grid gap-5 lg:grid-cols-5">
        <div className="lg:col-span-3 space-y-3">
          <div className="max-w-xs"><Input placeholder="Search stops" value={q} onChange={(e) => setQ(e.target.value)} /></div>
          <DataTable
            rows={rows}
            rowKey={(s) => s.id}
            cols={[
              { h: "Code", c: (s) => <span className="font-mono text-xs">{s.code}</span> },
              { h: "Name", c: (s) => <span className="font-medium">{s.name} {s.is_demo && <DemoBadge />}</span> },
              { h: "Coordinates", c: (s) => <span className="text-xs text-slate-500">{s.lat.toFixed(5)}, {s.lng.toFixed(5)}</span> },
              { h: "Routes", c: (s) => s.route_count },
              { h: "", c: (s) => <Button size="sm" variant="ghost" onClick={() => setEdit(s)}>Edit</Button>, className: "text-right" },
            ]}
          />
        </div>
        <Card className="lg:col-span-2 h-[480px] overflow-hidden sticky top-4">
          <MapView stops={rows} fitKey={`stops-${rows.length}`} onStopClick={(s) => setEdit(s as AdminStop)} />
        </Card>
      </div>
      {edit && <StopForm stop={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); stops.reload(); }} />}
    </div>
  );
}

function StopForm({ stop, onClose, onSaved }: { stop: AdminStop | null; onClose: () => void; onSaved: () => void }) {
  const { v, set, setV } = useForm({
    code: stop?.code || "",
    name: stop?.name || "",
    name_ur: stop?.name_ur || "",
    lat: stop ? String(stop.lat) : "",
    lng: stop ? String(stop.lng) : "",
    source_reference: stop?.source_reference || "",
  });
  const [err, setErr] = useState<string | null>(null);
  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    const body = { code: v.code.trim(), name: v.name.trim(), name_ur: nullIfEmpty(v.name_ur), lat: Number(v.lat), lng: Number(v.lng), source_reference: nullIfEmpty(v.source_reference) };
    try {
      if (stop) await api(`/api/admin/stops/${stop.id}`, { method: "PATCH", json: body });
      else await api("/api/admin/stops", { method: "POST", json: body });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const del = async () => {
    if (!stop || !confirm(`Delete stop ${stop.name}?`)) return;
    try {
      await api(`/api/admin/stops/${stop.id}`, { method: "DELETE" });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const center: [number, number] = v.lat && v.lng ? [Number(v.lat), Number(v.lng)] : [31.5204, 74.3587];
  return (
    <Modal open onClose={onClose} title={stop ? `Edit ${stop.name}` : "Add stop"}>
      <form onSubmit={save} className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Stop code" required value={v.code} onChange={set("code")} />
          <Input label="Name" required value={v.name} onChange={set("name")} />
          <Input label="Name (Urdu)" dir="rtl" value={v.name_ur} onChange={set("name_ur")} />
          <Input label="Source reference" value={v.source_reference} onChange={set("source_reference")} placeholder="e.g. PMA stop list 2026" />
          <Input label="Latitude" required type="number" step="any" value={v.lat} onChange={set("lat")} />
          <Input label="Longitude" required type="number" step="any" value={v.lng} onChange={set("lng")} />
        </div>
        <div className="h-48 overflow-hidden rounded-xl border border-slate-200">
          <MapView center={center} zoom={v.lat ? 15 : 12}
            points={v.lat && v.lng ? [{ lat: Number(v.lat), lng: Number(v.lng), label: v.name || "Stop", kind: "destination" }] : []}
            onMapClick={(lat, lng) => setV((p) => ({ ...p, lat: lat.toFixed(6), lng: lng.toFixed(6) }))} />
        </div>
        <p className="text-xs text-slate-500">Tap the map to set the position.</p>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-between pt-2">
          {stop ? <Button type="button" variant="danger" onClick={del}>Delete</Button> : <span />}
          <Button type="submit">Save</Button>
        </div>
      </form>
    </Modal>
  );
}
