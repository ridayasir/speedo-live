"use client";

import { useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Download, Plus, Trash2, Upload } from "lucide-react";
import MapView from "../MapView";
import { Button, Card, DemoBadge, ErrorBox, Input, Modal, PageHeader, SectionTitle, Select, Spinner } from "../ui";
import { RouteChip } from "../widgets";
import { DataTable, nullIfEmpty } from "./common";
import { api, download } from "@/lib/api";
import { km, useApi } from "@/lib/hooks";
import type { RouteDetail, RouteSummary, Stop } from "@/lib/types";

type AdminRoute = RouteSummary & { bus_count: number; schedule_count: number };

export function RoutesAdmin() {
  const routes = useApi<AdminRoute[]>("/api/admin/routes");
  const [edit, setEdit] = useState<number | "new" | null>(null);
  const [importing, setImporting] = useState(false);
  if (routes.loading && !routes.data) return <Spinner />;
  return (
    <div>
      <PageHeader
        title="Routes"
        subtitle="Create routes, order their stops and set the line on the map."
        action={
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => setImporting(true)}><Upload className="h-4 w-4" /> Import CSV / Excel</Button>
            <Button onClick={() => setEdit("new")}><Plus className="h-4 w-4" /> New route</Button>
          </div>
        }
      />
      {routes.error && <ErrorBox error={routes.error} onRetry={routes.reload} />}
      <DataTable
        rows={routes.data || []}
        rowKey={(r) => r.id}
        cols={[
          { h: "Code", c: (r) => <RouteChip code={r.code} color={r.color} /> },
          { h: "Name", c: (r) => <span className="font-medium">{r.name} {r.is_demo && <DemoBadge />}</span> },
          { h: "From → To", c: (r) => <span className="text-xs text-slate-500">{r.start_stop?.name} → {r.end_stop?.name}</span> },
          { h: "Stops", c: (r) => r.stop_count },
          { h: "Length", c: (r) => km(r.length_m) },
          { h: "Buses", c: (r) => r.bus_count },
          { h: "Schedules", c: (r) => r.schedule_count },
          { h: "Status", c: (r) => <span className="capitalize">{r.status}</span> },
          { h: "Source", c: (r) => <span className="text-xs text-slate-400">{r.source_reference || "–"}</span> },
          { h: "", c: (r) => <Button size="sm" variant="ghost" onClick={() => setEdit(r.id)}>Edit</Button>, className: "text-right" },
        ]}
      />
      {edit !== null && <RouteEditor routeId={edit === "new" ? null : edit} onClose={() => setEdit(null)} onSaved={() => { setEdit(null); routes.reload(); }} />}
      {importing && <ImportModal onClose={() => setImporting(false)} onDone={() => { setImporting(false); routes.reload(); }} />}
    </div>
  );
}

interface EditStop { stop_id: number; offset_minutes: number; is_major: boolean }

