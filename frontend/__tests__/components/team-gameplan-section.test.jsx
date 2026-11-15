// /rosters "Team Gameplan" (owner decision 2026-11-07, W20-F001): on-demand, selected team only.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor, cleanup } from "@testing-library/react";

import TeamGameplanSection from "@/components/TeamGameplanSection";

function payload(ownerId = "owner0", overrides = {}) {
  return {
    team: { ownerId, teamName: `Team ${ownerId}` },
    competitivePosture: {
      available: true,
      label: "PUSH",
      evidence: "measured",
      confidence: 0.62,
      isVerdict: false,
    },
    roster: {
      competitiveWindow: { mostLikely: "playoff_contender", confidence: 0.49, affinities: {} },
      weakness: {
        available: true,
        needs: [
          { position: "RB", level: "high", priority: 3 },
          { position: "TE", level: "none", priority: 0 },
        ],
        urgentPositions: ["RB"],
      },
      positions: {
        QB: { position: "QB", tradeableSurplus: 153, surplusPlayers: ["Qb One", "Qb Two"] },
        WR: { position: "WR", tradeableSurplus: 0, surplusPlayers: [] },
      },
      // The audited fake zeros: must never reach the screen.
      values: { market: 0, consensus: 0, leagueAdjusted: 0 },
    },
    targetPositions: [
      { position: "RB", viability: "viable", reason: "upgrade" },
      { position: "TE", viability: "noCandidates", reason: "none supplied" },
    ],
    targetPlayers: [{ playerId: "p1", name: "Target Guy", position: "RB", recommended: true, reason: "r" }],
    timing: { sourceStamp: "abc" },
    ...overrides,
  };
}

function jsonResponse(status, body) {
  return Promise.resolve({ status, ok: status < 400, json: () => Promise.resolve(body) });
}

