"use client";

import { useEffect, useState } from "react";
import { ListOrdered, Pause, Play, Square, Volume2 } from "lucide-react";
import {
  RATES, hasUrduVoice, loadRate, loadVoiceLang, pauseSpeech, resumeSpeech, saveRate, speak, stopSpeech, useSpeechState,
  type VoiceLang,
} from "@/lib/voice";
import clsx from "./clsx";

import type { SpokenTrip } from "@/lib/journey";
export type { SpokenTrip };

const btn = "inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold";

/** Read the trip aloud: a short summary first, the step-by-step details on request; pause, stop and speed. */
export default function VoiceGuide({ trip }: { trip: SpokenTrip }) {
  const st = useSpeechState();
  const [rate, setRate] = useState(0.95);
  const [lang, setLang] = useState<VoiceLang>("en-IN");
  const [urdu, setUrdu] = useState(true);
  useEffect(() => {
    setRate(loadRate());
    setLang(loadVoiceLang());
    // voices load asynchronously on some browsers
    const check = () => setUrdu(hasUrduVoice());
    check();
    const t = setTimeout(check, 1000);
    return () => clearTimeout(t);
  }, []);
  if (!st.supported) return null;
  const say = (part: "summary" | "details") => speak(trip[part].en, trip[part].ur, lang);
  return (
    <div className="flex flex-wrap items-center gap-1.5" aria-label="Voice directions">
      <button type="button" onClick={() => say("summary")} className={clsx(btn, "bg-brand-600 text-white hover:bg-brand-700")}
        aria-label="Listen to a short summary">
        <Volume2 className="h-3 w-3" /> Listen
      </button>
      <button type="button" onClick={() => say("details")} className={clsx(btn, "bg-white text-brand-700 shadow-sm hover:bg-brand-50")}
        aria-label="Listen to step-by-step directions">
        <ListOrdered className="h-3 w-3" /> Step by step
      </button>
      {st.speaking && (
        <>
          <button type="button" onClick={st.paused ? resumeSpeech : pauseSpeech} className={clsx(btn, "bg-white text-slate-700 shadow-sm hover:bg-slate-50")}
            aria-label={st.paused ? "Resume" : "Pause"}>
            {st.paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />} {st.paused ? "Resume" : "Pause"}
          </button>
          <button type="button" onClick={stopSpeech} className={clsx(btn, "bg-white text-slate-700 shadow-sm hover:bg-slate-50")} aria-label="Stop speaking">
            <Square className="h-3 w-3" /> Stop
          </button>
        </>
      )}
      <label className="inline-flex items-center gap-1 text-[11px] text-slate-600">
        <span className="sr-only">Speaking speed</span>
        <select value={rate} onChange={(e) => { const r = Number(e.target.value); setRate(r); saveRate(r); }}
          className="rounded-full border border-slate-200 bg-white px-1.5 py-0.5 text-[11px]">
          {RATES.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </select>
      </label>
      <select value={lang} onChange={(e) => setLang(e.target.value as VoiceLang)} aria-label="Voice language"
        className="rounded-full border border-slate-200 bg-white px-1.5 py-0.5 text-[11px]">
        <option value="en-IN">English</option>
        <option value="ur-PK">اردو</option>
      </select>
      {lang === "ur-PK" && !urdu && (
        <span className="basis-full text-[11px] text-amber-700">This phone has no Urdu voice installed, so directions are read in English.</span>
      )}
    </div>
  );
}
