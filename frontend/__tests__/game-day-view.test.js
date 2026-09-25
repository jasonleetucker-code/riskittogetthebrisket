/**
 * lib/game-day-view — the Game Day presentation helpers.
 *
 * They format, label and SELECT backend fields; they never compute a
 * probability, lineup, score, margin or leverage. These tests pin that on
 * real `/api/matchup/intel` payloads generated from the U4 replay
 * (`tests/game_day/ui_payloads.py`): every number a selector surfaces is
 * the backend's own value, and missing stays missing.
 */
import { describe, expect, it } from "vitest";

import {
  couldEnterPlayers,
  displaceablePlayers,
  formatLineupPct,
  formatPct,
  formatPoints,
  formatAge,
  freshnessLine,
  freshnessReasonText,
  medianUnverifiedText,
  gamePhaseKind,
  gameStatusText,
  leverageGames,
  marginText,
  pendingForecast,
  reasonText,
  slotLabel,
  whatMattersNow,
  withheldProbabilityReasons,
} from "@/lib/game-day-view";

import PREGAME from "./fixtures/game-day/pregame.json";
import HALFTIME from "./fixtures/game-day/halftime.json";
import OVERTIME from "./fixtures/game-day/overtime.json";
import WEEK_FINAL from "./fixtures/game-day/week-final.json";
import MIXED from "./fixtures/game-day/mixed-slate.json";
import FEED_DOWN from "./fixtures/game-day/live-feed-down.json";
import STALE from "./fixtures/game-day/stale.json";
import PENDING from "./fixtures/game-day/pending.json";

describe("formatters keep missing distinct from zero", () => {
  it.each([null, undefined, Number.NaN, "3"])("formats %s as null, never 0", (v) => {
    expect(formatPoints(v)).toBeNull();
    expect(formatPct(v)).toBeNull();
    expect(formatLineupPct(v)).toBeNull();
    expect(marginText(v, "A", "B")).toBeNull();
  });

  it("formats real zeros and negatives as numbers", () => {
    expect(formatPoints(0)).toBe("0.0");
    expect(formatPoints(-1.25)).toBe("-1.3");
    expect(formatPct(0)).toBe("0.0%");
  });

  it("keeps the open ends of a lineup chance honest", () => {
    expect(formatLineupPct(0)).toBe("0%");
    expect(formatLineupPct(0.4)).toBe("<1%");
    expect(formatLineupPct(99.6)).toBe(">99%");
    expect(formatLineupPct(100)).toBe("100%");
    expect(formatLineupPct(41.6)).toBe("42%");
  });

  it("names the margin leader from the backend's sign, magnitude verbatim", () => {
    expect(marginText(29.03, "Team 8", "Team 10")).toBe("Team 8 by 29.0");
    expect(marginText(-4.5, "Team 8", "Team 10")).toBe("Team 10 by 4.5");
    expect(marginText(0, "Team 8", "Team 10")).toBe("Dead even");
  });

  it("humanizes slots instead of printing implementation names", () => {
    expect(slotLabel("SUPER_FLEX")).toBe("SF");
    expect(slotLabel("FLEX")).toBe("FLEX");
  });
});

describe("game status from observed phase / period / clock", () => {
  const game = (over) => ({ awayTeam: "ATL", homeTeam: "GB", kickoffAt: 1790295300, ...over });
  it.each([
    [{ phase: "IN_PROGRESS", period: 2, clockSeconds: 578 }, "Q2 9:38"],
    [{ phase: "IN_PROGRESS", period: 5, clockSeconds: 480 }, "OT 8:00"],
    [{ phase: "END_PERIOD", period: 1 }, "End Q1"],
    [{ phase: "HALFTIME", period: 2 }, "Halftime"],
    [{ phase: "FINAL", period: 4 }, "Final"],
    [{ phase: "DELAYED" }, "Delayed"],
    [{ phase: "POSTPONED" }, "Postponed"],
    [{ phase: "UNKNOWN" }, "Status unknown"],
    [{ phase: null, state: "unknown" }, "Status unknown"],
    [{ phase: "HALFTIME", remainingReason: "stale_live_state" }, "Halftime · feed stale"],
  ])("%j -> %s", (over, text) => {
    expect(gameStatusText(game(over))).toBe(text);
  });

  it("classifies games for emphasis without inventing a state", () => {
    expect(gamePhaseKind({ phase: "HALFTIME" })).toBe("live");
    expect(gamePhaseKind({ phase: null, state: "not_started" })).toBe("upcoming");
    expect(gamePhaseKind({ phase: "POSTPONED" })).toBe("halted");
    expect(gamePhaseKind({ phase: null, state: "unknown" })).toBe("unknown");
  });

  it("names every backend reason in words", () => {
    expect(reasonText("overtime")).toBe("Overtime");
    expect(reasonText("overtime_possible")).toMatch(/overtime possible/);
    expect(reasonText("unknown_status:STATUS_WEIRD")).toBe("Unrecognized game status");
  });
});

