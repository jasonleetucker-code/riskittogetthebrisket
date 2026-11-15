// Manager Intelligence Batch D — seeding the trade tools from a scouted
// roster.  Link and seed round-trips through the tools' own restore formats,
// one package-model receipt across surfaces, unresolved assets never priced,
// and league-scoped tools only for the league whose rosters are loaded.
import { describe, expect, it } from "vitest";
import {
  calculatorSeedHref,
  calculatorSeedTrade,
  leagueScopedToolsAvailable,
  packageBuilderSeedHref,
  resolvedSeedKeys,
  rosterSeedAssets,
  seedPicksNote,
  tradeToolsScopeNote,
  unresolvedReasonText,
} from "@/lib/manager-trade-tools";
import {
  builderSeedHref,
  parseBuilderSeed,
  seedOpponentTeam,
  seedProblemText,
} from "@/lib/package-builder";
import {
  describeShareModelChange,
  encodeTrade,
  parseShareParam,
} from "@/lib/trade-share";
import { leagueTradeToolsHref, readFocusManager } from "@/lib/manager-intel";
import { ACTIVE_PACKAGE_MODEL_ID, PACKAGE_MODELS } from "@/lib/trade-logic";
import {
  EXTERNAL_TOOLS,
  NOT_LOADED_TOOLS,
  RECEIPT,
  SCOPED_TOOLS,
  scoutedManager,
} from "./fixtures/manager-trade-tools";

const byLabel = (assets, label) => assets.find((a) => a.label === label);

function seedInput(tradeTools, leagueKey, labels) {
  const manager = scoutedManager(leagueKey);
  const assets = rosterSeedAssets(manager, tradeTools);
  const selectedKeys = new Set(labels.map((l) => byLabel(assets, l).key));
  return { manager, assets, selectedKeys, tradeTools };
}

function decode(href) {
  expect(href.startsWith("/trade?share=")).toBe(true);
  return parseShareParam(href.slice("/trade".length));
}

describe("roster seed assets", () => {
  it("marks unresolved assets with a reason and never a 0 value", () => {
    const assets = rosterSeedAssets(scoutedManager(), SCOPED_TOOLS);
    expect(assets.map((a) => a.label)).toEqual([
      "Quinn Passer",
      "Alpha Back",
      "Deep Veteran",
      "Zed Unranked",
      "2027 Round 1",
      "2027 Round 2",
      "2026 Round 1",
    ]);
    const unpriced = byLabel(assets, "Deep Veteran");
    expect(unpriced).toMatchObject({
      resolved: false,
      value: null,
      seedName: null,
    });
    expect(unresolvedReasonText(unpriced.reason)).toBe(
      "the canonical board does not price him",
    );
    expect(byLabel(assets, "Zed Unranked")).toMatchObject({
      resolved: false,
      value: null,
      reason: "not_on_board",
    });
    expect(byLabel(assets, "2026 Round 1")).toMatchObject({
      resolved: false,
      value: null,
      reason: "pick_already_used",
      assetId: null,
    });
    expect(
      assets.filter((a) => !a.resolved).every((a) => a.value === null),
    ).toBe(true);
    expect(resolvedSeedKeys(assets)).toHaveLength(4);
  });

  it("keeps a pick's canonical id only in the loaded league", () => {
    const scoped = rosterSeedAssets(
      scoutedManager("dynasty_main"),
      SCOPED_TOOLS,
    );
    expect(byLabel(scoped, "2027 Round 1").assetId).toBe(
      "pick:dynasty_main:2027:r1:o4",
    );
    const external = rosterSeedAssets(
      scoutedManager("sleeper-555"),
      EXTERNAL_TOOLS,
    );
    expect(byLabel(external, "2027 Round 1").assetId).toBeNull();
    const notLoaded = rosterSeedAssets(
      scoutedManager("dynasty_main"),
      NOT_LOADED_TOOLS,
    );
    expect(byLabel(notLoaded, "2027 Round 1").assetId).toBeNull();
  });

  it("says when picks are unknown rather than listing none", () => {
    const m = scoutedManager();
    expect(seedPicksNote(m)).toBe("");
    m.draftCapital = {
      pickOwnershipState: "unavailable",
      pickOwnershipReason: "traded_picks_fetch_failed",
      picks: null,
    };
    expect(
      rosterSeedAssets(m, SCOPED_TOOLS).some((a) => a.kind === "pick"),
    ).toBe(false);
    expect(seedPicksNote(m)).toMatch(/traded-picks feed could not be read/);
    expect(
      seedPicksNote({ draftCapital: { available: false, picks: null } }),
    ).toMatch(/current season only/);
  });
});

