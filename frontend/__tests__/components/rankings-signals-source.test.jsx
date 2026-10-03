/**
 * Signals Fantasy in the Rankings source/ranks column (owner addendum
 * 2026-10-03, acceptance item 5).
 *
 * Rows here are LABELLED SYNTHETIC (no real Signals values). Pinned:
 *   - an offense and an IDP Signals observation render with the source
 *     name, the native value, "value-ordered rank (derived)", VALUE vs
 *     RANK-fallback, the dataset, the format and the as-of — on the desktop
 *     cell title, the mobile chip and the expanded audit card alike;
 *   - a RANK-fallback row (rank stamped, no native value) says so and is
 *     never labelled as derived from a value;
 *   - a row Signals did not list renders "—" (missing, never zero);
 *   - nothing here computes a rank: every number is a backend stamp.
 */
import { describe, expect, it } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import { RANKING_SOURCES } from "@/lib/dynasty-data";
import {
  formatSourceCell,
  sourceObservation,
  sourceObservationText,
} from "@/app/rankings/board-utils";
import { MobileSourceStrip, SourceAuditPanel } from "@/app/rankings/board-sections";

const SIGNALS_SF = RANKING_SOURCES.find((s) => s.key === "signalsSf");
const SIGNALS_IDP = RANKING_SOURCES.find((s) => s.key === "signalsIdp");

const RAW = {
  sourceWeighting: {
    sources: {
      signalsSf: { subsets: { players: { sourceDataAsOf: "2026-10-03T11:30:00Z", state: "ON_SCHEDULE" } } },
      signalsIdp: { subsets: { players: { sourceDataAsOf: "2026-09-30T20:00:00Z", state: "OVERDUE" } } },
    },
  },
};

function offenseRow(overrides = {}) {
  return {
    name: "Synthetic Receiver",
    pos: "WR",
    canonicalSites: { signalsSf: 997100 },
    sourceRanks: { signalsSf: 31 },
    sourceOriginalRanks: { signalsSf: 29 },
    sourceNativeValues: { signalsSf: 6400 },
    sourceRankMeta: { signalsSf: { valueContribution: 6123, appliedWeight: 0.5 } },
    sourceAudit: { matchedSources: ["signalsSf"], expectedSources: ["signalsSf"] },
    ...overrides,
  };
}

function idpRow() {
  return {
    name: "Synthetic Edge",
    pos: "DL",
    canonicalSites: { signalsIdp: 998700 },
    sourceRanks: { signalsIdp: 61 },
    sourceOriginalRanks: { signalsIdp: 13 },
    sourceNativeValues: { signalsIdp: 4310 },
    sourceRankMeta: { signalsIdp: { valueContribution: 3420, appliedWeight: 1 } },
    sourceAudit: { matchedSources: ["signalsIdp"], expectedSources: ["signalsIdp"] },
  };
}

describe("registry mirror", () => {
  it("declares both Signals datasets with display provenance", () => {
    expect(SIGNALS_SF).toMatchObject({
      isRankSignal: true,
      isTepPremium: false,
      correlationGroup: "fantasyCalc",
      observationDataset: "Offense",
    });
    expect(SIGNALS_SF.observationFormat).toMatch(/Superflex/);
    expect(SIGNALS_SF.observationFormat).toMatch(/non-TEP/);
    expect(SIGNALS_IDP).toMatchObject({
      scope: "overall_idp",
      needsSharedMarketTranslation: true,
      correlationGroup: "fantasyCalc",
      observationDataset: "IDP",
    });
  });
});

describe("sourceObservation", () => {
  it("offense VALUE: native value + derived rank + format + as-of", () => {
    const obs = sourceObservation(offenseRow(), SIGNALS_SF, RAW);
    expect(obs).toMatchObject({
      basis: "VALUE",
      nativeValue: 6400,
      rankLabel: "#29 value-ordered rank (derived)",
      dataset: "Offense",
      asOf: "2026-10-03T11:30:00Z",
      state: "ON_SCHEDULE",
    });
    const text = sourceObservationText(obs);
    expect(text).toContain("native value 6,400 (VALUE)");
    expect(text).toContain("value-ordered rank (derived)");
    expect(text).toContain("Offense dataset");
    expect(text).toContain("Dynasty · Superflex · non-TEP (TE++ converted)");
    expect(text).toContain("as of 2026-10-03 (ON_SCHEDULE)");
  });

  it("RANK fallback: a stamped rank without a value is never called derived", () => {
    const row = offenseRow({ sourceNativeValues: {} });
    const obs = sourceObservation(row, SIGNALS_SF, RAW);
    expect(obs.basis).toBe("RANK");
    expect(obs.rankLabel).toBe("#29 published rank");
    expect(sourceObservationText(obs)).toContain("RANK fallback");
    expect(sourceObservationText(obs)).not.toContain("derived");
  });

  it("is null for an unlisted row and for sources without provenance", () => {
    expect(sourceObservation({ name: "x" }, SIGNALS_SF, RAW)).toBeNull();
    const fc = RANKING_SOURCES.find((s) => s.key === "fantasyCalc");
    expect(sourceObservation(offenseRow(), fc, RAW)).toBeNull();
  });

  it("unknown as-of stays unknown, never borrowed", () => {
    const obs = sourceObservation(offenseRow(), SIGNALS_SF, {});
    expect(obs.asOf).toBeNull();
    expect(sourceObservationText(obs)).not.toContain("as of");
  });
});

describe("Rankings source column", () => {
  it("desktop cell: Hill value + effective rank, provenance in the title", () => {
    const cell = formatSourceCell(offenseRow(), SIGNALS_SF, RAW);
    expect(cell.hasVal).toBe(true);
    expect(cell.primary).toBe("6,123");
    expect(cell.rankLabel).toBe("#31");
    expect(cell.title).toContain("Signals Fantasy Dynasty SF");
    expect(cell.title).toContain("native value 6,400 (VALUE)");
    expect(cell.title).not.toContain("original rank");
  });

  it("an unlisted player is a dash, never zero", () => {
    const cell = formatSourceCell({ name: "x" }, SIGNALS_SF, RAW);
    expect(cell.hasVal).toBe(false);
    expect(cell.primary).toBe("—");
  });

  it("mobile chip shows the basis, derived rank and as-of (no hover needed)", () => {
    render(
      <MobileSourceStrip
        row={offenseRow()}
        formatSourceCell={(r, s) => formatSourceCell(r, s, RAW)}
      />,
    );
    const chip = screen.getByTestId("source-observation-signalsSf");
    expect(chip.textContent).toContain("native 6,400");
    expect(chip.textContent).toContain("value-ordered rank (derived)");
    expect(chip.textContent).toContain("2026-10-03");
  });

  it("IDP audit card: native value, derived rank, IDP dataset, format, as-of", () => {
    render(
      <SourceAuditPanel
        row={idpRow()}
        rawData={RAW}
        val={3500}
        edge={{ label: "—", title: "" }}
        confidence={{ label: "Medium", reasons: [] }}
      />,
    );
    expect(screen.getByText("VALUE (native value)")).toBeTruthy();
    expect(screen.getByText("Native value")).toBeTruthy();
    expect(screen.getByText("4,310")).toBeTruthy();
    expect(screen.getByText("#13 value-ordered rank (derived)")).toBeTruthy();
    expect(screen.getByText("IDP")).toBeTruthy();
    expect(screen.getByText(/CB\/S → DB/)).toBeTruthy();
    expect(screen.getByText("2026-09-30 · OVERDUE")).toBeTruthy();
  });
});
