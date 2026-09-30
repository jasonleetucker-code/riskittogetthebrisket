/**
 * Schedule Intelligence on Power Rankings — CONTEXT ONLY (owner directive
 * 2026-09-29, #1530). The Schedule column and the expanded-row reading come
 * from the canonical schedule contract on the public luck section. Ranks,
 * power scores and their order must be identical with or without it: schedule
 * impact is displayed next to the ranking, never folded into it.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

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
  Card: ({ title, children }) => (
    <section>
      {title ? <h2>{title}</h2> : null}
      {children}
    </section>
  ),
}));

const ROWS = [
  { ownerId: "o1", displayName: "Alice", teamName: "A Team", rank: 1, powerScore: 92.1, record: "2-1" },
  { ownerId: "o2", displayName: "Bob", teamName: "B Team", rank: 2, powerScore: 80.4, record: "1-2" },
  { ownerId: "o3", displayName: "Cara", teamName: "C Team", rank: 3, powerScore: 71.9, record: "1-2" },
];

function power() {
  return {
    currentRanking: ROWS,
    unrankable: null,
    lens: "canonical",
    weights: { team_ros_strength: 0.4, all_play: 0.2 },
    effectiveWeights: { team_ros_strength: 0.75, all_play: 0.25 },
    blend: { forwardWeight: 0.75, resultsWeight: 0.25 },
    missingInputs: [],
    rosTeamStrengthAvailable: true,
    preseason: false,
    asOfSeason: "2026",
    asOfWeek: 3,
    shareSnapshot: null,
    officialSnapshot: null,
    officialHistory: [],
    trend: { lens: "results_only", weeks: [], seriesByOwner: {} },
  };
}

function scheduleTeam(ownerId, impact, extra = {}) {
  return {
    teamKey: ownerId,
    ownerId,
    actualH2HCredits: 2,
    h2hWins: 2,
    h2hLosses: 1,
    h2hTies: 0,
    equalOpponentExpectedH2HCredits: 2 - impact,
    scheduleImpact: impact,
    ...extra,
  };
}

// Impact order deliberately runs AGAINST rank order (and is not its exact
// reverse either), so sorting the table by schedule impact in EITHER
// direction changes it -- the invariance test must catch both.
const IMPACTS = { o1: -0.4, o2: 0.8, o3: 0.1 };

function serve({ withSchedule, failed = false, season = "2026" }) {
  global.fetch = vi.fn((url) => {
    const u = String(url);
    let body = power();
    if (u.includes("playoffOdds")) body = { owners: [] };
    if (u.includes("/luck")) {
      body = failed
        ? { data: { scheduleImpact: { currentSeason: null, bySeason: {}, state: "failed" } } }
        : withSchedule
          ? {
              data: {
                scheduleImpact: {
                  currentSeason: season,
                  bySeason: {
                    [season]: {
                      state: "complete",
                      teams: Object.entries(IMPACTS).map(([o, v]) => scheduleTeam(o, v)),
                    },
                  },
                },
              },
            }
          : { data: {} };
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
}

async function renderFresh() {
  vi.resetModules();
  const mod = await import("../../app/league/sections/ros-power.jsx");
  return mod.default;
}

function tableSnapshot() {
  const table = screen.getAllByRole("table")[0];
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((r) => within(r).getAllByRole("cell").slice(0, 3).map((c) => c.textContent).join("|"));
}

describe("Power Rankings schedule context", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("shows the Schedule column and leaves ranks and power scores unchanged", async () => {
    serve({ withSchedule: false });
    let Section = await renderFresh();
    const first = render(<Section />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    const without = tableSnapshot();
    expect(screen.queryByText("Schedule")).toBeNull();
    first.unmount();

    serve({ withSchedule: true });
    Section = await renderFresh();
    render(<Section />);
    await waitFor(() => expect(screen.getByText("Schedule")).toBeTruthy());
    expect(tableSnapshot()).toEqual(without);
    expect(screen.getByText("+0.8")).toBeTruthy();
    expect(screen.getByText("−0.4")).toBeTruthy();
    expect(screen.getByText(/Context only — not part of the power score/)).toBeTruthy();
  });

  it("a failed schedule block adds no column and says so, ranks unchanged", async () => {
    serve({ withSchedule: false });
    let Section = await renderFresh();
    const first = render(<Section />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    const without = tableSnapshot();
    first.unmount();

    serve({ withSchedule: true, failed: true });
    Section = await renderFresh();
    render(<Section />);
    await waitFor(() => expect(screen.getByText(/could not be calculated right now/)).toBeTruthy());
    expect(screen.queryByText("Schedule")).toBeNull();
    expect(tableSnapshot()).toEqual(without);
  });

  it("looks up the ranking's own season, never another season's numbers", async () => {
    serve({ withSchedule: true, season: "2025" });
    const Section = await renderFresh();
    render(<Section />);
    await waitFor(() => expect(screen.getByText("Schedule")).toBeTruthy());
    expect(screen.queryByText("+0.8")).toBeNull();
    expect(screen.queryByText("−0.4")).toBeNull();
  });

  it("the expanded row explains the schedule context as not part of the score", async () => {
    serve({ withSchedule: true });
    const Section = await renderFresh();
    render(<Section />);
    await waitFor(() => expect(screen.getByText("+0.8")).toBeTruthy());
    fireEvent.click(screen.getAllByText("Alice")[0]);
    await waitFor(() => expect(screen.getByText(/Schedule context \(not part of the power score\)/)).toBeTruthy());
    expect(screen.getByText(/Schedule context \(not part of the power score\)/).textContent).toMatch(/equally likely opponent/);
  });
});
