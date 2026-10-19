/**
 * TC-B / TCM-H12 — holes and bye coverage in "Your lineup before and after".
 *
 * The roster lens carries `lineupHoles` from the one best-ball utility owner
 * (`src/roster_intel/best_ball_utility.py`); the War Room words it and
 * computes nothing.  The committed fixtures are real analyze output (a full
 * roster: zero empty slots); a hole is shown by editing one copy.
 */
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TradeWarRoom from "@/components/trade/TradeWarRoom";
import { countedSlots, lineupHolesSummary, slotWords } from "@/lib/trade-war-room";
import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";
import SUPERFLEX from "../fixtures/trade-war-room/superflex-holes.json";

const ok = (body) => ({ ok: true, status: 200, json: async () => body });

async function renderWith(payload) {
  globalThis.fetch = vi.fn(async () => ok(payload));
  render(
    <TradeWarRoom
      request={{ ...payload._fixture.request, mySide: 0 }}
      leagueKey="main"
      useTeamContext={payload._fixture.request.useTeamContext}
    />,
  );
  await act(async () => {
    vi.advanceTimersByTime(800);
  });
  await act(async () => {});
  // Holes live in the "Your lineup before and after" detail (owner directive
  // 2026-10-19: expandable, not on the first screen).
  fireEvent.click(screen.getByRole("button", { name: "Your lineup before and after" }));
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("lineupHolesSummary", () => {
  it("words the owner's block; an unmeasured side reads —, never 0", () => {
    expect(lineupHolesSummary({})).toBeNull();
    const s = lineupHolesSummary({
      lineupHoles: {
        before: {
          emptySlotsPerWeek: null,
          emptyBySlot: null,
          noEligiblePlayer: [],
          onlyUnprojected: [],
        },
        after: {
          emptySlotsPerWeek: 1.08,
          emptyBySlot: { TE: 1, FLEX: 0.08 },
          noEligiblePlayer: ["TE"],
          onlyUnprojected: [],
        },
        emptySlotsPerWeekDelta: null,
      },
    });
    expect(s.perWeek).toBe("— → 1.1 empty starting slots per week");
    expect(s.bySlotAfter).toBe("TE 1.0 · flex (RB/WR/TE) 0.1");
    expect(s.noEligible).toEqual(["TE"]);
    expect(s.delta).toBeNull();
  });
});

describe("TradeWarRoom — holes", () => {
  it("the real fixture (a full roster) reports zero empty slots, measured", async () => {
    const h = CONSOLIDATION.analysis.lenses.roster.detail.lineupHoles;
    expect(h.before.emptySlotsPerWeek).toBe(0);
    await renderWith(CONSOLIDATION);
    const row = screen.getByTestId("war-room-lineup-holes");
    expect(within(row).getByRole("rowheader")).toHaveTextContent(/^Empty starting slots per week/);
    expect(
      within(row)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["0.0", "0.0"]);
  });

  it("names a slot the roster can no longer fill", async () => {
    const payload = structuredClone(CONSOLIDATION);
    payload.analysis.lenses.roster.detail.lineupHoles.after = {
      emptySlotsPerWeek: 1,
      emptyBySlot: { TE: 1 },
      noEligiblePlayer: ["TE"],
      onlyUnprojected: [],
    };
    payload.analysis.lenses.roster.detail.lineupHoles.emptySlotsPerWeekDelta = 1;
    await renderWith(payload);
    const row = screen.getByTestId("war-room-lineup-holes");
    expect(
      within(row)
        .getAllByRole("cell")
        .map((c) => c.textContent),
    ).toEqual(["0.0", "1.0"]);
    expect(row.textContent).toMatch(/After the trade: TE 1\.0\./);
    expect(row.textContent).toMatch(/Slots no player can fill: TE\./);
  });

  it("REAL superflex / IDP holes: slot codes worded, repeats counted", async () => {
    // `superflex-holes`: the best-ball owner's own lineupHoles for a lineup
    // the 7-man roster cannot fill.
    const h = SUPERFLEX.analysis.lenses.roster.detail.lineupHoles.after;
    expect(h.noEligiblePlayer).toEqual([
      "RB",
      "WR",
      "WR",
      "WR",
      "SUPER_FLEX",
      "WR_RB_FLEX",
      "DB",
      "DB",
      "IDP_FLEX",
    ]); // as emitted
    const s = lineupHolesSummary(SUPERFLEX.analysis.lenses.roster.detail);
    expect(s.noEligible).toEqual([
      "RB",
      "3 WR",
      "superflex",
      "RB/WR flex",
      "2 DB",
      "defensive flex (DL/LB/DB)",
    ]);
    expect(s.bySlotAfter).toBe(
      "WR 3.0 · DB 2.0 · RB 2.0 · defensive flex (DL/LB/DB) 1.0 · superflex 1.0 · RB/WR flex 1.0",
    );
    await renderWith(SUPERFLEX);
    const row = screen.getByTestId("war-room-lineup-holes");
    expect(row.textContent).toContain(
      "Slots no player can fill: RB, 3 WR, superflex, RB/WR flex, 2 DB and defensive flex (DL/LB/DB).",
    );
    expect(row.textContent).not.toMatch(/SUPER_FLEX|WR_RB_FLEX|IDP_FLEX|_/);
  });

  it("every slot code has words; an unknown code is never shown", () => {
    for (const [slot, words] of [
      ["SUPER_FLEX", "superflex"],
      ["FLEX", "flex (RB/WR/TE)"],
      ["WR_RB_FLEX", "RB/WR flex"],
      ["REC_FLEX", "WR/TE flex"],
      ["IDP_FLEX", "defensive flex (DL/LB/DB)"],
      ["DL_LB", "DL/LB flex"],
      ["DB_LB", "DB/LB flex"],
      ["DL_DB", "DL/DB flex"],
      ["QB", "QB"],
      ["K", "K"],
      ["DEF", "team defense"],
      ["WEIRD_SLOT", "another starting slot"],
    ]) {
      expect(slotWords(slot)).toBe(words);
    }
    expect(countedSlots(["RB", "RB", "WR"])).toEqual(["2 RB", "WR"]);
  });
});
