/**
 * V1-52 — the canonical engine's results-only lens and per-week trend
 * were shipped in the backend (power_v2.build_section) but nothing on
 * the client ever asked for them: no lens toggle existed, and the
 * `trend` field the engine already computes was never read. This
 * closed two of the four named Step-5 prerequisites.
 *
 * The trend is RESULTS-ONLY at every point (see power_v2.py's own
 * comment on why forward-looking has no per-week history to trend),
 * so the delta indicator must never be described as agreeing with a
 * forward-looking headline score — it is a distinct, always-retrospective
 * quantity, named as such in the UI.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";

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

function rankedPayload({ lens, ownerRank, priorRank }) {
  return {
    currentRanking: [
      {
        ownerId: "o1",
        displayName: "Alice",
        powerScore: 88.5,
        rank: ownerRank,
        components: { ppg: 0.9 },
        rosStrengthPercentile: 0.7,
        weightsApplied: { ppg: 0.18 },
      },
    ],
    unrankable: null,
    lens,
    weights: { ppg: 0.18 },
    effectiveWeights: { ppg: 0.18 },
    missingInputs: [],
    preseason: false,
    trend: {
      lens: "results_only",
      weeks: [
        { season: "2025", week: 1, rankings: [] },
        { season: "2025", week: 2, rankings: [] },
      ],
      seriesByOwner: {
        o1: [
          { season: "2025", week: 1, powerScore: 70, rank: priorRank },
          { season: "2025", week: 2, powerScore: 80, rank: ownerRank },
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

describe("RosPowerSection — lens toggle and trend", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("fetches the default forward-looking lens with no query param", async () => {
    const calls = [];
    global.fetch = vi.fn((url) => {
      calls.push(String(url));
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(rankedPayload({ lens: "forward_looking", ownerRank: 1, priorRank: 2 })),
      });
    });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(calls[0]).toBe("/api/public/league/rosPower");
  });

  it("switching to results-only re-fetches with the lens query param", async () => {
    const calls = [];
    global.fetch = vi.fn((url) => {
      calls.push(String(url));
      const lens = String(url).includes("lens=results_only") ? "results_only" : "forward_looking";
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(rankedPayload({ lens, ownerRank: 1, priorRank: 2 })),
      });
    });
    const RosPowerSection = await renderFresh();
    render(<RosPowerSection />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());

    fireEvent.click(screen.getByRole("button", { name: /results only/i }));

    await waitFor(() =>
      expect(calls.some((u) => u.includes("lens=results_only"))).toBe(true),
    );
  });

  it("renders an up arrow when the trend series shows an improving rank", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        // prior week rank 5, current week rank 1 -> moved up 4 spots
        json: () => Promise.resolve(rankedPayload({ lens: "forward_looking", ownerRank: 1, priorRank: 5 })),
      }),
    );
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(container.textContent).toContain("▲");
    expect(container.textContent).toContain("4");
  });

  it("renders a dash, not a fabricated zero, when trend history is too short", async () => {
    global.fetch = vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            currentRanking: [
              {
                ownerId: "o1",
                displayName: "Alice",
                powerScore: 88.5,
                rank: 1,
                components: {},
                weightsApplied: {},
              },
            ],
            unrankable: null,
            lens: "forward_looking",
            weights: {},
            effectiveWeights: {},
            missingInputs: [],
            preseason: false,
            trend: { lens: "results_only", weeks: [], seriesByOwner: {} },
          }),
      }),
    );
    const RosPowerSection = await renderFresh();
    const { container } = render(<RosPowerSection />);
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(container.textContent).not.toContain("▲");
    expect(container.textContent).not.toContain("▼");
  });
});
