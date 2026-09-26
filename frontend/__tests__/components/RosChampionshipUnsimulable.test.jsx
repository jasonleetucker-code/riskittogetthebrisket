/**
 * D1 (2026-09-26) — a refused championship simulation must render its
 * refusal, never flat coin-flip odds and never "wait for games".
 *
 * A refresh lost Sleeper's NFL player dump, every team strength became 0,
 * and the page published ~13/12/10% odds for every team as if they were
 * real. The backend now refuses (`unsimulable.reason ===
 * "team_strength_unavailable"`) and this section shows that reason. The
 * generic empty copy ("Need at least a partial regular season") would be
 * false here: the games were played.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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

const REFUSED = {
  championshipOdds: [],
  n_simulations: 0,
  playoffSeeds: 7,
  byeSeeds: 1,
  rosStrengthAvailable: false,
  unsimulable: {
    reason: "team_strength_unavailable",
    detail:
      "ROS team strength is unavailable (the last roster refresh could not price any team). This is not an equal chance for everyone.",
    teamsWithoutEvidence: 12,
    teamCount: 12,
  },
};

async function renderWith(payload) {
  vi.resetModules();
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }),
  );
  const mod = await import("../../app/league/sections/ros-championship.jsx");
  const Section = mod.default;
  return render(<Section />);
}

describe("RosChampionshipSection — the team-strength refusal", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("names the refusal and shows the backend's reason", async () => {
    const { container } = await renderWith(REFUSED);
    await waitFor(() =>
      expect(screen.getByText(/rosters could not be priced/i)).toBeTruthy(),
    );
    expect(screen.getByText(/not an equal chance for everyone/i)).toBeTruthy();
    // Not the generic "wait for games" copy, and no odds table at all.
    expect(screen.queryByText(/Need at least a partial regular season/i)).toBeNull();
    expect(container.querySelector("table")).toBeNull();
  });

  it("still renders real odds (non-vacuity)", async () => {
    await renderWith({
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
    expect(screen.queryByText(/rosters could not be priced/i)).toBeNull();
  });
});