describe("Trade Calculator seed (lib/trade-share round trip)", () => {
  it("round-trips the selected assets onto the scouted manager's side", () => {
    const input = seedInput(SCOPED_TOOLS, "dynasty_main", [
      "Quinn Passer",
      "2027 Round 1",
    ]);
    const state = decode(calculatorSeedHref(input, encodeTrade));
    expect(state.sides).toHaveLength(2);
    expect(state.sides[0].players).toEqual([]);
    expect(state.sides[1].name).toBe("Dana");
    expect(state.sides[1].players).toEqual(["Quinn Passer", "2027 Round 1"]);
    expect(state.sides[1].assetIds).toEqual([
      null,
      "pick:dynasty_main:2027:r1:o4",
    ]);
    expect(state.truncated).toBe(false);
  });

  it("an external league travels as the generic seed (no owned-pick ids)", () => {
    const input = seedInput(EXTERNAL_TOOLS, "sleeper-555", [
      "Alpha Back",
      "2027 Round 2",
    ]);
    const state = decode(calculatorSeedHref(input, encodeTrade));
    expect(state.sides[1].players).toEqual(["Alpha Back", "2027 Round 2"]);
    expect(state.sides[1].assetIds).toEqual([null, null]);
  });

  it("never seeds an unresolved asset, even when its key is selected", () => {
    const manager = scoutedManager();
    const assets = rosterSeedAssets(manager, SCOPED_TOOLS);
    const selectedKeys = new Set([
      byLabel(assets, "Deep Veteran").key,
      byLabel(assets, "Zed Unranked").key,
      byLabel(assets, "2026 Round 1").key,
    ]);
    const input = { manager, assets, selectedKeys, tradeTools: SCOPED_TOOLS };
    expect(calculatorSeedTrade(input).sides[1].players).toEqual([]);
    expect(calculatorSeedHref(input, encodeTrade)).toBeNull();
    selectedKeys.add(byLabel(assets, "Alpha Back").key);
    expect(
      decode(calculatorSeedHref(input, encodeTrade)).sides[1].players,
    ).toEqual(["Alpha Back"]);
  });

  it("needs an encoder and a selection", () => {
    const input = seedInput(SCOPED_TOOLS, "dynasty_main", []);
    expect(calculatorSeedHref(input, encodeTrade)).toBeNull();
    expect(
      calculatorSeedHref(
        seedInput(SCOPED_TOOLS, "dynasty_main", ["Alpha Back"]),
        null,
      ),
    ).toBeNull();
  });
});

describe("one package-model receipt across surfaces", () => {
  it("the backend receipt travels into the calculator link and matches its active model", () => {
    // config/trade/package_model.json is parity-pinned to ACTIVE_PACKAGE_MODEL_ID
    // (tests/valuation_math/test_package_model.py); the league payload stamps
    // the same receipt, and the seed carries it into /trade.
    expect(RECEIPT.id).toBe(ACTIVE_PACKAGE_MODEL_ID);
    for (const tools of [SCOPED_TOOLS, EXTERNAL_TOOLS]) {
      const input = seedInput(tools, "dynasty_main", ["Quinn Passer"]);
      const state = decode(calculatorSeedHref(input, encodeTrade));
      expect(state.packageModel).toBe(tools.packageModel.id);
      // Same model on both surfaces: the calculator shows no model-change note.
      expect(
        describeShareModelChange(
          state.packageModel,
          ACTIVE_PACKAGE_MODEL_ID,
          PACKAGE_MODELS,
        ),
      ).toBeNull();
    }
  });

  it("a receipt that differs from the calculator's model is named, not hidden", () => {
    const tools = {
      ...SCOPED_TOOLS,
      packageModel: { ...RECEIPT, id: "ktc_2026_04" },
    };
    const state = decode(
      calculatorSeedHref(
        seedInput(tools, "dynasty_main", ["Quinn Passer"]),
        encodeTrade,
      ),
    );
    expect(
      describeShareModelChange(
        state.packageModel,
        ACTIVE_PACKAGE_MODEL_ID,
        PACKAGE_MODELS,
      ),
    ).toMatch(/This link was made under KTC Value Adjustment/);
  });
});

describe("league-scoped tools gate", () => {
  it("is open only for the loaded league", () => {
    expect(leagueScopedToolsAvailable(SCOPED_TOOLS)).toBe(true);
    expect(leagueScopedToolsAvailable(EXTERNAL_TOOLS)).toBe(false);
    expect(leagueScopedToolsAvailable(NOT_LOADED_TOOLS)).toBe(false);
    expect(leagueScopedToolsAvailable(undefined)).toBe(false);
    expect(tradeToolsScopeNote(SCOPED_TOOLS)).toBe("");
    expect(tradeToolsScopeNote(EXTERNAL_TOOLS)).toMatch(
      /not one of the site's leagues/,
    );
    expect(tradeToolsScopeNote(NOT_LOADED_TOOLS)).toMatch(
      /rosters are not loaded/,
    );
  });

  it("offers no Package Builder link outside the loaded league", () => {
    expect(
      packageBuilderSeedHref(
        seedInput(EXTERNAL_TOOLS, "sleeper-555", ["Alpha Back"]),
      ),
    ).toBeNull();
    expect(
      packageBuilderSeedHref(
        seedInput(NOT_LOADED_TOOLS, "dynasty_main", ["Alpha Back"]),
      ),
    ).toBeNull();
  });
});

