/**
 * Schedule Intelligence UI foundation (Milestone A). The components render the
 * canonical contract verbatim; lib/schedule-impact.js only formats. Every
 * non-complete state says so honestly; no manager-quality language.
 */
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  ImpactValue,
  ScheduleImpactSummary,
  ScheduleImpactTable,
} from "@/components/league/ScheduleImpact";
import {
  fmtRecord,
  fmtSignedCredits,
  impactDirection,
  interpretation,
  stateNotice,
  teamLabel,
} from "@/lib/schedule-impact";

function team(key, over = {}) {
  return {
    teamKey: key,
    ownerId: key,
    orphanRoster: false,
    rosterId: 1,
    teamName: `Team ${key}`,
    displayName: key,
    games: 3,
    h2hWins: 2,
    h2hLosses: 1,
    h2hTies: 0,
    actualH2HCredits: 2,
    allPlayWins: 21,
    allPlayLosses: 12,
    allPlayTies: 0,
    allPlayRate: 21 / 33,
    equalOpponentExpectedH2HCredits: 1.91,
    scheduleImpact: 0.09,
    avgOpponentScorePercentile: 0.47,
    officialRecord: { wins: 4, losses: 2, ties: 0 },
    medianComponent: { state: "complete", wins: 2, losses: 1, ties: 0 },
    ...over,
  };
}

function contract(teams, over = {}) {
  return {
    state: "complete",
    season: "2026",
    finalizedWeeks: [1, 2, 3],
    algorithmVersion: "schedule-impact-2026.09-a1",
    model: { id: "equal_opponent_v1" },
    teams,
    ...over,
  };
}

describe("lib/schedule-impact formatting", () => {
  it("signs credits with a true minus and never shows -0.0", () => {
    expect(fmtSignedCredits(0.94)).toBe("+0.9");
    expect(fmtSignedCredits(-0.36)).toBe("−0.4");
    expect(fmtSignedCredits(-0.04)).toBe("0.0");
    expect(fmtSignedCredits(null)).toBe("—");
    expect(impactDirection(-0.04)).toBe("flat");
    expect(impactDirection(1.2)).toBe("up");
  });

  it("formats records and never invents one", () => {
    expect(fmtRecord(5, 1, 0)).toBe("5-1");
    expect(fmtRecord(5, 1, 1)).toBe("5-1-1");
    expect(fmtRecord(undefined, 1, 0)).toBe("—");
  });

  it("labels an orphan roster honestly", () => {
    expect(teamLabel({ orphanRoster: true, rosterId: 3, teamName: "" })).toBe("Roster 3 (no manager)");
  });

  it("the reading uses the backend numbers only and judges nobody", () => {
    const text = interpretation(team("A", { actualH2HCredits: 3, h2hWins: 3, h2hLosses: 0, equalOpponentExpectedH2HCredits: 1.82, scheduleImpact: 1.18 }));
    expect(text).toContain("3 head-to-head wins");
    expect(text).toContain("average 1.8");
    expect(text).toContain("+1.2 schedule wins");
    expect(text).not.toMatch(/lucky|unlucky|blessed|cursed|skill|deserv/i);
  });

  it("every non-complete state has honest copy", () => {
    expect(stateNotice(null).text).toMatch(/not available/);
    expect(stateNotice({ state: "complete" })).toBeNull();
    expect(stateNotice({ state: "partial" }).text).toMatch(/left out/);
    expect(stateNotice({ state: "unsupported" }).text).toMatch(/not supported/);
    expect(stateNotice({ state: "unavailable" }).text).toMatch(/week 1 is final/);
  });
});

describe("ScheduleImpactTable", () => {
  it("renders every team, sorted by schedule impact, with signed values", () => {
    const rows = [
      team("A", { scheduleImpact: -0.73, teamName: "Down Team" }),
      team("B", { scheduleImpact: 1.18, teamName: "Up Team" }),
      team("C", { scheduleImpact: 0.0, teamName: "Flat Team" }),
    ];
    render(<ScheduleImpactTable contract={contract(rows)} />);
    const block = screen.getByTestId("schedule-impact");
    expect(block.getAttribute("data-state")).toBe("complete");
    const bodyRows = within(block).getAllByRole("row").slice(1);
    expect(bodyRows).toHaveLength(3);
    expect(within(bodyRows[0]).getByText("Up Team")).toBeTruthy();
    expect(within(bodyRows[0]).getByText("+1.2")).toBeTruthy();
    expect(within(bodyRows[2]).getByText("−0.7")).toBeTruthy();
    // Official record and head-to-head record are both shown, separately.
    expect(within(bodyRows[0]).getByText("4-2")).toBeTruthy();
    expect(within(bodyRows[0]).getByText("2-1")).toBeTruthy();
  });

  it("direction is carried by a glyph and a data attribute, not colour alone", () => {
    const { container } = render(<ImpactValue value={-0.5} />);
    const el = container.querySelector("[data-direction]");
    expect(el.getAttribute("data-direction")).toBe("down");
    expect(el.textContent).toContain("▼");
  });

  it("unavailable: says so and renders no table (never zeros)", () => {
    render(<ScheduleImpactTable contract={contract([], { state: "unavailable" })} />);
    const block = screen.getByTestId("schedule-impact");
    expect(within(block).getByText(/week 1 is final/)).toBeTruthy();
    expect(within(block).queryByRole("table")).toBeNull();
  });

  it("partial and unsupported states are announced", () => {
    const { unmount } = render(<ScheduleImpactTable contract={contract([team("A")], { state: "partial" })} />);
    expect(screen.getByText(/left out/)).toBeTruthy();
    unmount();
    render(<ScheduleImpactTable contract={contract([], { state: "unsupported" })} />);
    expect(screen.getByText(/not supported/)).toBeTruthy();
  });
});

describe("ScheduleImpactSummary", () => {
  it("shows record, expected wins, impact and one reading; median only when known", () => {
    render(<ScheduleImpactSummary row={team("A")} contract={contract([team("A")])} />);
    const s = screen.getByTestId("schedule-impact-summary");
    expect(within(s).getByText("4-2")).toBeTruthy();
    expect(within(s).getByText(/\(median 2-1\)/)).toBeTruthy();
    expect(within(s).getByText("1.9")).toBeTruthy();
    expect(within(s).getByText("+0.1")).toBeTruthy();
    expect(within(s).getByText(/head-to-head wins/)).toBeTruthy();
  });

  it("an unknown median component is not shown as a record", () => {
    render(
      <ScheduleImpactSummary
        row={team("A", { medianComponent: { state: "unavailable", reason: "official_record_unaligned" } })}
        contract={contract([])}
      />,
    );
    expect(screen.queryByText(/median/)).toBeNull();
  });

  it("no row: honest empty state", () => {
    render(<ScheduleImpactSummary row={null} contract={contract([], { state: "unavailable" })} />);
    expect(screen.getByTestId("schedule-impact-summary").getAttribute("data-state")).toBe("unavailable");
  });
});
