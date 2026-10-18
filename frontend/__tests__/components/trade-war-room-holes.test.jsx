/**
 * TC-B / TCM-H12 — holes and bye coverage in Roster construction impact.
 *
 * The roster lens carries `lineupHoles` from the one best-ball utility owner
 * (`src/roster_intel/best_ball_utility.py`); the War Room words it and
 * computes nothing.  The committed fixtures are real analyze output (a full
 * roster: zero empty slots); a hole is shown by editing one copy.
 */
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import TradeWarRoom from "@/components/trade/TradeWarRoom";
import { lineupHolesSummary } from "@/lib/trade-war-room";
import CONSOLIDATION from "../fixtures/trade-war-room/consolidation.json";

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
        before: { emptySlotsPerWeek: null, emptyBySlot: null, noEligiblePlayer: [], onlyUnprojected: [] },
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
    expect(s.bySlotAfter).toBe("TE 1.0 · FLEX 0.1");
    expect(s.noEligible).toEqual(["TE"]);
    expect(s.delta).toBeNull();
  });
});

describe("TradeWarRoom — holes", () => {
  it("the real fixture (a full roster) reports zero empty slots, measured", async () => {
    const h = CONSOLIDATION.analysis.lenses.roster.detail.lineupHoles;
    expect(h.before.emptySlotsPerWeek).toBe(0);
    await renderWith(CONSOLIDATION);
    expect(screen.getByTestId("war-room-lineup-holes").textContent).toMatch(
      /0\.0 → 0\.0 empty starting slots per week/,
    );
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
    expect(row.textContent).toMatch(/0\.0 → 1\.0 empty starting slots per week \(after: TE 1\.0\)/);
    expect(row.textContent).toMatch(/no player can start at TE/);
  });
});
