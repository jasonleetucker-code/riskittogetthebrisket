// /league/phases is structurally dead, and TeamPhasePanel is why.
//
// The route's entire body is <TeamPhasePanel />.  The panel read its
// data from `useApp()` — but AppShell hard-refuses to hydrate the
// private contract on anything under the `/league` prefix
// (PUBLIC_ONLY_ROUTE_PREFIXES in components/AppShell.jsx), so on this
// route `useApp()` always yields `{loading: false, rows: [], rawData:
// null}`.  This pins that the panel does NOT read useApp() — it reads
// the canonical `/api/roster/intelligence` endpoint via
// useRosterIntelligence(), same as /rosters' TeamStrengthCard.
//
// V1-31 audit finding F-3: this panel used to derive its own "how good
// is this team" number (a client-side top-25 rankDerivedValue sum plus
// a raw age lookup) via useDynastyData() + lib/team-phase.js. That
// duplicate is retired; this file now mocks useRosterIntelligence
// instead of useDynastyData.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseRosterIntelligence = vi.fn();
const mockUseUserState = vi.fn();

// AppShell's useApp is what the panel used to read (before it read
// useDynastyData(), before it read useRosterIntelligence()). Pin it to
// the values AppShell really supplies under /league/* so a regression
// back onto useApp() fails this suite instead of silently blanking the
// page.
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: null, loading: false, error: "" }),
}));
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => {
    throw new Error("TeamPhasePanel must not read useDynastyData — see V1-31 audit F-3");
  },
}));
vi.mock("@/components/useRosterIntelligence", () => ({
  useRosterIntelligence: (...args) => mockUseRosterIntelligence(...args),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => mockUseUserState(),
}));

import TeamPhasePanel from "@/components/TeamPhasePanel";

function payload(teams) {
  return {
    leagueContext: teams.map((t) => ({
      ownerId: t.ownerId,
      teamName: t.teamName,
      strengthTotal: t.strengthTotal,
      strengthRank: t.strengthRank ?? null,
      youngCoreIndex: t.youngCoreIndex ?? null,
      valueWeightedCoreAge: t.valueWeightedCoreAge,
    })),
  };
}

beforeEach(() => {
  mockUseUserState.mockReturnValue({ state: {} });
});

describe("TeamPhasePanel (the whole body of /phases)", () => {
  it("renders league phases from GET /api/roster/intelligence, not from useApp or useDynastyData", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload([
        { ownerId: "own-a", teamName: "Alpha", strengthTotal: 17500, valueWeightedCoreAge: 22.5 },
        { ownerId: "own-b", teamName: "Bravo", strengthTotal: 4000, valueWeightedCoreAge: 30 },
      ]),
    });
    render(<TeamPhasePanel />);
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    expect(document.querySelectorAll("tbody tr").length).toBe(2);
  });

  it("shows a loading state instead of rendering nothing", () => {
    mockUseRosterIntelligence.mockReturnValue({ loading: true, failure: null, data: null });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent.trim()).not.toBe("");
    expect(container.textContent).toMatch(/loading/i);
  });

  it("explains itself instead of rendering nothing when there is no team selected", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: { kind: "team_required", message: "" },
      data: null,
    });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent.trim()).not.toBe("");
    expect(container.textContent).toMatch(/choose a team/i);
  });

  it("explains itself instead of rendering nothing when the league has no data", () => {
    mockUseRosterIntelligence.mockReturnValue({
      loading: false,
      failure: null,
      data: payload([]),
    });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent.trim()).not.toBe("");
    expect(container.textContent).toMatch(/unavailable|sign in|no league/i);
  });
});
