// /tools/trade-coverage audits EVERY team in the contract — including an
// ownerless (orphaned) roster.
//
// Sleeper publishes ``owner_id: null`` when a manager leaves; the contract
// then carries that roster with ``ownerId: ""`` and the name
// ``"Team <roster_id>"``.  The page used to build its fan-out queue with
// ``.filter((entry) => entry.ownerId)`` and key its state by ownerId, so the
// orphan was silently dropped: 11 rows and "11/12 scanned" for a 12-team
// league (dynasty_main roster 12, 2026-10-20, E2E run 39348160535).
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const TEAMS = [
  { ownerId: "o1", roster_id: 1, name: "Jason", players: ["A", "B"] },
  { ownerId: "o2", roster_id: 2, name: "Ed", players: ["C"] },
  { ownerId: "", roster_id: 12, name: "Team 12", players: ["D", "E", "F"] },
];

vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rawData: { sleeper: { teams: TEAMS } }, loading: false }),
}));
vi.mock("@/components/useTeam", () => ({
  useTeam: () => ({ availableTeams: TEAMS, loading: false }),
}));

import TradeCoveragePage from "@/app/tools/trade-coverage/page";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ authenticated: true, teamAggregates: {} }),
    }),
  );
});

describe("trade coverage audit — ownerless roster", () => {
  it("renders one row per contract team, the orphan included", async () => {
    const { container } = render(<TradeCoveragePage />);
    await waitFor(() =>
      expect(container.querySelectorAll(".trade-coverage-row")).toHaveLength(TEAMS.length),
    );
    const names = [...container.querySelectorAll(".trade-coverage-team-name")].map(
      (el) => el.textContent,
    );
    expect(names.sort()).toEqual(["Ed", "Jason", "Team 12"]);
    expect(screen.getByText(`${TEAMS.length}/${TEAMS.length}`)).toBeTruthy();
  });

  it("asks the terminal for the orphan by its contract name, never by an empty ownerId", async () => {
    render(<TradeCoveragePage />);
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(TEAMS.length));
    const queries = fetch.mock.calls.map(([url]) => new URL(url, "http://x").searchParams);
    for (const q of queries) {
      expect(q.get("team"), "an empty ownerId is never sent").not.toBe("");
    }
    const orphan = queries.find((q) => q.get("teamName") === "Team 12");
    expect(orphan, "orphan roster queried by name").toBeTruthy();
    expect(orphan.has("team")).toBe(false);
  });
});
