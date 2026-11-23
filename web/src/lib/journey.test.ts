// SYNTHETIC fixtures: made-up stops and routes shaped like the API, not real Speedo data.
import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";
import { journeySpeech, loadTrip, saveTrip, tripKey } from "./journey";
import type { PlanOption, PlanResult, Stop } from "./types";

const stop = (id: number, name: string): Stop => ({ id, code: `T${id}`, name, lat: 31.5 + id / 1000, lng: 74.3 } as Stop);
const A = stop(1, "1. Alpha Chowk"), B = stop(2, "Beta"), C = stop(3, "Gamma"), D = stop(4, "Delta Town");

const ride = (from: Stop, to: Stop, code: string, towards: string, n: number) => ({
  type: "ride" as const, route_id: n, route_code: code, route_name: code, color: "#b91c1c", direction: "forward" as const,
  towards, board: from, alight: to, stops: [from, to], stop_count: 1, distance_m: 1000, minutes: 4, is_demo: false,
});
const walk = (from: Stop | { lat: number; lng: number; name: string }, to: Stop, m: number, transfer = false) => ({
  type: "walk" as const, from, to, distance_m: m, minutes: m / 75, estimate_basis: "straight_line" as const, transfer,
});
const option = (legs: PlanOption["legs"]): PlanOption =>
  ({ legs, total_minutes: 20, wait_minutes: 5, transfers: legs.filter((l) => l.type === "ride").length - 1, walk_m: 0, is_demo: false });
const plan = (options: PlanOption[], status: PlanResult["status"] = "ok"): PlanResult =>
  ({ origin: { lat: 0, lng: 0, name: "Start" }, destination: { lat: 0, lng: 0, name: "End" }, nearest_boarding_stop: null,
     nearest_destination_stop: null, options, straight_line_m: 0, status, search_limits: { max_walk_m: 1500, max_transfers: 2 } });

describe("journeySpeech: voice says only what the itinerary says (spec 8, 9)", () => {
  const trip = option([walk({ lat: 0, lng: 0, name: "Start" }, A, 300), ride(A, B, "R1", "Zeta", 1), walk(B, C, 60, true), ride(C, D, "R2", "Omega", 2)]);
  const t = journeySpeech(trip, plan([trip]));

  it("summary names the boarding stop (without numbering), the bus, the walking change and where to get off", () => {
    assert.equal(t.summary.en, "Go to Alpha Chowk stop and take the R1 bus towards Zeta. Change buses at Beta (walk to Gamma). Get off at Delta Town.");
  });
  it("details keep every leg in order, with walking marked as an estimate", () => {
    const en = t.details.en;
    const order = ["Walk to Alpha Chowk", "take the R1 bus", "To change buses, walk about 60 m to Gamma", "take the R2 bus", "get off at Delta Town"];
    let at = -1;
    for (const part of order) {
      const i = en.indexOf(part);
      assert.ok(i > at, part);
      at = i;
    }
    assert.ok((en).includes("in a straight line"));
  });
  it("never speaks bus arrival times (not verified)", () => {
    assert.doesNotMatch(`${t.summary.en} ${t.details.en}`, /arriv|comes in|next bus/i);
  });
  it("same-stop change is said as such", () => {
    const same = option([ride(A, B, "R1", "Zeta", 1), ride(B, D, "R2", "Omega", 2)]);
    assert.ok((journeySpeech(same, plan([same])).details.en).includes("At the same stop, Beta"));
  });
  it("no route: names the search limit instead of claiming there is no bus", () => {
    assert.ok((journeySpeech(undefined, plan([], "no_route")).summary.en).includes("within 1.5 kilometres"));
  });
  it("outside Lahore: says Speedo runs in Lahore only", () => {
    assert.ok((journeySpeech(undefined, plan([], "outside_coverage")).summary.en).includes("Lahore only"));
  });
});

describe("saved trips for offline use (spec 11)", () => {
  beforeEach(() => {
    const mem = new Map<string, string>();
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
    };
  });
  const trip = option([ride(A, B, "R1", "Zeta", 1)]);

  it("a planned trip is kept with the time it was planned", () => {
    const k = tripKey({ lat: 31.5, lng: 74.3 }, { lat: 31.6, lng: 74.4 }, "fastest");
    saveTrip(k, plan([trip]), 1234);
    assert.deepEqual(loadTrip(k), { key: k, at: 1234, result: plan([trip]) });
  });
  it("a different preference or place is a different trip; empty results are not kept", () => {
    const k = tripKey({ lat: 31.5, lng: 74.3 }, { lat: 31.6, lng: 74.4 }, "fastest");
    saveTrip(k, plan([trip]));
    assert.equal(loadTrip(tripKey({ lat: 31.5, lng: 74.3 }, { lat: 31.6, lng: 74.4 }, "less_walking")), null);
    const empty = tripKey({ lat: 31.1, lng: 74.1 }, { lat: 31.2, lng: 74.2 }, "fastest");
    saveTrip(empty, plan([], "no_route"));
    assert.equal(loadTrip(empty), null);
  });
  it("keeps only the last five trips", () => {
    for (let i = 0; i < 7; i++) saveTrip(`k${i}`, plan([trip]));
    assert.equal(loadTrip("k0"), null);
    assert.notEqual(loadTrip("k6"), null);
  });
});
