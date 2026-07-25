import { describe, it, expect } from "vitest";
import { buildPlayerMetaIndex, filterByPlayerFacets } from "@/lib/news-filters";

const ROWS = [
  { name: "CeeDee Lamb", pos: "WR", raw: { team: "DAL" } },
  { name: "Dak Prescott", pos: "QB", raw: { team: "DAL" } },
  { name: "Russell Wilson", pos: "QB", raw: { team: "NYG" } },
  { name: "Micah Parsons", pos: "DL/EDGE", raw: { team: "DAL" } },
  { name: "T.J. Hockenson", pos: "TE", raw: { team: "MIN" } },
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
  it("maps normalized keys to team + position family", () => {
    expect(META.get("ceedee lamb")).toEqual({ team: "DAL", family: "WR" });
    // Compound position keeps the leading family only.
    expect(META.get("micah parsons").family).toBe("DL");
    // Dotted-initial names index under the collapsed key.
    expect(META.get("tj hockenson")).toEqual({ team: "MIN", family: "TE" });
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
