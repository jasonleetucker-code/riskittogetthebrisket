/**
 * TC-A / UX audit P0-5 — the War Room never analyses an ASSUMED side.
 *
 * On a picks-only trade the selected team owned nothing in, `tradeRequestForTeam`
 * broke the 0-0 tie to Side A: the War Room said "For Jason… PASS" while no
 * side card carried the "You" badge and the draft-capital control had Side A
 * as a different team.  A tie now resolves to "ask", and the War Room,
 * Simulate impact and the badge share one resolver.
 */
import { describe, it, expect, vi, afterEach } from "vitest";
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

vi.mock("@/components/useSettings", () => ({ useSettings: () => ({ settings: {} }) }));

const { resolveTeamSide, tradeRequestForTeam } = await import("@/lib/trade-war-room");
const { default: TradeWarRoom } = await import("@/components/trade/TradeWarRoom");

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const sides = (a, b) => [{ assets: a.map((name) => ({ name })) }, { assets: b.map((name) => ({ name })) }];

describe("resolveTeamSide", () => {
  it("0-0 (the team owns none of the assets) is ambiguous, never Side A", () => {
    expect(resolveTeamSide(sides(["2027 Pick 1.05"], ["2028 Mid 1st"]), new Set(["Someone"]))).toEqual({
      side: null,
      basis: "ambiguous",
    });
  });
  it("an equal non-zero overlap is ambiguous too", () => {
    expect(resolveTeamSide(sides(["Mine"], ["Also mine"]), new Set(["Mine", "Also mine"])).side).toBeNull();
  });
  it("roster evidence decides when one side holds more", () => {
    expect(resolveTeamSide(sides(["Theirs"], ["Mine"]), new Set(["Mine"]))).toEqual({ side: 1, basis: "roster" });
  });
  it("an explicit choice wins", () => {
    expect(resolveTeamSide(sides(["Theirs"], ["Mine"]), new Set(["Mine"]), 0)).toEqual({
      side: 0,
      basis: "explicit",
    });
  });
});

describe("tradeRequestForTeam", () => {
  it("returns no request (asks) instead of assuming Side A", () => {
    expect(tradeRequestForTeam(sides(["A"], ["B"]), new Set(), "Jason")).toBeNull();
  });
  it("builds the request from the user's explicit side", () => {
    const r = tradeRequestForTeam(sides(["A"], ["B"]), new Set(), "Jason", 1);
    expect(r).toMatchObject({ mySide: 1, playersOut: ["B"], playersIn: ["A"], sideBasis: "explicit" });
  });
});

describe("War Room asks which side is the team's", () => {
  it("renders the question and never calls Analyze", () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch");
    const choose = vi.fn();
    render(<TradeWarRoom request={null} teamName="Jason" sideChoiceNeeded onChooseSide={choose} />);
    expect(screen.getByTestId("war-room-side-choice").textContent).toMatch(/Which side is Jason\?/);
    expect(screen.queryByText(/Pick your team/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "I give Side B" }));
    expect(choose).toHaveBeenCalledWith(1);
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it("/trade derives the badge, the request and the prompt from one resolver", async () => {
    const fs = await import("node:fs");
    const path = await import("node:path");
    const src = fs.readFileSync(path.resolve(__dirname, "../../app/trade/page.jsx"), "utf8");
    expect(src).toMatch(/resolveTeamSide\(sides, teamRosterNames\(selectedTeam\), explicitMySide\)/);
    expect(src).toMatch(/if \(sides\.length === 2\) return teamSide\.side \?\? -1;/);
    expect(src).toMatch(/sideChoiceNeeded=\{sideChoiceNeeded\}/);
  });
});

describe("idle copy with a selected team", () => {
  it("an empty or one-sided trade asks for assets, not for a team the user already picked", () => {
    // tradeRequestForTeam answers null for an empty (0-0) trade; that must not
    // read as "no team selected".
    render(<TradeWarRoom request={null} teamName="Jason" sideChoiceNeeded={false} />);
    expect(screen.getByText(/Add assets to both sides/)).toBeTruthy();
    expect(screen.queryByText(/Pick your team/)).toBeNull();
  });
  it("with no team it still asks for one", () => {
    render(<TradeWarRoom request={null} teamName="" sideChoiceNeeded={false} />);
    expect(screen.getByText(/Pick your team/)).toBeTruthy();
  });
});
