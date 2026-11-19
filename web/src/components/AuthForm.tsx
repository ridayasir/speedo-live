"use client";

import { useState } from "react";
import { Button, ErrorBox, Input } from "./ui";
import { useAuth } from "@/lib/hooks";
import type { User } from "@/lib/types";

export default function AuthForm({ allowRegister = true, onDone, hint }: { allowRegister?: boolean; onDone?: (u: User) => void; hint?: React.ReactNode }) {
  const { login, register } = useAuth();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [contact, setContact] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      let u: User;
      if (mode === "login") u = await login(identifier.trim(), password);
      else {
        const isEmail = contact.includes("@");
        u = await register({ full_name: name.trim(), password, ...(isEmail ? { email: contact.trim() } : { phone: contact.replace(/[\s-]/g, "") }) });
      }
      onDone?.(u);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      {allowRegister && (
        <div className="grid grid-cols-2 rounded-xl bg-slate-100 p-1 text-sm">
          {(["login", "register"] as const).map((m) => (
            <button key={m} type="button" onClick={() => setMode(m)} className={`rounded-lg py-1.5 font-medium ${mode === m ? "bg-white text-brand-700 shadow" : "text-slate-500"}`}>
              {m === "login" ? "Sign in" : "Create account"}
            </button>
          ))}
        </div>
      )}
      {mode === "login" ? (
        <>
          <Input label="Email or phone" autoComplete="username" required value={identifier} onChange={(e) => setIdentifier(e.target.value)} placeholder="you@example.com or 03xx xxxxxxx" />
          <Input label="Password" type="password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </>
      ) : (
        <>
          <Input label="Full name" required minLength={2} value={name} onChange={(e) => setName(e.target.value)} />
          <Input label="Email or mobile number" required value={contact} onChange={(e) => setContact(e.target.value)} placeholder="you@example.com or 03xx xxxxxxx" />
          <Input label="Password (min 8 characters)" type="password" autoComplete="new-password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} />
        </>
      )}
      {error && <ErrorBox error={error} />}
      <Button type="submit" className="w-full" loading={busy}>{mode === "login" ? "Sign in" : "Create account"}</Button>
      {hint}
    </form>
  );
}
