/**
 * Second Opinions — WHY a source does or does not cover a trade, and what
 * may be counted (#791; owner directive 2026-09-26).
 *
 * Owner observation: a trade with one IDP player showed "KeepTradeCut
 * Crowd — Incomplete", which reads like a failure. It is not: KTC
 * publishes no IDP (its registry scope is offense). And the same panel
 * published winners for offense-only vendors on IDP-only trades whose
 * every number was OUR canonical value — our opinion under their name.
 *
 * Pinned here:
 *   - a fully native row is the only opinion, and the only vote;
 *   - out-of-scope (declared registry scope) is "Not applicable", named,
 *     never "Incomplete" and never counted;
 *   - a vendor with no native piece leaves the table and is named below
 *     it — never a verdict built on imputed values;
 *   - an in-scope gap is "Incomplete" with its reason;
 *   - canonical imputation never becomes a KTC opinion;
 *   - one vote per independent family, a split family counts once.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render } from "@testing-library/react";

import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import {
  ASSET_COVERAGE,
  VENDOR_VERDICT,
  assetCoverage,
  tallySecondOpinions,
  vendorAdmitsAssetClass,
  vendorVerdict,
} from "@/lib/second-opinions";

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    // Real registry shapes (scope / extraScopes / correlationGroup) for
    // the sources the cases need.
    RANKING_SOURCES: [
      {
        key: "ktcCrowdSfTep",
        displayName: "KTC Crowd",
        columnLabel: "KTC Crowd",
        scope: "overall_offense",
        correlationGroup: "ktcCrowd",
      },
      {
        key: "idpTradeCalc",
        displayName: "IDP Trade Calc",
        columnLabel: "IDPTC",
        scope: "overall_idp",
        extraScopes: ["overall_offense"],
      },
      {
        key: "fantasyNavigatorSf",
        displayName: "Fantasy Navigator",
        columnLabel: "FN",
        scope: "overall_offense",
        correlationGroup: "ktcCrowd",
      },
      {
        key: "fantasyCalc",
        displayName: "FantasyCalc",
        columnLabel: "FC",
        scope: "overall_offense",
      },
      {
        key: "fantasyProsSf",
        displayName: "FantasyPros SF",
        columnLabel: "FP",
        scope: "overall_offense",
        correlationGroup: "fantasyPros",
      },
      {
        key: "fantasyProsFitzmaurice",
        displayName: "Fitzmaurice",
        columnLabel: "Fitz",
        scope: "overall_offense",
        correlationGroup: "fantasyPros",
      },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

const TRANSLATED = [
  "idpTradeCalc",
  "fantasyNavigatorSf",
  "fantasyCalc",
  "fantasyProsSf",
  "fantasyProsFitzmaurice",
];

/** A materialized board row. `covers` maps source key → contribution. */
function asset({ name, assetClass, canonical, ktc = null, covers = {}, unmatched }) {
  const sourceRankMeta = {};
  for (const [k, v] of Object.entries(covers)) sourceRankMeta[k] = { valueContribution: v };
  return {
    name,
    displayName: name,
    assetClass,
    rankDerivedValue: canonical,
    values: { full: canonical },
    sourceRankMeta,
    rawSourceValues: ktc == null ? {} : { ktcCrowdSfTep: ktc },
    canonicalSites: {},
    ...(unmatched ? { sourceAudit: { unmatchedSources: unmatched } } : {}),
  };
}

function offense(name, canonical, overrides = {}) {
  const covers = {};
  for (const k of TRANSLATED) covers[k] = canonical;
  return asset({
    name,
    assetClass: "offense",
    canonical,
    ktc: canonical,
    covers: { ...covers, ...(overrides.covers || {}) },
    ...overrides,
  });
}

function idp(name, canonical) {
  return asset({ name, assetClass: "idp", canonical, covers: { idpTradeCalc: canonical } });
}

function view(sides) {
  const { container, unmount } = render(<TradeSourceBreakdown sides={sides} settings={{}} />);
  const rows = {};
  for (const tr of container.querySelectorAll("tbody tr")) {
    const cells = [...tr.querySelectorAll("td")].map((td) => (td.textContent || "").trim());
    rows[cells[0].replace(/(native value|translated rank)$/, "").trim()] = cells;
  }
  const tally = container.querySelector('[data-testid="second-opinions-tally"]')?.textContent || "";
  const uncovered =
    container.querySelector('[data-testid="second-opinions-uncovered"]')?.textContent || "";
  const text = container.textContent || "";
  unmount();
  return { rows, tally, uncovered, text };
}

