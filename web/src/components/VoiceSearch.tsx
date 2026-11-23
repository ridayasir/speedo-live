"use client";

import { Mic, MicOff, X } from "lucide-react";
import clsx from "./clsx";
import type { VoiceLang, useVoiceSearch } from "@/lib/voice";

type Voice = ReturnType<typeof useVoiceSearch>;

/** Mic button that sits inside a search box. Hidden when the browser cannot do speech recognition. */
export function MicButton({ voice, className }: { voice: Voice; className?: string }) {
  if (!voice.supported) return null;
  return (
    <button
      type="button"
      onClick={() => (voice.listening ? voice.stop() : voice.start())}
      className={clsx(
        "shrink-0 rounded-full p-1.5 transition",
        voice.listening ? "animate-pulse bg-brand-600 text-white" : "text-brand-600 hover:bg-brand-50 hover:text-brand-800",
        className,
      )}
      title={voice.listening ? "Stop listening" : "Search by voice"}
      aria-label={voice.listening ? "Stop listening" : "Search by voice: say the stop or place name"}
      aria-pressed={voice.listening}
    >
      {voice.listening ? <MicOff className="h-4 w-4" /> : <Mic className="h-4 w-4" />}
    </button>
  );
}

const LANGS: { id: VoiceLang; label: string }[] = [
  { id: "en-IN", label: "English" },
  { id: "ur-PK", label: "اردو" },
];

/** Shown under the search box while listening (or after a voice error): what we heard, language choice, errors. */
export function VoicePanel({ voice }: { voice: Voice }) {
  if (!voice.listening && !voice.error) return null;
  return (
    <div className="mt-2 rounded-xl border border-brand-100 bg-brand-50 p-3 text-sm" role="status" aria-live="polite">
      {voice.listening ? (
        <>
          <div className="flex items-center gap-2 font-semibold text-brand-800">
            <span className="relative flex h-2.5 w-2.5">
              <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-brand-500 opacity-75" />
              <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-brand-600" />
            </span>
            Listening… say the stop or place name
          </div>
          <p className="mt-0.5 text-xs text-brand-700" dir="rtl" lang="ur">اپنے اسٹاپ یا جگہ کا نام بولیں</p>
          {voice.heard && <p className="mt-2 rounded-lg bg-white px-2 py-1 text-slate-800">“{voice.heard}”</p>}
          <p className="mt-1 text-[11px] text-slate-500">
            Your browser&apos;s speech service turns your voice into text. Speedo Live does not record or keep your voice.
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="text-slate-500">Language:</span>
            {LANGS.map((l) => (
              <button key={l.id} type="button" onClick={() => voice.setLang(l.id)}
                className={clsx("rounded-full border px-2.5 py-0.5 font-medium",
                  voice.lang === l.id ? "border-brand-600 bg-brand-600 text-white" : "border-slate-300 bg-white text-slate-700 hover:border-brand-400")}>
                {l.label}
              </button>
            ))}
            <button type="button" onClick={voice.stop} className="ml-auto rounded-full px-2.5 py-0.5 font-medium text-brand-700 hover:bg-white">
              Done
            </button>
          </div>
        </>
      ) : (
        <div className="flex items-start gap-2 text-red-700">
          <span className="flex-1">{voice.error}</span>
          <button type="button" onClick={voice.clearError} aria-label="Close" className="rounded p-0.5 hover:bg-white"><X className="h-4 w-4" /></button>
        </div>
      )}
    </div>
  );
}
