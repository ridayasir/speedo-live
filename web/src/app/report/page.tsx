"use client";

import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, Copy, Flag, Search, ShieldCheck } from "lucide-react";
import { Button, Card, ErrorBox, Input, Select, Spinner } from "@/components/ui";
import { RouteChip } from "@/components/widgets";
import { api } from "@/lib/api";
import { ago, useApi, useAuth } from "@/lib/hooks";
import type { Complaint, ComplaintCategory } from "@/lib/types";

const STATUS_STYLE: Record<string, string> = {
  new: "bg-sky-50 text-sky-700 border-sky-200",
  in_review: "bg-amber-50 text-amber-700 border-amber-200",
  resolved: "bg-emerald-50 text-emerald-700 border-emerald-200",
  rejected: "bg-slate-100 text-slate-600 border-slate-200",
};

function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

function ComplaintCard({ c }: { c: Complaint }) {
  return (
    <div className="rounded-xl border border-slate-100 bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-sm font-bold text-brand-800">{c.ref_code}</span>
        <span className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${STATUS_STYLE[c.status]}`}>{c.status_label}</span>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        <span className="font-semibold text-slate-800">Bus {c.bus_number}</span>
        {c.route_code && <RouteChip code={c.route_code} color={c.route_color || "#b91c1c"} className="max-w-[14rem]" />}
      </div>
      <p className="mt-1 text-sm font-medium text-slate-700">{c.category_label}</p>
      <p className="mt-1 whitespace-pre-line text-sm text-slate-600">{c.description}</p>
      <p className="mt-2 text-xs text-slate-400">
        {c.location ? `${c.location} · ` : ""}reported {ago(c.created_at)}
      </p>
      {c.reply && (
        <div className="mt-3 rounded-lg bg-brand-50 p-3 text-sm text-brand-900">
          <span className="block text-xs font-semibold uppercase tracking-wide text-brand-700">Reply from Speedo</span>
          {c.reply}
        </div>
      )}
    </div>
  );
}

function ReportInner() {
  const params = useSearchParams();
  const { user } = useAuth();
  const cats = useApi<ComplaintCategory[]>("/api/complaints/categories");
  const mine = useApi<Complaint[]>(user ? "/api/me/complaints" : null, [user?.id]);
  const [form, setForm] = useState({
    bus_number: params.get("bus") || "", category: "", description: "", location: "", incident_at: nowLocal(),
    contact_name: "", contact_phone: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Complaint | null>(null);
  const [copied, setCopied] = useState(false);
  const [ref, setRef] = useState("");
  const [lookup, setLookup] = useState<{ c?: Complaint; error?: string; busy?: boolean }>({});
  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = {
        bus_number: form.bus_number.trim(), category: form.category, description: form.description.trim(),
        location: form.location.trim() || undefined,
        incident_at: form.incident_at ? new Date(form.incident_at).toISOString() : undefined,
        contact_name: form.contact_name.trim() || undefined,
        contact_phone: form.contact_phone.replace(/[\s-]/g, "") || undefined,
      };
      setDone(await api<Complaint>("/api/complaints", { method: "POST", json: body }));
      mine.reload();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const check = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ref.trim()) return;
    setLookup({ busy: true });
    try {
      setLookup({ c: await api<Complaint>(`/api/complaints/${encodeURIComponent(ref.trim())}`) });
    } catch (err) {
      setLookup({ error: (err as Error).message });
    }
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <div className="mb-5 flex items-start gap-3">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"><Flag className="h-5 w-5" /></span>
        <div>
          <h1 className="text-2xl font-bold text-brand-900">Report a driver</h1>
          <p className="text-sm text-slate-500">
            Rash driving, rude behaviour, a skipped stop? Tell us the bus number. Speedo reviews every report.
          </p>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <Card className="p-5 lg:col-span-3">
          {done ? (
            <div className="text-center py-4">
              <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-600" />
              <h2 className="mt-2 text-lg font-bold text-slate-800">Thank you, your report was received</h2>
              <p className="mt-1 text-sm text-slate-500">Keep this reference code to check what happens with it:</p>
              <div className="mt-3 inline-flex items-center gap-2 rounded-xl border border-brand-200 bg-brand-50 px-4 py-2">
                <span className="font-mono text-xl font-bold tracking-wider text-brand-800">{done.ref_code}</span>
                <button type="button" className="rounded-lg p-1 text-brand-700 hover:bg-white" aria-label="Copy reference code"
                  onClick={() => { navigator.clipboard?.writeText(done.ref_code); setCopied(true); }}>
                  <Copy className="h-4 w-4" />
                </button>
              </div>
              {copied && <p className="mt-1 text-xs text-emerald-700">Copied</p>}
              {!user && <p className="mt-3 text-xs text-slate-500">Sign in next time to see all your reports and get a notification when one is answered.</p>}
              <div className="mt-5">
                <Button variant="ghost" onClick={() => { setDone(null); setCopied(false); setForm((f) => ({ ...f, category: "", description: "", location: "", incident_at: nowLocal() })); }}>
                  Report something else
                </Button>
              </div>
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-3">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="Bus number" required value={form.bus_number} onChange={set("bus_number")} placeholder="e.g. SP-101 (painted on the bus)" />
                <Select label="What happened?" required value={form.category} onChange={set("category")}>
                  <option value="">Choose…</option>
                  {(cats.data || []).map((c) => <option key={c.id} value={c.id}>{c.label}</option>)}
                </Select>
              </div>
              <label className="block text-sm">
                <span className="mb-1 block font-medium text-slate-600">Describe what happened</span>
                <textarea required minLength={10} maxLength={2000} rows={5} value={form.description} onChange={set("description")}
                  placeholder="What did the driver do? (at least 10 characters)"
                  className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100" />
                <span className="mt-0.5 block text-right text-[11px] text-slate-400">{form.description.length}/2000</span>
              </label>
              <div className="grid gap-3 sm:grid-cols-2">
                <Input label="Where? (optional)" maxLength={160} value={form.location} onChange={set("location")} placeholder="Stop or road" />
                <Input label="When?" type="datetime-local" value={form.incident_at} max={nowLocal()} onChange={set("incident_at")} />
              </div>
              {!user && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Input label="Your name (optional)" maxLength={120} value={form.contact_name} onChange={set("contact_name")} />
                  <Input label="Your phone (optional)" value={form.contact_phone} onChange={set("contact_phone")} placeholder="03xx xxxxxxx" />
                </div>
              )}
              <p className="flex items-start gap-2 rounded-xl bg-surface p-3 text-xs text-slate-500">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
                Your report goes only to Speedo administrators. Contact details are optional and used only to follow up.
              </p>
              {error && <ErrorBox error={error} />}
              <Button type="submit" className="w-full" loading={busy}>Send report</Button>
            </form>
          )}
        </Card>

        <div className="space-y-6 lg:col-span-2">
          <Card className="p-5">
            <h2 className="mb-3 font-semibold text-slate-800">Check a report</h2>
            <form onSubmit={check} className="flex gap-2">
              <Input value={ref} onChange={(e) => setRef(e.target.value)} placeholder="Reference code, e.g. SPC-7KX4QM" aria-label="Reference code" />
              <Button type="submit" loading={lookup.busy} aria-label="Check"><Search className="h-4 w-4" /></Button>
            </form>
            <div className="mt-3">
              {lookup.error && <ErrorBox error={lookup.error} />}
              {lookup.c && <ComplaintCard c={lookup.c} />}
            </div>
          </Card>

          {user && (
            <Card className="p-5">
              <h2 className="mb-3 font-semibold text-slate-800">My reports</h2>
              {mine.loading && !mine.data && <Spinner />}
              {mine.data && mine.data.length === 0 && <p className="text-sm text-slate-500">You have not reported anything yet.</p>}
              <div className="space-y-3">{(mine.data || []).map((c) => <ComplaintCard key={c.ref_code} c={c} />)}</div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ReportPage() {
  return <Suspense fallback={<Spinner />}><ReportInner /></Suspense>;
}
