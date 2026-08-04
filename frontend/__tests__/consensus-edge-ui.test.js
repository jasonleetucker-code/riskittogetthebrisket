import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const root = path.resolve(__dirname, "..");

function read(relative) {
  return fs.readFileSync(path.join(root, relative), "utf8");
}

describe("Consensus Edge UI", () => {
  const page = read("app/consensus-edge/page.jsx");

  it("leads with the shadow-mode warning rather than burying it", () => {
    expect(page).toContain("Shadow mode — not validated for decisions");
    // The warning must appear before the ranked lists, not after them.
    expect(page.indexOf("Shadow mode")).toBeLessThan(page.indexOf("Top buys"));
  });

  it("states the specific limitations rather than a vague disclaimer", () => {
    expect(page).toContain("not");
    expect(page).toContain("fitted out-of-sample");
    expect(page).toContain("Sharp Flow has no historical data");
    expect(page).toContain("IDP cannot");
    expect(page).toContain("market movement");
  });

  it("renders every component separately instead of only the composite", () => {
    for (const key of ["mispricing", "sharp_flow", "momentum", "data_quality"]) {
      expect(page).toContain(key);
    }
  });

  it("labels momentum as context so it cannot read as a buy reason", () => {
    expect(page).toContain("(context)");
  });

  it("shows Conflicted and Insufficient Evidence as first-class states", () => {
    expect(page).toContain("Conflicted");
    expect(page).toContain("Insufficient Evidence");
  });

  it("never pads a ranked list to a target length", () => {
    expect(page).toContain("The list is not padded");
    expect(page).toContain("No qualifying buy");
  });

  it("computes no score of its own — display only", () => {
    // The scoring vocabulary must arrive from the backend, never be derived here.
    expect(page).not.toMatch(/function\s+(computeScore|classify|scoreOf)\b/);
    expect(page).not.toMatch(/Math\.tanh/);
    expect(page).toContain("PURE DISPLAY");
  });
});

describe("Consensus Edge bridge routes", () => {
  it("forwards no leagueKey — the board is scoring-profile scoped", () => {
    const route = read("app/api/consensus-edge/top/route.js");
    expect(route).toContain("/api/consensus-edge/top");
    // Assert the BEHAVIOUR, not the word: the file explains in a comment why it
    // forwards no leagueKey, and a bare substring check fails on the
    // explanation while passing on a route that quietly forwards one.
    const withoutComments = route.replace(/\/\/.*$/gm, "");
    expect(withoutComments).not.toMatch(/leagueKey/);
    expect(withoutComments).not.toMatch(/searchParams/);
  });

  it("degrades to 503 rather than throwing", () => {
    for (const name of ["top", "health", "methodology"]) {
      const route = read(`app/api/consensus-edge/${name}/route.js`);
      expect(route).toContain("503");
    }
  });
});

describe("navigation", () => {
  it("marks the entry as shadow so it cannot be mistaken for a promoted feature", () => {
    const nav = read("lib/nav-model.js");
    expect(nav).toContain("/consensus-edge");
    expect(nav).toContain("Consensus Edge (shadow)");
  });
});
