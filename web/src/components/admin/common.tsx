"use client";

import { useState } from "react";
import { Card, Empty } from "../ui";

export function DataTable<T>({ rows, cols, empty = "Nothing here yet.", rowKey }: {
  rows: T[];
  cols: { h: string; c: (r: T) => React.ReactNode; className?: string }[];
  empty?: string;
  rowKey: (r: T) => string | number;
}) {
  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
            <tr>{cols.map((c) => <th key={c.h} className={`px-4 py-2.5 font-semibold ${c.className || ""}`}>{c.h}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={rowKey(r)} className="border-t border-slate-100 hover:bg-slate-50/60">
                {cols.map((c) => <td key={c.h} className={`px-4 py-2.5 align-middle ${c.className || ""}`}>{c.c(r)}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length === 0 && <Empty>{empty}</Empty>}
    </Card>
  );
}

export function useForm<T extends Record<string, unknown>>(initial: T) {
  const [v, setV] = useState<T>(initial);
  const set = (k: keyof T) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setV((p) => ({ ...p, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value }));
  return { v, setV, set };
}

export function Stat({ label, value, tone = "brand" }: { label: string; value: React.ReactNode; tone?: "brand" | "green" | "amber" | "slate" | "red" }) {
  const tones = {
    brand: "text-brand-800",
    green: "text-emerald-700",
    amber: "text-amber-700",
    slate: "text-slate-600",
    red: "text-red-700",
  };
  return (
    <Card className="p-4">
      <div className="text-xs font-medium text-slate-500">{label}</div>
      <div className={`mt-1 text-3xl font-bold ${tones[tone]}`}>{value}</div>
    </Card>
  );
}

export function nullIfEmpty(v: unknown) {
  return v === "" || v === undefined ? null : v;
}
