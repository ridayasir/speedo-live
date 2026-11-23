// SYNTHETIC places: coordinates around Lahore, not real stop records.
import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { clearMatch } from "./VoiceTrip";
import type { PlaceHit } from "./widgets";

const hit = (label: string, lat: number, lng: number, kind: "stop" | "place" = "stop"): PlaceHit => ({ label, lat, lng, kind });

describe("clearMatch: never pick silently between places in different areas (spec 3)", () => {
  it("one match is used", () => {
    assert.equal(clearMatch([hit("Liberty Chowk", 31.5109, 74.3413)], "Liberty Chowk")?.label, "Liberty Chowk");
  });
  it("a stop with exactly the said name wins over places with the same name", () => {
    const hits = [hit("15. Kalma Chowk", 31.5035, 74.3319), hit("Kalma Chowk", 31.5043, 74.3316),
      hit("Kalma Chowk, Garden Town", 31.49, 74.32, "place")];
    assert.equal(clearMatch(hits, "Kalma Chowk")?.label, "15. Kalma Chowk");
  });
  it("matches spread over different areas: ask", () => {
    const hits = [hit("Main Market Gulberg", 31.51, 74.345), hit("Gulberg, Lahore Cant", 31.52, 74.36, "place"),
      hit("Gulberg, Garden Town", 31.49, 74.32, "place")];
    assert.equal(clearMatch(hits, "Gulberg"), null);
  });
  it("matches all in one small area (two sides of a road): no need to ask", () => {
    const hits = [hit("Model Town Link Road", 31.4800, 74.3200), hit("Model Town Link Rd", 31.4803, 74.3204)];
    assert.equal(clearMatch(hits, "Model Town Link")?.label, "Model Town Link Road");
  });
  it("nothing found: nothing chosen", () => {
    assert.equal(clearMatch([], "Xyz"), null);
  });
});
