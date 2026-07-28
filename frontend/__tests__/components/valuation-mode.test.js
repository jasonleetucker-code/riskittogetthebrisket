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

  it("reads the persisted lens", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    expect(readValuationMode()).toBe(LEAGUE_ADJUSTED);
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

  it("adds the lens when the adjusted board is selected", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    expect(withValuationMode({ roster: ["A"] })).toEqual({
      roster: ["A"],
      valuation_mode: LEAGUE_ADJUSTED,
    });
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
  it("returns the mode so callers can key a cache on it", () => {
    // THE POINT of the return value: /api/terminal caches by
    // (team, window, league). A cache keyed without the board serves
    // the stale market payload for the full TTL after the user
    // switches, which looks exactly like the toggle not working.
    const params = new URLSearchParams();
    expect(applyValuationModeParam(params)).toBe(MARKET);
    expect(params.toString()).toBe("");

    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    const adjusted = new URLSearchParams();
    expect(applyValuationModeParam(adjusted)).toBe(LEAGUE_ADJUSTED);
    expect(adjusted.get("valuationMode")).toBe(LEAGUE_ADJUSTED);
  });

  it("leaves other params untouched", () => {
    setSettings({ valuationMode: LEAGUE_ADJUSTED });
    const params = new URLSearchParams();
    params.set("team", "123");
    applyValuationModeParam(params);
    expect(params.get("team")).toBe("123");
  });
});
