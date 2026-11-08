/**
 * lib/waiver-advisor.js — the Waiver Advisor's pure display helpers.
 *
 * Display only: every number comes from POST /api/waiver/advisor
 * (src/waivers/advisor.py).  These pin that the helpers never turn an absence
 * into a number, keep the market estimate apart from the team's ceiling, and
 * classify the gate (flag off / route missing) as "disabled".
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  WAIVER_ADVISOR_ENDPOINT,
  buildAdvisorRequest,
  classifyAdvisorFailure,
  expectedWinText,
  forcedDropText,
  isStaleAdvisorPayload,
  lineupText,
  maxRationalText,
  planOptimalityText,
  planStatusLabel,
  postureText,
  recommendedBidText,
  releaseText,
} from "@/lib/waiver-advisor";

describe("request + gate", () => {
  it("never guesses a team; the team-less body is the gate probe", () => {
    expect(buildAdvisorRequest({ leagueKey: "dynasty_main" })).toEqual({
      position: "ALL",
      leagueKey: "dynasty_main",
    });
    expect(buildAdvisorRequest({ ownerId: 42, position: "LB", limit: 10 })).toEqual({
      position: "LB",
      teamOwnerId: "42",
      limit: 10,
    });
    expect(WAIVER_ADVISOR_ENDPOINT).toBe("/api/waiver/advisor");
  });

  it("classifies the flag-off and unregistered-route answers as disabled", () => {
    expect(classifyAdvisorFailure(503, { error: "feature_disabled", flag: "waiver_advisor" }).kind).toBe(
      "disabled",
    );
    expect(classifyAdvisorFailure(404, { detail: "Not Found" }).kind).toBe("disabled");
    expect(classifyAdvisorFailure(404, null).kind).toBe("disabled");
  });

  it("states every other failure", () => {
    expect(classifyAdvisorFailure(400, { error: "team_required" })).toMatchObject({
      kind: "degraded",
      code: "team_required",
    });
    expect(classifyAdvisorFailure(401, {}).kind).toBe("auth");
    expect(classifyAdvisorFailure(503, { error: "waiver_advisor_unavailable" }).kind).toBe(
      "unavailable",
    );
  });

  it("drops a late answer for another league or team", () => {
    const p = { leagueKey: "a", team: { ownerId: "me" } };
    expect(isStaleAdvisorPayload(p, { leagueKey: "a", ownerId: "me" })).toBe(false);
    expect(isStaleAdvisorPayload(p, { leagueKey: "b", ownerId: "me" })).toBe(true);
    expect(isStaleAdvisorPayload(p, { leagueKey: "a", ownerId: "you" })).toBe(true);
  });
});

describe("missing is never zero", () => {
  it("withholds the market estimate and the ceiling in ceiling-only mode", () => {
    const faab = {
      state: "ceiling_only",
      recommendedBid: 4,
      expectedWinningBid: { state: "unavailable", reason: "ceiling_only_no_rival_model" },
      maxRationalBid: { state: "unavailable", value: null },
    };
    expect(expectedWinText(faab).text).toMatch(/^Unavailable/);
    expect(expectedWinText(faab).text).not.toContain("$0");
    expect(maxRationalText(faab)).toBe("Unavailable");
    expect(recommendedBidText(faab)).toBe("$4");
  });

  it("keeps the expected winning bid apart from the max rational bid", () => {
    const faab = {
      state: "market_aware",
      recommendedBid: 5,
      expectedWinningBid: { state: "estimated", low: 3, median: 7, high: 12 },
      maxRationalBid: { state: "available", value: 31 },
    };
    expect(expectedWinText(faab)).toMatchObject({ text: "$3–$12", median: "$7", estimated: true });
    expect(maxRationalText(faab)).toBe("$31");
  });

  it("renders a real $0 bid as $0", () => {
    expect(recommendedBidText({ state: "market_aware", recommendedBid: 0 })).toBe("$0");
  });

  it("states an unevaluated lineup and an unknown cap", () => {
    expect(lineupText({ state: "unavailable", reason: "starter_slots_unknown" })).toEqual({
      text: "Unknown — starter slots unknown",
      starts: null,
    });
    expect(lineupText({ state: "unavailable", reason: "candidate_position_unknown" })).toEqual({
      text: "Unknown — player's position unknown",
      starts: null,
    });
    expect(lineupText({ state: "evaluated", entersOptimalLineup: true, slot: "TE" }).text).toBe(
      "Starts (TE)",
    );
    expect(forcedDropText({ state: "unknown", requiresDrops: null }).known).toBe(false);
    expect(forcedDropText({ state: "exact", requiresDrops: false }).text).toBe("No drop needed");
    expect(
      forcedDropText({
        state: "partial",
        requiresDrops: true,
        forcedDropsAreUpperBound: true,
        forcedDrops: [{ name: "Deep WR" }],
      }).text,
    ).toBe("Up to: Deep WR");
  });

  it("names the plan status and release verbatim", () => {
    // A candidate row cannot see whether the plan was PROVEN optimal (Part 5).
    expect(planStatusLabel({ status: "in_plan" }).label).toBe("In plan");
    expect(planStatusLabel(null).label).toBe("Plan unavailable");
    expect(releaseText({ kind: "drop", name: "Weak TE" })).toBe("Drop Weak TE");
    expect(releaseText({ kind: "openSpot" })).toBe("Open roster spot");
  });

  it("calls a plan optimal only when the solver proved it (Part 5)", () => {
    expect(planOptimalityText({ provenOptimal: true, freeAgentsConsidered: 1 })).toEqual({
      label: "Optimal plan",
      proven: true,
      note: "proven optimal over the 1 free agent considered",
      badge: "Proven optimal over the 1 free agent considered",
    });
    expect(planOptimalityText({ provenOptimal: true }).note).toBe(
      "proven optimal over the free agents considered",
    );
    expect(planOptimalityText({ provenOptimal: false, freeAgentsConsidered: 9 })).toEqual({
      label: "Best plan found",
      proven: false,
      note: "not proven optimal",
    });
    // Missing proof is not proof.
    expect(planOptimalityText(undefined).label).toBe("Best plan found");
    expect(planOptimalityText({}).note).toBe("optimality not stated");
  });

  it("labels posture as context, and its absence by reason", () => {
    expect(postureText({ state: "available", label: "RETOOL", confidence: 0.61 })).toEqual({
      label: "RETOOL",
      note: "61% model share (uncalibrated) · context only",
    });
    expect(postureText({ state: "unavailable", reason: "league_bundle_not_warm" }).note).toBe(
      "posture bundle not built yet",
    );
  });
});

describe("no frontend engine", () => {
  it("the helpers and the page carry no bid or value arithmetic", () => {
    const root = process.cwd();
    for (const rel of ["lib/waiver-advisor.js", "app/waiver-advisor/page.jsx"]) {
      const src = readFileSync(path.join(root, rel), "utf8");
      expect(src).not.toMatch(/computeFaabHint|_compute_faab_bid|recommend\(/);
      expect(src).not.toMatch(/rankDerivedValue\s*[-+*/]/);
    }
  });

  // Superseded 2026-11-01 (owner directive, PR #2032): the page IS in the
  // nav now, but only behind server capabilities that fail closed — every
  // nav entry pointing at it must declare one.  Behaviour is pinned in
  // nav-capability-gating.test.js; this keeps the source-level guard.
  it("is linked from the navigation model only behind a capability", () => {
    const nav = readFileSync(path.join(process.cwd(), "lib/nav-model.js"), "utf8");
    const entries = nav.match(/\{\s*href:\s*"\/waiver-advisor[^"]*"[^}]*\}/g) || [];
    expect(entries.length).toBe(2);
    for (const entry of entries) expect(entry).toMatch(/capability:\s*"(waiverAdvisor|idpStreaming)"/);
  });
});
