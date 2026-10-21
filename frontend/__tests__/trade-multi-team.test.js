/**
 * lib/trade-multi-team.js + lib/trade-team-binding.js — the private /trade
 * side of N-team Analyze Trade (spec docs/trade/NTEAM_TRADE_ENGINE_SPEC.md
 * §3.2).  The ledger is built by id only, every refusal is named, and a
 * response is accepted only for the exact trade that was asked.
 */
import { describe, expect, it, vi } from "vitest";

import {
  buildMultiTeamLedger,
  effectiveBindings,
  entryAssetRef,
  inferSideRosterId,
  multiErrorRetryable,
  multiErrorText,
  multiRequestKey,
  probeMultiTeamAnalysis,
  teamOptions,
  validMultiPayload,
} from "@/lib/trade-multi-team";
import { builderFromFixture } from "./helpers/multi-team-fixture";

import THREE_CTX from "./fixtures/trade-multi/three-team-team-context.json";
import FOUR from "./fixtures/trade-multi/four-team-asset-only.json";
import STALE from "./fixtures/trade-multi/three-team-stale-rosters.json";

const fixtureRequest = (fx) => ({
  teams: [...fx._fixture.request.teams].sort((a, b) => a - b),
  assets: [...fx._fixture.request.assets]
    .map(({ id, from, to }) => ({ id, from, to }))
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
});

describe("asset identity is by canonical id only", () => {
  it("owned pick → its league pick id; player → p:<sleeperId>", () => {
    expect(entryAssetRef({ name: "2027 Mid 1st (from Ed)", assetId: "pick:dynasty_main:2027:r1:o2" })).toEqual({
      id: "pick:dynasty_main:2027:r1:o2",
      kind: "pick",
    });
    expect(entryAssetRef({ name: "Tre Tucker", playerId: "10213" })).toEqual({
      id: "p:10213",
      kind: "player",
    });
    expect(entryAssetRef({ name: "Tre Tucker", raw: { playerId: "10213" } }).id).toBe("p:10213");
  });

  it("a generic market pick and a row with no player id are refused, never guessed", () => {
    expect(entryAssetRef({ name: "2027 Mid 1st", pos: "PICK" })).toEqual({ reason: "generic_pick" });
    expect(entryAssetRef({ name: "2026 Pick 1.06" })).toEqual({ reason: "generic_pick" });
    expect(entryAssetRef({ name: "Someone" })).toEqual({ reason: "no_player_id" });
  });

  it("teamOptions keeps only teams with a roster id", () => {
    expect(teamOptions([{ roster_id: 3, name: "A" }, { name: "no id" }, { rosterId: 7, name: "B" }])).toEqual([
      { rosterId: 3, name: "A" },
      { rosterId: 7, name: "B" },
    ]);
  });
});

describe("side → team binding", () => {
  const { sides, sleeperTeams } = builderFromFixture(THREE_CTX);

  it("infers the ONE team that holds every asset on a side, by id", () => {
    expect(sides.map((s) => inferSideRosterId(s, sleeperTeams))).toEqual(THREE_CTX.teams.map((t) => t.rosterId));
  });

  it("refuses to infer an empty side, an unidentified asset, or a mixed side", () => {
    expect(inferSideRosterId({ assets: [] }, sleeperTeams)).toBeNull();
    expect(inferSideRosterId({ assets: [{ name: "2027 Mid 1st", pos: "PICK" }] }, sleeperTeams)).toBeNull();
    const mixed = { assets: [...sides[0].assets, ...sides[1].assets] };
    expect(inferSideRosterId(mixed, sleeperTeams)).toBeNull();
  });

  it("an explicit choice wins; null is explicitly none", () => {
    const b = effectiveBindings(sides, [undefined, null, 99], sleeperTeams);
    expect(b[0]).toEqual({ rosterId: THREE_CTX.teams[0].rosterId, basis: "roster" });
    expect(b[1]).toEqual({ rosterId: null, basis: "none" });
    expect(b[2]).toEqual({ rosterId: 99, basis: "explicit" });
  });
});

