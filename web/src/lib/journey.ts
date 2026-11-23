/**
 * The planned trip as words (for the voice guide) and a small on-device cache of the last trips (for offline use).
 * Pure functions: no React, so they are unit-tested (journey.test.ts).
 */
import { km } from "./format";
import type { PlanResult } from "./types";
import type { PlanLegRide, PlanOption } from "./types";

export interface SpokenTrip {
  summary: { en: string; ur: string };
  details: { en: string; ur: string };
}

export const spokenName = (n: string) => n.replace(/^\s*\d+[.)]?\s*/, "");


/**
 * What the voice says, built only from the planned trip (no times of buses: those are not verified).
 * Summary: which stop, which bus, where to change, where to get off. Details: every leg with walking estimates.
 */
export function journeySpeech(o: PlanOption | undefined, result: PlanResult | null): SpokenTrip {
  if (!o && result?.status === "outside_coverage") {
    const msg = {
      en: "Speedo buses run in Lahore only. Please choose places inside Lahore.",
      ur: "اسپیڈو بسیں صرف لاہور میں چلتی ہیں۔ لاہور کے اندر کی جگہ چنیں۔",
    };
    return { summary: msg, details: msg };
  }
  if (!o) {
    const kms = ((result?.search_limits?.max_walk_m ?? 1500) / 1000).toFixed(1);
    const msg = {
      en: `Sorry, we found no Speedo connection within ${kms} kilometres walking of these places. Try a nearby main stop.`,
      ur: `معاف کیجیے، ان جگہوں سے ${kms} کلومیٹر پیدل کے اندر کوئی اسپیڈو بس نہیں ملی۔ قریب کا کوئی بڑا اسٹاپ آزمائیں۔`,
    };
    return { summary: msg, details: msg };
  }
  const rides = o.legs.filter((l): l is PlanLegRide => l.type === "ride");
  const first = rides[0], last = rides[rides.length - 1];
  const towards = (r: PlanLegRide) =>
    r.towards ? { en: ` towards ${spokenName(r.towards)}`, ur: `، جو ${spokenName(r.towards)} کی طرف جاتی ہے` } : { en: "", ur: "" };
  // where each change happens; a walking change names both stops
  const changes = rides.slice(1).map((r, k) =>
    rides[k].alight.id === r.board.id ? spokenName(r.board.name) : `${spokenName(rides[k].alight.name)} (walk to ${spokenName(r.board.name)})`);
  const summary = {
    en: `Go to ${spokenName(first.board.name)} stop and take the ${first.route_code} bus${towards(first).en}.` +
      (changes.length ? ` Change buses at ${changes.join(", then at ")}.` : "") +
      ` Get off at ${spokenName(last.alight.name)}.`,
    ur: `${spokenName(first.board.name)} اسٹاپ پر جائیں اور ${first.route_code} بس لیں${towards(first).ur}۔` +
      (changes.length ? ` ${changes.join("، پھر ")} پر بس بدلیں۔` : "") +
      ` ${spokenName(last.alight.name)} پر اتر جائیں۔`,
  };
  const en: string[] = [], ur: string[] = [];
  o.legs.forEach((l, i) => {
    if (l.type === "walk") {
      const m = Math.max(1, Math.round(l.minutes)), d = km(l.distance_m);
      const target = spokenName(l.to.name || "the stop");
      if (l.transfer) {
        en.push(`To change buses, walk about ${d} to ${target} stop, roughly ${m} minute${m === 1 ? "" : "s"}.`);
        ur.push(`بس بدلنے کے لیے تقریباً ${d} پیدل چل کر ${target} اسٹاپ جائیں، اندازاً ${m} منٹ۔`);
      } else if (i === 0) {
        en.push(`Walk to ${target} stop, about ${d} in a straight line, roughly ${m} minutes.`);
        ur.push(`${target} اسٹاپ تک پیدل جائیں، سیدھی لکیر میں تقریباً ${d}، اندازاً ${m} منٹ۔`);
      } else {
        en.push(`Then walk about ${d} to ${target}, roughly ${m} minutes.`);
        ur.push(`پھر تقریباً ${d} پیدل چل کر ${target} پہنچیں، اندازاً ${m} منٹ۔`);
      }
    } else {
      const k = rides.indexOf(l);
      const sameStop = k > 0 && rides[k - 1].alight.id === l.board.id;
      en.push(`${sameStop ? "At the same stop," : "At"} ${spokenName(l.board.name)}, take the ${l.route_code} bus${towards(l).en}. Ride ${l.stop_count} stop${l.stop_count === 1 ? "" : "s"} and get off at ${spokenName(l.alight.name)}.`);
      ur.push(`${spokenName(l.board.name)} سے ${l.route_code} بس لیں${towards(l).ur}۔ ${l.stop_count} اسٹاپ کے بعد ${spokenName(l.alight.name)} پر اتر جائیں۔`);
    }
  });
  return { summary, details: { en: en.join(" "), ur: ur.join(" ") } };
}


/* ------------------------------------------------------------------ last trips, kept on this device */
const TRIPS_KEY = "speedo.savedTrips";
const KEEP = 5;

export interface SavedTrip {
  key: string;
  at: number; // when it was planned (ms)
  result: PlanResult;
}

/** Same start and end (to about 10 m) and the same preference = the same saved trip. */
export function tripKey(f: { lat: number; lng: number }, t: { lat: number; lng: number }, prefer: string): string {
  const r = (x: number) => x.toFixed(4);
  return `${r(f.lat)},${r(f.lng)}>${r(t.lat)},${r(t.lng)}:${prefer}`;
}

function readAll(): SavedTrip[] {
  try {
    const v = JSON.parse(localStorage.getItem(TRIPS_KEY) || "[]");
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

export function saveTrip(key: string, result: PlanResult, at = Date.now()) {
  if (!result.options.length) return;
  try {
    const rest = readAll().filter((x) => x.key !== key);
    localStorage.setItem(TRIPS_KEY, JSON.stringify([{ key, at, result }, ...rest].slice(0, KEEP)));
  } catch {
    /* storage full or blocked: the trip just is not kept */
  }
}

export function loadTrip(key: string): SavedTrip | null {
  return readAll().find((x) => x.key === key) ?? null;
}
