"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bell, History, LogOut, Shield } from "lucide-react";
import AuthForm from "@/components/AuthForm";
import { Button, Card, Empty, ErrorBox, Input, PageHeader, SectionTitle, Spinner } from "@/components/ui";
import { RouteChip } from "@/components/widgets";
import { api } from "@/lib/api";
import { ago, useApi, useAuth, useMeta } from "@/lib/hooks";
import type { NotificationPrefs, RouteSummary, Stop } from "@/lib/types";

interface Note { id: number; kind: string; title: string; body: string; created_at: string; read_at: string | null }
interface JourneyRow { id: number; created_at: string; route: RouteSummary | null; from_stop: Stop | null; to_stop: Stop | null }

const PREF_LABELS: [keyof NotificationPrefs, string][] = [
  ["bus_approaching", "My bus is approaching"],
  ["delays", "Delays on my favorite routes"],
  ["disruptions", "Service disruptions"],
  ["schedule_changes", "Timetable changes"],
];

export default function ProfilePage() {
  const { user, ready, logout, refresh } = useAuth();
  const meta = useMeta();
  if (!ready) return <Spinner />;
  if (!user)
    return (
      <div className="mx-auto max-w-md px-4 py-10">
        <Card className="p-6">
          <h1 className="mb-1 text-xl font-bold text-brand-900">Welcome to Speedo Live</h1>
          <p className="mb-4 text-sm text-slate-500">Route search and live tracking work without an account. Sign in to save favorites and get bus alerts.</p>
          <AuthForm
            hint={meta?.demo_mode ? <p className="text-xs text-slate-500">Demo passenger: passenger@speedolive.demo / Passenger@123</p> : null}
          />
        </Card>
      </div>
    );
  return <Profile key={user.id} onLogout={logout} onSaved={refresh} />;
}