describe("buildMultiTeamLedger", () => {
  for (const fx of [THREE_CTX, FOUR]) {
    it(`reproduces the real request of ${fx._fixture.scenario} (canonical order)`, () => {
      const { sides, sleeperTeams, teamIds } = builderFromFixture(fx);
      const out = buildMultiTeamLedger({ sides, bindings: teamIds, teams: sleeperTeams });
      expect(out.ok).toBe(true);
      expect(out.request).toEqual(fixtureRequest(fx));
      expect(validMultiPayload(fx, out.request, { leagueKey: "dynasty_main" })).toBe(true);
    });
  }

  it("is invariant to side order (teams are canonicalised by rosterId)", () => {
    const { sides, sleeperTeams, teamIds } = builderFromFixture(THREE_CTX);
    const order = [2, 0, 1];
    const remap = new Map(order.map((old, neu) => [old, neu]));
    const permuted = order.map((old, neu) => ({
      ...sides[old],
      id: neu,
      label: "ABC"[neu],
      destinations: Object.fromEntries(
        Object.entries(sides[old].destinations).map(([k, d]) => [k, remap.get(d)]),
      ),
    }));
    const a = buildMultiTeamLedger({ sides, bindings: teamIds, teams: sleeperTeams });
    const b = buildMultiTeamLedger({
      sides: permuted,
      bindings: order.map((i) => teamIds[i]),
      teams: sleeperTeams,
    });
    expect(b.request).toEqual(a.request);
  });

  const base = () => builderFromFixture(THREE_CTX);
  const codes = (out) => out.reasons.map((r) => r.code);

  it("an unbound side and a team on two sides are named", () => {
    const { sides, sleeperTeams, teamIds } = base();
    expect(codes(buildMultiTeamLedger({ sides, bindings: [teamIds[0], null, teamIds[2]], teams: sleeperTeams }))).toContain(
      "unbound_side",
    );
    expect(
      codes(buildMultiTeamLedger({ sides, bindings: [teamIds[0], teamIds[0], teamIds[2]], teams: sleeperTeams })),
    ).toContain("duplicate_team");
  });

  it("a generic pick, a copy, a bad destination and an unheld asset are each refused by name", () => {
    const { sides, sleeperTeams, teamIds } = base();
    const s = structuredClone(sides);
    s[0].assets.push({ name: "2028 Mid 2nd", pos: "PICK" });
    s[0].assets.push({ ...s[0].assets[0] }); // a hypothetical copy
    const firstKey = Object.keys(s[1].destinations)[0];
    s[1].destinations[firstKey] = 1; // routed to itself
    s[2].assets.push({ name: "Not Theirs", playerId: "99999" });
    s[2].destinations["Not Theirs"] = 0;
    const out = buildMultiTeamLedger({ sides: s, bindings: teamIds, teams: sleeperTeams });
    expect(out.ok).toBe(false);
    expect(codes(out)).toEqual(
      expect.arrayContaining(["generic_pick", "duplicate_asset", "invalid_destination", "not_on_team"]),
    );
    const generic = out.reasons.find((r) => r.code === "generic_pick");
    expect(generic.text).toMatch(/^2028 Mid 2nd is a market pick reference/);
    expect(generic.sideIdx).toBe(0);
  });

  it("two DIFFERENT assets sharing one side line (one display name) are refused, never routed as one (E1-F3)", () => {
    const { sides, sleeperTeams, teamIds } = base();
    const s = structuredClone(sides);
    const teams = structuredClone(sleeperTeams);
    const t0 = teams.find((t) => Number(t.roster_id ?? t.rosterId) === teamIds[0]);
    // Two real, different players the same team holds, one display name
    // (the live league has such a pair: two "Byron Murphy").
    t0.playerIds = [...(t0.playerIds || []), "77701", "77702"];
    s[0].assets.push({ name: "Byron Murphy", playerId: "77701" });
    s[0].assets.push({ name: "Byron Murphy", playerId: "77702" });
    s[0].destinations["Byron Murphy"] = 1;
    const out = buildMultiTeamLedger({ sides: s, bindings: teamIds, teams });
    expect(out.ok).toBe(false);
    const shared = out.reasons.filter((r) => r.code === "shared_line");
    expect(shared).toHaveLength(1); // one reason per line, not per copy
    expect(shared[0].sideIdx).toBe(0);
    expect(shared[0].text).toMatch(/^Byron Murphy shares its name with a different asset/);
    expect(codes(out)).not.toContain("duplicate_asset");
    // A COPY of one asset (same id) is still the duplicate refusal, not this one.
    const copy = structuredClone(sides);
    copy[0].assets.push({ ...copy[0].assets[0] });
    expect(codes(buildMultiTeamLedger({ sides: copy, bindings: teamIds, teams: sleeperTeams }))).toEqual([
      "duplicate_asset",
    ]);
  });

  it("an idle side and an empty trade are refused", () => {
    const { sides, sleeperTeams, teamIds } = base();
    const s = structuredClone(sides);
    s.push({ id: 3, label: "D", assets: [], destinations: {} });
    const out = buildMultiTeamLedger({
      sides: s,
      bindings: [...teamIds, 12],
      teams: [...sleeperTeams, { roster_id: 12, name: "Idle", playerIds: [], pickDetails: [] }],
    });
    expect(codes(out)).toEqual(["idle_team"]);
    const empty = sides.map((x) => ({ ...x, assets: [], destinations: {} }));
    expect(codes(buildMultiTeamLedger({ sides: empty, bindings: teamIds, teams: sleeperTeams }))).toEqual([
      "empty_trade",
    ]);
  });

  it("a missing destination is never silently re-routed", () => {
    const { sides, sleeperTeams, teamIds } = base();
    const s = structuredClone(sides);
    s[0].destinations = {};
    const out = buildMultiTeamLedger({ sides: s, bindings: teamIds, teams: sleeperTeams });
    expect(out.ok).toBe(false);
    expect(new Set(codes(out))).toEqual(new Set(["invalid_destination"]));
  });
});

