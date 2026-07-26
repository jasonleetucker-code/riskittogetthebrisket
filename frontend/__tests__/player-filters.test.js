/**
 * player-filters.js — Phase 3 filter-engine tests.
 *
 * Pure-predicate coverage: every criterion alone, fail-closed
 * semantics for unknown fields under range filters, owner mapping via
 * the league-scoped teamByPlayer join, and the token search grammar.
 */
import { describe, expect, it } from "vitest";

import {
  EXPERIENCE_BUCKETS,
  FREE_AGENT_OWNER,
  filterRows,
  matchesQuery,
  rowMatches,
  teamOptions,
} from "../lib/player-filters.js";

const row = (over = {}) => ({
  name: "Test Player",
  pos: "WR",
  team: "CHI",
  age: 25,
  yearsExp: 3,
  rookie: false,
  canonicalConsensusRank: 40,
  rankDerivedValue: 5000,
  canonicalTierId: 3,
  marketGapDirection: "none",
  ...over,
});

describe("rowMatches — individual criteria", () => {
  it("empty criteria matches everything", () => {
    expect(rowMatches(row(), {})).toBe(true);
  });

  it("positions set", () => {
    expect(rowMatches(row(), { positions: new Set(["WR"]) })).toBe(true);
    expect(rowMatches(row(), { positions: new Set(["QB"]) })).toBe(false);
  });

  it("age range is inclusive and fails closed on unknown age", () => {
    expect(rowMatches(row(), { ageMin: 25, ageMax: 25 })).toBe(true);
    expect(rowMatches(row({ age: null }), { ageMin: 20 })).toBe(false);
    expect(rowMatches(row(), { ageMax: 24 })).toBe(false);
  });

  it("experience buckets map yearsExp", () => {
    expect(rowMatches(row({ yearsExp: 0 }), { experience: "rookie" })).toBe(true);
    expect(rowMatches(row({ yearsExp: 1 }), { experience: "sophomore" })).toBe(true);
    expect(rowMatches(row({ yearsExp: 7 }), { experience: "vet" })).toBe(true);
    expect(rowMatches(row({ yearsExp: 0 }), { experience: "vet" })).toBe(false);
    // unknown experience fails closed under an experience filter
    expect(rowMatches(row({ yearsExp: null }), { experience: "vet" })).toBe(false);
  });

  it("nfl team incl. FA", () => {
    expect(rowMatches(row(), { nflTeam: "chi" })).toBe(true);
    expect(rowMatches(row({ team: "FA" }), { nflTeam: "FA" })).toBe(true);
    expect(rowMatches(row({ team: null }), { nflTeam: "CHI" })).toBe(false);
  });

  it("owner filter uses the teamByPlayer join, FREE_AGENT_OWNER matches unmapped", () => {
    const extras = { teamByPlayer: { "test player": "Brisket Bros" } };
    expect(rowMatches(row(), { ownerTeam: "Brisket Bros" }, extras)).toBe(true);
    expect(rowMatches(row(), { ownerTeam: "Other Team" }, extras)).toBe(false);
    expect(rowMatches(row(), { ownerTeam: FREE_AGENT_OWNER }, extras)).toBe(false);
    expect(rowMatches(row({ name: "Nobody Owns Me" }), { ownerTeam: FREE_AGENT_OWNER }, extras)).toBe(true);
  });

  it("rank / value ranges and tier", () => {
    expect(rowMatches(row(), { rankMin: 1, rankMax: 40 })).toBe(true);
    expect(rowMatches(row(), { rankMax: 39 })).toBe(false);
    expect(rowMatches(row({ canonicalConsensusRank: null }), { rankMax: 100 })).toBe(false);
    expect(rowMatches(row(), { valueMin: 5000 })).toBe(true);
    expect(rowMatches(row(), { valueMin: 5001 })).toBe(false);
    expect(rowMatches(row(), { tier: 3 })).toBe(true);
    expect(rowMatches(row(), { tier: 2 })).toBe(false);
  });

  it("edge direction maps buy/sell to marketGapDirection", () => {
    expect(rowMatches(row({ marketGapDirection: "consensus_higher" }), { edge: "buy" })).toBe(true);
    expect(rowMatches(row({ marketGapDirection: "market_higher" }), { edge: "sell" })).toBe(true);
    expect(rowMatches(row(), { edge: "buy" })).toBe(false);
  });

  it("rookieOnly and watchlist", () => {
    expect(rowMatches(row({ rookie: true }), { rookieOnly: true })).toBe(true);
    expect(rowMatches(row(), { rookieOnly: true })).toBe(false);
    expect(rowMatches(row(), { watchlist: new Set(["test player"]) })).toBe(true);
    expect(rowMatches(row(), { watchlist: new Set(["someone else"]) })).toBe(false);
  });
});

describe("matchesQuery — token grammar", () => {
  it("all tokens must match across name/team/pos/owner", () => {
    expect(matchesQuery(row(), "test")).toBe(true);
    expect(matchesQuery(row(), "wr chi")).toBe(true);
    expect(matchesQuery(row(), "qb chi")).toBe(false);
  });

  it("explicit prefixes", () => {
    const extras = { teamByPlayer: { "test player": "Brisket Bros" } };
    expect(matchesQuery(row(), "owner:brisket", extras)).toBe(true);
    expect(matchesQuery(row(), "owner:nope", extras)).toBe(false);
    expect(matchesQuery(row(), "team:chi pos:wr")).toBe(true);
    expect(matchesQuery(row(), "pos:qb")).toBe(false);
  });

  it("empty query matches", () => {
    expect(matchesQuery(row(), "")).toBe(true);
  });
});

describe("filterRows + teamOptions", () => {
  it("no active criteria returns the same array reference", () => {
    const rows = [row()];
    expect(filterRows(rows, {})).toBe(rows);
  });

  it("combined criteria conjunct", () => {
    const rows = [
      row({ name: "A", pos: "WR", age: 22, yearsExp: 1 }),
      row({ name: "B", pos: "WR", age: 29, yearsExp: 7 }),
      row({ name: "C", pos: "QB", age: 22, yearsExp: 1 }),
    ];
    const out = filterRows(rows, { positions: new Set(["WR"]), ageMax: 25 });
    expect(out.map((r) => r.name)).toEqual(["A"]);
  });

  it("teamOptions sorts FA last and drops unknowns", () => {
    const rows = [row({ team: "GB" }), row({ team: "FA" }), row({ team: "ARI" }), row({ team: null })];
    expect(teamOptions(rows)).toEqual(["ARI", "GB", "FA"]);
  });

  it("EXPERIENCE_BUCKETS covers 0/1/2+ exhaustively", () => {
    for (const y of [0, 1, 2, 5, 15]) {
      const matches = EXPERIENCE_BUCKETS.filter((b) => b.match(y));
      expect(matches.length).toBe(1);
    }
  });
});
