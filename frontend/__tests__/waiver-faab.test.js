// The /waivers FAAB column joins backend bids onto client-computed
// add/drop rows at render time — the same shape as the BDVM "Fund gap"
// join on /rankings.  What is pinned here:
//
//   • the join key is ``normalizeName`` (waiver-logic family 3), so it
//     agrees with the owned/my-roster Sets the rest of the page uses;
//   • the position half of the key runs through ``normalizePos`` on
//     BOTH sides, so the backend's raw "DE"/"CB" meets the board's
//     "DL"/"DB" instead of silently missing;
//   • a candidate the backend declined to price is absent, not zero;
//   • an ambiguous name (two positions, one name) resolves to NOTHING
//     rather than a guess;
//   • every failure mode collapses to a null index, which is what
//     makes the column vanish silently.
//
// And the load-bearing negative: this module derives NO bid. Every
// number that comes out is byte-identical to what the payload carried.

import { describe, it, expect } from "vitest";
import { buildWaiverBidIndex, waiverBidForRow } from "@/lib/waiver-faab";

const EGBUKA = {
  name: "Emeka Egbuka",
  position: "WR",
  consensusValue: 3100,
  adjustedValue: 3100,
  rank: 88,
  isRookie: true,
  bid: { aggressive: 12, reasonable: 8, lowball: 3 },
};

// Backend publishes the RAW contract position ("DE"); board rows carry
// the normalized family ("DL").
const BONITTO = {
  name: "Nik Bonitto",
  position: "DE",
  consensusValue: 2200,
  adjustedValue: 2200,
  rank: 210,
  isRookie: false,
  bid: { aggressive: 6, reasonable: 4, lowball: 1 },
};

// `to_dict` emits ``bid: null`` when the engine returned nothing.
const UNPRICED = {
  name: "Unpriced Guy",
  position: "WR",
  consensusValue: 900,
  adjustedValue: 900,
  rank: null,
  isRookie: false,
  bid: null,
};

function payload(overrides = {}) {
  return {
    by_position: { WR: [EGBUKA, UNPRICED], DE: [BONITTO] },
    // by_family is derived from by_position — the SAME candidate
    // objects, re-bucketed. Walking both must not double-count or
    // manufacture ambiguity.
    by_family: { WR: [EGBUKA, UNPRICED], DL: [BONITTO] },
    total: 3,
    leagueKey: "dynasty_main",
    ...overrides,
  };
}

describe("buildWaiverBidIndex", () => {
  it("indexes priced candidates and skips unpriced ones", () => {
    const index = buildWaiverBidIndex(payload());
    expect(index).not.toBeNull();
    expect(index.byName.has("emeka egbuka")).toBe(true);
    expect(index.byName.has("nik bonitto")).toBe(true);
    // bid: null ⇒ absent from the index entirely, never $0.
    expect(index.byName.has("unpriced guy")).toBe(false);
  });

  it("returns the backend's numbers verbatim — no derivation", () => {
    const index = buildWaiverBidIndex(payload());
    const bid = waiverBidForRow(index, { name: "Emeka Egbuka", pos: "WR" });
    expect(bid.aggressive).toBe(12);
    expect(bid.reasonable).toBe(8);
    expect(bid.lowball).toBe(3);
    expect(bid.consensusValue).toBe(3100);
    expect(bid.rank).toBe(88);
    expect(bid.isRookie).toBe(true);
  });

  it("a bid object with no finite reasonable is treated as unpriced", () => {
    const index = buildWaiverBidIndex({
      by_position: {
        WR: [{ ...EGBUKA, bid: { aggressive: 12, reasonable: null, lowball: 3 } }],
      },
    });
    expect(index).toBeNull();
  });

  it("returns null for every non-joinable payload shape", () => {
    expect(buildWaiverBidIndex(null)).toBeNull();
    expect(buildWaiverBidIndex(undefined)).toBeNull();
    expect(buildWaiverBidIndex({})).toBeNull();
    expect(buildWaiverBidIndex({ by_position: {}, by_family: {}, total: 0 })).toBeNull();
    // A backend error body is just another payload with nothing in it.
    expect(buildWaiverBidIndex({ error: "Live contract not loaded yet." })).toBeNull();
    expect(buildWaiverBidIndex({ by_position: { WR: [UNPRICED] } })).toBeNull();
    // Defensive against a shape change: non-array buckets don't throw.
    expect(buildWaiverBidIndex({ by_position: { WR: "nope" } })).toBeNull();
  });

  it("joins from by_family alone when by_position is absent", () => {
    const index = buildWaiverBidIndex({ by_family: { DL: [BONITTO] } });
    expect(waiverBidForRow(index, { name: "Nik Bonitto", pos: "DL" }).reasonable).toBe(4);
  });
});

