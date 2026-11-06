"use client";

import Link from "next/link";
import { Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AlertTriangle, BarChart3, Bus, CalendarClock, LayoutDashboard, LogOut, MapPin, Radar, Route, Settings, Users } from "lucide-react";
import AuthForm from "@/components/AuthForm";
import { Logo } from "@/components/Shell";
import { Card, DemoBanner, Spinner } from "@/components/ui";
import clsx from "@/components/clsx";
import { useAuth, useMeta } from "@/lib/hooks";
import { Overview } from "@/components/admin/Overview";
import { BusesAdmin } from "@/components/admin/Buses";
import { RoutesAdmin } from "@/components/admin/Routes";
import { StopsAdmin } from "@/components/admin/Stops";
import { DriversAdmin } from "@/components/admin/Drivers";
import { FleetAdmin } from "@/components/admin/Fleet";
import { SchedulesAdmin } from "@/components/admin/Schedules";
import { AlertsAdmin } from "@/components/admin/Alerts";
import { ReportsAdmin } from "@/components/admin/Reports";
import { SettingsAdmin } from "@/components/admin/Settings";

const TABS = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, C: Overview },
  { id: "buses", label: "Buses", icon: Bus, C: BusesAdmin },
  { id: "routes", label: "Routes", icon: Route, C: RoutesAdmin },
  { id: "stops", label: "Stops", icon: MapPin, C: StopsAdmin },
  { id: "drivers", label: "Drivers", icon: Users, C: DriversAdmin },
  { id: "fleet", label: "Live Fleet", icon: Radar, C: FleetAdmin },
  { id: "schedules", label: "Schedules", icon: CalendarClock, C: SchedulesAdmin },
  { id: "alerts", label: "Service Alerts", icon: AlertTriangle, C: AlertsAdmin },
  { id: "reports", label: "Reports", icon: BarChart3, C: ReportsAdmin },
  { id: "settings", label: "Settings", icon: Settings, C: SettingsAdmin },
];

function AdminInner() {
  const { user, ready, logout } = useAuth();
  const meta = useMeta();
  const params = useSearchParams();
  const router = useRouter();
  const tab = TABS.find((t) => t.id === params.get("tab")) || TABS[0];

  if (!ready) return <Spinner />;
  if (!user || user.role !== "admin")
    return (
      <div className="min-h-screen bg-surface">
        <DemoBanner />
        <div className="mx-auto max-w-md px-4 py-16">
          <Logo className="mb-6 justify-center" />
          <Card className="p-6">
            <h1 className="mb-1 text-xl font-bold text-brand-900">Admin sign in</h1>
            <p className="mb-4 text-sm text-slate-500">Only authorised Speedo Live administrators can access this dashboard.</p>
            {user && user.role !== "admin" && (
              <p className="mb-3 rounded-lg bg-red-50 p-2 text-sm text-red-700">You are signed in as a {user.role}. Sign in with an admin account.</p>
            )}
            <AuthForm allowRegister={false} hint={meta?.demo_mode ? <p className="text-xs text-slate-500">Demo admin: admin@speedolive.demo / Admin@12345</p> : null} />
          </Card>
          <p className="mt-4 text-center text-sm"><Link href="/" className="text-brand-600">← Back to passenger app</Link></p>
        </div>
      </div>
    );

  const C = tab.C;
  return (
    <div className="min-h-screen bg-surface">
      <DemoBanner />
      <div className="flex">
        <aside className="hidden lg:flex w-60 shrink-0 flex-col border-r border-slate-200 bg-white min-h-screen sticky top-0">
          <div className="p-4 border-b border-slate-100"><Logo /><div className="mt-1 text-xs font-semibold text-accent-600 ml-11">Admin</div></div>
          <nav className="flex-1 p-3 space-y-0.5" aria-label="Admin">
            {TABS.map((t) => (
              <button key={t.id} onClick={() => router.push(`/admin/?tab=${t.id}`)}
                className={clsx("flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium", t.id === tab.id ? "bg-brand-700 text-white" : "text-slate-600 hover:bg-slate-50")}>
                <t.icon className="h-4 w-4" /> {t.label}
              </button>
            ))}
          </nav>
          <div className="border-t border-slate-100 p-3 text-sm">
            <div className="px-2 text-slate-700 font-medium">{user.full_name}</div>
            <div className="px-2 text-xs text-slate-400 mb-2">{user.email}</div>
            <button onClick={logout} className="flex w-full items-center gap-2 rounded-xl px-3 py-2 text-slate-600 hover:bg-slate-50"><LogOut className="h-4 w-4" /> Log out</button>
          </div>
        </aside>
        <div className="flex-1 min-w-0">
          <div className="lg:hidden sticky top-0 z-[1100] border-b border-slate-200 bg-white px-4 py-2 flex items-center gap-3">
            <Logo />
            <select className="ml-auto rounded-lg border border-slate-200 px-2 py-1.5 text-sm" value={tab.id} onChange={(e) => router.push(`/admin/?tab=${e.target.value}`)} aria-label="Section">
              {TABS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </div>
          <main className="p-4 lg:p-8 max-w-7xl"><C /></main>
        </div>
      </div>
    </div>
  );
}

export default function AdminPage() {
  return <Suspense fallback={<Spinner />}><AdminInner /></Suspense>;
}
