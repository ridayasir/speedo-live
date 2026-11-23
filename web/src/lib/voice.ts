"use client";

import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Voice search with the browser's built-in speech recognition (Chrome, Edge, Samsung Internet, Safari).
 * Nothing to install and no API key: the browser turns speech into text. Needs HTTPS (or localhost) and mic permission.
 */
export type VoiceLang = "en-IN" | "ur-PK";
const LANG_KEY = "speedo.voiceLang";

/* eslint-disable @typescript-eslint/no-explicit-any */
function recognizerClass(): any {
  if (typeof window === "undefined") return null;
  const w = window as any;
  return w.SpeechRecognition || w.webkitSpeechRecognition || null;
}

export function loadVoiceLang(): VoiceLang {
  try {
    return localStorage.getItem(LANG_KEY) === "ur-PK" ? "ur-PK" : "en-IN";
  } catch {
    return "en-IN";
  }
}

function saveVoiceLang(l: VoiceLang) {
  try {
    localStorage.setItem(LANG_KEY, l);
  } catch {
    /* private mode: the choice just isn't remembered */
  }
}

// "take me to Liberty", "mujhe Liberty jana hai", "مجھے لبرٹی جانا ہے" -> "Liberty" / "لبرٹی"
const LEADING = [
  /^(please\s+)?(i\s+want\s+to\s+go\s+to|i\s+want\s+to\s+go|take\s+me\s+to|go\s+to|where\s+is|find|search(\s+for)?|show\s+me|navigate\s+to|directions?\s+to)\s+/i,
  /^(mujhe|mujhay|mjhe|main\s+ne|mein\s+ne|hamein)\s+/i,
  /^(مجھے|میں\s+نے|ہمیں)\s+/,
];
const TRAILING = [
  /\s+(jana|jaana|jaanaa)\s+(hai|hay|he|h)$/i,
  /\s+(kaise|kese|kaisay)\s+(jaun|jaon|jayen|jain)$/i,
  /\s+(stop|bus\s+stop)\s+(kahan|kidhar)\s+(hai|hay|he)$/i,
  /\s+(kahan|kidhar)\s+(hai|hay|he)$/i,
  /\s+(tak|par|pe)$/i,
  /\s+جانا\s+ہے$/,
  /\s+کیسے\s+جاؤں$/,
  /\s+کہاں\s+ہے$/,
  /\s+(تک|پر)$/,
];

export function cleanSpokenPlace(text: string): string {
  let t = text.trim().replace(/[.?!۔؟,،]+$/g, "").trim();
  for (let i = 0; i < 2; i++) {
    for (const r of LEADING) t = t.replace(r, "");
    for (const r of TRAILING) t = t.replace(r, "");
    t = t.trim();
  }
  return t || text.trim();
}

export function useVoiceSearch(onResult: (text: string, lang: VoiceLang) => void) {
  const [supported, setSupported] = useState(false);
  const [listening, setListening] = useState(false);
  const [heard, setHeard] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lang, setLangState] = useState<VoiceLang>("en-IN");
  const rec = useRef<any>(null);
  const cb = useRef(onResult);
  cb.current = onResult;

  useEffect(() => {
    setSupported(!!recognizerClass());
    setLangState(loadVoiceLang());
    return () => rec.current?.abort?.();
  }, []);

  const stop = useCallback(() => {
    rec.current?.stop?.();
  }, []);

  const start = useCallback((useLang?: VoiceLang) => {
    const R = recognizerClass();
    if (!R) {
      setError("Voice search does not work in this browser. Please use Chrome.");
      return;
    }
    rec.current?.abort?.();
    const l = useLang || loadVoiceLang();
    const r = new R();
    r.lang = l;
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;
    let final = "";
    r.onresult = (e: any) => {
      let text = "";
      for (let i = 0; i < e.results.length; i++) {
        text += e.results[i][0].transcript;
        if (e.results[i].isFinal) final = text;
      }
      setHeard(text);
    };
    r.onerror = (e: any) => {
      const code = e?.error;
      if (code === "aborted") return;
      setError(
        code === "not-allowed" || code === "service-not-allowed"
          ? "Microphone permission is blocked. Allow the microphone for this site and try again."
          : code === "no-speech"
            ? "We did not hear anything. Tap the mic and say the stop name."
            : code === "network"
              ? "Voice search needs an internet connection."
              : "Voice search stopped. Please try again.",
      );
    };
    r.onend = () => {
      setListening(false);
      if (final.trim()) cb.current(cleanSpokenPlace(final), l);
    };
    rec.current = r;
    setHeard("");
    setError(null);
    setListening(true);
    try {
      r.start();
    } catch {
      setListening(false);
      setError("Voice search could not start. Please try again.");
    }
  }, []);

  const setLang = useCallback(
    (l: VoiceLang) => {
      saveVoiceLang(l);
      setLangState(l);
      if (listening) start(l);
    },
    [listening, start],
  );

  return { supported, listening, heard, error, lang, setLang, start, stop, clearError: () => setError(null) };
}

/**
 * Read a short message aloud (for passengers who find reading hard). Uses the Urdu text when the passenger spoke
 * Urdu and the phone has an Urdu voice, otherwise the English text. Silently does nothing if unsupported.
 */
export function speak(english: string, urdu: string, lang: VoiceLang) {
  try {
    const s = window.speechSynthesis;
    if (!s) return;
    s.cancel();
    const urVoice = lang === "ur-PK" ? s.getVoices().find((v) => v.lang.toLowerCase().startsWith("ur")) : undefined;
    const u = new SpeechSynthesisUtterance(urVoice ? urdu : english);
    if (urVoice) u.voice = urVoice;
    u.lang = urVoice ? urVoice.lang : "en-IN";
    u.rate = 0.95;
    s.speak(u);
  } catch {
    /* no speech output available */
  }
}
