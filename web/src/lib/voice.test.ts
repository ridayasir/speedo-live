import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { cleanSpokenPlace, parseJourney } from "./voice";

describe("parseJourney: where the passenger is and where they go (spec 3)", () => {
  const cases: [string, { from: string | null; to: string } | null][] = [
    ["Main Model Town mein hoon, mujhe Liberty Chowk jana hai", { from: "Model Town", to: "Liberty Chowk" }],
    ["main johar town me hun mujhe kalma chowk jana hai", { from: "johar town", to: "kalma chowk" }],
    ["Mujhe Model Town se Liberty Chowk jana hai", { from: "Model Town", to: "Liberty Chowk" }],
    ["Model Town se Liberty Chowk tak", { from: "Model Town", to: "Liberty Chowk" }],
    ["Yahan se Liberty Chowk tak jana hai", { from: null, to: "Liberty Chowk" }],
    ["main yahan hoon mujhe Liberty jana hai", { from: null, to: "Liberty" }],
    ["I am in Model Town and I want to go to Liberty Chowk", { from: "Model Town", to: "Liberty Chowk" }],
    ["from Shadman to Kalma Chowk", { from: "Shadman", to: "Kalma Chowk" }],
    ["میں ماڈل ٹاؤن میں ہوں مجھے لبرٹی چوک جانا ہے", { from: "ماڈل ٹاؤن", to: "لبرٹی چوک" }],
    ["ماڈل ٹاؤن سے کلمہ چوک", { from: "ماڈل ٹاؤن", to: "کلمہ چوک" }],
    // one place only: not a journey sentence
    ["mujhe Liberty Chowk jana hai", null],
    ["Main Boulevard", null],
  ];
  for (const [said, expected] of cases) {
    it(said, () => assert.deepEqual(parseJourney(said), expected));
  }
});

describe("cleanSpokenPlace: only the place name is searched", () => {
  const cases: [string, string][] = [
    ["mujhe Liberty Chowk jana hai", "Liberty Chowk"],
    ["I want to go to Emporium Mall", "Emporium Mall"],
    ["main Liberty jana chahti hoon", "Liberty"],
    ["Kalma Chowk kahan hai?", "Kalma Chowk"],
    ["مجھے لبرٹی چوک جانا ہے", "لبرٹی چوک"],
    ["Main Boulevard", "Main Boulevard"], // "Main" is part of the name here
  ];
  for (const [said, place] of cases) {
    it(`${said} -> ${place}`, () => assert.equal(cleanSpokenPlace(said), place));
  }
});
