/**
 * The War Room keeps four different quantities apart (owner request
 * 2026-10-28).  Display copy only -- no number changes:
 *
 *   trade value        long-term dynasty market value (the board)
 *   impact on the team expected points for the rest of THIS season, from
 *                      projections (separate row, with its basis stated)
 *   roster fit         roster spots / forced cuts (separate row)
 *   playoff / title    not part of the analysis; labelled experimental and
 *                      uncalibrated wherever it is mentioned
 *
 * and an IDP caveat when defenders are in the simulated lineup.
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TradeWarRoom from "@/components/trade/TradeWarRoom";
import {
  LINEUP_BASIS_NOTE,
  SEASON_ODDS_CAVEAT,
  hasInternalIdentifier,
  idpProjectionCaveat,
  lineupBasisNotes,
} from "@/lib/trade-war-room-copy";

import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";

const req = (fixture) => ({ ...fixture._fixture.request, mySide: 0 });

async function renderWith(fixture) {
  globalThis.fetch = vi.fn(async () => ({
    ok: true,
    status: 200,
    json: async () => fixture,
  }));
  const view = render(
    <TradeWarRoom
      request={req(fixture)}
      leagueKey="main"
      useTeamContext={fixture._fixture.request.useTeamContext}
    />,
  );
  await act(async () => {
    vi.advanceTimersByTime(800);
  });
  await act(async () => {});
  return view;
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("lineup basis copy", () => {
  it("states what the impact number is and is not", () => {
    expect(LINEUP_BASIS_NOTE).toMatch(/rest of this season/);
    expect(LINEUP_BASIS_NOTE).toMatch(/not long-term dynasty value/);
    expect(LINEUP_BASIS_NOTE).toMatch(/does not include playoff or title odds/);
    expect(hasInternalIdentifier(LINEUP_BASIS_NOTE)).toBe(false);
  });

  it("adds an IDP caveat only when a defender is listed", () => {
    const offense = { players: [{ position: "QB" }, { position: "WR" }] };
    expect(idpProjectionCaveat(offense)).toBeNull();
    expect(lineupBasisNotes(offense)).toEqual([LINEUP_BASIS_NOTE]);
    for (const pos of ["DL", "LB", "DB", "edge", "CB", "S"]) {
      const withIdp = { players: [{ position: "QB" }, { position: pos }] };
      expect(idpProjectionCaveat(withIdp)).toMatch(
        /point scale has not been confirmed/,
      );
      expect(lineupBasisNotes(withIdp)).toHaveLength(2);
    }
    expect(idpProjectionCaveat(null)).toBeNull();
    expect(idpProjectionCaveat({ players: [{}] })).toBeNull();
  });

  it("calls season odds experimental and uncalibrated", () => {
    expect(SEASON_ODDS_CAVEAT).toMatch(/experimental/);
    expect(SEASON_ODDS_CAVEAT).toMatch(/uncalibrated/);
  });
});

describe("TradeWarRoom keeps value, expected points and odds apart", () => {
  it("states the basis under 'Impact on your team' and separates it from trade value", async () => {
    await renderWith(CONSOLIDATION);
    const impactRow = document.querySelector('[data-lens="roster"]');
    expect(impactRow).toHaveTextContent(/rest of this season/);
    expect(screen.getAllByTestId("war-room-impact-basis")[0]).toHaveTextContent(
      LINEUP_BASIS_NOTE,
    );
    // Trade value is the other concept and is not described as points.
    const valueRow = document.querySelector('[data-lens="market"]');
    expect(valueRow).not.toHaveTextContent(/rest of this season/);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Sources, simulations and methodology",
      }),
    );
    expect(
      screen.getByText(
        /Trade value is long-term dynasty market value, not this season's expected points/,
      ),
    ).toBeInTheDocument();
  });

  it("labels the not-yet-included playoff and title odds as experimental and uncalibrated", async () => {
    await renderWith(CONSOLIDATION);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Sources, simulations and methodology",
      }),
    );
    // The dimension name is unchanged (other tests rely on it) ...
    expect(
      screen.getByText("Change in this season's playoff and title odds"),
    ).toBeInTheDocument();
    // ... and its line carries the caveat.
    const li = screen
      .getByText("Change in this season's playoff and title odds")
      .closest("li");
    expect(li).toHaveTextContent(/experimental and uncalibrated/);
    // Team direction is read from those odds and says the same.
    expect(document.body.textContent).toContain(SEASON_ODDS_CAVEAT);
  });
});