describe("waiverBidForRow", () => {
  it("keys on the loose trim+lowercase name (waiver-logic parity)", () => {
    const index = buildWaiverBidIndex(payload());
    expect(waiverBidForRow(index, { name: "  EMEKA EGBUKA  " }).reasonable).toBe(8);
    expect(waiverBidForRow(index, { displayName: "emeka egbuka" }).reasonable).toBe(8);
    expect(waiverBidForRow(index, { name: "Somebody Else" })).toBeNull();
  });

  // The loose key is deliberately NOT the strict player-name key: a
  // row named "Emeka Egbuka Jr." is a different player as far as the
  // waiver ownership vocabulary is concerned, and must not inherit a
  // bid.
  it("does not collapse generational suffixes into a match", () => {
    const index = buildWaiverBidIndex(payload());
    expect(waiverBidForRow(index, { name: "Emeka Egbuka Jr." })).toBeNull();
  });

  it("normalizes position on both sides so DE meets DL", () => {
    const index = buildWaiverBidIndex(payload());
    // Board row carries the normalized family; payload carried "DE".
    expect(waiverBidForRow(index, { name: "Nik Bonitto", pos: "DL" }).reasonable).toBe(4);
    // And the raw form still resolves.
    expect(waiverBidForRow(index, { name: "Nik Bonitto", position: "DE" }).reasonable).toBe(4);
  });

  it("prefers the position-qualified entry over the bare name", () => {
    const index = buildWaiverBidIndex({
      by_position: {
        RB: [{ ...EGBUKA, name: "Chris Rodriguez", position: "RB", bid: { aggressive: 9, reasonable: 5, lowball: 2 } }],
        LB: [{ ...EGBUKA, name: "Chris Rodriguez", position: "LB", bid: { aggressive: 3, reasonable: 2, lowball: 1 } }],
      },
    });
    expect(waiverBidForRow(index, { name: "Chris Rodriguez", pos: "RB" }).reasonable).toBe(5);
    expect(waiverBidForRow(index, { name: "Chris Rodriguez", pos: "LB" }).reasonable).toBe(2);
  });

  it("an ambiguous name with no position match resolves to nothing", () => {
    const index = buildWaiverBidIndex({
      by_position: {
        RB: [{ ...EGBUKA, name: "Chris Rodriguez", position: "RB" }],
        LB: [{ ...EGBUKA, name: "Chris Rodriguez", position: "LB" }],
      },
    });
    expect(index.ambiguous.has("chris rodriguez")).toBe(true);
    expect(waiverBidForRow(index, { name: "Chris Rodriguez" })).toBeNull();
    expect(waiverBidForRow(index, { name: "Chris Rodriguez", pos: "TE" })).toBeNull();
  });

  it("duplicate by_family copies do not manufacture ambiguity", () => {
    const index = buildWaiverBidIndex(payload());
    expect(index.ambiguous.size).toBe(0);
    expect(waiverBidForRow(index, { name: "Emeka Egbuka" }).reasonable).toBe(8);
  });

  it("a null index resolves nothing — this is the silent vanish", () => {
    expect(waiverBidForRow(null, { name: "Emeka Egbuka", pos: "WR" })).toBeNull();
    expect(waiverBidForRow(buildWaiverBidIndex(payload()), null)).toBeNull();
    expect(waiverBidForRow(buildWaiverBidIndex(payload()), { name: "" })).toBeNull();
    expect(waiverBidForRow(buildWaiverBidIndex(payload()), {})).toBeNull();
  });
});
