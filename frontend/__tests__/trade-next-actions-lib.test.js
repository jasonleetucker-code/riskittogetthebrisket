// TC-B / TCM-O11, O13, L01 — the deep-link / body owner for /trade "Next
// steps" (lib/trade-next-actions.js).  Every link points at an EXISTING
// engine with the parameters that page reads; nothing here values a trade.
import { describe, expect, it } from "vitest";
import {
  DESK_MAX_ASSETS_PER_SIDE,
  arbitrageHref,
  balanceStep,
  deskBodyFromCalculator,
  offerEvidenceBody,
  offerEvidenceUrl,
  parseArbitrageQuery,
  tradeDatabaseHref,
  tradeParties,
} from "@/lib/trade-next-actions";

const P = (name, pos, playerId) => ({ name, pos, assetClass: "offense", playerId });
const PICK = { name: "2027 Mid 1st", pos: "PICK", assetClass: "pick" };
const OWNED = {
  name: "2027 Mid 1st",
  pos: "PICK",
  assetClass: "pick",
  assetId: "pick:dynasty_main:2027:r1:o4",
  assetLabel: "2027 Mid 1st (Joey)",
};

describe("arbitrage links", () => {
  it("round-trips tool, team and opponent", () => {
    const href = arbitrageHref("scan", { team: "Jason", opponent: "Joey" });
    expect(href).toBe("/arbitrage?tool=scan&team=Jason&opponent=Joey");
    const q = parseArbitrageQuery(href.split("?")[1], ["Jason", "Joey"]);
    expect(q).toEqual({ tool: "scan", team: "Jason", opponent: "Joey", seed: null });
  });

  it("refuses an unknown tool and drops unknown or self opponents", () => {
    expect(arbitrageHref("nope", { team: "Jason" })).toBeNull();
    expect(arbitrageHref("best", { team: "Jason", opponent: "Jason" })).toBe(
      "/arbitrage?tool=best&team=Jason",
    );
    expect(parseArbitrageQuery("tool=x&team=Nobody&opponent=Joey", ["Jason"])).toEqual({
      tool: null,
      team: null,
      opponent: null,
      seed: null,
    });
  });
});

describe("tradeDatabaseHref", () => {
  it("sends players by stable id and picks by board row, counting the unlinkable", () => {
    const sides = [
      { assets: [P("A", "WR", "11"), P("A", "WR", "11"), OWNED] },
      { assets: [P("B", "RB", null), PICK] },
    ];
    const { href, unlinked } = tradeDatabaseHref(sides);
    const params = new URL(href, "https://x").searchParams;
    expect(new URL(href, "https://x").pathname).toBe("/market/trade-database");
    expect(params.get("players")).toBe("11");
    expect(params.get("picks")).toBe("2027 Mid 1st");
    expect(unlinked).toBe(1);
  });

  it("is null when nothing identifiable is on the trade", () => {
    expect(tradeDatabaseHref([{ assets: [P("B", "RB", null)] }, { assets: [] }])).toEqual({
      href: null,
      unlinked: 1,
    });
  });
});

describe("tradeParties", () => {
  const sides = [{ assets: [P("A", "WR", "1")] }, { assets: [P("B", "RB", "2")] }];
  it("names what is missing instead of guessing a team", () => {
    expect(tradeParties({ sides: [...sides, { assets: [] }], mySideIdx: 0, myTeam: "J" }).reason).toBe(
      "not_two_team",
    );
    expect(tradeParties({ sides, mySideIdx: 0, myTeam: "" }).reason).toBe("no_team_selected");
    expect(tradeParties({ sides, mySideIdx: null, myTeam: "J" }).reason).toBe("side_unknown");
    expect(
      tradeParties({ sides, mySideIdx: 0, myTeam: "J", sideTeamNames: ["J", null] }).reason,
    ).toBe("opponent_unknown");
    expect(
      tradeParties({ sides, mySideIdx: 1, myTeam: "J", sideTeamNames: ["K", "J"] }),
    ).toEqual({ ok: true, myTeam: "J", opponent: "K", mySideIdx: 1, reason: null });
  });
});

describe("deskBodyFromCalculator", () => {
  const parties = { ok: true, myTeam: "J", opponent: "K", mySideIdx: 0, reason: null };

  it("sends what my side gives and receives the other side, one asset per copy", () => {
    const sides = [{ assets: [P("A", "WR", "1"), P("A", "WR", "1"), OWNED] }, { assets: [PICK] }];
    const { body } = deskBodyFromCalculator({ sides, parties, leagueKey: "dynasty_main" });
    expect(body).toEqual({
      leagueKey: "dynasty_main",
      myTeam: "J",
      opponent: "K",
      source: "calculator",
      send: [
        { name: "A", isPick: false, position: "WR" },
        { name: "A", isPick: false, position: "WR" },
        {
          name: "2027 Mid 1st (Joey)",
          isPick: true,
          assetId: "pick:dynasty_main:2027:r1:o4",
          boardRowName: "2027 Mid 1st",
        },
      ],
      receive: [{ name: "2027 Mid 1st", isPick: true }],
    });
  });

  it("refuses rather than truncates past the desk's per-side cap", () => {
    const many = Array.from({ length: DESK_MAX_ASSETS_PER_SIDE + 1 }, (_, i) => P(`P${i}`, "WR", `${i}`));
    const out = deskBodyFromCalculator({
      sides: [{ assets: many }, { assets: [PICK] }],
      parties,
      leagueKey: "dynasty_main",
    });
    expect(out).toEqual({ body: null, reason: "too_many_assets" });
    expect(
      deskBodyFromCalculator({ sides: [{ assets: [] }, { assets: [PICK] }], parties, leagueKey: "x" })
        .reason,
    ).toBe("one_side_empty");
    expect(
      deskBodyFromCalculator({ sides: [{ assets: [] }, { assets: [] }], parties: { ok: false, reason: "side_unknown" } })
        .reason,
    ).toBe("side_unknown");
  });
});

describe("offerEvidenceBody", () => {
  it("is what the OPPONENT would receive and send", () => {
    const sides = [{ assets: [P("A", "WR", "1")] }, { assets: [P("B", "RB", "2"), PICK] }];
    const parties = { ok: true, myTeam: "J", opponent: "K", mySideIdx: 0 };
    expect(offerEvidenceBody({ sides, parties })).toEqual({
      myTeam: "J",
      opponent: "K",
      theyReceive: [{ name: "A", isPick: false, position: "WR" }],
      theySend: [
        { name: "B", isPick: false, position: "RB" },
        { name: "2027 Mid 1st", isPick: true },
      ],
    });
    expect(offerEvidenceUrl("dynasty_main")).toBe(
      "/api/manager-scout/offer-evidence?leagueKey=dynasty_main",
    );
  });
});

describe("balanceStep", () => {
  it("points at the page's own balancers or says why there are none", () => {
    expect(balanceStep({ evalState: "empty" }).state).toBe("empty");
    expect(balanceStep({ evalState: "incomplete" }).state).toBe("incomplete");
    expect(balanceStep({ evalState: "complete", isFair: true }).state).toBe("fair");
    expect(balanceStep({ evalState: "complete", balancerSideLabel: "B", sideCount: 2 })).toEqual({
      state: "suggested",
      text: "Balancing suggestions are listed under Side B.",
      href: "#trade-side-B-balancers",
    });
    expect(balanceStep({ evalState: "complete", sideCount: 2 }).state).toBe("none_found");
  });
});