describe("withheld probability reasons", () => {
  it("names overtime and the game it is in", () => {
    expect(withheldProbabilityReasons(OVERTIME)).toEqual([
      "Overtime in ATL @ GB: win chance paused.",
    ]);
  });

  it("names an unobserved game and why", () => {
    const [line] = withheldProbabilityReasons(FEED_DOWN);
    expect(line).toMatch(/^Game status unknown for ATL @ GB — the live game feed is unavailable/);
  });

  it("is silent when the probability is available or the week is final", () => {
    expect(withheldProbabilityReasons(HALFTIME)).toEqual([]);
    expect(withheldProbabilityReasons(WEEK_FINAL)).toEqual([]);
  });
});

describe("selectors pass backend values through", () => {
  it("could-enter players are outside the lineup, strictly between 0 and 100, backend-ordered", () => {
    const rows = couldEnterPlayers(MIXED.team, MIXED.mode);
    const counting = new Set(MIXED.team.actualLineup.slots.map((s) => s.playerId));
    expect(rows.length).toBeGreaterThan(0);
    for (const p of rows) {
      expect(counting.has(p.playerId)).toBe(false);
      expect(p.finalLineupPct).toBeGreaterThan(0);
      expect(p.finalLineupPct).toBeLessThan(100);
      // The very object the backend published, not a derived copy.
      expect(MIXED.team.players).toContain(p);
    }
    const pcts = rows.map((p) => p.finalLineupPct);
    expect(pcts).toEqual([...pcts].sort((a, b) => b - a));
  });

  it("pregame could-enter is measured against the illustrative lineup", () => {
    const rows = couldEnterPlayers(PREGAME.team, "pregame");
    const illustrative = new Set(PREGAME.team.expectedLineup.slots.map((s) => s.playerId));
    for (const p of rows) expect(illustrative.has(p.playerId)).toBe(false);
  });

  it("displaceable players are counting now and below 100", () => {
    const rows = displaceablePlayers(MIXED.team, "live");
    const counting = new Set(MIXED.team.actualLineup.slots.map((s) => s.playerId));
    for (const p of rows) {
      expect(counting.has(p.playerId)).toBe(true);
      expect(p.finalLineupPct).toBeLessThan(100);
    }
    expect(displaceablePlayers(PREGAME.team, "pregame")).toEqual([]);
  });

  it("key games are the backend's leverage rows in the backend's order", () => {
    const rows = leverageGames(HALFTIME, 3);
    const backend = HALFTIME.team.outcome.gameLeverage.filter((r) => r.leverage !== null);
    expect(rows.map((r) => r.gameId)).toEqual(backend.slice(0, 3).map((r) => r.gameId));
    expect(rows[0].winPctWhenGameFavorsTeam).toBe(backend[0].winPctWhenGameFavorsTeam);
  });

  it("what matters now has 1-5 items, all quoting backend numbers", () => {
    for (const p of [PREGAME, HALFTIME, MIXED]) {
      const items = whatMattersNow(p);
      expect(items.length).toBeGreaterThanOrEqual(1);
      expect(items.length).toBeLessThanOrEqual(5);
    }
    const [first] = whatMattersNow(HALFTIME);
    const lev = HALFTIME.team.outcome.gameLeverage.find((r) => r.leverage !== null);
    expect(first.detail).toContain(formatPct(lev.winPctWhenGameFavorsTeam));
    expect(first.detail).toContain(formatPct(lev.winPctWhenGameFavorsOpponent));
    expect(whatMattersNow(WEEK_FINAL)).toEqual([]);
  });

  it("a withheld week publishes no leverage, so no key game is invented", () => {
    expect(leverageGames(OVERTIME)).toEqual([]);
  });
});

