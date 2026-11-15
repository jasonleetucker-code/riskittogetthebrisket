import { describe, expect, it } from "vitest";
import fixture from "./fixtures/source-weighting-2026-10-13.json";
import {
  formatFactor,
  formatHours,
  stateStatus,
  stateSummary,
  weightingRows,
} from "@/lib/source-weighting";

const NOW = Date.parse("2026-10-13T18:30:00Z");

describe("weightingRows", () => {
  const rows = weightingRows(fixture, { labels: { ktcCrowdSfTep: "KTC Crowd" }, now: NOW });

  it("keeps the backend's state and factors verbatim", () => {
    const idp = rows.find((r) => r.source === "idpShowCombined");
    expect(idp.state).toBe("QUARANTINED");
    expect(idp.freshness).toBe(0);
    expect(idp.effectiveWeight).toBe(0);
    expect(idp.contentHours).toBeGreaterThan(idp.expectedHours * 5);
  });

  it("labels the KTC Market benchmark as a non-voter", () => {
    const market = rows.find((r) => r.source === "ktcCrowdTradesSfTep");
    expect(market.isBenchmark).toBe(true);
    expect(market.effectiveWeight).toBeNull();
  });

  it("uses registry labels and falls back to the key", () => {
    expect(rows.find((r) => r.source === "ktcCrowdSfTep").label).toBe("KTC Crowd");
    expect(rows.find((r) => r.source === "yahooBoone").label).toBe("yahooBoone");
  });

  it("measures fetch age separately from content age", () => {
    const ktc = rows.find((r) => r.source === "ktcCrowdSfTep");
    expect(ktc.fetchedHours).toBeCloseTo(2, 1);
    expect(ktc.contentHours).not.toBe(ktc.fetchedHours);
  });

  it("missing numbers stay null, never 0", () => {
    const [row] = weightingRows({ sources: [{ source: "x", state: "UNMEASURED" }] });
    expect(row.freshness).toBeNull();
    expect(row.effectiveWeight).toBeNull();
    expect(row.contentHours).toBeNull();
    expect(row.fetchedHours).toBeNull();
  });
});

describe("stateSummary", () => {
  it("counts per state, worst first", () => {
    const summary = stateSummary(weightingRows(fixture, { now: NOW }));
    expect(summary[0].state).toBe("QUARANTINED");
    expect(summary.find((s) => s.state === "ON_SCHEDULE").count).toBeGreaterThan(0);
  });
});

describe("formatting", () => {
  it("never renders unknown as zero", () => {
    expect(formatHours(null)).toBe("—");
    expect(formatFactor(undefined)).toBe("—");
    expect(formatFactor(0)).toBe("0.00");
  });

  it("formats hours and days", () => {
    expect(formatHours(9.3)).toBe("9h");
    expect(formatHours(1318.7)).toBe("55d");
    expect(formatHours(94)).toBe("3.9d");
  });

  it("an unknown state is shown as itself, not reassured", () => {
    expect(stateStatus("SOMETHING_NEW")).toEqual({ status: "neutral", label: "SOMETHING_NEW" });
    expect(stateStatus("QUARANTINED").status).toBe("negative");
  });
});