describe("TeamGameplanSection", () => {
  let fetchMock;
  beforeEach(() => {
    fetchMock = vi.fn(() => jsonResponse(200, payload()));
    vi.stubGlobal("fetch", fetchMock);
    window.localStorage.setItem("next_active_league_v1", "dynasty_main");
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    window.localStorage.clear();
  });

  const expand = () => fireEvent.click(screen.getByRole("button", { name: /Team Gameplan/ }));

  it("is collapsed by default and makes no request", async () => {
    render(<TeamGameplanSection ownerId="owner0" teamName="Team owner0" />);
    const btn = screen.getByRole("button", { name: /Team Gameplan/ });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("expanding fetches once with the selected team and league", async () => {
    render(<TeamGameplanSection ownerId="owner0" teamName="Team owner0" />);
    expand();
    await screen.findByText(/Push — competing now/);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const url = new URL(fetchMock.mock.calls[0][0], "http://x");
    expect(url.pathname).toBe("/api/gameplan");
    expect(url.searchParams.get("team")).toBe("owner0");
    expect(url.searchParams.get("leagueKey")).toBe("dynasty_main");
    // collapse + re-expand does not refetch
    expand();
    expand();
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("renders posture, window, strengths, weaknesses and opportunities from the payload", async () => {
    render(<TeamGameplanSection ownerId="owner0" teamName="Team owner0" />);
    expand();
    await screen.findByText(/Push — competing now/);
    expect(screen.getByText(/62% leaning/)).toBeTruthy();
    expect(screen.getByText("Playoff contender")).toBeTruthy();
    expect(screen.getByText(/surplus depth/)).toBeTruthy();
    expect(screen.getByText(/Qb One, Qb Two/)).toBeTruthy();
    expect(screen.getByText(/High need/)).toBeTruthy();
    expect(screen.getByText(/\(urgent\)/)).toBeTruthy();
    expect(screen.getByText(/upgrade is obtainable/)).toBeTruthy();
    expect(screen.getByText(/Target Guy \(RB\)/)).toBeTruthy();
    expect(screen.getByText(/Not measured: TE/)).toBeTruthy();
  });

  it("never surfaces the audited fake-zero value lanes", async () => {
    const { container } = render(<TeamGameplanSection ownerId="owner0" teamName="Team owner0" />);
    expand();
    await screen.findByText(/Push — competing now/);
    const text = container.textContent;
    expect(text).not.toMatch(/leagueAdjusted|consensus|market value/i);
    expect(text).not.toMatch(/\b0\.0\b/);
  });

  it("renders missing fields as unavailable, not 0", async () => {
    fetchMock.mockImplementation(() =>
      jsonResponse(200, {
        team: { ownerId: "owner0", teamName: "T" },
        competitivePosture: { available: false, unavailableReason: "league_bundle_not_warm" },
        roster: { weakness: { available: false, unavailableReason: "no_rosters_loaded" } },
      }),
    );
    const { container } = render(<TeamGameplanSection ownerId="owner0" teamName="T" />);
    expand();
    await screen.findByText(/Posture: not available/);
    expect(screen.getByText(/the league build has not been prepared yet/)).toBeTruthy();
    expect(screen.getByText(/Weaknesses: not available/)).toBeTruthy();
    expect(screen.getByText(/Strengths: not available/)).toBeTruthy();
    expect(screen.getByText(/Opportunities: not available/)).toBeTruthy();
    expect(container.textContent).not.toMatch(/\b0%/);
  });

  it("an unmeasured posture shows no confidence number", async () => {
    fetchMock.mockImplementation(() =>
      jsonResponse(
        200,
        payload("owner0", {
          competitivePosture: { available: true, label: "HOLD", evidence: "none", confidence: null },
        }),
      ),
    );
    const { container } = render(<TeamGameplanSection ownerId="owner0" teamName="T" />);
    expand();
    await screen.findByText(/Hold — no clear direction/);
    expect(container.textContent).not.toMatch(/leaning/);
    expect(container.textContent).toMatch(/Not enough competitiveness evidence/);
  });

  it.each([
    [401, { error: "unauthorized" }, /Sign-in required/],
    [403, { error: "forbidden" }, /Not available to this account/],
    [503, { error: "data_not_ready", message: "No data loaded for league x" }, /No data loaded for league x/],
  ])("status %i renders its own state", async (status, body, expected) => {
    fetchMock.mockImplementation(() => jsonResponse(status, body));
    render(<TeamGameplanSection ownerId="owner0" teamName="T" />);
    expand();
    await screen.findByText(expected);
    expect(screen.queryByText(/Push — competing now/)).toBeNull();
  });

  it("switching team refetches only on expand", async () => {
    const { rerender } = render(<TeamGameplanSection ownerId="owner0" teamName="A" />);
    expand();
    await screen.findByText(/Push — competing now/);
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // fold, switch team: nothing fetched while folded
    expand();
    fetchMock.mockImplementation(() => jsonResponse(200, payload("owner1")));
    rerender(<TeamGameplanSection ownerId="owner1" teamName="B" />);
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).toHaveBeenCalledTimes(1);

    // expand: exactly one more request, for the new team
    expand();
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(new URL(fetchMock.mock.calls[1][0], "http://x").searchParams.get("team")).toBe("owner1");
  });

  it("asks the user to choose a team when none is selected, without a request", async () => {
    render(<TeamGameplanSection ownerId="" teamName="" />);
    expand();
    await screen.findByText(/Choose a team/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("after team A errors, switching to team B shows loading, not A's stale error", async () => {
    let releaseB;
    fetchMock.mockImplementation((url) => {
      const team = new URL(url, "http://x").searchParams.get("team");
      if (team === "owner0") return jsonResponse(500, { error: "boom" });
      return new Promise((resolve) => {
        releaseB = () => resolve({ status: 200, ok: true, json: () => Promise.resolve(payload("owner1")) });
      });
    });
    const { rerender } = render(<TeamGameplanSection ownerId="owner0" teamName="A" />);
    expand();
    await waitFor(() => expect(screen.queryByText(/Building the gameplan/)).toBeNull());
    expect(screen.queryByText(/Push — competing now/)).toBeNull();

    rerender(<TeamGameplanSection ownerId="owner1" teamName="B" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(screen.getByText(/Building the gameplan/)).toBeTruthy();
    releaseB();
    await screen.findByText(/Push — competing now/);
  });

  it("a payload for a different owner renders loading, never 'not available' or the other team", async () => {
    let releaseB;
    fetchMock.mockImplementation((url) => {
      const team = new URL(url, "http://x").searchParams.get("team");
      if (team === "owner0") return jsonResponse(200, payload("owner0"));
      return new Promise((resolve) => {
        releaseB = () => resolve({ status: 200, ok: true, json: () => Promise.resolve(payload("owner1")) });
      });
    });
    const { rerender } = render(<TeamGameplanSection ownerId="owner0" teamName="A" />);
    expand();
    await screen.findByText(/Push — competing now/);

    rerender(<TeamGameplanSection ownerId="owner1" teamName="B" />);
    expect(screen.queryByText(/not available/i)).toBeNull();
    expect(screen.queryByText(/different team/i)).toBeNull();
    expect(screen.queryByText(/Push — competing now/)).toBeNull();
    expect(screen.getByText(/Building the gameplan/)).toBeTruthy();
    releaseB();
    await screen.findByText(/Push — competing now/);
  });
});
