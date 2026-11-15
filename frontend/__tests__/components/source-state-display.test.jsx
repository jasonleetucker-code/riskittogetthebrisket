/**
 * Source-state DISPLAY truthfulness (CLEANUP-3 D13): an excluded source is
 * labelled with the backend's own reason, a not-voting observation is never
 * drawn as a contributing bar, and "no run" is never painted healthy.
 * Display only — nothing here computes a value.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { render, screen, cleanup } from "@testing-library/react";

const ros = vi.hoisted(() => ({ sources: [], health: null }));
vi.mock("@/lib/ros-data", () => ({
  fetchRosSources: async () => ({ sources: ros.sources }),
  fetchRosHealth: async () => ros.health,
}));

import SourceContributionBars from "@/components/graphs/SourceContributionBars";
import { SourceFreshnessList } from "@/components/ValueExplain";
import { rowSourceFreshness, sourceExclusionLabel } from "@/lib/value-explainers";
import RosDataHealthPage from "@/app/tools/ros-data-health/page";

afterEach(cleanup);

describe("SourceFreshnessList — exclusion reason comes from the backend", () => {
  const row = {
    assetClass: "offense",
    sourceRankMeta: {
      ktcCrowdSfTep: { appliedWeight: 1, weight: 1 },
      // Freshness/health zero weight: the backend's stamped reason.
      dlfSf: {
        valueContribution: 9000,
        appliedWeight: 0,
        weight: 1,
        contributedToBlend: false,
        excludedReason: "freshness_or_health_zero_weight",
      },
      // Family-collapse rollback path: superseded, NO excludedReason.
      fantasyNavigatorSf: {
        valueContribution: 8800,
        weight: 1,
        contributedToBlend: false,
        supersededBy: "ktcCrowdSfTep",
      },
      // Not voting, reason not published at all.
      fantasycalc: { valueContribution: 8700, weight: 1, contributedToBlend: false },
    },
    raw: { freshnessExcludedSources: ["dlfSf"] },
  };

  it("does not call a superseded or reason-less exclusion 'stale or unhealthy'", () => {
    const items = rowSourceFreshness(row, {});
    const by = Object.fromEntries(items.map((s) => [s.key, s]));
    expect(by.dlfSf.excludedReason).toBe("freshness_or_health_zero_weight");
    expect(by.fantasyNavigatorSf.excludedReason).toBe("superseded_by_family");
    expect(by.fantasycalc.excludedReason).toBeNull();
    expect(sourceExclusionLabel(by.dlfSf)).toBe("not voting — stale or unhealthy source");
    expect(sourceExclusionLabel(by.fantasyNavigatorSf)).toMatch(/superseded by .* \(same provider family\)/);
    expect(sourceExclusionLabel(by.fantasycalc)).toBe("not voting — reason not published");

    const { container } = render(<SourceFreshnessList row={row} rawData={{}} />);
    const text = container.textContent;
    expect(text.match(/stale or unhealthy/g) || []).toHaveLength(1);
    expect(text).toContain("reason not published");
    expect(text).toContain("(same provider family)");
  });
});

describe("SourceContributionBars — a not-voting observation is not a contribution", () => {
  it("labels contributedToBlend:false observations 'not voting' and draws them muted", () => {
    const row = {
      sourceRankMeta: {
        ktcCrowdSfTep: { valueContribution: 8000 },
        dlfSf: { valueContribution: 9000, contributedToBlend: false },
      },
      droppedSources: [],
    };
    const { container } = render(<SourceContributionBars row={row} />);
    const labels = Array.from(container.querySelectorAll("text")).map((t) => t.textContent);
    expect(labels).toContain("9,000 (not voting)");
    expect(labels).toContain("8,000");
    const rects = container.querySelectorAll("rect");
    // Sorted by value: the not-voting 9,000 bar first — muted, not the accent fill.
    expect(rects[0].getAttribute("fill-opacity")).toBe("0.35");
    expect(rects[1].getAttribute("fill-opacity")).toBe("0.9");
    expect(rects[0].getAttribute("fill")).not.toBe(rects[1].getAttribute("fill"));
  });
});

describe("ROS Data Health — 'no run' is not healthy", () => {
  it("renders a source with no recorded run in a neutral colour, never green", async () => {
    const recent = new Date(Date.now() - 3_600_000).toISOString();
    ros.sources = [
      { key: "srcNoRun", displayName: "No Run Source", effectivelyEnabled: true },
      { key: "srcOk", displayName: "Ok Source", effectivelyEnabled: true },
    ];
    ros.health = {
      sources: { srcOk: { status: "ok", completed_at: recent, player_count: 10 } },
      aggregate: {},
      teamStrength: {},
      sims: {},
    };
    render(<RosDataHealthPage />);
    const noRun = await screen.findByText("no run");
    expect(noRun.style.color).toBe("var(--subtext)");
    expect(screen.getByText("ok").style.color).toBe("var(--green)");
  });

  it("an 'ok' run with no completion time is not painted healthy either", async () => {
    ros.sources = [{ key: "srcOk", displayName: "Ok Source", effectivelyEnabled: true }];
    ros.health = { sources: { srcOk: { status: "ok" } }, aggregate: {}, teamStrength: {}, sims: {} };
    render(<RosDataHealthPage />);
    const ok = await screen.findByText("ok");
    expect(ok.style.color).toBe("var(--subtext)");
  });
});
