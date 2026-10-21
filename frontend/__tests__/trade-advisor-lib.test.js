/**
 * Brisket Trade Advisor — the pure builder state (design §8.3, spec §4.5,
 * §5.2).
 *
 * The reducer holds identities, labels and roster ids only; these tests pin
 * every action, the 3→2 retarget, the disabled-team rule, the client
 * readiness rules that mirror the server's public validation
 * (send_and_receive for every team count, destinations, maxLegs), the
 * request shape of the §4.3 contract, the perspective switch over one
 * response, and the URL-over-session restore precedence.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  advisorReducer,
  canAnalyze,
  filterAssets,
  initialAdvisorState,
  positionsPresent,
  restoreAdvisorState,
  serializeAdvisorState,
  toAnalyzeRequest,
  tradeIssues,
  tradeKey,
  tradeSummary,
} from "@/lib/trade-advisor";

const FIX = path.resolve(__dirname, "fixtures", "trade-advisor");
const fixture = (name) => JSON.parse(fs.readFileSync(path.join(FIX, `${name}.json`), "utf8"));
const TEAMS = fixture("teams.success").teams;
const MINE = fixture("assets.position_alpha").assets;
const THEIRS = fixture("assets.pick-ownership-unavailable").assets;
// A sanitized four-team result (the shape lib/trade-advisor-client returns).
const FOUR = (() => {
  const d = fixture("analyze.four-team-mixed");
  return {
    overall: d.overall,
    teams: d.teams,
    trade: d.trade,
    perspectiveRosterId: d.perspectiveRosterId,
    teamCount: 4,
    generation: d.generation,
  };
})();
const asset = (list, id) => list.find((a) => a.id === id);

function run(actions, start = initialAdvisorState()) {
  return actions.reduce((s, a) => advisorReducer(s, a), start);
}

const twoTeam = () =>
  run([
    { type: "SET_SLOT", index: 0, rosterId: 1 },
    { type: "SET_SLOT", index: 1, rosterId: 2 },
  ]);

describe("reducer", () => {
  it("starts as an empty two-team builder", () => {
    const s = initialAdvisorState();
    expect(s).toMatchObject({ phase: "build", teamCount: 2, slots: [null, null], legs: [], result: null });
  });

  it("refuses a team that already occupies another slot (no swap)", () => {
    const s = twoTeam();
    expect(advisorReducer(s, { type: "SET_SLOT", index: 1, rosterId: 1 })).toBe(s);
    expect(advisorReducer(s, { type: "SET_SLOT", index: 0, rosterId: 2 })).toBe(s);
  });

  it("adds an asset once, routes it to the other team in a two-team trade, and removes it", () => {
    let s = twoTeam();
    s = advisorReducer(s, { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 });
    expect(s.legs).toEqual([{ id: "p:101", kind: "player", label: "Alpha Quarterback", from: 1, to: 2 }]);
    expect(advisorReducer(s, { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 })).toBe(s);
    s = advisorReducer(s, { type: "ADD_ASSET", asset: asset(MINE, "pick:main:2027:r1:o1"), from: 1 });
    expect(s.legs[1]).toMatchObject({ kind: "pick", from: 1, to: 2 });
    s = advisorReducer(s, { type: "REMOVE_ASSET", id: "p:101" });
    expect(s.legs.map((l) => l.id)).toEqual(["pick:main:2027:r1:o1"]);
  });

  it("refuses an asset from a team that is not in the trade", () => {
    const s = twoTeam();
    expect(advisorReducer(s, { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 3 })).toBe(s);
  });

  it("3 teams: new legs are unrouted until a destination is chosen; never to the origin", () => {
    let s = run(
      [
        { type: "SET_TEAM_COUNT", count: 3 },
        { type: "SET_SLOT", index: 2, rosterId: 3 },
      ],
      twoTeam(),
    );
    s = advisorReducer(s, { type: "ADD_ASSET", asset: asset(MINE, "p:103"), from: 1 });
    expect(s.legs[0].to).toBeNull();
    expect(advisorReducer(s, { type: "SET_DESTINATION", id: "p:103", to: 1 })).toBe(s);
    expect(advisorReducer(s, { type: "SET_DESTINATION", id: "p:103", to: 9 })).toBe(s);
    s = advisorReducer(s, { type: "SET_DESTINATION", id: "p:103", to: 3 });
    expect(s.legs[0].to).toBe(3);
  });

  it("3 → 2 removes the dropped team's legs (with a notice) and retargets every survivor", () => {
    let s = run(
      [
        { type: "SET_TEAM_COUNT", count: 3 },
        { type: "SET_SLOT", index: 2, rosterId: 3 },
      ],
      twoTeam(),
    );
    s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:103"), from: 1 },
        { type: "SET_DESTINATION", id: "p:103", to: 3 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
        { type: "SET_DESTINATION", id: "p:202", to: 1 },
        { type: "ADD_ASSET", asset: { id: "p:302", kind: "player", label: "Charlie Back" }, from: 3 },
        { type: "SET_DESTINATION", id: "p:302", to: 2 },
      ],
      s,
    );
    s = advisorReducer(s, { type: "SET_TEAM_COUNT", count: 2 });
    expect(s.slots).toEqual([1, 2]);
    expect(s.legs.map((l) => [l.id, l.from, l.to])).toEqual([
      ["p:103", 1, 2],
      ["p:202", 2, 1],
    ]);
    expect(s.notice).toEqual({ kind: "removed", labels: ["Charlie Back"] });
  });

  it("2 → 4 keeps legs and pads empty slots; team count is clamped to 2..the server's max", () => {
    let s = advisorReducer(twoTeam(), { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 });
    s = advisorReducer(s, { type: "SET_TEAM_COUNT", count: 4, max: 4 });
    expect(s.slots).toEqual([1, 2, null, null]);
    expect(s.legs[0].to).toBe(2);
    expect(advisorReducer(s, { type: "SET_TEAM_COUNT", count: 9, max: 4 }).teamCount).toBe(4);
    expect(advisorReducer(s, { type: "SET_TEAM_COUNT", count: 1, max: 4 }).teamCount).toBe(2);
    // The cap is the server's limits.maxTeams, not a constant: a league
    // capped at 3 never shows a fourth slot; a larger cap is honoured.
    expect(advisorReducer(twoTeam(), { type: "SET_TEAM_COUNT", count: 4, max: 3 }).teamCount).toBe(3);
    const six = advisorReducer(twoTeam(), { type: "SET_TEAM_COUNT", count: 6, max: 6 });
    expect(six.slots).toHaveLength(6);
  });

  it("changing the partner drops the old partner's assets and retargets yours", () => {
    let s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
      ],
      twoTeam(),
    );
    s = advisorReducer(s, { type: "SET_SLOT", index: 1, rosterId: 3 });
    expect(s.legs).toEqual([{ id: "p:101", kind: "player", label: "Alpha Quarterback", from: 1, to: 3 }]);
    expect(s.notice.labels).toEqual(["Bravo Runner"]);
  });

  it("any edit while a result is showing returns to the builder and clears it", () => {
    let s = run([
      { type: "SET_SLOT", index: 0, rosterId: 1 },
      { type: "SET_SLOT", index: 1, rosterId: 2 },
      { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
      { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
      { type: "SUBMIT" },
    ]);
    expect(s.phase).toBe("submitting");
    s = advisorReducer(s, { type: "RESULT", result: { ...FOUR, teams: FOUR.teams.slice(0, 2) } });
    expect(s.phase).toBe("result");
    const edited = advisorReducer(s, { type: "REMOVE_ASSET", id: "p:101" });
    expect(edited).toMatchObject({ phase: "build", result: null });
    expect(advisorReducer(s, { type: "EDIT" })).toMatchObject({ phase: "build", result: null, legs: s.legs });
    expect(advisorReducer(s, { type: "NEW_TRADE" })).toMatchObject({ phase: "build", legs: [], slots: [1, 2] });
    expect(advisorReducer(s, { type: "START_OVER" })).toEqual(initialAdvisorState());
  });

  it("a 409 flags the moved assets; removing one clears its flag", () => {
    let s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:201"), from: 2 },
        { type: "SUBMIT" },
        { type: "FAIL", error: { kind: "stale", assetIds: ["p:201"] } },
      ],
      twoTeam(),
    );
    expect(s.phase).toBe("build");
    expect(s.staleIds).toEqual(["p:201"]);
    s = advisorReducer(s, { type: "REMOVE_ASSET", id: "p:201" });
    expect(s.staleIds).toEqual([]);
  });
});

describe("perspective switch (one response, no new request)", () => {
  const withResult = () => {
    let s = run([
      { type: "SET_TEAM_COUNT", count: 4, max: 4 },
      { type: "SET_SLOT", index: 0, rosterId: 2 },
      { type: "SET_SLOT", index: 1, rosterId: 1 },
      { type: "SET_SLOT", index: 2, rosterId: 3 },
      { type: "SET_SLOT", index: 3, rosterId: 4 },
    ]);
    return advisorReducer(s, { type: "RESULT", result: FOUR });
  };

  it("opens on the selected team and switches to any participating team", () => {
    let s = withResult();
    expect(s.view).toBe(2);
    s = advisorReducer(s, { type: "SET_VIEW", rosterId: 4 });
    expect(s.view).toBe(4);
    expect(s.result).toBe(FOUR); // the same response; nothing recomputed
    expect(advisorReducer(s, { type: "SET_VIEW", rosterId: 9 })).toBe(s); // not in the trade
    expect(advisorReducer(s, { type: "EDIT" }).view).toBeNull();
  });

  it("does nothing without a result", () => {
    const s = twoTeam();
    expect(advisorReducer(s, { type: "SET_VIEW", rosterId: 1 })).toBe(s);
  });
});

describe("readiness (mirrors the server's validation; the server still enforces it)", () => {
  it("asks for the teams first, then for an asset", () => {
    expect(tradeIssues(initialAdvisorState()).map((i) => i.message)).toEqual([
      "Choose your team.",
      "Choose a trade partner.",
    ]);
    expect(tradeIssues(twoTeam(), TEAMS).map((i) => i.code)).toEqual(["empty_trade"]);
  });

  it("two teams: each team must send at least one asset (no gift trades)", () => {
    let s = advisorReducer(twoTeam(), { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 });
    expect(tradeIssues(s, TEAMS).map((i) => i.code)).toEqual(["team_receives_nothing", "team_sends_nothing"]);
    expect(canAnalyze(s, TEAMS)).toBe(false);
    s = advisorReducer(s, { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 });
    expect(tradeIssues(s, TEAMS)).toEqual([]);
    expect(canAnalyze(s, TEAMS)).toBe(true);
    expect(canAnalyze({ ...s, phase: "submitting" }, TEAMS)).toBe(false);
  });

  it("3+ teams: every team both sends and receives, and every asset has a destination", () => {
    let s = run(
      [
        { type: "SET_TEAM_COUNT", count: 3 },
        { type: "SET_SLOT", index: 2, rosterId: 3 },
      ],
      twoTeam(),
    );
    s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:103"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
      ],
      s,
    );
    const codes = tradeIssues(s, TEAMS).map((i) => i.code);
    expect(codes).toContain("idle_team");
    expect(codes.filter((c) => c === "choose_destination")).toHaveLength(2);
    // Team 3 only receiving is refused publicly (send_and_receive, spec
    // §4.5): it must also send.
    s = run(
      [
        { type: "SET_DESTINATION", id: "p:103", to: 2 },
        { type: "SET_DESTINATION", id: "p:202", to: 3 },
      ],
      s,
    );
    expect(tradeIssues(s, TEAMS).map((i) => [i.code, i.slot])).toEqual([
      ["team_receives_nothing", 0],
      ["team_sends_nothing", 2],
    ]);
    // A 3-team cycle 1 → 2 → 3 → 1 is valid.
    s = run(
      [
        { type: "ADD_ASSET", asset: { id: "p:302", kind: "player", label: "Charlie Back" }, from: 3 },
        { type: "SET_DESTINATION", id: "p:302", to: 1 },
      ],
      s,
    );
    expect(tradeIssues(s, TEAMS)).toEqual([]);
    expect(canAnalyze(s, TEAMS, { maxLegs: 128 })).toBe(true);
  });

  it("no more assets than limits.maxLegs", () => {
    let s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
        { type: "ADD_ASSET", asset: asset(MINE, "p:102"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
      ],
      twoTeam(),
    );
    expect(tradeIssues(s, TEAMS, { maxLegs: 3 })).toEqual([]);
    expect(tradeIssues(s, TEAMS, { maxLegs: 2 }).map((i) => i.code)).toEqual(["too_many_assets"]);
  });
});

describe("contract shapes", () => {
  it("builds the frozen §4.3 analyze body: identities and routing only", () => {
    const s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:201"), from: 2 },
      ],
      twoTeam(),
    );
    const body = toAnalyzeRequest(s);
    expect(body).toEqual({
      perspectiveRosterId: 1,
      teams: [1, 2],
      assets: [
        { id: "p:101", from: 1, to: 2 },
        { id: "p:201", from: 2, to: 1 },
      ],
    });
    // Same legs as the fixture's echoed (canonical, id-sorted) trade.
    expect(body.assets).toEqual(fixture("analyze.not-fair-two-team").trade);
    // The key ignores entry order and the perspective, like the server.
    const reordered = { ...body, perspectiveRosterId: 2, teams: [2, 1], assets: body.assets.slice().reverse() };
    expect(tradeKey(reordered)).toBe(tradeKey(body));
    expect(tradeKey({ ...body, assets: [{ id: "p:101", from: 1, to: 2 }] })).not.toBe(tradeKey(body));
  });

  it("summarises every team's sends (with destination) and receives (with origin)", () => {
    const s = run(
      [
        { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:201"), from: 2 },
        { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
      ],
      twoTeam(),
    );
    const summary = tradeSummary(s, TEAMS);
    expect(summary.teams.map((t) => [t.rosterId, t.isYou])).toEqual([
      [1, true],
      [2, false],
    ]);
    expect(summary.teams[0].sends.map((x) => x.label)).toEqual(["Alpha Quarterback"]);
    expect(summary.teams[0].receives.map((x) => [x.label, x.fromName])).toEqual([
      ["Bravo Star", "The Bravos (Bravo)"],
      ["Bravo Runner", "The Bravos (Bravo)"],
    ]);
    expect(summary.teams[1].sends.map((x) => x.toName)).toEqual(["The Alphas (Alpha)", "The Alphas (Alpha)"]);
  });
});

describe("filters never reorder the server's list", () => {
  it("keeps the server order for every filter", () => {
    const ids = (xs) => xs.map((a) => a.id);
    const all = ids(MINE);
    for (const opts of [
      {},
      { group: "offense" },
      { group: "defense" },
      { group: "pick" },
      { query: "alpha" },
      { position: "RB" },
    ]) {
      const out = ids(filterAssets(MINE, opts));
      expect(out).toEqual(all.filter((id) => out.includes(id)));
    }
    expect(ids(filterAssets(MINE, { group: "pick" }))).toEqual(["pick:main:2027:r1:o1", "pick:main:2027:r2:o2"]);
    expect(ids(filterAssets(MINE, { group: "defense" }))).toEqual(["p:104", "p:105"]);
    expect(filterAssets(MINE, { query: "zzz" })).toEqual([]);
  });

  it("offers only the positions present in the current group", () => {
    expect(positionsPresent(MINE)).toEqual(["QB", "RB", "WR", "DL", "LB"]);
    expect(positionsPresent(MINE, "defense")).toEqual(["DL", "LB"]);
    expect(positionsPresent(MINE, "pick")).toEqual([]);
  });
});

describe("session restore", () => {
  const saved = () =>
    serializeAdvisorState(
      run(
        [
          { type: "ADD_ASSET", asset: asset(MINE, "p:101"), from: 1 },
          { type: "ADD_ASSET", asset: asset(THEIRS, "p:202"), from: 2 },
        ],
        twoTeam(),
      ),
    );

  it("restores teams and legs (identities and labels only)", () => {
    const raw = saved();
    expect(raw).not.toMatch(/value|rank|score/i);
    const s = restoreAdvisorState(raw, { teams: TEAMS });
    expect(s.slots).toEqual([1, 2]);
    expect(s.legs.map((l) => l.id)).toEqual(["p:101", "p:202"]);
  });

  it("the URL team wins over a different saved team", () => {
    const s = restoreAdvisorState(saved(), { teams: TEAMS, urlTeam: "3" });
    expect(s.slots).toEqual([3, null]);
    expect(s.legs).toEqual([]);
    expect(restoreAdvisorState(saved(), { teams: TEAMS, urlTeam: "1" }).legs).toHaveLength(2);
  });

  it("keeps a saved result only in the allowlisted fairness shape", () => {
    const s = advisorReducer(twoTeam(), {
      type: "RESULT",
      result: { ...FOUR, teams: FOUR.teams.slice(0, 2), value: 4321, gap: 99, key: "k" },
    });
    const raw = serializeAdvisorState(s);
    expect(raw).not.toMatch(/4321|"gap"|"value"/);
    const back = JSON.parse(raw).result;
    expect(back.overall.result).toBe("NOT_FAIR");
    expect(back.teams.map((t) => t.result)).toEqual(["FAIR", "NOT_FAIR"]);
    // An old-format (pre-amendment) saved result is dropped, not shown.
    const legacy = JSON.stringify({ ...JSON.parse(raw), result: { category: "FAVORABLE", headline: "Accept" } });
    expect(restoreAdvisorState(legacy, { teams: TEAMS }).result).toBeNull();
  });

  it("drops teams no longer in the league, and tolerates garbage", () => {
    const s = restoreAdvisorState(saved(), { teams: TEAMS.filter((t) => t.rosterId !== 2) });
    expect(s.slots).toEqual([1, null]);
    // Your own asset survives, unrouted; the vanished team's asset does not.
    expect(s.legs.map((l) => [l.id, l.to])).toEqual([["p:101", null]]);
    expect(restoreAdvisorState("{nope", { teams: TEAMS })).toEqual(initialAdvisorState());
    expect(restoreAdvisorState(null, { teams: TEAMS, urlTeam: "2" }).slots).toEqual([2, null]);
    expect(restoreAdvisorState(null, { teams: TEAMS, urlTeam: "77" }).slots).toEqual([null, null]);
  });
});
