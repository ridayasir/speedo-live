"use client";

import { AlertTriangle, Loader2, Info, WifiOff } from "lucide-react";
import type { BusState } from "@/lib/types";
import { useMeta } from "@/lib/hooks";
import clsx from "./clsx";

export function Card({ className, children, ...rest }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx("rounded-xl2 bg-white shadow-card border border-slate-100", className)} {...rest}>
      {children}
    </div>
  );
}

export function SectionTitle({ children, action }: { children: React.ReactNode; action?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <h2 className="text-base font-semibold text-slate-800">{children}</h2>
      {action}
    </div>
  );
}

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "accent" | "ghost" | "outline" | "danger";
  size?: "sm" | "md";
  loading?: boolean;
};

export function Button({ variant = "primary", size = "md", loading, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      className={clsx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 disabled:opacity-50 disabled:cursor-not-allowed",
        size === "sm" ? "px-3 py-1.5 text-sm" : "px-4 py-2.5 text-sm",
        variant === "primary" && "bg-brand-700 text-white hover:bg-brand-800",
        variant === "accent" && "bg-accent-500 text-white hover:bg-accent-600",
        variant === "ghost" && "text-brand-700 hover:bg-brand-50",
        variant === "outline" && "border border-slate-200 bg-white text-slate-700 hover:bg-slate-50",
        variant === "danger" && "bg-red-600 text-white hover:bg-red-700",
        className,
      )}
      disabled={disabled || loading}
      {...rest}
    >
      {loading && <Loader2 className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
}

export function Input({ label, className, ...rest }: React.InputHTMLAttributes<HTMLInputElement> & { label?: string }) {
  const input = (
    <input
      className={clsx(
        "w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-100",
        className,
      )}
      {...rest}
    />
  );
  if (!label) return input;
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600">{label}</span>
      {input}
    </label>
  );
}

export function Select({ label, className, children, ...rest }: React.SelectHTMLAttributes<HTMLSelectElement> & { label?: string }) {
  const el = (
    <select
      className={clsx("w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-brand-500", className)}
      {...rest}
    >
      {children}
    </select>
  );
  if (!label) return el;
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-600">{label}</span>
      {el}
    </label>
  );
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-6 justify-center text-slate-500 text-sm" role="status">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="py-6 text-center text-sm text-slate-500">{children}</div>;
}

export function ErrorBox({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex items-start gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-700" role="alert">
      <AlertTriangle className="h-4 w-4 mt-0.5 shrink-0" />
      <div className="flex-1 whitespace-pre-line">{error}</div>
      {onRetry && (
        <button className="font-medium underline" onClick={onRetry}>
          Retry
        </button>
      )}
    </div>
  );
}

export function DemoBadge({ className }: { className?: string }) {
  return (
    <span className={clsx("inline-flex items-center rounded-md bg-accent-500 px-1.5 py-0.5 text-[10px] font-bold tracking-wider text-white", className)}>
      DEMO
    </span>
  );
}

export function DemoBanner() {
  const meta = useMeta();
  if (!meta?.demo_mode) return null;
  return (
    <div className="bg-accent-500 text-white text-xs sm:text-sm">
      <div className="mx-auto max-w-7xl px-4 py-1.5 flex items-center gap-2">
        <Info className="h-4 w-4 shrink-0" />
        <span>
          <b>DEMO MODE.</b> Buses, routes and times are simulated sample data, not real Speedo services.
        </span>
      </div>
    </div>
  );
}

/** Status as the passenger should see it now, re-checking GPS age on the client. */
export function effectiveStatus(b: BusState, staleAfter = 60, offlineAfter = 300): BusState["status"] {
  if (b.status === "out_of_service") return b.status;
  if (!b.last_gps_at) return b.trip_id ? "offline" : b.status;
  const age = (Date.now() - new Date(b.last_gps_at).getTime()) / 1000;
  if (age > offlineAfter) return "offline";
  if (age > staleAfter) return "stale";
  return b.status;
}

const STATUS_STYLE: Record<string, [string, string]> = {
  active: ["bg-emerald-50 text-emerald-700 border-emerald-200", "On route"],
  delayed: ["bg-amber-50 text-amber-700 border-amber-200", "Delayed"],
  stale: ["bg-slate-100 text-slate-600 border-slate-200", "GPS signal lost"],
  offline: ["bg-slate-100 text-slate-500 border-slate-200", "Offline"],
  idle: ["bg-sky-50 text-sky-700 border-sky-200", "Not on a trip"],
  out_of_service: ["bg-red-50 text-red-700 border-red-200", "Out of service"],
};

export function StatusPill({ status }: { status: string }) {
  const [cls, label] = STATUS_STYLE[status] || ["bg-slate-100 text-slate-600 border-slate-200", status];
  return (
    <span className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium", cls)}>
      {status === "stale" || status === "offline" ? <WifiOff className="h-3 w-3" /> : <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {label}
    </span>
  );
}

export function PageHeader({ title, subtitle, action }: { title: string; subtitle?: string; action?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-bold text-brand-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-slate-500">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}

export function Modal({ open, onClose, title, children }: { open: boolean; onClose: () => void; title: string; children: React.ReactNode }) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-[2000] flex items-end sm:items-center justify-center bg-slate-900/40 p-0 sm:p-4" onClick={onClose}>
      <div
        className="w-full sm:max-w-lg max-h-[90vh] overflow-y-auto rounded-t-2xl sm:rounded-2xl bg-white p-5 shadow-xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label={title}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-lg font-semibold text-brand-900">{title}</h3>
          <button onClick={onClose} className="rounded-lg px-2 py-1 text-slate-500 hover:bg-slate-100" aria-label="Close">
            ✕
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
