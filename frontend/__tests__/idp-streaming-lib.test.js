/**
 * lib/idp-streaming.js — the Weekly IDP Streaming display helpers.
 *
 * Pins: the request body never guesses a team, failures classify into named
 * states (the gate is `disabled`), backend codes become words, and a missing
 * number renders as its stated reason — never 0.  Display only.
 */
import { describe, expect, it } from "vitest";
import {
  bidText,
  buildStreamingRequest,
  classifyStreamingFailure,
  coverageText,
  dropClassBadge,
  dynastyChangeText,
  dynastyValueText,
  faabText,
  fmtSignedPoints,
  isStaleStreamingPayload,
  moveSummary,
  noMoveReasonText,
  playerNameIndex,
  postureContextText,
  solverStatusText,
  weekCellText,
} from "@/lib/idp-streaming";
import recommend from "./fixtures/idp-streaming/recommend.json";

describe("buildStreamingRequest", () => {
  it("carries no team when none is selected (the gate probe)", () => {
    expect(buildStreamingRequest({ leagueKey: "dynasty_main" })).toEqual({
      leagueKey: "dynasty_main",
    });
  });
  it("passes the user's choices through as numbers, and 'current week' as absent", () => {
    expect(
      buildStreamingRequest({
        leagueKey: "dynasty_main",
        ownerId: 42,
        week: "",
        horizonWeeks: 2,
        position: "LB",
        capacity: 3,
        dynastyBudget: "150",
      }),
    ).toEqual({
      leagueKey: "dynasty_main",
      teamOwnerId: "42",
      horizonWeeks: 2,
      position: "LB",
      capacity: 3,
      dynastyBudget: 150,
    });
    expect(buildStreamingRequest({ week: "11" }).week).toBe(11);
  });
});

