/**
 * Schedule Multiverse (Milestone B): renders the backend timing_only_v1 block
 * verbatim, marks the actual outcome, and is honest about unavailable states.
 */
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { ScheduleMultiverseTable, WinDistribution } from "@/components/league/ScheduleMultiverse";
import { fmtShare, timingNotice, timingReading } from "@/lib/schedule-impact";

function row(teamKey, name, extra) {
  return {
    teamKey,
    ownerId: teamKey,
    teamName: name,
    actualH2HCredits: 7,
    h2hWins: 7,
    h2hLosses: 6,
    h2hTies: 0,
    scheduleImpact: 0.5,
    ...extra,
  };
}

const complete = {
  state: "complete",
  season: "2025",
  teams: [
    row("a", "Lucky", {
      timingOnly: {
        state: "complete",
        expectedCredits: 4.0769,
        impact: 2.9231,
        probBelowActual: 0.9846,
        probEqualActual: 0.0103,
        probAboveActual: 0.0051,
        central80: { low: 2, high: 6 },
        minCredits: 0,
        maxCredits: 9,
        distribution: [
          [0, 0.01],
          [4, 0.5],
          [7, 0.0103],
          [9, 0.4797],
        ],
      },
    }),
    row("b", "Bye Team", { timingOnly: { state: "unavailable", reason: "bye_weeks_change_game_count" } }),
  ],
  timingOnly: {
    state: "complete",
    model: { id: "timing_only_v1" },
    algorithmVersion: "schedule-timing-2026.09-b1",
    permutedWeeks: [1, 2, 3],
    totalCalendars: 6227020800,
  },
};

describe("Schedule Multiverse", () => {
  it("shows backend numbers and flags a non-comparable team", () => {
    render(<ScheduleMultiverseTable contract={complete} />);
    const block = screen.getByTestId("schedule-multiverse");
    expect(block.dataset.state).toBe("complete");
    expect(within(block).getByText("+2.9")).toBeTruthy();
    expect(within(block).getByText(/Not comparable: a bye/)).toBeTruthy();
  });

  it("marks exactly the actual win total in the distribution", () => {
    const { container } = render(
      <WinDistribution distribution={complete.teams[0].timingOnly.distribution} actual={7} />,
    );
    const svg = container.querySelector("svg");
    expect(svg.getAttribute("aria-label")).toMatch(/Actual: 7/);
    // One bar + one marker for the actual total.
    const rects = [...svg.querySelectorAll("rect")];
    expect(rects).toHaveLength(5);
  });

  it("reads the tails with explicit direction and no false 0%", () => {
    const text = timingReading(complete.teams[0]);
    expect(text).toContain("average 4.1");
    expect(text).toContain("80% of orderings: 2.0–6.0");
    expect(text).toContain("1% of orderings give more wins");
    expect(fmtShare(0.004)).toBe("<1%");
    expect(text).toContain("98% give fewer");
    expect(fmtShare(0)).toBe("0%");
    expect(fmtShare(0.999)).toBe(">99%");
  });

  it("renders an honest notice instead of a table when the season is unsupported", () => {
    const contract = { ...complete, timingOnly: { state: "unsupported", reason: "structural_issues" } };
    render(<ScheduleMultiverseTable contract={contract} />);
    expect(screen.getByText(/missing score or matchup row/)).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
    expect(timingNotice({ state: "failed" }).tone).toBe("warning");
  });
});
