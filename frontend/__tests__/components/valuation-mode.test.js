/**
 * One answer to "which board did the user pick", for six call sites.
 *
 * The engines — trade suggestions, the arbitrage finder, angles, the
 * simulator, FAAB — run server-side off the loaded contract and used to
 * never see the valuation toggle at all. `/rankings` switched boards
 * and the advice did not.
 *
 * This is the client half of the fix. The tests that matter are the
 * ones about DEGRADATION, because every one of them is a path where the
 * request still has to go out: a corrupt settings blob, a server render
 * with no localStorage, a caller that already pinned its own lens.
 */

import { describe, expect, it, beforeEach, afterEach, vi } from "vitest";

import { SETTINGS_KEY } from "@/lib/trade-logic";
import {
  LEAGUE_ADJUSTED,
  MARKET,
  applyValuationModeParam,
  readValuationMode,
  withValuationMode,
} from "@/lib/valuation-mode";

function setSettings(value) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(value));
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("readValuationMode", () => {
  it("defaults to market when nothing is stored", () => {
    expect(readValuationMode()).toBe(MARKET);
  });

  it("ignores a persisted lens — a device may not pick a methodology", () => {
    // WITHDRAWN 2026-08-14. This used to assert the stored value was
    // honoured, which is precisely the defect: `next_settings_v2` is
    // device-local and never server-synced, so one account on two
    // devices held two answers, and the lens overwrote the canonical
    // field. See docs/valuation/LEAGUE_AWARE_METHODOLOGY_REJECTION.md.
    //
    // Read-and-ignore rather than deleted, so an old phone with
    // `leagueAdjusted` stored converges with no migration step.
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    expect(readValuationMode()).toBe(MARKET);
  });

  it("treats anything unrecognised as market", () => {
    for (const bad of ["leagueadjusted", "adjusted", "", null, 1, {}]) {
      setSettings({ valuationMode: bad });
      expect(readValuationMode()).toBe(MARKET);
    }
  });

  it("survives a corrupt settings blob", () => {
    // A trade request must not fail because some other setting wrote
    // garbage into the same key.
    localStorage.setItem(SETTINGS_KEY, "{not json");
    expect(readValuationMode()).toBe(MARKET);
  });

  it("survives localStorage throwing outright", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(readValuationMode()).toBe(MARKET);
  });
});

describe("withValuationMode", () => {
  it("adds nothing on the market board", () => {
    expect(withValuationMode({ roster: ["A"] })).toEqual({ roster: ["A"] });
  });

  it("adds no lens even when one is stored", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    expect(withValuationMode({ roster: ["A"] })).toEqual({ roster: ["A"] });
  });

  it("never mutates the caller's body", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    const body = { roster: ["A"] };
    withValuationMode(body);
    expect(body).toEqual({ roster: ["A"] });
  });

  it("leaves an explicitly pinned lens alone", () => {
    // A caller that names its own lens means it — including a caller
    // that deliberately pins market while the user is on adjusted.
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    expect(withValuationMode({ valuation_mode: "market" })).toEqual({
      valuation_mode: "market",
    });
    expect(withValuationMode({ valuationMode: "market" })).toEqual({
      valuationMode: "market",
    });
  });

  it("handles a missing body", () => {
    expect(withValuationMode()).toEqual({});
    expect(withValuationMode(null)).toEqual({});
  });
});

describe("applyValuationModeParam", () => {
  it("always reports the canonical board and adds no param", () => {
    // The return value still exists because /api/terminal keys its cache
    // on it. With one methodology it is constant — but keeping the seam
    // means a future validated methodology re-opens in one place rather
    // than re-threading six call sites.
    const params = new URLSearchParams();
    expect(applyValuationModeParam(params)).toBe(MARKET);
    expect(params.toString()).toBe("");

    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    const stored = new URLSearchParams();
    expect(applyValuationModeParam(stored)).toBe(MARKET);
    expect(stored.get("valuationMode")).toBeNull();
  });

  it("leaves other params untouched", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    const params = new URLSearchParams();
    params.set("team", "123");
    applyValuationModeParam(params);
    expect(params.get("team")).toBe("123");
  });
});
