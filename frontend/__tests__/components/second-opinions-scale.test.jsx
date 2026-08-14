/**
 * Second Opinions — every number entering package math has a declared,
 * compatible unit.
 *
 * WHAT THE PANEL DOES
 * -------------------
 * `TradeSourceBreakdown` re-answers "is this trade fair?" once per
 * vendor. A vendor's covered assets use
 * `sourceRankMeta[key].valueContribution` — the source's signal after
 * canonical normalization. When a vendor does not cover an asset, the
 * "Fill uncovered pieces with our value" toggle substitutes a Chase
 * Upside value so the vendor can still produce a complete opinion.
 *
 * That product behaviour is wanted. The mathematics is only valid if
 * the substituted number is in a unit system compatible with the
 * vendor values it is summed with, before Value Adjustment runs.
 *
 * NUMERIC RANGE EQUALITY IS NOT UNIT COMPATIBILITY. Measured on the
 * tracked 2026-08-14 board:
 *
 *   rawComposite / canonical   n=805   median 1.063
 *                                      p10 0.915  p90 1.262
 *                                      min 0.266  max 2.082
 *
 * Both live in "roughly 0-9999", and substituting one for the other is
 * wrong by up to a factor of two on a single row.
 *
 * THE DEFECT
 * ----------
 * The fallback was `effectiveValue(row, valueMode, settings)`, and
 * `effectiveValue` returns `row.values[valueMode]`. `valueMode` is the
 * Trade Calculator's DISPLAY toggle, passed straight in from
 * `/trade/page.jsx`. So flipping a diagnostic control from "Our value"
 * to "Raw" silently changed the unit system underneath Second
 * Opinions' arithmetic: `values.raw` is the legacy scraper composite,
 * summed alongside canonical-scale vendor contributions and fed into a
 * NONLINEAR Value Adjustment.
 *
 * A user's display selection may not change the math basis.
 */
import { describe, it, expect, vi } from "vitest";
import React from "react";
import { render, act } from "@testing-library/react";

import TradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";

vi.mock("@/lib/dynasty-data", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    RANKING_SOURCES: [
      { key: "dlfSf", displayName: "DLF SF", columnLabel: "DLF" },
      { key: "ktcSfTep", displayName: "KTC TE++", columnLabel: "KTC" },
    ],
    SOURCE_VENDOR_LABELS: {},
    vendorForSource: (key) => key,
  };
});

/**
 * One asset. `canonical` and `rawComposite` are deliberately far apart
 * so a substitution of one for the other cannot be mistaken for
 * rounding.
 */
function asset({
  name,
  canonical,
  rawComposite,
  covers = {},
  ktcNative = null,
}) {
  const sourceRankMeta = {};
  for (const [key, valueContribution] of Object.entries(covers)) {
    sourceRankMeta[key] = { valueContribution };
  }
  return {
    name,
    displayName: name,
    canonicalName: name,
    rankDerivedValue: canonical,
    values: { full: canonical, raw: rawComposite },
    sourceRankMeta,
    rawSourceValues: ktcNative == null ? {} : { ktcSfTep: ktcNative },
    canonicalSites: {},
  };
}

/**
 * Render and return the table CELLS.
 *
 * Cell-by-cell rather than a regex over `textContent`: adjacent cells
 * concatenate ("9000" + "3000" -> "90003000") and a whole-text regex
 * then reads a number that was never displayed.
 *
 * `valueMode` is still passed to prove the component IGNORES it — the
 * prop is gone from the signature, and a stray one must not resurrect
 * the old behaviour.
 */
function renderCells(sides, valueMode) {
  const { container, unmount } = render(
    <TradeSourceBreakdown sides={sides} settings={{}} valueMode={valueMode} />,
  );
  const cells = Array.from(container.querySelectorAll("td")).map((td) =>
    (td.textContent || "").trim(),
  );
  const text = container.textContent || "";
  unmount();
  return { cells, text };
}

