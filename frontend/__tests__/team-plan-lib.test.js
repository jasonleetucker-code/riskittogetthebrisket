/**
 * lib/team-plan.js — the home "This week" panel's display helpers.
 *
 * Fixtures are produced by the REAL composer (src/api/team_plan.py) and pinned
 * by tests/api/test_team_plan_frontend_fixtures.py, so these tests read the
 * actual contract.  Pins: actions keep the payload's order (no client
 * re-rank); every unavailable section reads "not available yet (reason)";
 * a missing number is never 0; the incomplete state names what was not
 * assessed; roster staleness is stated.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  actionEvidence,
  actionSubjectText,
  actionUncertainty,
  buildTeamPlanView,
  formatNumber,
  notAvailableText,
  planActions,
  planContextRows,
  planStateView,
  reasonText,
  rosterFreshnessView,
} from "@/lib/team-plan";

const load = (name) =>
  JSON.parse(
    fs.readFileSync(path.resolve(__dirname, `fixtures/team-plan/${name}.json`), "utf-8"),
  );
const ACTIONS = load("plan-actions");
const INCOMPLETE = load("plan-incomplete-stale");
const DO_NOTHING = load("plan-do-nothing");

const contextText = (plan, key) => planContextRows(plan).find((r) => r.key === key).text;
// A standalone 0 or $0 anywhere in a rendered string.
const STANDALONE_ZERO = /(?<![\w.,$])\$?0(?![\w.,])/;

describe("actions", () => {
  it("keep the payload's order and backend rank (no client re-rank)", () => {
    const rows = planActions(ACTIONS);
    expect(rows.map((r) => [r.rank, r.kind])).toEqual(
      ACTIONS.actions.map((a) => [a.rank, a.kind]),
    );
    expect(rows.map((r) => r.kind)).toEqual([
      "buy_target",
      "sell_high",
      "waiver_move",
      "aging_asset_risk",
      "buy_target",
      "waiver_move",
      "waiver_move",
    ]);
  });

  it("does not re-sort even when the payload order disagrees with rank", () => {
    const reversed = { ...ACTIONS, actions: [...ACTIONS.actions].reverse() };
    expect(planActions(reversed).map((r) => r.rank)).toEqual([7, 6, 5, 4, 3, 2, 1]);
  });

  it("states each kind's subject from the owner's subject verbatim", () => {
    const [buy, sell, waiver, aging] = ACTIONS.actions;
    expect(actionSubjectText(buy)).toBe("Player t1 (WR)");
    expect(actionSubjectText(sell)).toBe("Give A for B");
    expect(actionSubjectText(waiver)).toBe("Add FA w1 (LB), release Rel (LB)");
    expect(actionSubjectText(aging)).toBe("QB room is older than league peers");
    expect(
      actionSubjectText({ kind: "waiver_move", subject: { add: { name: "X" }, release: { kind: "openSpot" } } }),
    ).toBe("Add X, into an open roster spot");
    expect(actionSubjectText(DO_NOTHING.actions[0])).toBe("Hold: no move cleared any assessed check");
  });

  it("reads unmeasured uncertainty as 'not measured', never 0", () => {
    const buy = actionUncertainty(ACTIONS.actions[0]);
    expect(buy).toEqual([
      { key: "confidence", label: "Confidence", text: "0.5" },
      { key: "marketEdge", label: "Market edge", text: "not measured" },
      { key: "availability", label: "Availability", text: "not measured" },
    ]);
    const aging = actionUncertainty(ACTIONS.actions[3]);
    expect(aging.find((u) => u.key === "coverage").text).toBe("3 of 3 players aged");
    expect(aging.find((u) => u.key === "ruleStatus").text).toBe("PRIOR");
  });

  it("keeps evidence verbatim with null as 'not available' and skips nested objects", () => {
    const waiver = actionEvidence(ACTIONS.actions[2]);
    expect(waiver.map((e) => e.key)).toEqual(["gain", "relativeGap", "material", "standsAlone"]);
    expect(waiver.find((e) => e.key === "gain").text).toBe("967");
    expect(waiver.find((e) => e.key === "material").text).toBe("yes");
    const withNull = actionEvidence({ evidence: { lineupGain: null, notes: [], signals: ["a", "b"] } });
    expect(withNull).toEqual([
      { key: "lineupGain", label: "Lineup gain", text: "not available" },
      { key: "notes", label: "Notes", text: "none" },
      { key: "signals", label: "Signals", text: "a, b" },
    ]);
  });
});

describe("context rows", () => {
  it("render each owner's answer", () => {
    expect(contextText(ACTIONS, "posture")).toBe("PUSH (a classification, not a verdict)");
    expect(contextText(ACTIONS, "strength")).toBe("Rank 2 of 4");
    expect(contextText(ACTIONS, "weakness")).toBe("TE (high)");
    expect(contextText(ACTIONS, "age")).toBe("26.4 (value-weighted)");
    expect(contextText(ACTIONS, "draft")).toBe("2027 class $100; all classes $300");
    expect(contextText(ACTIONS, "rosters")).toBe("Current, fetched 1 hour ago");
  });

  it("show unavailable sections as 'not available yet (reason)'", () => {
    expect(contextText(INCOMPLETE, "posture")).toBe(
      "not available yet (the league analysis has not been built yet)",
    );
    expect(contextText(INCOMPLETE, "draft")).toBe(
      "not available yet (the draft-capital board has not been built yet)",
    );
    expect(notAvailableText("some_new_code")).toBe("not available yet (some new code)");
    expect(reasonText(null)).toBe("no reason given");
  });

  it("never render a missing number as 0", () => {
    expect(contextText(INCOMPLETE, "strength")).toBe("league rank not available");
    expect(contextText(INCOMPLETE, "age")).toBe("not available (unmeasured)");
    for (const row of planContextRows(INCOMPLETE)) {
      expect(row.text, row.key).not.toMatch(STANDALONE_ZERO);
    }
    const unpriced = {
      ...ACTIONS,
      draftCapital: {
        ...ACTIONS.draftCapital,
        teamTotalsState: "unavailable",
        teamTotalsReason: "upcoming_class_unpriced",
        upcomingClass: { ...ACTIONS.draftCapital.upcomingClass, auctionDollars: null },
        allYears: { ...ACTIONS.draftCapital.allYears, auctionDollars: null },
      },
    };
    const draft = contextText(unpriced, "draft");
    expect(draft).toMatch(/^Auction budgets unavailable: the upcoming draft class has no priced picks/);
    // The one reader's copy says "Not shown as $0." — no value is shown as $0.
    expect(draft.replace("Not shown as $0.", "")).not.toMatch(STANDALONE_ZERO);
  });

  it("read weak spots from the owner's urgent list only", () => {
    const withWeakness = (weakness) => ({
      ...ACTIONS,
      teamWeakness: { ...ACTIONS.teamWeakness, weakness },
    });
    expect(contextText(withWeakness({ urgentPositions: [], needs: [] }), "weakness")).toBe(
      "none urgent",
    );
    // No urgent list published: unknown, not "none" (no client-side level cut).
    expect(
      contextText(withWeakness({ needs: [{ position: "TE", level: "critical" }] }), "weakness"),
    ).toBe("not available");
  });

  it("names unavailable pick ownership beside draft capital", () => {
    const plan = {
      ...ACTIONS,
      draftCapital: {
        ...ACTIONS.draftCapital,
        pickOwnership: { state: "unavailable", reason: "traded_picks_fetch_failed" },
      },
    };
    expect(contextText(plan, "draft")).toMatch(/; pick ownership unavailable$/);
  });

  it("report an unknown roster age without a number", () => {
    const plan = { ...ACTIONS, rosterFreshness: { state: "unknown", ageHours: null, source: null } };
    expect(rosterFreshnessView(plan)).toMatchObject({ state: "unknown", unknown: true, ageText: null });
    expect(contextText(plan, "rosters")).toBe("Freshness unknown");
  });
});

describe("plan state", () => {
  it("names what an incomplete plan did not assess", () => {
    const view = planStateView(INCOMPLETE);
    expect(view.incomplete).toBe(true);
    expect(view.unassessed.map((u) => `${u.kindLabel}: ${u.text}`)).toEqual([
      "Buy target: not available yet (trade targets have not been built for this team yet)",
      "Waiver move: not available yet (Perfect Waivers has not run for this team recently)",
      "Aging room: only partly assessed (DB: age versus the league median could not be measured)",
    ]);
    expect(view.notAssessable.map((n) => n.kindLabel)).toEqual(["Pick move"]);
  });

  it("states stale rosters", () => {
    const fresh = rosterFreshnessView(INCOMPLETE);
    expect(fresh).toMatchObject({ state: "stale", stale: true });
    expect(fresh.text).toBe("Stale, fetched 30.5 hours ago, from the last good snapshot");
  });

  it("carries do_nothing as its own state", () => {
    const view = buildTeamPlanView(DO_NOTHING);
    expect(view.planState.doNothing).toBe(true);
    expect(view.actions.map((a) => a.kindLabel)).toEqual(["No move"]);
    expect(view.actions[0].uncertainty).toEqual([
      { key: "notAssessed", label: "Not assessed", text: "Pick move" },
    ]);
  });
});

describe("formatNumber", () => {
  it("formats without inventing a value", () => {
    expect(formatNumber(null)).toBeNull();
    expect(formatNumber(undefined)).toBeNull();
    expect(formatNumber(Number.NaN)).toBeNull();
    expect(formatNumber("5")).toBeNull();
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(30000)).toBe("30,000");
    expect(formatNumber(0.4652)).toBe("0.47");
    expect(formatNumber(0.004)).toBe("0.0040");
  });
});

describe("lazy chunk boundary", () => {
  const src = (rel) => fs.readFileSync(path.resolve(__dirname, "..", rel), "utf-8");

  it("keeps lib/team-plan.js and the panel body out of the home chunk", () => {
    // The hook and the mount wrapper are in the home chunk; the body and this
    // lib load only after a plan arrives (flag off: never).
    expect(src("components/terminal/useTeamPlan.js")).not.toMatch(
      /from\s+["'][^"']*team-plan["']/,
    );
    const wrapper = src("components/terminal/ThisWeekPanel.jsx");
    expect(wrapper).not.toMatch(/from\s+["'][^"']*team-plan["']/);
    expect(wrapper).not.toMatch(/import\s+ThisWeekPlan\s+from/);
    expect(wrapper).toMatch(/lazy\(\(\)\s*=>\s*import\(["']\.\/ThisWeekPlan["']\)\)/);
    expect(wrapper).not.toMatch(/from\s+["']next\/dynamic["']/);
    expect(src("components/terminal/TerminalLayout.jsx")).toMatch(/<ThisWeekPanel\s*\/>/);
  });
});
