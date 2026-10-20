/**
 * lib/source-voting-status.js — the ONE frontend owner of the voting-status
 * label map and formatting (owner directive 2026-10-19 §8).
 *
 * What must hold:
 *   * the eight owner labels, verbatim, and the server's `statusLabel` wins;
 *   * an absent value stays absent ("Not measured" / "Unknown"), never 0%;
 *   * every number is the backend's, passed through — no weight product, no
 *     age threshold, no freshness step is computed here.
 */
import { describe, expect, it } from "vitest";
import fixture from "./fixtures/source-voting-status-2026-10-19.json";
import {
  VOTING_STATUS_LABELS,
  VOTING_STATUS_ORDER,
  formatDaysAgo,
  formatPct,
  formatUpdateDate,
  formatWeight,
  isActiveStatus,
  statusLabelFor,
  statusTone,
  votingStatusAvailability,
  votingStatusBlock,
  votingStatusRows,
  votingStatusSummary,
} from "@/lib/source-voting-status";

const OWNER_LABELS = [
  "Active — 100%",
  "Active — 75%",
  "Active — 50%",
  "Active — 25%",
  "Stale — Not Voting",
  "Data Issue — Not Voting",
  "Seasonal — Not Voting",
  "Testing — Not Voting",
];

describe("status labels", () => {
  it("are exactly the owner's eight plain labels, in display order", () => {
    expect(VOTING_STATUS_ORDER.map((s) => VOTING_STATUS_LABELS[s])).toEqual(OWNER_LABELS);
    expect(Object.keys(VOTING_STATUS_LABELS)).toHaveLength(8);
  });

  it("match the labels the backend publishes in the block", () => {
    expect(fixture.statusLabels).toEqual(VOTING_STATUS_LABELS);
  });

  it("prefer the server's statusLabel, then the map, then the code itself", () => {
    expect(statusLabelFor({ status: "stale", statusLabel: "Server words" })).toBe("Server words");
    expect(statusLabelFor({ status: "active_25" })).toBe("Active — 25%");
    expect(statusLabelFor({ status: "testing", statusLabel: "  " })).toBe("Testing — Not Voting");
    // An unknown code is shown as itself, never mapped onto a reassuring label.
    expect(statusLabelFor({ status: "brand_new_state" })).toBe("brand_new_state");
    expect(statusLabelFor({})).toBe("Unknown status");
    expect(statusLabelFor(null)).toBe("Unknown status");
  });

  it("tones are secondary to the label and never claim a pause is a failure", () => {
    expect(statusTone("active_100")).toBe("positive");
    expect(statusTone("stale")).toBe("negative");
    expect(statusTone("seasonal")).toBe("neutral");
    expect(statusTone("testing")).toBe("neutral");
    expect(statusTone("nope")).toBe("neutral");
    expect(isActiveStatus("active_50")).toBe(true);
    expect(isActiveStatus("stale")).toBe(false);
  });
});

describe("block access and availability", () => {
  it("reads either carrier: /api/sources/weighting or the contract", () => {
    expect(votingStatusBlock({ votingStatus: fixture })).toBe(fixture);
    expect(votingStatusBlock({ sourceVotingStatus: fixture })).toBe(fixture);
    // Pre-#1831 weighting payload: the key is absent or null.
    expect(votingStatusBlock({ sources: [] })).toBeNull();
    expect(votingStatusBlock({ votingStatus: null })).toBeNull();
    expect(votingStatusBlock(null)).toBeNull();
  });

  it("distinguishes absent, malformed and empty from available", () => {
    expect(votingStatusAvailability(null)).toEqual({ available: false, reason: "absent" });
    expect(votingStatusAvailability({ sources: "x" })).toEqual({
      available: false,
      reason: "malformed",
    });
    expect(votingStatusAvailability({ sources: [] })).toEqual({ available: false, reason: "empty" });
    expect(votingStatusAvailability(fixture)).toEqual({ available: true, reason: null });
  });
});