describe("a response is accepted only for the trade that was asked", () => {
  const req = fixtureRequest(THREE_CTX);
  it("accepts the matching payload", () => {
    expect(validMultiPayload(THREE_CTX, req)).toBe(true);
    expect(validMultiPayload(STALE, fixtureRequest(STALE))).toBe(true);
  });
  it("rejects another league, another team set, another ledger or another version", () => {
    expect(validMultiPayload(THREE_CTX, req, { leagueKey: "dynasty_new" })).toBe(false);
    expect(validMultiPayload(THREE_CTX, { ...req, teams: [1, 2, 3] })).toBe(false);
    expect(validMultiPayload(THREE_CTX, { ...req, assets: req.assets.slice(1) })).toBe(false);
    expect(validMultiPayload({ ...THREE_CTX, multiTeamVersion: "x" }, req)).toBe(false);
    expect(validMultiPayload(FOUR, req)).toBe(false);
  });
  it("the request key changes with the ledger, league and mode", () => {
    const k = multiRequestKey(req, { leagueKey: "a", useTeamContext: true });
    expect(multiRequestKey(req, { leagueKey: "a", useTeamContext: false })).not.toBe(k);
    expect(multiRequestKey(req, { leagueKey: "b", useTeamContext: true })).not.toBe(k);
    expect(multiRequestKey(null)).toBe("");
  });
});

describe("the flag probe and error words", () => {
  const res = (status, body) => ({ status, json: async () => body });
  it("flag off answers 503 multi_team_analysis_disabled → off", async () => {
    const f = vi.fn(async () => res(503, { error: "multi_team_analysis_disabled" }));
    expect(await probeMultiTeamAnalysis(f)).toBe(false);
    expect(f).toHaveBeenCalledWith("/api/trade/analyze-multi", expect.objectContaining({ method: "POST", body: "{}" }));
  });
  it("flag on answers the empty body with 400 invalid_request → on; anything else → off", async () => {
    expect(await probeMultiTeamAnalysis(async () => res(400, { error: "invalid_request" }))).toBe(true);
    expect(await probeMultiTeamAnalysis(async () => res(401, { error: "auth_required" }))).toBe(false);
    expect(await probeMultiTeamAnalysis(async () => res(502, {}))).toBe(false);
    expect(
      await probeMultiTeamAnalysis(async () => {
        throw new Error("network");
      }),
    ).toBe(false);
  });
  it("words and retryability", () => {
    expect(multiErrorText(409, { error: "stale_assets" })).toMatch(/not held by the team sending them/);
    expect(multiErrorText(400, { error: "invalid_trade", message: "An asset can move only once in a trade." })).toBe(
      "an asset can move only once in a trade",
    );
    expect(multiErrorRetryable(409, { error: "stale_assets" })).toBe(false);
    expect(multiErrorRetryable(500, { error: "internal_error" })).toBe(true);
    expect(multiErrorRetryable(0, { error: "timeout" })).toBe(true);
  });
});
