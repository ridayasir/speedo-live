"use client";

import { useState } from "react";
import { Bus, MapPin, RotateCcw, X } from "lucide-react";
import { parseJourney, speak, type VoiceLang } from "@/lib/voice";
import { placeHits, type Place, type PlaceHit, type VoiceJourney } from "./widgets";
import clsx from "./clsx";

/** Matches this close to the first one are the same area (e.g. two "Kalma Chowk" stops on either side of a road). */
const SAME_AREA_M = 600;

function meters(a: { lat: number; lng: number }, b: { lat: number; lng: number }) {
  const r = Math.PI / 180;
  const x = (b.lng - a.lng) * r * Math.cos(((a.lat + b.lat) / 2) * r);
  const y = (b.lat - a.lat) * r;
  return Math.sqrt(x * x + y * y) * 6371000;
}

const norm = (s: string) =>
  s.toLowerCase().replace(/^\s*\d+[.)]?\s*/, "").replace(/[^a-z0-9؀-ۿ]+/g, " ").trim();

/**
 * The match to use without asking, or null when the passenger must choose.
 * A Speedo stop with exactly the said name wins (if all such stops are in one area); otherwise the name is clear
 * only when it has one match, or all its top matches are in the same small area.
 */
export function clearMatch(hits: PlaceHit[], said: string): PlaceHit | null {
  const named = hits.filter((h) => h.kind === "stop" && norm(h.label) === norm(said));
  const pool = named.length ? named : hits.slice(0, 5);
  if (!pool.length) return null;
  return pool.every((h) => meters(h, pool[0]) <= SAME_AREA_M) ? pool[0] : null;
}

const toPlace = (h: PlaceHit): Place => ({ label: h.label, lat: h.lat, lng: h.lng, stop_id: h.stop_id });

interface End {
  text: string;
  hits: PlaceHit[];
  chosen: Place | null;
}

interface State {
  transcript: string;
  lang: VoiceLang;
  from: End | null; // null = the passenger's current location
  to: End;
}

/**
 * Turns a spoken trip into two places. Never picks silently between places in different areas: it shows the
 * choices (spec section 3), keeps the transcript visible and editable, and only then calls onResolved.
 */
export function useVoiceTrip(onResolved: (from: Place | null, to: Place, lang: VoiceLang) => void) {
  const [state, setState] = useState<State | null>(null);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const finishIfReady = (s: State) => {
    if (s.to.chosen && (s.from === null || s.from.chosen)) {
      setState(null);
      setProblem(null);
      onResolved(s.from?.chosen ?? null, s.to.chosen, s.lang);
    } else {
      setState(s);
    }
  };

  const start = async (j: VoiceJourney, lang: VoiceLang, transcript: string) => {
    setBusy(true);
    setProblem(null);
    const [fromHits, toHits] = await Promise.all([j.from ? placeHits(j.from) : Promise.resolve(null), placeHits(j.to)]);
    setBusy(false);
    const end = (text: string, hits: PlaceHit[]): End => {
      const m = clearMatch(hits, text);
      return { text, hits, chosen: m ? toPlace(m) : null };
    };
    const s: State = { transcript, lang, from: j.from && fromHits ? end(j.from, fromHits) : null, to: end(j.to, toHits) };
    const missing = !toHits.length ? j.to : j.from && !fromHits?.length ? j.from : null;
    if (missing) {
      setState(s);
      setProblem(`We could not find “${missing}”. Check the words below, fix them and search again, or type the place.`);
      speak(`Sorry, we could not find ${missing}. Please try again.`, `معاف کیجیے، ${missing} نہیں ملا۔ دوبارہ کوشش کریں۔`, lang);
      return;
    }
    if (!s.to.chosen || (s.from && !s.from.chosen)) {
      const name = !s.to.chosen ? j.to : j.from!;
      speak(
        `There is more than one place called ${name}. Please choose one on the screen.`,
        `${name} نام کی ایک سے زیادہ جگہیں ہیں۔ اسکرین پر ایک چنیں۔`,
        lang,
      );
    }
    finishIfReady(s);
  };

  /** the passenger corrected the transcript and pressed Search again */
  const retry = (text: string, lang: VoiceLang) => {
    const t = text.trim();
    if (t.length < 2) return;
    const j = parseJourney(t) ?? { from: null, to: t };
    void start(j, lang, t);
  };

  const choose = (side: "from" | "to", h: PlaceHit) => {
    if (!state) return;
    const s = { ...state, [side]: { ...(state[side] as End), chosen: toPlace(h) } } as State;
    finishIfReady(s);
  };

  const cancel = () => {
    setState(null);
    setProblem(null);
  };

  return { state, busy, problem, start, retry, choose, cancel };
}