/** Numeric cell contents, e.g. "9,000" -> 9000. */
function numbersIn(cells) {
  return cells
    .filter((c) => /^[\d,]+$/.test(c) && c !== "")
    .map((c) => Number(c.replace(/,/g, "")));
}

describe("Second Opinions does not inherit the display value mode", () => {
  // DLF covers one asset and not the other, so the uncovered one goes
  // through the fallback — which is the whole subject.
  const sides = [
    {
      label: "A",
      assets: [
        asset({
          name: "Covered",
          canonical: 5000,
          rawComposite: 5900,
          covers: { dlfSf: 5000 },
        }),
        asset({ name: "Uncovered", canonical: 4000, rawComposite: 4800 }),
      ],
    },
    {
      label: "B",
      assets: [
        asset({
          name: "Other",
          canonical: 3000,
          rawComposite: 3600,
          covers: { dlfSf: 3000 },
        }),
      ],
    },
  ];

  it("renders the same arithmetic under full and raw", () => {
    const full = renderCells(sides, "full").cells;
    const raw = renderCells(sides, "raw").cells;

    expect(raw).toEqual(full);
  });

  it("imputes the canonical value, not the legacy composite", () => {
    // Uncovered asset: canonical 4000, rawComposite 4800. The DLF row's
    // side-A total must be 5000 + 4000 = 9000, never 5000 + 4800 = 9800.
    const seen = numbersIn(renderCells(sides, "full").cells);

    expect(seen).toContain(9000);
    expect(seen).not.toContain(9800);
  });

  it("still imputes the canonical value when the display mode is raw", () => {
    const seen = numbersIn(renderCells(sides, "raw").cells);

    expect(seen).toContain(9000);
    expect(seen).not.toContain(9800);
  });
});

describe("Second Opinions does not treat a missing value as zero", () => {
  it("an asset with no canonical value is not summed as a zero-value piece", () => {
    // No vendor coverage AND no canonical value: the honest answer is
    // that this vendor's opinion of the trade is incomplete, not that
    // the asset is worthless.
    const sides = [
      {
        label: "A",
        assets: [
          asset({
            name: "Priced",
            canonical: 5000,
            rawComposite: 5900,
            covers: { dlfSf: 5000 },
          }),
          {
            name: "Unpriced",
            displayName: "Unpriced",
            values: {},
            sourceRankMeta: {},
            rawSourceValues: {},
            canonicalSites: {},
          },
        ],
      },
      {
        label: "B",
        assets: [
          asset({
            name: "Other",
            canonical: 3000,
            rawComposite: 3600,
            covers: { dlfSf: 3000 },
          }),
        ],
      },
    ];

    const { text } = renderCells(sides, "full");

    // 5000 + 0 = 5000 would be the defect: an unpriced asset silently
    // contributing nothing while the row still claims a full verdict.
    expect(text).toMatch(/incomplete|partial|unresolved/i);
  });
});

describe("KTC is not imputed into, because its basis is not ours", () => {
  /**
   * KTC's covered assets use KTC-NATIVE values on purpose: the V13 VA
   * formula and its raw-difference suppression thresholds were
   * calibrated against them.
   *
   * Dropping a canonical value into that array would only be valid if
   * the two were interchangeable. Measured over the 385 players
   * carrying both on the 2026-08-14 board:
   *
   *   KTC native / canonical   median 1.091  min 0.400  max 1.491
   *     top (>=7000)           median 0.947
   *     middle (3000-7000)     median 1.027
   *     tail (<3000)           median 1.142
   *
   * Not identity, and not a constant — it drifts with board depth, so
   * the error's DIRECTION depends on where the player sits. Inside a
   * nonlinear VA that compares raw differences, that is not rounding.
   *
   * So an asset KTC does not cover makes KTC's opinion INCOMPLETE. We
   * do not manufacture KTC's view of a player it never published.
   */
  it("reports incomplete rather than substituting our canonical value", () => {
    const sides = [
      {
        label: "A",
        assets: [
          asset({
            name: "KTC has this",
            canonical: 5000,
            rawComposite: 5900,
            ktcNative: 5200,
          }),
          asset({
            name: "KTC lacks this",
            canonical: 4000,
            rawComposite: 4800,
          }),
        ],
      },
      {
        label: "B",
        assets: [
          asset({
            name: "Other",
            canonical: 3000,
            rawComposite: 3600,
            ktcNative: 3100,
          }),
        ],
      },
    ];

    const { cells, text } = renderCells(sides, "full");
    const seen = numbersIn(cells);

    expect(text).toMatch(/incomplete/i);
    // 5200 + 4000 would be canonical imputed into a KTC-native array.
    expect(seen).not.toContain(9200);
  });
});

