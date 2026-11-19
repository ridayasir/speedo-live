"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Star } from "lucide-react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/hooks";
import type { RouteSummary, Stop } from "@/lib/types";

export default function FavoriteButton({ kind, id }: { kind: "routes" | "stops"; id: number }) {
  const { user } = useAuth();
  const [fav, setFav] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!user) return;
    api<{ routes: RouteSummary[]; stops: Stop[] }>("/api/me/favorites")
      .then((f) => setFav((kind === "routes" ? f.routes : f.stops).some((x) => x.id === id)))
      .catch(() => {});
  }, [user, kind, id]);
  if (!user)
    return (
      <Link href="/profile/" className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50">
        <Star className="h-4 w-4" /> Sign in to save
      </Link>
    );
  const toggle = async () => {
    setBusy(true);
    try {
      await api(`/api/me/favorites/${kind}/${id}`, { method: fav ? "DELETE" : "PUT" });
      setFav(!fav);
    } finally {
      setBusy(false);
    }
  };
  return (
    <button
      onClick={toggle}
      disabled={busy}
      aria-pressed={fav}
      className="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 hover:bg-slate-50 disabled:opacity-50"
    >
      <Star className={`h-4 w-4 ${fav ? "fill-accent-400 text-accent-500" : ""}`} /> {fav ? "Saved" : "Save"}
    </button>
  );
}
