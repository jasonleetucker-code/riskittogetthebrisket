/**
 * V1-52 — legacy Power tab retirement (the follow-up to #996).
 *
 * The retired ``power.jsx`` gave readers two things ``ros-power.jsx`` didn't
 * have until now: a week-by-week browsable table, and a power-score-over-time
 * line chart. Both are materialized from data the canonical engine already
 * publishes (``trend.weeks`` / ``trend.seriesByOwner``) — no new computation
 * on the client, same posture as ``buildRows``. This file pins that the
 * migration actually reads that data rather than silently dropping the
 * feature.
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

function payload() {
  return {
    currentRanking: [
      {
        ownerId: "o1",
        displayName: "Alice",
        powerScore: 88.5,
        rank: 1,
        record: "5-2",
        components: { ppg: 0.9, recent: 0.8, pointsPerGame: 121.4, recentAvg: 118.2 },
        rosStrengthPercentile: 0.7,
        weightsApplied: { ppg: 0.18 },
      },
      {
        ownerId: "o2",
        displayName: "Bob",
        powerScore: 60.1,
        rank: 2,
        record: "2-5",
        components: { ppg: 0.4, recent: 0.5, pointsPerGame: 95.0, recentAvg: 97.5 },
        rosStrengthPercentile: 0.3,
        weightsApplied: { ppg: 0.18 },
      },
    ],
    unrankable: null,
    lens: "forward_looking",
    weights: { ppg: 0.18 },
    effectiveWeights: { ppg: 0.18 },
    missingInputs: [],
    preseason: false,
    trend: {
      lens: "results_only",
      note: "Results only. Forward-looking roster strength is a current snapshot with no per-week history.",
      weeks: [
        {
          season: "2025",
          week: 1,
          rankings: [
            {
              ownerId: "o1",
              displayName: "Alice",
              powerScore: 70,
              rank: 2,
              record: "1-0",
              components: { ppg: 0.5, recent: 0.5, pointsPerGame: 110.0, recentAvg: 110.0 },
              rosStrengthPercentile: null,
              weightsApplied: {},
            },
            {
              ownerId: "o2",
              displayName: "Bob",
              powerScore: 90,
              rank: 1,
              record: "1-0",
              components: { ppg: 0.9, recent: 0.9, pointsPerGame: 130.0, recentAvg: 130.0 },
              rosStrengthPercentile: null,
              weightsApplied: {},
            },
          ],
        },
        {
          season: "2025",
          week: 2,
          rankings: [
            {
              ownerId: "o1",
              displayName: "Alice",
              powerScore: 80,
              rank: 1,
              record: "2-0",
              components: { ppg: 0.8, recent: 0.8, pointsPerGame: 121.4, recentAvg: 118.2 },
              rosStrengthPercentile: null,
              weightsApplied: {},
            },
            {
              ownerId: "o2",
              displayName: "Bob",
              powerScore: 65,
              rank: 2,
              record: "1-1",
              components: { ppg: 0.4, recent: 0.5, pointsPerGame: 95.0, recentAvg: 97.5 },
              rosStrengthPercentile: null,
              weightsApplied: {},
            },
          ],
        },
      ],
      seriesByOwner: {
        o1: [
          { season: "2025", week: 1, powerScore: 70, rank: 2 },
          { season: "2025", week: 2, powerScore: 80, rank: 1 },
        ],
        o2: [
          { season: "2025", week: 1, powerScore: 90, rank: 1 },
          { season: "2025", week: 2, powerScore: 65, rank: 2 },
        ],
      },
    },
  };
}

async function renderFresh() {
  vi.resetModules();
  const mod = await import("../../app/league/sections/ros-power.jsx");
  return mod.default;
}

describe("RosPowerSection — week history and chart (V1-52 retirement)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    global.fetch = vi.fn((url) => {
      if (String(url).includes("playoffOdds")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ owners: [] }) });
      }
      return Promise.resolve({ ok: true, json: () => Promise.resolve(payload()) });
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("defaults to the headline ranking, not a trend week", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const table = document.querySelector("table");
    // Headline powerScore is 88.5, not either trend week's 70/80.
    expect(within(table).getByText("88.5")).toBeTruthy();
  });

  it("the week selector renders every trend week plus 'Most recent'", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const select = screen.getByRole("combobox");
    const optionLabels = Array.from(select.querySelectorAll("option")).map((o) => o.textContent);
    expect(optionLabels).toEqual(["Most recent", "2025 Wk 2", "2025 Wk 1"]);
  });

  it("selecting a historical week shows that week's own scores, not the headline's", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2025:1" } });

    const table = document.querySelector("table");
    // Week 1's Alice score (70), not the headline's (88.5).
    await waitFor(() => expect(within(table).getByText("70.0")).toBeTruthy());
    expect(within(table).queryByText("88.5")).toBeNull();
  });

  it("labels a historical week as the results-only view", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    // Most recent (default): no results-only disclaimer shown.
    expect(screen.queryByText(/Results only\. Forward-looking/i)).toBeNull();

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2025:1" } });
    await waitFor(() =>
      expect(screen.getByText(/Results only\. Forward-looking/i)).toBeTruthy(),
    );
  });

  it("a historical week's trend arrow is computed against ITS prior week, not the headline's", async () => {
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2025:2" } });
    // Alice: week1 rank 2 -> week2 rank 1, moved up 1.
    await waitFor(() => expect(container.textContent).toContain("▲"));
    expect(container.textContent).toContain("1");
  });

  it("week 1 (no prior week) shows no trend arrow for either owner", async () => {
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    fireEvent.change(screen.getByRole("combobox"), { target: { value: "2025:1" } });
    await waitFor(() => expect(container.textContent).toContain("110.0"));
    expect(container.textContent).not.toContain("▲");
    expect(container.textContent).not.toContain("▼");
  });

  it("renders the raw PPG/recent-form magnitudes as their own columns", async () => {
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const table = document.querySelector("table");
    expect(within(table).getByText("121.4")).toBeTruthy();
    expect(within(table).getByText("118.2")).toBeTruthy();
  });

  it("renders the power-score-over-time chart from trend.seriesByOwner", async () => {
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));

    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg.querySelectorAll("path").length).toBe(2); // one line per owner
  });

  it("does not render the chart when the trend series is empty", async () => {
    global.fetch = vi.fn((url) => {
      if (String(url).includes("playoffOdds")) {
        return Promise.resolve({ ok: true, json: () => Promise.resolve({ owners: [] }) });
      }
      const body = payload();
      body.trend = { lens: "results_only", weeks: [], seriesByOwner: {} };
      return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
    });
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getAllByText("Alice").length).toBeGreaterThan(0));
    expect(container.querySelector("svg")).toBeNull();
  });

  it("threads managers through for Avatar/name rendering", async () => {
    const RosPowerSection = await renderFresh();
    const managers = { o1: { displayName: "Alice M." } };
    render(<RosPowerSection managers={managers} />);
    await waitFor(() => expect(screen.getAllByTestId("avatar").length).toBeGreaterThan(0));
  });
});
