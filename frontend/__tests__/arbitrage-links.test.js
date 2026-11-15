import { describe, expect, it } from "vitest";

import {
  arbitrageHref,
  builderSeedHref,
  parseArbitrageQuery,
  parseBuilderSeed,
} from "@/lib/arbitrage-links";
import * as nextActions from "@/lib/trade-next-actions";
import * as packageBuilder from "@/lib/package-builder";
import { seedProblemText } from "@/lib/package-builder";

const TEAMS = ["Alpha", "Bravo", "Charlie"];

describe("arbitrage-links — one owner for both /arbitrage link shapes", () => {
  it("is the single definition the two consumer modules re-export", () => {
    expect(nextActions.arbitrageHref).toBe(arbitrageHref);
    expect(nextActions.parseArbitrageQuery).toBe(parseArbitrageQuery);
    expect(packageBuilder.builderSeedHref).toBe(builderSeedHref);
    expect(packageBuilder.parseBuilderSeed).toBe(parseBuilderSeed);
  });

  it("a /trade builder tool link is NOT read as a malformed seed", () => {
    const href = arbitrageHref("builder", { team: "Alpha", opponent: "Bravo" });
    const search = href.slice(href.indexOf("?"));
    expect(parseBuilderSeed(search)).toBeNull();
    const q = parseArbitrageQuery(search, TEAMS);
    expect(q).toEqual({ tool: "builder", team: "Alpha", opponent: "Bravo", seed: null });
    // The builder must not claim the link's team "could not be read".
    expect(seedProblemText(q.seed, { teams: [{ name: "Alpha" }], myTeam: "Alpha" })).toBe("");
  });

  it("a Manager Intelligence seed keeps its owner id out of the team-name opponent", () => {
    const href = builderSeedHref({
      leagueKey: "dynasty_main",
      opponentOwner: "735693375101108224",
      target: "Puka Nacua",
    });
    const q = parseArbitrageQuery(href.slice(href.indexOf("?")), TEAMS);
    expect(q.tool).toBe("builder");
    expect(q.opponent).toBeNull();
    expect(q.seed).toEqual({
      opponentOwner: "735693375101108224",
      leagueKey: "dynasty_main",
      target: "Puka Nacua",
    });
  });

  it("a seed link that happens to name a team as opponent still resolves only by owner id", () => {
    const q = parseArbitrageQuery("?tool=builder&league=dynasty_main&opponent=Bravo", TEAMS);
    expect(q.opponent).toBeNull();
    // Malformed owner on a seed link → empty seed, so the view says nothing applied.
    expect(q.seed).toEqual({ opponentOwner: "", leagueKey: "", target: "" });
  });

  it("non-builder tools never produce a seed, and unknown teams are dropped", () => {
    expect(parseArbitrageQuery("?tool=scan&team=Zulu&opponent=Bravo", TEAMS)).toEqual({
      tool: "scan",
      team: null,
      opponent: "Bravo",
      seed: null,
    });
    expect(parseArbitrageQuery("?tool=golden&league=dynasty_main", TEAMS).seed).toBeNull();
    expect(parseArbitrageQuery("", TEAMS)).toEqual({
      tool: null,
      team: null,
      opponent: null,
      seed: null,
    });
  });
});