describe("Package Builder seed (/arbitrage query round trip)", () => {
  it("one selected player becomes the target; the opponent travels by owner id", () => {
    const href = packageBuilderSeedHref(
      seedInput(SCOPED_TOOLS, "dynasty_main", ["Alpha Back"]),
    );
    expect(href.startsWith("/arbitrage?")).toBe(true);
    expect(parseBuilderSeed(href.slice("/arbitrage".length))).toEqual({
      opponentOwner: "735693375101108224",
      leagueKey: "dynasty_main",
      target: "Alpha Back",
    });
  });

  it("several assets, or a pick, seed the opponent only", () => {
    for (const labels of [
      ["Alpha Back", "Quinn Passer"],
      ["2027 Round 1"],
      [],
    ]) {
      const href = packageBuilderSeedHref(
        seedInput(SCOPED_TOOLS, "dynasty_main", labels),
      );
      expect(parseBuilderSeed(href.split("?")[1])).toEqual({
        opponentOwner: "735693375101108224",
        leagueKey: "dynasty_main",
        target: "",
      });
    }
  });

  it("rejects malformed seeds instead of half-applying them", () => {
    expect(
      builderSeedHref({ leagueKey: "dynasty_main", opponentOwner: "u1" }),
    ).toBeNull();
    expect(
      builderSeedHref({ leagueKey: "../x", opponentOwner: "123" }),
    ).toBeNull();
    expect(parseBuilderSeed("")).toBeNull();
    expect(
      parseBuilderSeed("?tool=scan&opponent=1&league=dynasty_main"),
    ).toBeNull();
    expect(
      parseBuilderSeed("?tool=builder&opponent=abc&league=dynasty_main"),
    ).toEqual({
      opponentOwner: "",
      leagueKey: "",
      target: "",
    });
    const long = "x".repeat(65);
    expect(
      parseBuilderSeed(
        `?tool=builder&opponent=1&league=dynasty_main&target=${long}`,
      ).target,
    ).toBe("");
  });

  it("resolves the team by owner id, never the user's own team", () => {
    const teams = [
      { name: "Mine", ownerId: "111" },
      { name: "Dana's Team", ownerId: "735693375101108224" },
    ];
    const seed = parseBuilderSeed(
      "?tool=builder&league=dynasty_main&opponent=735693375101108224",
    );
    expect(seedOpponentTeam(seed, teams, "Mine")).toBe("Dana's Team");
    expect(
      seedProblemText(seed, {
        teams,
        myTeam: "Mine",
        leagueKey: "dynasty_main",
      }),
    ).toBe("");
    const own = parseBuilderSeed(
      "?tool=builder&league=dynasty_main&opponent=111",
    );
    expect(seedOpponentTeam(own, teams, "Mine")).toBe("");
    expect(
      seedProblemText(own, {
        teams,
        myTeam: "Mine",
        leagueKey: "dynasty_main",
      }),
    ).toMatch(/your own/);
    expect(
      seedProblemText(seed, {
        teams: [teams[0]],
        myTeam: "Mine",
        leagueKey: "dynasty_new",
      }),
    ).toMatch(/different league/);
    expect(
      seedProblemText(seed, {
        teams: [teams[0]],
        myTeam: "Mine",
        leagueKey: "dynasty_main",
      }),
    ).toMatch(/no team in the selected league/);
    // Teams not loaded yet: nothing to say.
    expect(
      seedProblemText(seed, { teams: [], myTeam: "", leagueKey: "" }),
    ).toBe("");
  });
});

describe("opening a manager's trade tools from /managers", () => {
  it("links to the league scouting page focused on that manager", () => {
    const href = leagueTradeToolsHref(
      "1312006700437352448",
      "735693375101108224",
    );
    expect(href).toBe(
      "/managers/league/1312006700437352448?manager=735693375101108224",
    );
    expect(
      readFocusManager(href.split("/managers/league/1312006700437352448")[1]),
    ).toBe("735693375101108224");
    expect(leagueTradeToolsHref("1312006700437352448", "u1")).toBeNull();
    expect(leagueTradeToolsHref("../x", "123")).toBeNull();
    expect(readFocusManager("?manager=<script>")).toBe("");
    expect(readFocusManager("")).toBe("");
  });
});
