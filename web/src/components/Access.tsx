"use client";

import { useEffect, useState } from "react";
import { WifiOff } from "lucide-react";
import clsx from "./clsx";

/* ------------------------------------------------------------------ larger text */
const SIZE_KEY = "speedo.textSize";
const SIZES = [
  { pct: 100, label: "Normal text" },
  { pct: 115, label: "Large text" },
  { pct: 130, label: "Extra large text" },
];

function applySize(pct: number) {
  // the app's spacing and type are in rem, so scaling the root font scales the whole page
  document.documentElement.style.fontSize = pct === 100 ? "" : `${pct}%`;
}

/** A+ button: cycles Normal -> Large -> Extra large text, remembered on this device. */
export function TextSizeButton({ className }: { className?: string }) {
  const [i, setI] = useState(0);
  useEffect(() => {
    let saved = 0;
    try {
      saved = Math.max(0, SIZES.findIndex((s) => s.pct === Number(localStorage.getItem(SIZE_KEY))));
    } catch {
      /* storage blocked: normal size */
    }
    setI(saved);
    applySize(SIZES[saved].pct);
  }, []);
  const next = () => {
    const n = (i + 1) % SIZES.length;
    setI(n);
    applySize(SIZES[n].pct);
    try {
      localStorage.setItem(SIZE_KEY, String(SIZES[n].pct));
    } catch {
      /* not remembered */
    }
  };
  return (
    <button type="button" onClick={next} title={`${SIZES[i].label} (tap to change)`}
      aria-label={`Text size: ${SIZES[i].label}. Tap for ${SIZES[(i + 1) % SIZES.length].label.toLowerCase()}.`}
      className={clsx("rounded-xl px-2 py-1.5 font-bold text-slate-600 hover:bg-slate-50", className)}>
      <span className="text-sm">A</span>
      <span className="text-base">{i === 0 ? "+" : i === 1 ? "++" : "−"}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ offline */
export function useOnline(): boolean {
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    update();
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  return online;
}

export function OfflineBanner() {
  const online = useOnline();
  if (online) return null;
  return (
    <div role="status" className="flex items-center justify-center gap-2 bg-slate-800 px-4 py-2 text-sm text-white">
      <WifiOff className="h-4 w-4 shrink-0" aria-hidden />
      No internet connection. Live buses, search and voice need internet; saved trips still open.
    </div>
  );
}