type VoiceTrip = ReturnType<typeof useVoiceTrip>;

function Choices({ end, side, onPick }: { end: End; side: "from" | "to"; onPick: (side: "from" | "to", h: PlaceHit) => void }) {
  if (end.chosen || !end.hits.length) return null;
  return (
    <div className="mt-3">
      <p className="text-sm font-semibold text-slate-800">
        {side === "from" ? "Where are you now?" : "Where do you want to go?"} More than one place matches “{end.text}”:
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {end.hits.slice(0, 6).map((h, i) => (
          <li key={`${h.kind}-${h.stop_id ?? i}`}>
            <button type="button" onClick={() => onPick(side, h)}
              className="flex w-full items-start gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-left text-sm hover:border-brand-400 hover:bg-brand-50">
              {h.kind === "stop" ? <Bus className="mt-0.5 h-4 w-4 shrink-0 text-brand-600" /> : <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-accent-500" />}
              <span className="min-w-0 flex-1">
                <span className="block truncate font-medium text-slate-800">{h.label}</span>
                <span className="block truncate text-xs text-slate-500">{h.kind === "stop" ? "Speedo stop" : h.detail || "Place"}</span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** What was heard (editable), problems, and "which one did you mean?" choices. Renders nothing when idle. */
export function VoiceTripPanel({ trip }: { trip: VoiceTrip }) {
  const { state, busy, problem } = trip;
  const [edit, setEdit] = useState<string | null>(null);
  if (busy) return <p className="mt-2 text-sm text-brand-700" role="status">Finding the places you said…</p>;
  if (!state) return null;
  const text = edit ?? state.transcript;
  return (
    <div className="mt-3 rounded-xl border border-brand-100 bg-brand-50/60 p-3" role="region" aria-label="Voice search">
      <div className="flex items-start justify-between gap-2">
        <label htmlFor="voice-transcript" className="text-xs font-semibold uppercase tracking-wide text-brand-700">You said</label>
        <button type="button" onClick={() => { setEdit(null); trip.cancel(); }} aria-label="Close voice search" className="rounded p-0.5 text-slate-500 hover:bg-white">
          <X className="h-4 w-4" />
        </button>
      </div>
      <form className="mt-1 flex gap-2" onSubmit={(e) => { e.preventDefault(); trip.retry(text, state.lang); setEdit(null); }}>
        <input id="voice-transcript" value={text} onChange={(e) => setEdit(e.target.value)} dir="auto"
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-sm outline-none focus:border-brand-500" />
        <button type="submit" className={clsx("inline-flex shrink-0 items-center gap-1 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-brand-700")}>
          <RotateCcw className="h-3.5 w-3.5" /> Search again
        </button>
      </form>
      <p className="mt-1 text-[11px] text-slate-500">Fix any wrong word, then press Search again.</p>
      {problem && <p className="mt-2 text-sm text-red-700" role="alert">{problem}</p>}
      {state.from && <Choices end={state.from} side="from" onPick={trip.choose} />}
      <Choices end={state.to} side="to" onPick={trip.choose} />
    </div>
  );
}
