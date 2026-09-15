/**
 * Historical Power view: movement semantics and the canonical/diagnostic split.
 *
 * Two defects this pins, both reported as "the arrows don't match reality":
 *
 * 1. ``trend.weeks`` chains EVERY tracked season onto one sequential list
 *    (power_v2.py's ``week_states`` loops over ``seasons_sorted``), so walking
 *    backward from a season's first week stepped into the PREVIOUS season's
 *    ranking — a different league state, and in this lens a standings-derived
 *    one. Movement must stop at the season boundary and report nothing.
 *
 * 2. The reconstruction rendered under the same plain "Power Rankings" heading
 *    as the canonical blend. They answer different questions: canonical is 40%
 *    forward-looking roster strength, the reconstruction has none of it and
 *    renormalizes onto results, which at week 1 is close to a single-week
 *    points sort. Labelling is the fix, not hiding the diagnostic.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent, within } from "@testing-library/react";

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

function weekRows(ranks) {
  return Object.entries(ranks).map(([ownerId, rank]) => ({
    ownerId,
    displayName: ownerId,
    powerScore: 90 - rank,
    rank,
    record: "1-0",
    components: { ppg: 0.5, recent: 0.5, pointsPerGame: 110, recentAvg: 110 },
    rosStrengthPercentile: null,
    weightsApplied: {},
  }));
}

function payload() {
  return {
    currentRanking: [
      {
        ownerId: "o1",
        displayName: "o1",
        powerScore: 88.5,
        rank: 1,
        record: "5-2",
        components: { ppg: 0.9, recent: 0.8, pointsPerGame: 121.4, recentAvg: 118.2 },
        componentRanks: { team_ros_strength: 2, all_play: 1, recent: 4, wl_record: 6 },
        rosStrengthPercentile: 0.7,
        weightsApplied: { ppg: 0.18 },
      },
      {
        ownerId: "o2",
        displayName: "o2",
        powerScore: 60.1,
        rank: 2,
        record: "2-5",
        components: { ppg: 0.4, recent: 0.5, pointsPerGame: 95.0, recentAvg: 97.5 },
        rosStrengthPercentile: 0.3,
        weightsApplied: { ppg: 0.18 },
      },
    ],
    unrankable: null,
    lens: "canonical",
    weights: { ppg: 0.18 },
    effectiveWeights: { ppg: 0.18 },
    blend: { forwardWeight: 0.4, resultsWeight: 0.6 },
    missingInputs: [],
    preseason: false,
    trend: {
      lens: "results_only",
      note: "Diagnostic results-only history.",
      weeks: [
        // Prior season. Its final week must never anchor the next season.
        { season: "2025", week: 1, rankings: weekRows({ o1: 2, o2: 1 }), effectiveWeights: {} },
        { season: "2025", week: 2, rankings: weekRows({ o1: 1, o2: 2 }), effectiveWeights: {} },
        // New season, first week — no in-season predecessor.
        { season: "2026", week: 1, rankings: weekRows({ o1: 2, o2: 1 }), effectiveWeights: {} },
      ],
      seriesByOwner: {},
    },
  };
}

async function renderFresh() {
  vi.resetModules();
  const mod = await import("../../app/league/sections/ros-power.jsx");
  return mod.default;
}

function moveCellFor(ownerId) {
  const row = screen.getAllByText(ownerId)[0].closest("tr");
  return row.querySelectorAll("td")[7];
}

async function selectWeek(label) {
  fireEvent.change(screen.getByRole("combobox"), { target: { value: label } });
  await waitFor(() => expect(screen.getByRole("combobox").value).toBe(label));
}

describe("RosPowerSection — historical movement and the canonical/diagnostic split", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn((url) => {
      if (String(url).includes("playoffOdds")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ owners: [] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload()) });
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("a season's FIRST week shows no movement instead of comparing to last season", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("o1").length).toBeGreaterThan(0));

    await selectWeek("2026:1");

    // Without the season guard o1 would read ▼ 1 here, by comparing its 2026
    // week-1 rank of 2 against its 2025 week-2 rank of 1. That is the bug.
    expect(moveCellFor("o1").textContent.trim()).toBe("—");
    expect(moveCellFor("o2").textContent.trim()).toBe("—");
    expect(moveCellFor("o1").textContent).not.toMatch(/[▲▼]/);
  });

  it("a later week in the same season still shows its in-season movement", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("o1").length).toBeGreaterThan(0));

    await selectWeek("2025:2");

    // o1: rank 2 -> 1 is up one. o2: rank 1 -> 2 is down one.
    expect(moveCellFor("o1").textContent.replace(/\s+/g, "")).toBe("▲1");
    expect(moveCellFor("o2").textContent.replace(/\s+/g, "")).toBe("▼1");
  });

  it("a historical week is labelled diagnostic, never a bare 'Power Rankings'", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("o1").length).toBeGreaterThan(0));

    await selectWeek("2026:1");

    const heading = screen.getByRole("heading", { name: /Power Rankings/ });
    expect(heading.textContent).toMatch(/diagnostic \(results-only\)/i);
    expect(heading.textContent).toMatch(/2026 Wk 1/);
    // The exact string that used to mislead must not be the whole heading.
    expect(heading.textContent.trim()).not.toBe("Power Rankings");
    // And the reader is told what they are looking at, in THIS card — scoped,
    // because the chart card below carries its own subtitle.
    const card = heading.closest("section");
    expect(within(card).getByTestId("card-subtitle").textContent).toMatch(/results/i);
  });

  it("the canonical view keeps the plain heading and no diagnostic warning", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("o1").length).toBeGreaterThan(0));

    const heading = screen.getByRole("heading", { name: /Power Rankings/ });
    expect(heading.textContent.trim()).toBe("Power Rankings");
    expect(screen.queryByText(/not the canonical ranking/i)).toBeNull();
  });

  it("renders the backend's component sub-ranks verbatim", async () => {
    // The page must not derive these — they are ordinals over the league, and
    // the backend owns them. Absent keys (team_vorp here) simply do not show.
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("o1").length).toBeGreaterThan(0));

    const row = screen.getAllByText("o1")[0].closest("tr");
    expect(within(row).getByText(/ROS #2 · All-play #1 · Last 4 #4 · Record #6/)).toBeTruthy();
    expect(row.textContent).not.toMatch(/VORP #/);
  });
});
