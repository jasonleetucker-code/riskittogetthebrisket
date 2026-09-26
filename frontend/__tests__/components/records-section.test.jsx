import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/components/ui", () => ({ PlayerImage: () => null }));

import RecordsSection from "@/app/league/sections/records";

function row(teamName, points, margin, week) {
  return { teamName, season: "2025", week, points, opponentPoints: points - margin, margin };
}

const data = {
  singleWeekHighest: [row("High Team", 301.4, 40, 1)],
  singleWeekLowest: [row("Low Team", 150.2, -20, 2)],
  biggestMargin: [row("Blowout Team", 290.0, 120.5, 3)],
  // A winner's score (287.3) and its margin (0.4) are very different
  // numbers; the card is ranked by the margin, so it must show the margin.
  narrowestVictory: [row("Squeaker Team", 287.3, 0.4, 4)],
  mostPointsInLoss: [row("Unlucky Team", 280.0, -3, 5)],
  fewestPointsInWin: [row("Lucky Team", 160.0, 2, 6)],
  playerRecords: {},
  playerRecordPositions: [],
};

function valueFor(teamName) {
  const label = screen.getByText(teamName);
  // Row = <div><span>{rank}{team}{(season wk)}</span><span>{value}</span></div>
  return label.closest("div").lastElementChild.textContent;
}

describe("RecordsSection record book", () => {
  it("leads narrowest victories with the margin, not the winner's score", () => {
    render(<RecordsSection data={data} />);
    expect(valueFor("Squeaker Team")).toBe("0.4 (287.3)");
  });

  it("keeps the margin format for the biggest margin of victory", () => {
    render(<RecordsSection data={data} />);
    expect(valueFor("Blowout Team")).toBe("120.5 (290.0)");
  });

  it("shows points alone for categories ranked by points", () => {
    render(<RecordsSection data={data} />);
    expect(valueFor("High Team")).toBe("301.4");
    expect(valueFor("Unlucky Team")).toBe("280.0");
    expect(valueFor("Lucky Team")).toBe("160.0");
  });
});