function RouteEditor({ routeId, onClose, onSaved }: { routeId: number | null; onClose: () => void; onSaved: () => void }) {
  const detail = useApi<RouteDetail>(routeId ? `/api/admin/routes/${routeId}` : null);
  const allStops = useApi<Stop[]>("/api/admin/stops");
  const [f, setF] = useState({ code: "", name: "", color: "#1d4ed8", status: "active", fare_pkr: "", source_reference: "" });
  const [stops, setStops] = useState<EditStop[]>([]);
  const [pathText, setPathText] = useState("");
  const [add, setAdd] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const r = detail.data;
    if (!r) return;
    setF({ code: r.code, name: r.name, color: r.color, status: r.status, fare_pkr: r.fare_pkr ? String(r.fare_pkr) : "", source_reference: r.source_reference || "" });
    setStops(r.stops.map((s) => ({ stop_id: s.id, offset_minutes: s.offset_minutes, is_major: s.is_major })));
    const stopPath = r.stops.map((s) => `${s.lat},${s.lng}`).join("|");
    const pth = r.path.map((p) => `${p[0]},${p[1]}`).join("|");
    setPathText(pth === stopPath ? "" : r.path.map((p) => `${p[0]}, ${p[1]}`).join("\n"));
  }, [detail.data]);

  const byId = Object.fromEntries((allStops.data || []).map((s) => [s.id, s]));
  const move = (i: number, d: number) => setStops((p) => {
    const n = [...p];
    const j = i + d;
    if (j < 0 || j >= n.length) return p;
    [n[i], n[j]] = [n[j], n[i]];
    return n;
  });
  const parsePath = (): [number, number][] | null => {
    if (!pathText.trim()) return null;
    const pts = pathText.split(/\n|;/).map((l) => l.split(",").map((x) => Number(x.trim()))).filter((p) => p.length === 2 && p.every((x) => !isNaN(x)));
    return pts as [number, number][];
  };
  const save = async () => {
    setBusy(true);
    setErr(null);
    const body = {
      code: f.code.trim(), name: f.name.trim(), color: f.color, status: f.status,
      fare_pkr: f.fare_pkr ? Number(f.fare_pkr) : null, source_reference: nullIfEmpty(f.source_reference),
      stops, path: parsePath(),
    };
    try {
      if (routeId) await api(`/api/admin/routes/${routeId}`, { method: "PATCH", json: body });
      else await api("/api/admin/routes", { method: "POST", json: body });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  const del = async () => {
    if (!routeId || !confirm("Delete this route, its stop list and schedules? Stops themselves are kept.")) return;
    try {
      await api(`/api/admin/routes/${routeId}`, { method: "DELETE" });
      onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const previewPath = parsePath() || stops.map((s) => byId[s.stop_id]).filter(Boolean).map((s) => [s.lat, s.lng] as [number, number]);
  const previewStops = stops.map((s) => byId[s.stop_id]).filter(Boolean);

  if (routeId && detail.loading) return <Modal open onClose={onClose} title="Loading route"><Spinner /></Modal>;
  return (
    <Modal open onClose={onClose} title={routeId ? `Edit ${f.code}` : "New route"}>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-3">
          <Input label="Route code" value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} required />
          <Select label="Status" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value })}>
            <option value="active">Active</option><option value="suspended">Suspended</option><option value="inactive">Inactive</option>
          </Select>
        </div>
        <Input label="Route name" value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} required />
        <div className="grid grid-cols-3 gap-3">
          <label className="block text-sm"><span className="mb-1 block font-medium text-slate-600">Colour</span>
            <input type="color" value={f.color} onChange={(e) => setF({ ...f, color: e.target.value })} className="h-10 w-full rounded-xl border border-slate-200" /></label>
          <Input label="Fare (Rs)" type="number" min={0} value={f.fare_pkr} onChange={(e) => setF({ ...f, fare_pkr: e.target.value })} />
          <Input label="Source" value={f.source_reference} onChange={(e) => setF({ ...f, source_reference: e.target.value })} placeholder="PMA/PTC ref" />
        </div>

        <SectionTitle>Stops in order (first = start, last = end)</SectionTitle>
        <ol className="space-y-1.5">
          {stops.map((s, i) => (
            <li key={s.stop_id} className="flex items-center gap-2 rounded-xl border border-slate-100 p-2 text-sm">
              <span className="w-5 text-center text-xs text-slate-400">{i + 1}</span>
              <span className="flex-1 truncate">{byId[s.stop_id]?.name || `Stop ${s.stop_id}`}</span>
              <label className="flex items-center gap-1 text-xs text-slate-500">+
                <input type="number" min={0} step="0.5" className="w-16 rounded-lg border border-slate-200 px-1.5 py-1" value={s.offset_minutes}
                  onChange={(e) => setStops((p) => p.map((x, k) => (k === i ? { ...x, offset_minutes: Number(e.target.value) } : x)))} aria-label="Minutes from start" /> min
              </label>
              <label className="flex items-center gap-1 text-xs text-slate-500" title="Major stop (shown in timetables)">
                <input type="checkbox" checked={s.is_major} onChange={(e) => setStops((p) => p.map((x, k) => (k === i ? { ...x, is_major: e.target.checked } : x)))} /> major
              </label>
              <button onClick={() => move(i, -1)} className="p-1 text-slate-400 hover:text-slate-700" aria-label="Move up"><ArrowUp className="h-4 w-4" /></button>
              <button onClick={() => move(i, 1)} className="p-1 text-slate-400 hover:text-slate-700" aria-label="Move down"><ArrowDown className="h-4 w-4" /></button>
              <button onClick={() => setStops((p) => p.filter((_, k) => k !== i))} className="p-1 text-slate-400 hover:text-red-600" aria-label="Remove"><Trash2 className="h-4 w-4" /></button>
            </li>
          ))}
        </ol>
        <div className="flex gap-2">
          <Select value={add} onChange={(e) => setAdd(e.target.value)} aria-label="Add stop">
            <option value="">Add a stop…</option>
            {(allStops.data || []).filter((s) => !stops.some((x) => x.stop_id === s.id)).map((s) => <option key={s.id} value={s.id}>{s.name} ({s.code})</option>)}
          </Select>
          <Button type="button" variant="outline" disabled={!add} onClick={() => {
            const last = stops[stops.length - 1];
            setStops([...stops, { stop_id: Number(add), offset_minutes: last ? last.offset_minutes + 3 : 0, is_major: false }]);
            setAdd("");
          }}>Add</Button>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium text-slate-600">Road geometry (optional, one “lat, lng” per line; blank = straight lines between stops)</span>
          <textarea rows={3} className="w-full rounded-xl border border-slate-200 p-2 font-mono text-xs" value={pathText} onChange={(e) => setPathText(e.target.value)} />
        </label>
        <div className="h-52 overflow-hidden rounded-xl border border-slate-200">
          <MapView routes={previewPath.length > 1 ? [{ id: 0, color: f.color, path: previewPath }] : []} stops={previewStops} fitKey={`p${previewPath.length}-${stops.length}`} />
        </div>
        {err && <ErrorBox error={err} />}
        <div className="flex justify-between pt-2">
          {routeId ? <Button variant="danger" onClick={del}>Delete</Button> : <span />}
          <Button onClick={save} loading={busy} disabled={stops.length < 2}>Save route</Button>
        </div>
      </div>
    </Modal>
  );
}