describe("freshness line (the U5 collector block)", () => {
  const without = (p) => {
    const out = JSON.parse(JSON.stringify(p));
    delete out.freshness;
    return out;
  };

  it("names a current generation with its as-of time and age", () => {
    expect(HALFTIME.freshness.state).toBe("current");
    const line = freshnessLine(HALFTIME);
    expect(line.text).toMatch(/^Current · as of \d{1,2}:\d{2} [AP]M E[SD]T \(20 s old\)$/);
    expect(line.warn).toBe(false);
  });

  it("flags a partial state with the failed source (ESPN 403), never hiding it", () => {
    expect(FEED_DOWN.freshness.state).toBe("partial");
    const line = freshnessLine(FEED_DOWN);
    expect(line.text).toMatch(/^Partial · as of .* · live game feed unavailable$/);
    expect(line.warn).toBe(true);
  });

  it("flags a stale generation with its true age against the budget", () => {
    expect(STALE.freshness.state).toBe("stale");
    const line = freshnessLine(STALE);
    expect(line.stale).toBe(true);
    expect(line.text).toMatch(/^Stale · as of .*\(2 h old\) · past its 3 min freshness budget$/);
  });

  it("names a degraded, background-computed answer and a running refresh", () => {
    const p = JSON.parse(JSON.stringify(HALFTIME));
    p.freshness = { ...p.freshness, state: "degraded", reasons: ["no_collector_generation"], refreshInProgress: true };
    const line = freshnessLine(p);
    expect(line.text).toMatch(/^Degraded · .* not published this week; computed in the background · refresh running$/);
    expect(line.warn).toBe(true);
  });

  it("falls back to the lineage's observed live time when the block is absent", () => {
    expect(freshnessLine(without(HALFTIME)).text).toMatch(/^Live game status observed \d/);
    expect(freshnessLine(without(FEED_DOWN))).toEqual({
      text: "Live game feed unavailable — game status from the schedule only",
      warn: true,
      stale: false,
    });
    expect(freshnessLine(without(PREGAME)).text).toMatch(/^Projections as of /);
  });

  it("words every backend reason, and shows an unknown one verbatim", () => {
    expect(freshnessReasonText("payload_age_7200s_exceeds_180s")).toBe(
      "2 h old, past its 3 min freshness budget",
    );
    expect(freshnessReasonText("weekly_projections:no_usable_fetch")).toBe(
      "weekly projections unavailable (no_usable_fetch)",
    );
    expect(freshnessReasonText("last_collector_tick_failed:Timeout")).toMatch(/last run failed \(Timeout\)/);
    expect(freshnessReasonText("something_new")).toBe("something new");
    expect(freshnessReasonText("generation_pending")).toMatch(/being computed in the background/);
    expect(freshnessReasonText("generation_failed:Timeout")).toMatch(/run failed \(Timeout\); it will be retried/);
    expect(freshnessReasonText("previous_attempt_failed:Boom")).toMatch(/earlier forecast run failed \(Boom\)/);
    expect(freshnessReasonText("background_refresh_failed:Boom")).toMatch(/showing the last answer/);
    expect(freshnessReasonText("background_compute_capacity_exhausted")).toMatch(/server is busy/);
    expect(freshnessReasonText("stat_correction_pending_host")).toMatch(/host has not applied/);
    expect(freshnessReasonText("weekly_projections:pending")).toBe(
      "weekly projections not read yet (forecast computing)",
    );
    expect(formatAge(20)).toBe("20 s");
    expect(formatAge(null)).toBeNull();
  });

  it("names an unverified median rule", () => {
    expect(medianUnverifiedText("odd_team_count_host_rule_unverified")).toMatch(/odd team count/);
    expect(medianUnverifiedText(null)).toMatch(/not verified/);
  });
});

describe("pending forecast (Game Day G: cold request)", () => {
  it("is not a withheld chance: real scores, forecast computing, one running compute", () => {
    expect(PENDING.probabilityState).toBe("PENDING");
    expect(PENDING.freshness.state).toBe("pending");
    expect(withheldProbabilityReasons(PENDING)).toEqual([]);
    const pending = pendingForecast(PENDING);
    expect(pending.failed).toBe(false);
    expect(pending.title).toBe("Computing the forecast");
    expect(pending.text).toMatch(/Scores and lineups shown are real/);
    // Forecast fields are withheld as null — never zero.
    expect(PENDING.team.outcome).toBeNull();
    expect(PENDING.team.scoreNow.bestBallFromBankedPoints).toBeGreaterThan(0);
    const line = freshnessLine(PENDING);
    expect(line.text).toMatch(
      /^Computing forecast · as of .* · forecast being computed in the background · refresh running$/,
    );
    expect(line.warn).toBe(true);
    expect(line.stale).toBe(false);
  });

  it("says a failed compute failed and will be retried", () => {
    const p = JSON.parse(JSON.stringify(PENDING));
    p.freshness = { ...p.freshness, state: "failed", reasons: ["generation_failed:Timeout"] };
    p.freshness.backgroundCompute = { ...p.freshness.backgroundCompute, state: "failed" };
    const pending = pendingForecast(p);
    expect(pending.failed).toBe(true);
    expect(pending.title).toBe("Forecast failed");
    expect(freshnessLine(p).text).toMatch(/^Forecast failed · .* the forecast run failed \(Timeout\)/);
  });

  it("is null for a computed payload", () => {
    expect(pendingForecast(HALFTIME)).toBeNull();
    expect(pendingForecast(WEEK_FINAL)).toBeNull();
  });
});