const winnerCell = (cells, nSides = 2) => cells[1 + nSides];

describe("offense-only trade with full KTC coverage", () => {
  it("KTC votes, and a correlated family votes once", () => {
    const { rows, tally } = view([
      { label: "A", assets: [offense("Star WR", 8000)] },
      { label: "B", assets: [offense("Good RB", 6000)] },
    ]);
    expect(winnerCell(rows["KTC Crowd"])).toMatch(/^Side A/);
    // Families: ktcCrowd (KTC Crowd + FN), IDPTC, FC, fantasyPros (FP + Fitz).
    expect(tally).toMatch(/Side A 4 · Side B 0/);
    expect(tally).toMatch(/independent source family \(4\)/);
  });
});

describe("IDP-only trade", () => {
  const view_ = () =>
    view([
      { label: "A", assets: [idp("Star LB", 5000)] },
      { label: "B", assets: [idp("Edge DL", 4000)] },
    ]);

  it("offense-only vendors publish no winner and are named as not applicable", () => {
    const { rows, uncovered } = view_();
    for (const label of ["KTC Crowd", "FN", "FC", "FP", "Fitz"]) {
      expect(rows[label]).toBeUndefined();
    }
    expect(uncovered).toMatch(/Not applicable — KTC Crowd, FN, FC, FP, Fitz don't price IDP/);
  });

  it("the IDP-covering source is the one real opinion", () => {
    const { rows, tally } = view_();
    expect(winnerCell(rows.IDPTC)).toMatch(/^Side A/);
    expect(tally).toMatch(/Side A 1 · Side B 0/);
  });
});

describe("mixed offense + IDP trade", () => {
  it("KTC is not applicable, names the IDP piece, and is not counted", () => {
    const { rows, tally } = view([
      { label: "A", assets: [offense("WR", 6000)] },
      { label: "B", assets: [offense("RB", 4000), idp("LB", 2500)] },
    ]);
    const cells = rows["KTC Crowd"];
    expect(winnerCell(cells)).toMatch(/^Not applicable/);
    expect(winnerCell(cells)).toMatch(/Doesn't price IDP \(1 of 3 pieces\)/);
    expect(cells[4]).toBe("—");
    // Only IDPTC covers all three natively.
    expect(tally).toMatch(/independent source family \(1\)/);
    expect(tally).toMatch(/Not counted: 5 not applicable/);
    // Offense-only translated vendors are not applicable either — the LB
    // piece would otherwise be priced with our value under their name.
    expect(winnerCell(rows.FC)).toMatch(/^Not applicable/);
  });
});

describe("in-scope gaps are incomplete, with the reason", () => {
  it("a genuinely missing KTC offense row reads Incomplete, not not-applicable", () => {
    const missing = asset({
      name: "Deep WR",
      assetClass: "offense",
      canonical: 900,
      covers: Object.fromEntries(TRANSLATED.map((k) => [k, 900])),
      unmatched: ["ktcCrowdSfTep"],
    });
    const { rows, tally } = view([
      { label: "A", assets: [offense("WR", 6000), missing] },
      { label: "B", assets: [offense("RB", 6500)] },
    ]);
    expect(winnerCell(rows["KTC Crowd"])).toMatch(/^Incomplete/);
    expect(winnerCell(rows["KTC Crowd"])).toMatch(/No value published for 1 of 3 pieces/);
    expect(tally).toMatch(/1 incomplete/);
  });

  it("canonical imputation never becomes a KTC opinion", () => {
    const noKtc = asset({ name: "No KTC", assetClass: "offense", canonical: 4000 });
    const { rows } = view([
      { label: "A", assets: [offense("WR", 5000), noKtc] },
      { label: "B", assets: [offense("RB", 3000)] },
    ]);
    const cells = rows["KTC Crowd"];
    expect(winnerCell(cells)).toMatch(/^Incomplete/);
    expect(cells[1]).not.toBe("9,000"); // 5000 native + 4000 of ours
  });

  it("an imputed in-scope gap is an estimate, shown but never counted", () => {
    const partial = asset({
      name: "FC gap",
      assetClass: "offense",
      canonical: 3000,
      ktc: 3000,
      covers: Object.fromEntries(TRANSLATED.filter((k) => k !== "fantasyCalc").map((k) => [k, 3000])),
    });
    const { rows, tally } = view([
      { label: "A", assets: [offense("WR", 6000), partial] },
      { label: "B", assets: [offense("RB", 7000)] },
    ]);
    expect(winnerCell(rows.FC)).toMatch(/\(est\.\)/);
    expect(winnerCell(rows.FC)).toMatch(/1 of 3 pieces use our value/);
    expect(tally).toMatch(/1 estimated/);
    // FC is its own family; it leaves the vote, the other three remain.
    expect(tally).toMatch(/independent source family \(3\)/);
  });

  it("an unresolved piece is incomplete, not zero", () => {
    const { rows } = view([
      { label: "A", assets: [offense("WR", 6000), null] },
      { label: "B", assets: [offense("RB", 1000)] },
    ]);
    expect(winnerCell(rows["KTC Crowd"])).toMatch(/^Incomplete/);
    expect(winnerCell(rows["KTC Crowd"])).toMatch(/1 piece not on the board/);
  });
});

describe("tally", () => {
  it("a family whose members disagree is one split, not a vote each way", () => {
    const a = offense("WR", 6000, { covers: { fantasyProsSf: 7000, fantasyProsFitzmaurice: 5000 } });
    const b = offense("RB", 6000);
    const { tally } = view([
      { label: "A", assets: [a] },
      { label: "B", assets: [b] },
    ]);
    expect(tally).toMatch(/Split 1/);
  });

  it("counts only COUNTED rows, one per family", () => {
    const t = tallySecondOpinions(
      [
        { key: "x", family: "f1", verdict: { state: VENDOR_VERDICT.COUNTED }, winnerIdx: 0 },
        { key: "y", family: "f1", verdict: { state: VENDOR_VERDICT.COUNTED }, winnerIdx: 0 },
        { key: "z", family: "f2", verdict: { state: VENDOR_VERDICT.COUNTED }, winnerIdx: null },
        { key: "k", family: "f3", verdict: { state: VENDOR_VERDICT.NOT_APPLICABLE }, winnerIdx: 1 },
        { key: "e", family: "f4", verdict: { state: VENDOR_VERDICT.ESTIMATE }, winnerIdx: 1 },
      ],
      2,
    );
    expect(t.wins).toEqual([1, 0]);
    expect(t.even).toBe(1);
    expect(t.families).toBe(2);
    expect(t.notCounted).toEqual({ estimate: 1, notApplicable: 1, incomplete: 0 });
  });
});

describe("scope is proven only by a declared registry scope", () => {
  const offenseOnly = [{ key: "k", scope: "overall_offense" }];
  it("an IDP player is out of scope for an offense-only board", () => {
    expect(vendorAdmitsAssetClass(offenseOnly, "idp")).toBe(false);
    expect(vendorAdmitsAssetClass(offenseOnly, "offense")).toBe(true);
  });
  it("extra scopes admit", () => {
    expect(
      vendorAdmitsAssetClass([{ key: "i", scope: "overall_idp", extraScopes: ["overall_offense"] }], "offense"),
    ).toBe(true);
  });
  it("picks and undeclared scopes are unknown, never out of scope", () => {
    expect(vendorAdmitsAssetClass(offenseOnly, "pick")).toBeNull();
    expect(vendorAdmitsAssetClass([{ key: "n" }], "idp")).toBeNull();
    const pick = { assetClass: "pick", sourceRankMeta: {} };
    expect(assetCoverage({ row: pick, subs: offenseOnly, resolution: { value: null } }).status).toBe(
      ASSET_COVERAGE.NOT_PUBLISHED,
    );
  });
  it("a vendor with no native piece has no coverage, whatever was imputed", () => {
    const imputedOnly = [[{ status: ASSET_COVERAGE.NOT_PUBLISHED, imputed: true }]];
    expect(vendorVerdict(imputedOnly).state).toBe(VENDOR_VERDICT.NO_COVERAGE);
  });
});
