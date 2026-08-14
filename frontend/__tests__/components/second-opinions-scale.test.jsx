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
import { render, screen } from "@testing-library/react";

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
function asset({ name, canonical, rawComposite, covers = {}, ktcNative = null }) {
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

function renderPanel(sides, valueMode) {
  const { container, unmount } = render(
    <TradeSourceBreakdown sides={sides} settings={{}} valueMode={valueMode} />,
  );
  const text = container.textContent || "";
  unmount();
  return text;
}

/** Every number the table rendered, so a total can be compared. */
function numbersIn(text) {
  return (text.match(/[\d,]+/g) || []).map((s) => Number(s.replace(/,/g, "")));
}

describe("Second Opinions does not inherit the display value mode", () => {
  // DLF covers one asset and not the other, so the uncovered one goes
  // through the fallback — which is the whole subject.
  const sides = [
    {
      label: "A",
      assets: [
        asset({ name: "Covered", canonical: 5000, rawComposite: 5900, covers: { dlfSf: 5000 } }),
        asset({ name: "Uncovered", canonical: 4000, rawComposite: 4800 }),
      ],
    },
    { label: "B", assets: [asset({ name: "Other", canonical: 3000, rawComposite: 3600, covers: { dlfSf: 3000 } })] },
  ];

  it("renders the same arithmetic under full and raw", () => {
    const full = numbersIn(renderPanel(sides, "full"));
    const raw = numbersIn(renderPanel(sides, "raw"));

    expect(raw).toEqual(full);
  });

  it("imputes the canonical value, not the legacy composite", () => {
    // Uncovered asset: canonical 4000, rawComposite 4800. The DLF row's
    // side-A total must be 5000 + 4000 = 9000, never 5000 + 4800 = 9800.
    const text = renderPanel(sides, "full");
    const seen = numbersIn(text);

    expect(seen).toContain(9000);
    expect(seen).not.toContain(9800);
  });

  it("still imputes the canonical value when the display mode is raw", () => {
    const seen = numbersIn(renderPanel(sides, "raw"));

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
          asset({ name: "Priced", canonical: 5000, rawComposite: 5900, covers: { dlfSf: 5000 } }),
          { name: "Unpriced", displayName: "Unpriced", values: {}, sourceRankMeta: {}, rawSourceValues: {}, canonicalSites: {} },
        ],
      },
      { label: "B", assets: [asset({ name: "Other", canonical: 3000, rawComposite: 3600, covers: { dlfSf: 3000 } })] },
    ];

    const text = renderPanel(sides, "full");

    // 5000 + 0 = 5000 would be the defect: an unpriced asset silently
    // contributing nothing while the row still claims a full verdict.
    expect(text).toMatch(/incomplete|partial|unresolved/i);
  });
});
