import { describe, it, expect } from "vitest";
import {
  buildMentionButtons,
  buildPlayerMetaIndex,
  filterByPlayerFacets,
} from "@/lib/news-filters";

const ROWS = [
  { name: "CeeDee Lamb", pos: "WR", raw: { team: "DAL" } },
  { name: "Dak Prescott", pos: "QB", raw: { team: "DAL" } },
  { name: "Russell Wilson", pos: "QB", raw: { team: "NYG" } },
  { name: "Micah Parsons", pos: "DL/EDGE", raw: { team: "DAL" } },
  { name: "T.J. Hockenson", pos: "TE", raw: { team: "MIN" } },
  // Documented name collision (src/utils/name_clean.py): two REAL
  // distinct players whose names normalize to the same key.
  { name: "CJ Allen", pos: "LB", raw: { team: "TEN" } },
  { name: "C.J. Allen", pos: "WR", raw: { team: "ATL" } },
];

const META = buildPlayerMetaIndex(ROWS);

const CROSS_ITEM = {
  id: "x1",
  headline: "Cowboys WR and Giants QB linked in trade talk",
  players: [{ name: "CeeDee Lamb" }, { name: "Russell Wilson" }],
};
const DAL_QB_ITEM = {
  id: "x2",
  headline: "Prescott extension news",
  players: [{ name: "Dak Prescott" }],
};
const GENERAL_ITEM = { id: "x3", headline: "League notes", players: [] };

describe("buildPlayerMetaIndex", () => {
  it("maps normalized keys to candidate meta lists", () => {
    expect(META.get("ceedee lamb")).toEqual([{ team: "DAL", family: "WR" }]);
    // Compound position keeps the leading family only.
    expect(META.get("micah parsons")[0].family).toBe("DL");
    // Dotted-initial names index under the collapsed key.
    expect(META.get("tj hockenson")).toEqual([{ team: "MIN", family: "TE" }]);
  });

  it("keeps EVERY colliding player's meta, not just the first row", () => {
    const candidates = META.get("cj allen");
    expect(candidates).toHaveLength(2);
    expect(candidates).toContainEqual({ team: "TEN", family: "LB" });
    expect(candidates).toContainEqual({ team: "ATL", family: "WR" });
  });

  it("dedupes identical metas from duplicate rows", () => {
    const index = buildPlayerMetaIndex([
      { name: "CeeDee Lamb", pos: "WR", raw: { team: "DAL" } },
      { name: "Ceedee Lamb", pos: "WR", raw: { team: "DAL" } },
    ]);
    expect(index.get("ceedee lamb")).toHaveLength(1);
  });

  it("returns an empty map for invalid input", () => {
    expect(buildPlayerMetaIndex(null).size).toBe(0);
  });
});

describe("filterByPlayerFacets — conjunction per mention", () => {
  const items = [CROSS_ITEM, DAL_QB_ITEM, GENERAL_ITEM];

  it("passes everything through when both facets are ALL", () => {
    expect(
      filterByPlayerFacets(items, {
        teamFilter: "ALL",
        posFilter: "ALL",
        playerMeta: META,
      }),
    ).toEqual(items);
  });

  it("DAL + QB rejects an item whose only DAL mention is a WR and only QB mention is NYG", () => {
    const out = filterByPlayerFacets(items, {
      teamFilter: "DAL",
      posFilter: "QB",
      playerMeta: META,
    });
    // CROSS_ITEM mentions a DAL WR and an NYG QB — no single mention
    // satisfies both facets, so it must NOT pass.
    expect(out.map((i) => i.id)).toEqual(["x2"]);
  });

  it("single-facet team filter matches any mention on that team", () => {
    const out = filterByPlayerFacets(items, {
      teamFilter: "DAL",
      posFilter: "ALL",
      playerMeta: META,
    });
    expect(out.map((i) => i.id)).toEqual(["x1", "x2"]);
  });

  it("single-facet position filter matches any mention at that position", () => {
    const out = filterByPlayerFacets(items, {
      teamFilter: "ALL",
      posFilter: "QB",
      playerMeta: META,
    });
    expect(out.map((i) => i.id)).toEqual(["x1", "x2"]);
  });

  it("drops general items and unresolved mentions when a facet is active", () => {
    const unresolved = {
      id: "x4",
      headline: "Unknown player note",
      players: [{ name: "Somebody Offboard" }],
    };
    const out = filterByPlayerFacets([GENERAL_ITEM, unresolved], {
      teamFilter: "DAL",
      posFilter: "ALL",
      playerMeta: META,
    });
    expect(out).toEqual([]);
  });

  it("resolves mentions through the fuzzy name normalization", () => {
    const item = {
      id: "x5",
      headline: "Hockenson update",
      players: [{ name: "TJ Hockenson" }], // no dots, unlike the row
    };
    const out = filterByPlayerFacets([item], {
      teamFilter: "MIN",
      posFilter: "TE",
      playerMeta: META,
    });
    expect(out.map((i) => i.id)).toEqual(["x5"]);
  });

  it("is defensive about bad input", () => {
    expect(filterByPlayerFacets(null, { playerMeta: META })).toEqual([]);
    expect(
      filterByPlayerFacets([DAL_QB_ITEM], {
        teamFilter: "DAL",
        posFilter: "QB",
        playerMeta: null,
      }),
    ).toEqual([]);
  });
});