describe("Foreign vendor-native scales never reach package math", () => {
  it("uses the normalized contribution, not the vendor's own published number", () => {
    // A source publishing 72 on its own 0-100 scale while its
    // normalized contribution is 5600. Summing 72 with canonical-scale
    // numbers would be the same defect class as rawComposite.
    const row = asset({
      name: "Scaled",
      canonical: 5600,
      rawComposite: 6100,
      covers: { dlfSf: 5600 },
    });
    row.sourceNativeValues = { dlfSf: 72 };
    row.canonicalSites = { dlfSf: 100072 }; // synthetic rank encoding

    const sides = [
      { label: "A", assets: [row] },
      {
        label: "B",
        assets: [
          asset({
            name: "Other",
            canonical: 3000,
            rawComposite: 3600,
            covers: { dlfSf: 3000 },
          }),
        ],
      },
    ];

    const seen = numbersIn(renderCells(sides, "full").cells);

    expect(seen).toContain(5600);
    expect(seen).not.toContain(72);
    expect(seen).not.toContain(100072);
  });
});

describe("Strict mode keeps its meaning", () => {
  it("uncovered pieces are unresolved, not zero-valued", () => {
    const sides = [
      {
        label: "A",
        assets: [
          asset({
            name: "Covered",
            canonical: 5000,
            rawComposite: 5900,
            covers: { dlfSf: 5000 },
          }),
          asset({ name: "Uncovered", canonical: 4000, rawComposite: 4800 }),
        ],
      },
      {
        label: "B",
        assets: [
          asset({
            name: "Other",
            canonical: 3000,
            rawComposite: 3600,
            covers: { dlfSf: 3000 },
          }),
        ],
      },
    ];

    const { container, unmount } = render(
      <TradeSourceBreakdown sides={sides} settings={{}} />,
    );
    const toggle = container.querySelector('input[type="checkbox"]');
    act(() => {
      toggle.click();
    });
    const text = container.textContent || "";
    unmount();

    // With imputation off the vendor covers only part of the trade, so
    // the honest report is incomplete — not a 5,000-vs-3,000 verdict
    // built on an asset silently priced at nothing.
    expect(text).toMatch(/incomplete/i);
  });
});

describe("Multi-team trades hold the same unit invariants", () => {
  it("three sides render identically under full and raw", () => {
    const sides = [
      {
        label: "A",
        assets: [
          asset({
            name: "A1",
            canonical: 5000,
            rawComposite: 5900,
            covers: { dlfSf: 5000 },
          }),
        ],
      },
      {
        label: "B",
        assets: [asset({ name: "B1", canonical: 4000, rawComposite: 4800 })],
      },
      {
        label: "C",
        assets: [
          asset({
            name: "C1",
            canonical: 3000,
            rawComposite: 3600,
            covers: { dlfSf: 3000 },
          }),
        ],
      },
    ];

    expect(renderCells(sides, "raw").cells).toEqual(
      renderCells(sides, "full").cells,
    );
  });
});