describe("votingStatusRows", () => {
  const rows = votingStatusRows(fixture);
  const byKey = Object.fromEntries(rows.map((r) => [r.key, r]));

  it("one row per registered source, in the backend's order", () => {
    expect(rows).toHaveLength(fixture.sources.length);
    expect(rows.map((r) => r.key)).toEqual(fixture.sources.map((s) => s.key));
    expect(new Set(rows.map((r) => r.id)).size).toBe(rows.length);
  });

  it("a partly fresh source reads as the backend stated it", () => {
    const r = byKey.idpTradeCalc;
    expect(r.label).toBe("IDP Trade Calculator");
    expect(r.statusLabel).toBe("Active — 75%");
    expect(r.lastUpdatedLabel).toBe("Oct 10, 2026");
    expect(r.agoLabel).toBe("8 days ago");
    expect(r.freshnessLabel).toBe("75%");
    expect(formatWeight(r.effectiveWeight)).toBe("0.75");
    expect(r.coverageLabel).toBe("Offense + IDP");
    expect(r.notVotingRows).toEqual([
      { reason: "outlier_filter", label: "Set aside by the outlier filter", count: 5 },
    ]);
    expect(r.picks.freshnessLabel).toBe("75%");
  });

  it("an unmeasured source is Not measured / Not tracked — never 0%", () => {
    const r = byKey.signalsSf;
    expect(r.freshnessPct).toBeNull();
    expect(r.freshnessLabel).toBe("Not measured");
    expect(r.lastUpdatedLabel).toBe("Not tracked");
    expect(r.agoLabel).toBeNull();
    expect(r.statusLabel).toBe("Data Issue — Not Voting");
  });

  it("an unknown genuine update stays Unknown", () => {
    const [r] = votingStatusRows({
      sources: [
        {
          key: "x",
          status: "data_issue",
          lastGenuineUpdate: null,
          lastGenuineUpdateBasis: "unknown",
          freshnessPct: null,
        },
      ],
    });
    expect(r.lastUpdatedLabel).toBe("Unknown");
    expect(r.freshnessLabel).toBe("Unknown");
    expect(r.playersContributing).toBeNull();
  });

  it("a stale source keeps its real date and its real 0%", () => {
    const r = byKey.idpShowCombined;
    expect(r.statusLabel).toBe("Stale — Not Voting");
    expect(r.lastUpdatedLabel).toBe("Aug 19, 2026");
    expect(r.agoLabel).toBe("60 days ago");
    expect(r.freshnessLabel).toBe("0%");
    expect(r.reason).toMatch(/older than 30 days/);
  });

  it("passes the backend's numbers through — it computes no weight", () => {
    // Deliberately inconsistent with base × freshness: the row must show the
    // backend's effective weight, not a product computed here.
    const [r] = votingStatusRows({
      sources: [
        {
          key: "k",
          status: "active_75",
          baseWeight: 1,
          freshnessPct: 75,
          effectiveWeight: 0.4,
          weightFactors: { freshness: 0.75, health: 1, coverage: 1, applied: true },
          daysSinceUpdate: 99,
          lastGenuineUpdate: "2026-10-18T00:00:00Z",
          lastGenuineUpdateBasis: "content_change_observed",
        },
      ],
    });
    expect(r.effectiveWeight).toBe(0.4);
    expect(r.agoLabel).toBe("99 days ago"); // the backend's day count, not a date diff
    expect(r.statusLabel).toBe("Active — 75%");
  });

  it("vote holds carry the owner decision through", () => {
    const r = byKey.dlfIdp;
    expect(r.statusLabel).toBe("Testing — Not Voting");
    expect(r.voteHold.decision).toMatch(/owner directive 2026-10-16/);
    expect(r.restoreRequirement).toMatch(/hold is lifted/);
  });
});

describe("votingStatusSummary", () => {
  it("uses the backend's totals and orders groups voting-first", () => {
    const s = votingStatusSummary(fixture);
    expect(s.votingCount).toBe(17);
    expect(s.registeredCount).toBe(26);
    expect(s.stepSchedule).toBe(true);
    expect(s.freshnessApplied).toBe(true);
    expect(s.asOfLabel).toBe("Oct 19, 2026");
    expect(s.groups.map((g) => g.status)).toEqual([
      "active_100",
      "active_75",
      "active_50",
      "stale",
      "data_issue",
      "seasonal",
      "testing",
    ]);
    expect(s.groups.reduce((n, g) => n + g.count, 0)).toBe(26);
  });
});

describe("formatters", () => {
  it("never turn a missing value into zero", () => {
    expect(formatPct(null)).toBeNull();
    expect(formatPct(75)).toBe("75%");
    expect(formatPct(0)).toBe("0%");
    expect(formatWeight(null)).toBe("—");
    expect(formatWeight(0)).toBe("0.00");
    expect(formatDaysAgo(null)).toBeNull();
    expect(formatDaysAgo(0)).toBe("today");
    expect(formatDaysAgo(1)).toBe("1 day ago");
    expect(formatUpdateDate(null)).toBeNull();
    expect(formatUpdateDate("not a date")).toBeNull();
    // UTC, the backend's clock: a late-evening UTC stamp keeps its UTC date.
    expect(formatUpdateDate("2026-10-10T23:59:00Z")).toBe("Oct 10, 2026");
  });
});
