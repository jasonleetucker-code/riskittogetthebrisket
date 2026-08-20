/**
 * V1-52 — "nothing to rank on" must not render as "not ready yet".
 *
 * The backend refuses to publish a ranking when every weighted component
 * is unavailable, because the alternative is what it used to do: score
 * every owner 0.0 and hand out ranks 1..N in owner-id order, an
 * identifier ordering presented as a power ranking.
 *
 * On the client the two states look identical if nothing distinguishes
 * them — both are "no numbers" — but they mean opposite things. "Not
 * ready" promises the numbers arrive on their own; the refusal does not,
 * and for the results-only lens in the offseason it persists until the
 * season starts. Same argument as the unknown-playoff-bracket state.
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

const UNRANKABLE = {
  currentRanking: [
    { ownerId: "o1", displayName: "Alice", powerScore: null, rank: null, components: {} },
    { ownerId: "o2", displayName: "Bob", powerScore: null, rank: null, components: {} },
  ],
  unrankable: {
    reason: "preseason_and_no_forward_looking_input",
    missingInputs: ["ppg", "recent", "team_ros_strength (lens: results_only)"],
    explanation:
      "Every weighted component is unavailable, so there is no quantity to rank on.",
  },
  weights: {},
  effectiveWeights: {},
  missingInputs: [],
  preseason: true,
};

async function renderWith(payload) {
  vi.resetModules();
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(payload) }),
  );
  const mod = await import("../../app/league/sections/ros-power.jsx");
  const RosPowerSection = mod.default;
  return render(<RosPowerSection />);
}

describe("RosPowerSection — the refusal", () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.restoreAllMocks());

  it("names the state instead of promising the numbers are coming", async () => {
    await renderWith(UNRANKABLE);
    await waitFor(() => expect(screen.getByText(/Not enough to rank on/i)).toBeTruthy());
    // The "not ready" copy promises a future scrape will populate it.
    expect(screen.queryByText(/next scheduled scrape/i)).toBeNull();
    expect(screen.queryByText(/ROS Power not ready/i)).toBeNull();
  });

  it("shows the reason the backend gave", async () => {
    await renderWith(UNRANKABLE);
    await waitFor(() => expect(screen.getByText(/no quantity to rank on/i)).toBeTruthy());
    expect(screen.getByText(/team_ros_strength/)).toBeTruthy();
  });

  it("does not print a rank or a score for anyone", async () => {
    const { container } = await renderWith(UNRANKABLE);
    await waitFor(() => expect(screen.getByText(/Not enough to rank on/i)).toBeTruthy());
    // No ranking table at all — not a table of dashes, which reads as
    // "loading" to anyone scanning the page.
    expect(container.querySelector("table")).toBeNull();
  });

  it("still ranks when a component survives (non-vacuity)", async () => {
    await renderWith({
      currentRanking: [
        {
          ownerId: "o1",
          displayName: "Alice",
          powerScore: 88.5,
          rank: 1,
          components: { ppg: 0.9 },
          weightsApplied: { ppg: 0.18 },
        },
      ],
      unrankable: null,
      weights: { ppg: 0.18 },
      effectiveWeights: { ppg: 0.18 },
      missingInputs: [],
      preseason: false,
    });
    await waitFor(() => expect(screen.getByText("Alice")).toBeTruthy());
    expect(screen.queryByText(/Not enough to rank on/i)).toBeNull();
  });
});
