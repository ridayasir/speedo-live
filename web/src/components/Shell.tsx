"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Bus, Clock, Heart, Home, Map, Route as RouteIcon, User } from "lucide-react";
import { DemoBanner } from "./ui";
import clsx from "./clsx";
import { useAuth } from "@/lib/hooks";

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/live/", label: "Live Tracking", short: "Live Map", icon: Map },
  { href: "/routes/", label: "Routes", short: "Explore", icon: RouteIcon },
  { href: "/timetable/", label: "Timetable", icon: Clock, desktopOnly: true },
  { href: "/favorites/", label: "Favorites", icon: Heart },
  { href: "/profile/", label: "Profile", icon: User },
];

export function Logo({ className }: { className?: string }) {
  return (
    <Link href="/" className={clsx("flex items-center gap-2", className)} aria-label="Speedo Live home">
      <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-700 text-white shadow-card">
        <Bus className="h-5 w-5" />
      </span>
      <span className="leading-tight">
        <span className="block text-lg font-extrabold tracking-tight text-brand-800">
          Speedo<span className="text-accent-500">Live</span>
        </span>
        <span className="hidden sm:block text-[10px] font-medium text-slate-500 -mt-0.5">Your Bus, Your Route, Your Time.</span>
      </span>
    </Link>
  );
}

function isActive(path: string, href: string) {
  if (href === "/") return path === "/";
  return path.startsWith(href.replace(/\/$/, ""));
}

export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname() || "/";
  const { user } = useAuth();
  if (path.startsWith("/admin")) return <>{children}</>;
  return (
    <div className="min-h-screen flex flex-col">
      <DemoBanner />
      <header className="sticky top-0 z-[1100] border-b border-slate-200 bg-white/95 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between px-4">
          <Logo />
          <nav className="hidden md:flex items-center gap-1" aria-label="Main">
            {NAV.map((n) => (
              <Link
                key={n.href}
                href={n.href}
                className={clsx(
                  "rounded-xl px-3 py-2 text-sm font-medium transition",
                  isActive(path, n.href) ? "bg-brand-50 text-brand-700" : "text-slate-600 hover:bg-slate-50",
                )}
              >
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            {user?.role === "admin" && (
              <Link href="/admin/" className="hidden sm:inline rounded-xl border border-slate-200 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
                Admin
              </Link>
            )}
            <Link href="/timetable/" className="md:hidden rounded-xl p-2 text-slate-600 hover:bg-slate-50" aria-label="Timetable">
              <Clock className="h-5 w-5" />
            </Link>
          </div>
        </div>
      </header>
      <main className="flex-1 pb-20 md:pb-0">{children}</main>
      <nav className="md:hidden fixed bottom-0 inset-x-0 z-[1100] border-t border-slate-200 bg-white" aria-label="Main mobile">
        <div className="grid grid-cols-5">
          {NAV.filter((n) => !n.desktopOnly).map((n) => {
            const Icon = n.icon;
            const active = isActive(path, n.href);
            return (
              <Link key={n.href} href={n.href} className={clsx("flex flex-col items-center gap-0.5 py-2 text-[11px]", active ? "text-brand-700" : "text-slate-500")}>
                <Icon className={clsx("h-5 w-5", active && "text-accent-500")} />
                {n.short || n.label}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