function ImportModal({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const [routesFile, setRoutesFile] = useState<File | null>(null);
  const [schedFile, setSchedFile] = useState<File | null>(null);
  const [shapesFile, setShapesFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [res, setRes] = useState<Record<string, number> | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!routesFile) return;
    const fd = new FormData();
    fd.append("routes_file", routesFile);
    fd.append("source_reference", source);
    if (schedFile) fd.append("schedules_file", schedFile);
    if (shapesFile) fd.append("shapes_file", shapesFile);
    setBusy(true);
    setErr(null);
    try {
      setRes(await api<Record<string, number>>("/api/admin/import/routes", { method: "POST", body: fd }));
    } catch (x) {
      setErr((x as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal open onClose={res ? onDone : onClose} title="Import verified route data">
      {res ? (
        <div className="space-y-3 text-sm">
          <p className="rounded-xl bg-emerald-50 p-3 text-emerald-800">
            Imported: {res.routes_created} new and {res.routes_updated} updated routes, {res.stops_created} new and {res.stops_updated} updated stops, {res.schedules} schedules.
          </p>
          <Button onClick={onDone}>Done</Button>
        </div>
      ) : (
        <form onSubmit={submit} className="space-y-3 text-sm">
          <p className="text-slate-600">
            Upload official route information (PMA, PTC or another authority). Each route in the file replaces that route&apos;s stop list. Only upload data you have verified.
          </p>
          <div className="flex flex-wrap gap-2">
            {["routes", "schedules", "shapes"].map((k) => (
              <button key={k} type="button" onClick={() => download(`/api/admin/import/templates/${k}`, `${k}_template.csv`)} className="inline-flex items-center gap-1 rounded-lg bg-slate-100 px-2 py-1 text-xs text-slate-700">
                <Download className="h-3 w-3" /> {k} template
              </button>
            ))}
          </div>
          <Input label="Data source (required)" required minLength={3} value={source} onChange={(e) => setSource(e.target.value)} placeholder="e.g. PMA Speedo route list, Nov 2026" />
          <label className="block"><span className="mb-1 block font-medium text-slate-600">Routes and stops file (CSV or XLSX)</span>
            <input type="file" accept=".csv,.xlsx" required onChange={(e) => setRoutesFile(e.target.files?.[0] || null)} /></label>
          <label className="block"><span className="mb-1 block font-medium text-slate-600">Schedules file (optional)</span>
            <input type="file" accept=".csv,.xlsx" onChange={(e) => setSchedFile(e.target.files?.[0] || null)} /></label>
          <label className="block"><span className="mb-1 block font-medium text-slate-600">Road geometry file (optional)</span>
            <input type="file" accept=".csv,.xlsx" onChange={(e) => setShapesFile(e.target.files?.[0] || null)} /></label>
          {err && <ErrorBox error={err} />}
          <div className="flex justify-end"><Button type="submit" loading={busy}>Import</Button></div>
        </form>
      )}
    </Modal>
  );
}

export function RoutePreviewCard({ r }: { r: RouteDetail }) {
  return <Card className="h-64 overflow-hidden"><MapView routes={[{ id: r.id, color: r.color, path: r.path }]} stops={r.stops} fitKey={`r${r.id}`} /></Card>;
}
