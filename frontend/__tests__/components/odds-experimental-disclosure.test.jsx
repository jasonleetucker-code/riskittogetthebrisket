/**
 * Owner decision 9 (2026-11-01): uncalibrated playoff / championship odds
 * carry the exact owner-approved disclosure wherever they are displayed.
 *
 * Pins (1) the wording verbatim, (2) its presence on the main odds surface
 * (/league ROS Championship Odds) and the Trade Deadline dashboard whenever
 * odds render, (3) its absence when no odds are shown (a refusal is not a
 * projection), and (4) that the Trade War Room's odds caveat carries it.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

import { ODDS_EXPERIMENTAL_DISCLOSURE } from "@/lib/odds-disclosure";
import { SEASON_ODDS_CAVEAT } from "@/lib/trade-war-room-copy";

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

const EXACT =
  "Experimental projection — not yet calibrated against this league's historical outcomes.";

async function renderSection(path, payload) {
  vi.resetModules();
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }),
  );
  const mod = await import(path);
  const Section = mod.default;
  return render(<Section />);
}

describe("uncalibrated odds disclosure (owner decision 9)", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("is the exact owner-approved sentence", () => {
    expect(ODDS_EXPERIMENTAL_DISCLOSURE).toBe(EXACT);
  });

  it("is shown on the ROS Championship Odds surface when odds render", async () => {
    await renderSection("../../app/league/sections/ros-championship.jsx", {
      championshipOdds: [
        {
          ownerId: "o1",
          displayName: "Alice",
          championshipOdds: 0.41,
          finalsOdds: 0.6,
          semifinalOdds: 0.8,
          playoffOdds: 0.95,
          expectedFinish: 2.1,
          contenderTier: "Favorite",
        },
      ],
      n_simulations: 10000,
      playoffSeeds: 7,
      byeSeeds: 1,
      rosStrengthAvailable: true,
    });
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(screen.getByText("41.0%")).toBeTruthy();
    expect(screen.getByText(EXACT)).toBeTruthy();
  });

  it("is not shown when the simulation is refused (no odds displayed)", async () => {
    await renderSection("../../app/league/sections/ros-championship.jsx", {
      championshipOdds: [],
      n_simulations: 0,
      unsimulable: { reason: "team_strength_unavailable", detail: "No team strength evidence." },
    });
    await waitFor(() =>
      expect(screen.getByText(/rosters could not be priced/i)).toBeTruthy(),
    );
    expect(document.querySelector("table")).toBeNull();
    expect(screen.queryByText(EXACT)).toBeNull();
  });

  it("is shown on the Trade Deadline dashboard beside its odds", async () => {
    await renderSection("../../app/league/sections/ros-trade-deadline.jsx", {
      teams: [
        {
          ownerId: "o1",
          displayName: "Bob",
          championshipOdds: 0.2,
          playoffOdds: 0.7,
          label: "Buyer",
        },
      ],
    });
    await waitFor(() => expect(screen.getByText("Bob")).toBeTruthy());
    expect(screen.getByText(EXACT)).toBeTruthy();
  });

  it("leads the Trade War Room's season-odds caveat", () => {
    expect(SEASON_ODDS_CAVEAT.startsWith(EXACT)).toBe(true);
  });
});
