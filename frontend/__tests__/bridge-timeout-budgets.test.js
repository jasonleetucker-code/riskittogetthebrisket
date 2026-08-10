/**
 * Bridge abort budgets on the page-load critical path.
 *
 * WHY THIS EXISTS
 * ---------------
 * The Next bridge routes each abort their backend fetch on a timer and
 * synthesize a 5xx. Those budgets were chosen ad hoc — a survey of the 15
 * routes that have one found 3s, 4s, 5s, 10s, 15s, 20s and 30s, with 502
 * vs 503 equally arbitrary.
 *
 * That matters because the backend is single-threaded on its event loop
 * and demonstrably stalls for longer than the short end of that range.
 * MEASURED 2026-08-06 on hardware faster than a CI runner: a cold
 * `POST /api/rankings/overrides` recompute takes 13.27s, and during it a
 * trivial `/api/health` went 7ms -> 10,218ms. It is CPU-bound pure Python
 * holding the GIL, so `run_in_threadpool` cannot help.
 *
 * A budget below that stall reports a BUSY backend as a DEAD one. On the
 * data route that is not cosmetic: the abort falls back to disk, the
 * committed snapshots are unstamped, the route refuses them (503), and
 * `/rankings` renders an error Banner instead of the table — so a
 * transient stall reads as a total board failure.
 *
 * WHAT THIS DOES NOT CLAIM
 * ------------------------
 * That these budgets caused any specific CI failure. Two tempting stories
 * are refuted and must not be re-derived:
 *   - "Playwright runs specs concurrently so another spec's overrides POST
 *     stalls this one" — FALSE, playwright.config.js sets workers: 1 in CI.
 *   - "/rankings fires the overrides POST itself" — FALSE, tepMultiplier
 *     defaults to null (useSettings.js:51), so settings are not
 *     "customized" and no POST is issued on that load path.
 * These tests pin a policy, not a diagnosis.
 */
import { describe, expect, it } from "vitest";
import fs from "node:fs";
import path from "node:path";

const API = path.resolve(__dirname, "..", "app", "api");
const read = (...p) => fs.readFileSync(path.join(API, ...p), "utf8");

// The measured worst-case event-loop stall. Any budget on the page-load
// path must clear it, or it will fire on a live backend.
const MEASURED_STALL_MS = 10218;

function abortBudget(source) {
  // Matches `setTimeout(() => ctl.abort(), N)` and the named-constant form
  // `setTimeout(() => ctl.abort(), NAME)` resolved via its declaration.
  const direct = source.match(/abort\(\)[\s\S]{0,40}?,\s*(\d[\d_]*)\s*\)/);
  if (direct) return Number(direct[1].replace(/_/g, ""));
  const named = source.match(/abort\(\)[\s\S]{0,60}?,\s*([A-Z_][A-Z0-9_]*)\s*\)/);
  if (named) {
    const decl = source.match(
      new RegExp(`${named[1]}\\s*=\\s*(\\d[\\d_]*)`),
    );
    if (decl) return Number(decl[1].replace(/_/g, ""));
  }
  return null;
}

describe("routes on the /rankings load path clear the measured stall", () => {
  it("dynasty-data (the contract fetch — a short budget blanks the board)", () => {
    const budget = abortBudget(read("dynasty-data", "route.js"));
    expect(budget, "could not parse a budget — the regex needs updating").toBeTruthy();
    expect(budget).toBeGreaterThan(MEASURED_STALL_MS);
  });

  it("auth/status (the 502 emitter — probed on every page mount)", () => {
    const budget = abortBudget(read("auth", "status", "route.js"));
    expect(budget).toBeTruthy();
    expect(budget).toBeGreaterThan(MEASURED_STALL_MS);
  });

  it("rankings/overrides (a bid is derived from a full recompute)", () => {
    const budget = abortBudget(read("rankings", "overrides", "route.js"));
    expect(budget).toBeTruthy();
    expect(budget).toBeGreaterThan(MEASURED_STALL_MS);
  });

  it("health (StaleDataBanner polls it from every page)", () => {
    const budget = abortBudget(read("health", "route.js"));
    expect(budget).toBeTruthy();
    expect(budget).toBeGreaterThan(MEASURED_STALL_MS);
  });
});

describe("the health bridge route exists at all", () => {
  // It did not, for the whole life of StaleDataBanner. The banner skips on
  // a 404 by design (StaleDataBanner.jsx:57-64, so a broken probe never
  // flashes a false "data stale"), which meant the endpoint being absent
  // was completely silent — and the banner could never fire in any
  // Next-fronted topology. Production was fine because nginx routes /api/*
  // straight to FastAPI, so the gap only existed in dev and CI.
  it("answers /api/health rather than 404ing on every page load", () => {
    expect(fs.existsSync(path.join(API, "health", "route.js"))).toBe(true);
  });

  it("passes the backend's 503 through, because 503 means DEGRADED here", () => {
    // The backend uses 503 for degraded-but-reporting, and the body still
    // carries the freshness numbers the banner reads. Collapsing it to a
    // generic error would suppress the exact warning this exists to raise.
    const src = read("health", "route.js");
    expect(src).toMatch(/status:\s*res\.status/);
  });
});

describe("the specific values that regressed", () => {
  it("dynasty-data is not back to 4000ms", () => {
    expect(read("dynasty-data", "route.js")).not.toMatch(
      /BACKEND_IDLE_TIMEOUT_MS\s*=\s*4000\b/,
    );
  });

  it("auth/status is not back to 3000ms", () => {
    expect(read("auth", "status", "route.js")).not.toMatch(/abort\(\),\s*3000\b/);
  });
});

describe("the refuted mechanisms stay refuted in the record", () => {
  // These comments are the reason nobody has to re-run the investigation.
  // If the note is deleted, the next person re-derives a story that is
  // already known to be false — which is how this flake got three wrong
  // published root causes.
  it("dynasty-data names workers:1 as refuting the concurrency story", () => {
    const src = read("dynasty-data", "route.js");
    expect(src).toMatch(/workers: 1/);
    expect(src).toMatch(/tepMultiplier/);
  });

  it("playwright really does run one worker in CI", () => {
    // The fact the comment rests on. If this changes, the comment becomes
    // wrong and this test says so.
    const cfg = fs.readFileSync(
      path.resolve(__dirname, "..", "..", "tests", "e2e", "playwright.config.js"),
      "utf8",
    );
    expect(cfg).toMatch(/workers:\s*process\.env\.CI\s*\?\s*1\s*:/);
    expect(cfg).toMatch(/fullyParallel:\s*false/);
  });

  it("tepMultiplier really does default to null", () => {
    const settings = fs.readFileSync(
      path.resolve(__dirname, "..", "components", "useSettings.js"),
      "utf8",
    );
    expect(settings).toMatch(/tepMultiplier:\s*null/);
  });
});