describe("buildMentionButtons — every mention gets a button", () => {
  it("renders unmatched (All-scope, out-of-pool) players as general buttons", () => {
    // rankByRelevance stamped nothing for this player (or the item
    // was never scored) — the button must still render so the popup
    // link works for any player the contract knows.
    const item = {
      id: "b1",
      headline: "Out-of-pool player note",
      players: [{ name: "Unknown Guy" }],
      __matchedOn: [],
    };
    expect(buildMentionButtons(item)).toEqual([
      { name: "Unknown Guy", scope: "general" },
    ]);
  });

  it("keeps roster/league styling from __matchedOn where present", () => {
    const item = {
      id: "b2",
      headline: "Mixed mention item",
      players: [{ name: "Bijan Robinson" }, { name: "Unknown Guy" }],
      __matchedOn: [{ name: "Bijan Robinson", scope: "roster" }],
    };
    expect(buildMentionButtons(item)).toEqual([
      { name: "Bijan Robinson", scope: "roster" },
      { name: "Unknown Guy", scope: "general" },
    ]);
  });

  it("works for unscored items (no __matchedOn field at all)", () => {
    const item = {
      id: "b3",
      headline: "Raw item",
      players: [{ name: "Tee Higgins" }],
    };
    expect(buildMentionButtons(item)).toEqual([
      { name: "Tee Higgins", scope: "general" },
    ]);
  });

  it("dedupes name variants and returns [] for playerless items", () => {
    const item = {
      id: "b4",
      headline: "Duplicate mentions",
      players: [{ name: "T.J. Hockenson" }, { name: "TJ Hockenson" }],
      __matchedOn: [{ name: "TJ Hockenson", scope: "league" }],
    };
    const buttons = buildMentionButtons(item);
    expect(buttons).toHaveLength(1);
    expect(buttons[0].scope).toBe("league");
    expect(
      buildMentionButtons({ id: "b5", headline: "General", players: [] }),
    ).toEqual([]);
  });
});

describe("filterByPlayerFacets — name-collision candidates", () => {
  // One mention, TWO real candidate players behind the key.
  const COLLISION_ITEM = {
    id: "c1",
    headline: "Allen camp report",
    players: [{ name: "CJ Allen" }],
  };

  it("each colliding player is reachable under its own facets", () => {
    // The LB's facets.
    expect(
      filterByPlayerFacets([COLLISION_ITEM], {
        teamFilter: "TEN",
        posFilter: "LB",
        playerMeta: META,
      }),
    ).toHaveLength(1);
    // The WR's facets — dotted-initial mention resolves to the same
    // candidate list.
    const dotted = { ...COLLISION_ITEM, players: [{ name: "C.J. Allen" }] };
    expect(
      filterByPlayerFacets([dotted], {
        teamFilter: "ATL",
        posFilter: "WR",
        playerMeta: META,
      }),
    ).toHaveLength(1);
  });

  it("rejects cross-matched facets no single candidate satisfies", () => {
    // TEN (the LB's team) + WR (the other player's position): no ONE
    // candidate meta has both, so the item must not pass — the
    // conjunction stays within a candidate meta.
    expect(
      filterByPlayerFacets([COLLISION_ITEM], {
        teamFilter: "TEN",
        posFilter: "WR",
        playerMeta: META,
      }),
    ).toEqual([]);
    expect(
      filterByPlayerFacets([COLLISION_ITEM], {
        teamFilter: "ATL",
        posFilter: "LB",
        playerMeta: META,
      }),
    ).toEqual([]);
  });
});
