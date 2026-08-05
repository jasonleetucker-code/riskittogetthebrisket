/**
 * The trade calculator's only search box must offer the current class.
 *
 * Audit finding W08-F004. `searchAssets()` filtered out every row
 * matching `r.assetClass === "pick" && /^2026\b/.test(r.name)`, and the
 * same hardcoded regex sat at three more call sites (both balancer
 * pools, twice each). Measured in a real browser through request
 * interception: typing "2026" or "2026 Pick 1.0" into the Side A search
 * box returned ZERO results while "2027 Mid 1st" returned a row — so
 * the current rookie class, the most-traded asset type in dynasty, read
 * as absent from the app rather than deliberately filtered. The
 * contract exposes `currentDraftYear` and the page already resolves it;
 * none of the four sites used it, so from 2027 the filter would have
 * excluded the wrong year.
 *
 * What the filter was reaching for is a real property, and the contract
 * already stamps it: `pickGenericSuppressed` marks the generic tier
 * rows the backend cleared because a slot-specific sibling exists. Those
 * are duplicates of a priced row, and they are the ONLY rows a trade
 * asset picker should hide.
 *
 * Audit finding W08-F006 covers the other half: an unpriced row stays
 * offerable (hiding 260 of 1,072 rows would be a bigger lie) but must be
 * identifiable as unpriced rather than cheap.
 */
import { describe, expect, it } from "vitest";
import {
  isSuppressedGenericPickRow,
  isTradeableBoardRow,
  isUnpricedBoardRow,
  searchTradeAssets,
} from "@/lib/trade-logic";

/** The live board's pick shape for the current and future years. */
function boardRows() {
  return [
    // Current year: the generic tier rows are suppressed ALIASES...
    {
      name: "2026 Early 1st",
      assetClass: "pick",
      pickGenericSuppressed: true,
      rankDerivedValue: null,
      values: { full: 0 },
      blendedSourceRank: null,
    },
    {
      name: "2026 Mid 1st",
      assetClass: "pick",
      pickGenericSuppressed: true,
      rankDerivedValue: null,
      values: { full: 0 },
      blendedSourceRank: null,
    },
    // ...and the SLOT rows are what the board is priced on.
    {
      name: "2026 Pick 1.01",
      assetClass: "pick",
      rankDerivedValue: 7799,
      values: { full: 7799 },
      blendedSourceRank: 12,
    },
    {
      name: "2026 Pick 1.06",
      assetClass: "pick",
      rankDerivedValue: 4987,
      values: { full: 4987 },
      blendedSourceRank: 52,
    },
    // Future year: the generic row IS the priced row.
    {
      name: "2027 Mid 1st",
      assetClass: "pick",
      rankDerivedValue: 5606,
      values: { full: 5606 },
      blendedSourceRank: 48,
    },
    // A pick the board declines to price.
    {
      name: "2028 Mid 6th",
      assetClass: "pick",
      rankDerivedValue: null,
      values: { full: 0 },
      blendedSourceRank: null,
    },
    { name: "Bijan Robinson", assetClass: "offense", rankDerivedValue: 8000, values: { full: 8000 }, blendedSourceRank: 3 },
  ];
}

describe("trade asset eligibility", () => {
  it("offers current-year slot picks — the defect's exact query", () => {
    const hits = searchTradeAssets(boardRows(), "2026", new Set());
    expect(hits.map((r) => r.name)).toEqual(["2026 Pick 1.01", "2026 Pick 1.06"]);
  });

  it("offers a specific current-year slot pick by name", () => {
    const hits = searchTradeAssets(boardRows(), "2026 Pick 1.0", new Set());
    expect(hits.length).toBeGreaterThan(0);
  });

  it("still hides the suppressed generic aliases — they duplicate a priced row", () => {
    const hits = searchTradeAssets(boardRows(), "2026", new Set());
    expect(hits.map((r) => r.name)).not.toContain("2026 Early 1st");
    expect(hits.map((r) => r.name)).not.toContain("2026 Mid 1st");
  });

  it("keeps offering future-year picks, which already worked", () => {
    const hits = searchTradeAssets(boardRows(), "2027 Mid 1st", new Set());
    expect(hits.map((r) => r.name)).toEqual(["2027 Mid 1st"]);
  });

  it("does not exclude by year, so 2027 is not broken from 2027 onward", () => {
    // The old rule was `/^2026\b/`; a year-agnostic rule must treat a
    // future-year slot row exactly like a current-year one.
    const rows = [
      ...boardRows(),
      {
        name: "2027 Pick 1.01",
        assetClass: "pick",
        rankDerivedValue: 7000,
        values: { full: 7000 },
        blendedSourceRank: 20,
      },
    ];
    expect(searchTradeAssets(rows, "2027 Pick", new Set()).map((r) => r.name)).toEqual([
      "2027 Pick 1.01",
    ]);
  });

  it("excludes anything already in the trade", () => {
    const hits = searchTradeAssets(boardRows(), "2026", new Set(["2026 Pick 1.01"]));
    expect(hits.map((r) => r.name)).toEqual(["2026 Pick 1.06"]);
  });

  it("sorts by blended source rank", () => {
    const hits = searchTradeAssets(boardRows(), "2026 Pick", new Set());
    expect(hits[0].name).toBe("2026 Pick 1.01");
  });

  it("reads the suppression stamp under `raw` too", () => {
    // The materializer keeps the whole backend row under `raw`.
    const row = { name: "2026 Mid 1st", assetClass: "pick", raw: { pickGenericSuppressed: true } };
    expect(isSuppressedGenericPickRow(row)).toBe(true);
    expect(isTradeableBoardRow(row)).toBe(false);
  });

  it("never hides a player row", () => {
    expect(isTradeableBoardRow({ name: "Bijan Robinson", assetClass: "offense" })).toBe(true);
  });
});

describe("unpriced assets stay offerable but identifiable", () => {
  it("marks a row the board declined to price", () => {
    const rows = boardRows();
    expect(isUnpricedBoardRow(rows.find((r) => r.name === "2028 Mid 6th"))).toBe(true);
  });

  it("does not mark a priced row", () => {
    const rows = boardRows();
    expect(isUnpricedBoardRow(rows.find((r) => r.name === "2027 Mid 1st"))).toBe(false);
  });

  it("still returns the unpriced row from a search", () => {
    // Hiding it would be a bigger lie than showing it: 260 of 1,072
    // live rows are unpriced, including 48 of 216 roster picks.
    const hits = searchTradeAssets(boardRows(), "2028 Mid 6th", new Set());
    expect(hits.map((r) => r.name)).toEqual(["2028 Mid 6th"]);
  });
});

describe("the page uses the rule, not a hardcoded year", () => {
  it("app/trade/page.jsx spells no literal draft year in an asset filter", async () => {
    // This is the assertion that would have been red for the RIGHT
    // reason before the fix: the defect was four copies of `/^2026\b/`
    // in page.jsx, and a helper in lib/ that the page does not call
    // fixes nothing. A literal year here is also a time bomb — the
    // filter silently targets the wrong class from 2027 onward.
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const path = fileURLToPath(new URL("../app/trade/page.jsx", import.meta.url));
    const src = readFileSync(path, "utf8");
    const code = src
      .split("\n")
      .filter((line) => !/^\s*(\/\/|\*|\/\*)/.test(line))
      .join("\n");
    expect(code).not.toMatch(/\/\^20\d{2}\\b\//);
    expect(code).toContain("isTradeableBoardRow");
  });
});
