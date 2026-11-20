"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";

// Set in web/.env.local (not committed). Leave empty on a public site: anyone could read them here.
const EMAIL = process.env.NEXT_PUBLIC_LOGIN_HINT_EMAIL || "";
const PASSWORD = process.env.NEXT_PUBLIC_LOGIN_HINT_PASSWORD || "";

function CopyRow({ label, value }: { label: string; value: string }) {
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      /* clipboard blocked: the value is still selectable */
    }
    setDone(true);
    setTimeout(() => setDone(false), 1500);
  };
  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-xs text-slate-500">{label}</span>
      <code className="min-w-0 flex-1 select-all truncate rounded-md bg-white px-2 py-1 text-xs text-slate-800 border border-slate-200">{value}</code>
      <button type="button" onClick={copy} aria-label={`Copy ${label.toLowerCase()}`}
        className="inline-flex shrink-0 items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-brand-700 hover:bg-brand-50">
        {done ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
        {done ? "Copied" : "Copy"}
      </button>
    </div>
  );
}

/** Admin sign-in details to copy and paste (only when configured in web/.env.local). */
export default function LoginHint() {
  if (!EMAIL || !PASSWORD) return null;
  return (
    <div className="space-y-1.5 rounded-xl border border-slate-200 bg-surface p-3">
      <p className="text-xs font-semibold text-slate-600">Admin login</p>
      <CopyRow label="Email" value={EMAIL} />
      <CopyRow label="Password" value={PASSWORD} />
    </div>
  );
}
