import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import PlayerRankHistoryChart from "../../components/PlayerRankHistoryChart";
import TradeFlowSankey from "../../components/graphs/TradeFlowSankey";
import SourceContributionBars from "../../components/graphs/SourceContributionBars";
import { CHART_COLORS, INVERSE_CHART_STYLE } from "../../lib/chart-primitives";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

const CREAM_SURFACES = ["#f0eddf", "#f7f5ec", "#e4e3d6", "#ffffff"];
const D14 = ["#986400", "#2264af", "#ac386a", "#6752b6", "#087650", "#aa3c17"];
const cream = Object.fromEntries(D14.map((color, i) => [`--chart-${i + 1}`, color]));
const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
const lum = (channels) => channels.map((c) => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
  .reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0);
function contrast(foreground, background, alpha = 1) {
  const back = rgb(background);
  const effective = rgb(foreground).map((c, i) => c * alpha + back[i] * (1 - alpha));
  const [hi, lo] = [lum(effective), lum(back)].sort((a, b) => b - a);
  return (hi + 0.05) / (lo + 0.05);
}
function resolve(value, scope = {}) {
  const match = value.match(/^var\((--[^, )]+)(?:,\s*(.*))?\)$/);
  return match ? resolve(scope[match[1]] || match[2], scope) : value;
}

describe("Sports Network chart contrast", () => {
  it("keeps interface text at 4.5:1 and semantic marks at 3:1 including their effective opacity", () => {
    for (const surface of CREAM_SURFACES) {
      expect(contrast(resolve(CHART_COLORS.axisLabel), surface)).toBeGreaterThanOrEqual(4.5);
      for (const token of [CHART_COLORS.accent, CHART_COLORS.accentMuted, CHART_COLORS.danger,
        CHART_COLORS.warn, CHART_COLORS.success, CHART_COLORS.positive, CHART_COLORS.negative,
        ...Object.values(CHART_COLORS.confidence)]) {
        // .8 is the least opaque filled semantic mark (matchup histogram).
        expect(contrast(resolve(token), surface, 0.8)).toBeGreaterThanOrEqual(3);
      }
      // These same tokens are used in small HTML/SVG status labels.
      for (const token of [CHART_COLORS.warn, CHART_COLORS.danger, CHART_COLORS.success]) {
        expect(contrast(resolve(token), surface)).toBeGreaterThanOrEqual(4.5);
      }
    }
    const navy = INVERSE_CHART_STYLE.background;
    for (const token of [CHART_COLORS.axisLabel, CHART_COLORS.warn, CHART_COLORS.success,
      CHART_COLORS.danger, CHART_COLORS.negative]) {
      expect(contrast(resolve(token, INVERSE_CHART_STYLE), navy)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("measures every rendered source line and matching dashed key against its actual inverse canvas", async () => {
    const dates = ["2026-11-01", "2026-11-02"];
    const sources = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [
      `source-${String(i).padStart(2, "0")}`, dates.map((date, n) => ({ date, value: 5000 + i * 80 + n * 10 })),
    ]));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({
      dates, sources, blended: dates.map((date, i) => ({ date, value: 5500 + i * 20 })),
    }) }));
    const { container } = render(<PlayerRankHistoryChart row={{ name: "Contrast fixture" }} />);
    const chart = await screen.findByRole("group", { name: /Per-source value history/ });
    expect(chart.style.background).toBe("rgb(11, 33, 48)");
    const paths = [...container.querySelectorAll(".player-rank-chart-svg path[stroke-opacity]")];
    expect(paths).toHaveLength(24); // Value and rank companion, all 12 retained.
    for (const path of paths) {
      expect(contrast(path.getAttribute("stroke"), INVERSE_CHART_STYLE.background,
        Number(path.getAttribute("stroke-opacity")))).toBeGreaterThanOrEqual(3);
    }
    const keys = [...container.querySelectorAll(".player-rank-chart-swatch path")];
    expect(keys).toHaveLength(paths.length);
    keys.forEach((key, i) => {
      expect(key.getAttribute("stroke")).toBe(paths[i].getAttribute("stroke"));
      expect(key.getAttribute("stroke-dasharray")).toBe(paths[i].getAttribute("stroke-dasharray"));
      expect(contrast(key.getAttribute("stroke"), INVERSE_CHART_STYLE.background,
        Number(key.getAttribute("stroke-opacity")))).toBeGreaterThanOrEqual(3);
    });
    expect(new Set(paths.map((p) => p.getAttribute("stroke-dasharray"))).size).toBeGreaterThan(1);
    for (const name of ["--muted", "--subtext", "--cyan", "--green", "--red", "--text"]) {
      expect(contrast(chart.style.getPropertyValue(name), INVERSE_CHART_STYLE.background)).toBeGreaterThanOrEqual(4.5);
    }
    expect(fetch.mock.calls[0][0]).toMatch(/^\/api\/data\/player-source-history\?/);
  });

  it.each([6, 8])("retains %i-owner flow hues and measures rendered ribbons at their effective opacity", (count) => {
    const sides = Array.from({ length: count }, (_, i) => ({
      ownerId: `owner-${i}`, displayName: `Owner ${i}`, receivedAssets: [String(i)],
    }));
    const { container } = render(<TradeFlowSankey trades={[{ sides }]} />);
    const svg = screen.getByRole("img");
    const scope = count > 6 ? INVERSE_CHART_STYLE : cream;
    const backgrounds = count > 6 ? [INVERSE_CHART_STYLE.background] : CREAM_SURFACES;
    expect(svg.style.background).toBe(count > 6 ? "rgb(11, 33, 48)" : "");
    const nodes = [...container.querySelectorAll("rect")].slice(0, count);
    expect(nodes.map((node) => resolve(node.getAttribute("fill"), scope)))
      .toEqual(count > 6 ? CHART_COLORS.legacyCategorical.slice(0, count) : D14);
    for (const path of container.querySelectorAll("path")) {
      for (const background of backgrounds) {
        expect(contrast(resolve(path.getAttribute("stroke"), scope), background,
          Number(path.getAttribute("stroke-opacity")))).toBeGreaterThanOrEqual(3);
      }
      expect(path.querySelector("title").textContent).toMatch(/Owner \d → Owner \d:/);
    }
  });

  it("keeps non-voting and dropped fills muted while providing visible outlines and explicit status labels", () => {
    const { container } = render(<SourceContributionBars row={{
      sourceRankMeta: {
        voting: { valueContribution: 6000 },
        excluded: { valueContribution: 5000, contributedToBlend: false },
        rejected: { valueContribution: 4000 },
      },
      droppedSources: ["rejected"],
    }} />);
    const bars = [...container.querySelectorAll("rect")];
    expect(bars.map((bar) => bar.getAttribute("fill-opacity"))).toEqual(["0.9", "0.35", "0.35"]);
    for (const bar of bars) {
      for (const surface of CREAM_SURFACES) {
        expect(contrast(resolve(bar.getAttribute("stroke")), surface)).toBeGreaterThanOrEqual(3);
      }
    }
    expect(bars[1].getAttribute("stroke-dasharray")).toBe("3 2");
    expect(container.textContent).toContain("5,000 (not voting)");
    expect(container.textContent).toContain("4,000 (dropped)");
    expect(container.querySelector("line")).not.toBeNull(); // Dropped-source strike-through retained.
  });
});
