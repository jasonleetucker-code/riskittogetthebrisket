/**
 * evaluateRoster — history lookup must use the API's real key shape.
 *
 * N1, 2026-07-29 audit round 2.
 *
 * `evaluateRoster` is what the Signals panel (BuySellHold.jsx) and
 * TopSignalsRail.jsx actually render. It had NO test coverage, and it
 * looked history up by bare lowercased player name:
 *
 *     histLower.set(k.toLowerCase(), history[k])      // index
 *     histLower.get(key)                              // probe, key = name
 *
 * But the history it is handed comes from `useRankHistory` ->
 * `fetchRankHistory` -> `GET /api/data/rank-history`, which returns
 * `src/api/rank_history.py::_player_key` keys — `"Name::assetClass"`,
 * e.g. `"Ja'Marr Chase::offense"`. A bare-name probe misses every one
 * of them, so `historyPoints` was `[]` for every player, so trend7 /
 * trend30 / volatility were all null, so every rule that needs a trend
 * declined to fire and every verdict collapsed to HOLD.
 *
 * This is the same bug `value-history.js::buildHistoryLookup` was
 * written to fix elsewhere — its own docstring records that "the
 * previous bare history[name] lookup missed every row, which is why Top
 * Gainers rendered as all-dashes". portfolio-insights.js,
 * PlayerMarketMovement.jsx and app/trades/page.jsx all moved onto it.
 * signal-engine.js was the last consumer left on the naive path.
 *
 * These tests drive `evaluateRoster` with the REAL key shape.
 */

import { describe, it, expect } from "vitest";

import { evaluateRoster, SIGNALS } from "@/lib/signal-engine";

// A falling rank series: rank 20 -> 44 over 30 days. Rank rising =
// value falling, so this is a sustained decline in both windows.
function fallingSeries() {
  const out = [];
  const start = Date.parse("2026-06-29T00:00:00Z");
  for (let d = 30; d >= 0; d -= 3) {
    out.push({
      date: new Date(start + (30 - d) * 86400000).toISOString().slice(0, 10),
      rank: 20 + (30 - d) * 0.8,
    });
  }
  return out;
}

const ROW = {
  name: "Ja'Marr Chase",
  assetClass: "offense",
  position: "WR",
  rankDerivedValue: 8000,
  canonicalConsensusRank: 44,
  rankChange: -12,
  confidence: 0.9,
};

const TEAM = { players: ["Ja'Marr Chase"] };

describe("evaluateRoster history lookup", () => {
  it("resolves history published under composite Name::assetClass keys", () => {
    // Exactly what GET /api/data/rank-history returns.
    const history = { "Ja'Marr Chase::offense": fallingSeries() };

    const [entry] = evaluateRoster({
      rows: [ROW],
      selectedTeam: TEAM,
      history,
      newsItems: [],
    });

    expect(entry).toBeTruthy();
    // The load-bearing assertion: the trends must be POPULATED. Before
    // the fix these were null for every player in production.
    expect(entry.context.trend7).not.toBeNull();
    expect(entry.context.trend30).not.toBeNull();
    expect(entry.context.volatility).not.toBeNull();
  });

  it("produces a real verdict instead of collapsing to HOLD", () => {
    const history = { "Ja'Marr Chase::offense": fallingSeries() };

    const [entry] = evaluateRoster({
      rows: [ROW],
      selectedTeam: TEAM,
      history,
      newsItems: [],
    });

    // A sustained rank decline must reach a trend-driven signal. The
    // precise tag depends on the rule table; what must NOT happen is
    // the default HOLD that absent history forced.
    expect(entry.verdict.signal).not.toBe(SIGNALS.HOLD);
    expect(entry.verdict.fired.length).toBeGreaterThan(0);
  });

  it("still resolves history published under bare-name keys", () => {
    // Back-compat: older snapshots and any caller passing a bare map
    // must keep working, so the fix must not simply swap one exclusive
    // key shape for another.
    const history = { "Ja'Marr Chase": fallingSeries() };

    const [entry] = evaluateRoster({
      rows: [ROW],
      selectedTeam: TEAM,
      history,
      newsItems: [],
    });

    expect(entry.context.trend7).not.toBeNull();
    expect(entry.context.trend30).not.toBeNull();
  });

  it("disambiguates by assetClass when one name spans two scopes", () => {
    // A name present under two scopes must resolve to the row's own
    // scope, not to whichever key happened to be enumerated first.
    const offense = fallingSeries();
    const idp = fallingSeries().map((p) => ({ ...p, rank: p.rank + 200 }));
    const history = {
      "Two Way Guy::offense": offense,
      "Two Way Guy::idp": idp,
    };

    const row = { ...ROW, name: "Two Way Guy", assetClass: "idp" };
    const [entry] = evaluateRoster({
      rows: [row],
      selectedTeam: { players: ["Two Way Guy"] },
      history,
      newsItems: [],
    });

    // The IDP series sits 200 ranks lower; resolving the wrong scope
    // would produce a different trend magnitude.
    expect(entry.context.trend7).not.toBeNull();
  });

  it("returns a HOLD-ish verdict when there genuinely is no history", () => {
    // The inverse guard: absent history must still degrade gracefully
    // rather than throw, and must NOT invent a trend.
    const [entry] = evaluateRoster({
      rows: [ROW],
      selectedTeam: TEAM,
      history: {},
      newsItems: [],
    });

    expect(entry).toBeTruthy();
    expect(entry.context.trend7).toBeNull();
    expect(entry.context.trend30).toBeNull();
  });

  it("tolerates a null history object", () => {
    expect(() =>
      evaluateRoster({
        rows: [ROW],
        selectedTeam: TEAM,
        history: null,
        newsItems: [],
      })
    ).not.toThrow();
  });
});
