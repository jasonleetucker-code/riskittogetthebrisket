/**
 * The "Power score over time" chart chains EVERY tracked season's played
 * weeks onto one sequential x-axis (power_v2.py's ``week_states`` loops
 * over ``seasons_sorted``). With no visual season boundary, a multi-season
 * history's dramatic swings from COMPLETED past seasons are indistinguishable
 * from the current season's — which is exactly what produced a real report:
 * "the power score has changed but the power rankings haven't", from a
 * reader comparing a chart showing mostly 2024/2025 movement against a
 * current-season table that (correctly) has no movement yet at week 1.
 *
 * This pins that the chart now stamps a season label + divider at each
 * season transition, and that this is purely a rendering addition — it
 * never changes which points are plotted or their x/y positions.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";

vi.mock("@/components/ui", () => ({
  LoadingState: ({ message }) => <div>{message}</div>,
  EmptyState: ({ title, message }) => (
    <div>
      <h3>{title}</h3>
      <p>{message}</p>
    </div>
  ),
}));

vi.mock("../../app/league/shared-server.jsx", () => ({
  Card: ({ title, subtitle, children }) => (
    <section>
      {title ? <h2>{title}</h2> : null}
      {subtitle ? <p data-testid="card-subtitle">{subtitle}</p> : null}
      {children}
    </section>
  ),
}));

vi.mock("../../app/league/shared.jsx", () => ({
  Avatar: () => <span data-testid="avatar" />,
  nameFor: (managers, ownerId) => ownerId,
}));

vi.mock("@/components/graphs/PlayoffOddsChart", () => ({
  default: () => <div data-testid="playoff-odds-chart" />,
}));

function basePayload() {
  return {
    currentRanking: [
      {
        ownerId: "o1",
        displayName: "Alice",
        powerScore: 88.5,
        rank: 1,
        record: "1-0",
        components: { ppg: 0.9, recent: 0.8, pointsPerGame: 121.4, recentAvg: 118.2 },
        rosStrengthPercentile: 0.7,
        weightsApplied: { ppg: 0.18 },
      },
    ],
    unrankable: null,
    lens: "canonical",
    weights: { ppg: 0.18 },
    effectiveWeights: { ppg: 0.18 },
    missingInputs: [],
    preseason: false,
    trend: { lens: "results_only", note: "", weeks: [], seriesByOwner: {} },
  };
}

async function renderFresh() {
  vi.resetModules();
  const mod = await import("../../app/league/sections/ros-power.jsx");
  return mod.default;
}

function mockFetch(payload) {
  global.fetch = vi.fn((url) => {
    if (String(url).includes("playoffOdds")) {
      return Promise.resolve({ ok: true, json: () => Promise.resolve({ owners: [] }) });
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(payload) });
  });
}

describe("PowerChart — season boundaries", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("labels every season and draws a divider at each transition, but not before the first season", async () => {
    const payload = basePayload();
    payload.trend.seriesByOwner = {
      o1: [
        { season: "2024", week: 1, powerScore: 40, rank: 2 },
        { season: "2024", week: 2, powerScore: 90, rank: 1 },
        { season: "2025", week: 1, powerScore: 30, rank: 2 },
        { season: "2026", week: 1, powerScore: 70, rank: 1 },
      ],
    };
    mockFetch(payload);
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(container.querySelector("svg")).toBeTruthy());

    const svg = container.querySelector("svg");
    // One label per distinct season, exactly three seasons here.
    expect(within(svg).getByText("2024")).toBeTruthy();
    expect(within(svg).getByText("2025")).toBeTruthy();
    expect(within(svg).getByText("2026")).toBeTruthy();

    // Two transitions (2024→2025, 2025→2026) draw a divider; the first
    // season's own start (x=0, the left edge) does not get a spurious one.
    const dividers = Array.from(svg.querySelectorAll("line")).filter(
      (l) => l.getAttribute("stroke-dasharray") === "2 4",
    );
    expect(dividers.length).toBe(2);
  });

  it("a single-season series gets one label and no divider line", async () => {
    const payload = basePayload();
    payload.trend.seriesByOwner = {
      o1: [
        { season: "2026", week: 1, powerScore: 40, rank: 1 },
        { season: "2026", week: 2, powerScore: 55, rank: 1 },
      ],
    };
    mockFetch(payload);
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(container.querySelector("svg")).toBeTruthy());

    const svg = container.querySelector("svg");
    expect(within(svg).getByText("2026")).toBeTruthy();
    const dividers = Array.from(svg.querySelectorAll("line")).filter(
      (l) => l.getAttribute("stroke-dasharray") === "2 4",
    );
    expect(dividers.length).toBe(0);
  });

  it("adding an earlier season does not move an existing point's y (score)", async () => {
    // The same 2026 points, with and without an earlier 2025 season
    // prepended, must place the shared 2026 score at the same y — the
    // x-scale simply grows to include the earlier season's weeks, never
    // distorting existing data. (Two 2026 points each, since the chart
    // requires xMax >= 1 to render at all.)
    const singleSeason = basePayload();
    singleSeason.trend.seriesByOwner = {
      o1: [
        { season: "2026", week: 1, powerScore: 40, rank: 1 },
        { season: "2026", week: 2, powerScore: 62, rank: 1 },
      ],
    };
    mockFetch(singleSeason);
    let RosPowerSection = await renderFresh();
    const { container: c1 } = render(<RosPowerSection />);
    await waitFor(() => expect(c1.querySelector("svg")).toBeTruthy());
    const lastPointCy = c1.querySelector("circle").getAttribute("cy");

    const multiSeason = basePayload();
    multiSeason.trend.seriesByOwner = {
      o1: [
        { season: "2025", week: 1, powerScore: 10, rank: 1 },
        { season: "2026", week: 1, powerScore: 40, rank: 1 },
        { season: "2026", week: 2, powerScore: 62, rank: 1 },
      ],
    };
    mockFetch(multiSeason);
    RosPowerSection = await renderFresh();
    const { container: c2 } = render(<RosPowerSection />);
    await waitFor(() => expect(c2.querySelector("svg")).toBeTruthy());
    // The rendered "last point" marker (one per owner) is still the final
    // 2026 week-2 score, at the identical y as the single-season case.
    expect(c2.querySelector("circle").getAttribute("cy")).toBe(lastPointCy);
  });
});