function Profile({ onLogout, onSaved }: { onLogout: () => Promise<void>; onSaved: () => Promise<void> }) {
  const { user } = useAuth();
  const [name, setName] = useState(user?.full_name || "");
  const [phone, setPhone] = useState(user?.phone || "");
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(user?.notification_prefs || null);
  const [pw, setPw] = useState({ current: "", next: "" });
  const notes = useApi<Note[]>("/api/me/notifications");
  const journeys = useApi<JourneyRow[]>("/api/me/journeys");

  useEffect(() => {
    const t = setInterval(notes.reload, 20000);
    return () => clearInterval(t);
  }, [notes.reload]);

  const saveProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await api("/api/auth/me", { method: "PATCH", json: { full_name: name, phone: phone || undefined } });
      await onSaved();
      setMsg("Profile saved");
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const savePrefs = async (p: NotificationPrefs) => {
    setPrefs(p);
    try {
      await api("/api/me/notification-preferences", { method: "PUT", json: p });
      await onSaved();
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const changePw = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    try {
      await api("/api/auth/me/password", { method: "POST", json: { current_password: pw.current, new_password: pw.next } });
      setPw({ current: "", next: "" });
      setMsg("Password changed");
    } catch (x) {
      setErr((x as Error).message);
    }
  };
  const markRead = async () => {
    await api("/api/me/notifications/read", { method: "POST" });
    notes.reload();
  };
  const clearHistory = async () => {
    await api("/api/me/journeys", { method: "DELETE" });
    journeys.reload();
  };

  return (
    <div className="mx-auto max-w-6xl px-4 py-6">
      <PageHeader
        title={`Hi, ${user?.full_name.split(" ")[0]}`}
        subtitle={user?.email || user?.phone || undefined}
        action={
          <div className="flex gap-2">
            {user?.role === "admin" && <Link href="/admin/" className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm"><Shield className="h-4 w-4" /> Admin dashboard</Link>}
            <Button variant="outline" onClick={onLogout}><LogOut className="h-4 w-4" /> Log out</Button>
          </div>
        }
      />
      {msg && <div className="mb-4 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-800">{msg}</div>}
      {err && <div className="mb-4"><ErrorBox error={err} /></div>}
      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5">
          <Card className="p-5">
            <SectionTitle>Profile</SectionTitle>
            <form onSubmit={saveProfile} className="space-y-3">
              <Input label="Full name" value={name} onChange={(e) => setName(e.target.value)} required minLength={2} />
              <Input label="Mobile number" value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="+92 3xx xxxxxxx" />
              <Button type="submit" size="sm">Save profile</Button>
            </form>
          </Card>
          <Card className="p-5">
            <SectionTitle>Change password</SectionTitle>
            <form onSubmit={changePw} className="space-y-3">
              <Input label="Current password" type="password" value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} required />
              <Input label="New password" type="password" minLength={8} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} required />
              <Button type="submit" size="sm" variant="outline">Update password</Button>
            </form>
          </Card>
        </div>
        <Card className="p-5">
          <SectionTitle>Notification preferences</SectionTitle>
          {prefs && (
            <div className="space-y-3">
              {PREF_LABELS.map(([k, label]) => (
                <label key={k} className="flex items-center justify-between gap-3 text-sm">
                  <span>{label}</span>
                  <input type="checkbox" className="h-5 w-5 accent-brand-700" checked={!!prefs[k]} onChange={(e) => savePrefs({ ...prefs, [k]: e.target.checked })} />
                </label>
              ))}
              <label className="flex items-center justify-between gap-3 text-sm">
                <span>Alert me this many minutes before arrival</span>
                <select className="rounded-lg border border-slate-200 px-2 py-1" value={prefs.arrival_minutes_before} onChange={(e) => savePrefs({ ...prefs, arrival_minutes_before: Number(e.target.value) })}>
                  {[2, 3, 5, 10, 15].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
              </label>
              <p className="text-xs text-slate-500">Push notifications go to the Android app. On the web, alerts appear in your inbox here.</p>
            </div>
          )}
          <div className="mt-6">
            <SectionTitle action={<button className="text-sm text-brand-600" onClick={markRead}>Mark all read</button>}>
              <span className="flex items-center gap-2"><Bell className="h-4 w-4" /> Inbox</span>
            </SectionTitle>
            {notes.loading && <Spinner />}
            {notes.data?.length === 0 && <Empty>No notifications yet.</Empty>}
            <ul className="space-y-2 max-h-80 overflow-y-auto scrollbar-thin">
              {notes.data?.map((n) => (
                <li key={n.id} className={`rounded-xl border p-3 text-sm ${n.read_at ? "border-slate-100" : "border-brand-200 bg-brand-50/50"}`}>
                  <div className="font-medium text-slate-800">{n.title}</div>
                  <div className="text-slate-600">{n.body}</div>
                  <div className="mt-1 text-[11px] text-slate-400">{ago(n.created_at)}</div>
                </li>
              ))}
            </ul>
          </div>
        </Card>
        <Card className="p-5">
          <SectionTitle action={journeys.data?.length ? <button className="text-sm text-slate-500" onClick={clearHistory}>Clear</button> : null}>
            <span className="flex items-center gap-2"><History className="h-4 w-4" /> Journey history</span>
          </SectionTitle>
          {journeys.loading && <Spinner />}
          {journeys.data?.length === 0 && <Empty>Journeys you track appear here.</Empty>}
          <ul className="space-y-2">
            {journeys.data?.map((j) => (
              <li key={j.id} className="rounded-xl border border-slate-100 p-3 text-sm">
                <div className="flex items-center gap-2">
                  {j.route && <RouteChip code={j.route.code} color={j.route.color} />}
                  <span className="text-xs text-slate-400">{ago(j.created_at)}</span>
                </div>
                <div className="mt-1 text-slate-700">{j.from_stop?.name || "?"} → {j.to_stop?.name || "?"}</div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