describe("classifyStreamingFailure", () => {
  it("treats feature_disabled and an unregistered route as the gate", () => {
    expect(classifyStreamingFailure(503, { error: "feature_disabled", flag: "idp_streaming" })).toEqual({
      kind: "disabled",
      code: "feature_disabled",
      flag: "idp_streaming",
    });
    expect(classifyStreamingFailure(404, { detail: "Not Found" }).kind).toBe("disabled");
  });
  it("names every composer code in words", () => {
    for (const [status, code] of [
      [503, "projections_refused"],
      [503, "starter_slots_unknown"],
      [503, "no_rosters_loaded"],
      [400, "not_in_season"],
      [400, "unknown_team"],
      [400, "bad_dynastyBudget"],
    ]) {
      const f = classifyStreamingFailure(status, { error: code });
      expect(f.code).toBe(code);
      expect(f.kind).toBe(status >= 500 ? "unavailable" : "degraded");
      expect(f.message).not.toMatch(/Unavailable \(/);
    }
  });
  it("appends the stated reason of an unavailable build", () => {
    const f = classifyStreamingFailure(503, {
      error: "idp_streaming_unavailable",
      reason: "config_unreadable",
    });
    expect(f.message).toMatch(/configuration could not be read/);
  });
  it("401 is an auth state", () => {
    expect(classifyStreamingFailure(401, { error: "auth_required" }).kind).toBe("auth");
  });
});

describe("isStaleStreamingPayload", () => {
  it("refuses another team's or league's answer", () => {
    expect(isStaleStreamingPayload(recommend, { leagueKey: "dynasty_main", ownerId: "owner-me" })).toBe(false);
    expect(isStaleStreamingPayload(recommend, { ownerId: "someone-else" })).toBe(true);
    expect(isStaleStreamingPayload(recommend, { leagueKey: "dynasty_new" })).toBe(true);
    expect(isStaleStreamingPayload(null, {})).toBe(true);
  });
});

describe("formatting — missing is never zero", () => {
  it("states an unknown dynasty value rather than 0", () => {
    expect(dynastyValueText(null, "unknown_off_board")).toMatch(/off the dynasty board/);
    expect(dynastyValueText(1450, "priced")).toBe("1,450");
  });
  it("marks a partial dynasty change as partial", () => {
    const c = dynastyChangeText(recommend.plan.dynastyValueChange);
    expect(c.partial).toBe(true);
    expect(c.text).toMatch(/partial/);
    expect(dynastyChangeText({ value: -250, state: "complete" })).toEqual({ text: "-250", partial: false });
  });
  it("renders unprojected weeks as their state, not a number", () => {
    expect(weekCellText({ state: "unprojected", reason: "not_in_projection_set" })).toBe("— no projection");
    expect(weekCellText({ state: "projected", points: 10.5 })).toBe("10.5");
    expect(weekCellText({ state: "bye" })).toBe("Bye");
    expect(weekCellText(undefined)).toBe("—");
    expect(coverageText({ state: "unprojected" })).toBe("No source");
  });
  it("labels a $0 claim apart from an engine bid", () => {
    expect(bidText({ bid: 4, bidBasis: "faab_engine" })).toBe("$4");
    expect(bidText({ bid: 0, bidBasis: "off_board_zero_claim_only" })).toBe("$0 claim");
    expect(bidText({ bid: null })).toBe("Unavailable");
  });
  it("unknown FAAB is unknown, not $0", () => {
    expect(faabText({ state: "unknown_zero_claims_only", remaining: null }).value).toBe("Unknown");
    expect(faabText({ state: "known", remaining: 62 }).value).toBe("$62");
  });
  it("signs points", () => {
    expect(fmtSignedPoints(3.44)).toBe("+3.4");
    expect(fmtSignedPoints(-1)).toBe("-1.0");
    expect(fmtSignedPoints(null)).toBe(null);
  });
});

describe("words for backend states", () => {
  it("states a bounded solve with its proven gap", () => {
    expect(solverStatusText({ status: "bounded", boundGap: 6.5 }).label).toBe(
      "Bounded — best found, proven within 6.5 points",
    );
    expect(solverStatusText({ status: "optimal" }).label).toMatch(/Optimal/);
    expect(solverStatusText(null).label).toMatch(/unknown/);
  });
  it("explains every no-move reason in plain language", () => {
    for (const code of [
      "below_materiality",
      "no_droppable_player",
      "no_projected_free_agent",
      "no_move_improves_the_lineup",
    ]) {
      expect(noMoveReasonText(code)).not.toMatch(/_/);
    }
  });
  it("names moves from the payload's own boards", () => {
    const names = playerNameIndex(recommend);
    expect(moveSummary(recommend.plan, names)).toBe(
      "Add Nick Lambright, Tyrell Gaines · Drop Elijah Banks, Andre Whitfield",
    );
    expect(moveSummary({ adds: [], drops: [] }, names)).toBe("No move");
  });
  it("posture is context only", () => {
    expect(postureContextText(recommend.posture)).toEqual({
      label: "PUSH",
      note: "71% confidence · context only — never raises the dynasty budget",
    });
    expect(postureContextText({ context: null, unavailableReason: "league_bundle_not_warm" }).note).toBe(
      "posture bundle not built yet",
    );
  });
  it("drop classes map to badges", () => {
    expect(dropClassBadge("protected").label).toBe("Protected");
    expect(dropClassBadge("churn").label).toBe("Churn");
    expect(dropClassBadge(undefined).label).toBe("Unclassified");
  });
});

describe("gate probe endpoint", () => {
  it("is the same endpoint the panel fetches", async () => {
    const { IDP_STREAMING_GATE_ENDPOINT } = await import("@/components/waivers/useIdpStreamingGate");
    const { IDP_STREAMING_ENDPOINT } = await import("@/lib/idp-streaming");
    expect(IDP_STREAMING_GATE_ENDPOINT).toBe(IDP_STREAMING_ENDPOINT);
  });
});
