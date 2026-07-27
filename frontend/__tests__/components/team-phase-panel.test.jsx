// /league/phases is structurally dead, and TeamPhasePanel is why.
//
// The route's entire body is <TeamPhasePanel />.  The panel read its
// data from `useApp()` — but AppShell hard-refuses to hydrate the
// private contract on anything under the `/league` prefix
// (PUBLIC_ONLY_ROUTE_PREFIXES in components/AppShell.jsx), so on this
// route `useApp()` always yields `{loading: false, rows: [], rawData:
// null}`.  `analyzeLeaguePhases(null, [])` returns zero teams, the
// panel hit `if (!analysis.teams.length) return null`, and the page
// rendered a title, a subtitle, and nothing else — forever, for
// everyone.  Walked signed-in against a warm backend, every run:
//
//   /league/phases  http=200 settled=3071ms len=282 rows=0
//
// (282 chars = global nav + heading + subtitle.)
//
// The sibling route /league/franchise/[owner] has the identical
// problem and already solves it: RosterComparePanel calls
// `useDynastyData()` directly instead of `useApp()`, and renders an
// explicit message for every state rather than returning null.  This
// pins that same contract for TeamPhasePanel.
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

const mockUseDynastyData = vi.fn();
const mockUseUserState = vi.fn();

// AppShell's useApp is what the panel used to read.  Pin it to the
// values AppShell really supplies under /league/* so a regression back
// onto useApp() fails this suite instead of silently blanking the page.
vi.mock("@/components/AppShell", () => ({
  useApp: () => ({ rows: [], rawData: null, loading: false, error: "" }),
}));
vi.mock("@/components/useDynastyData", () => ({
  useDynastyData: () => mockUseDynastyData(),
}));
vi.mock("@/components/useUserState", () => ({
  useUserState: () => mockUseUserState(),
}));

import TeamPhasePanel from "@/components/TeamPhasePanel";

const ROWS = [
  { name: "Young Star", rankDerivedValue: 9000, age: 23 },
  { name: "Old Star", rankDerivedValue: 8500, age: 31 },
  { name: "Young Depth", rankDerivedValue: 2000, age: 22 },
  { name: "Old Depth", rankDerivedValue: 1500, age: 32 },
];

const RAW = {
  sleeper: {
    teams: [
      { ownerId: "own-a", rosterId: 1, name: "Alpha", players: ["Young Star", "Young Depth"] },
      { ownerId: "own-b", rosterId: 2, name: "Bravo", players: ["Old Star", "Old Depth"] },
    ],
  },
};

beforeEach(() => {
  mockUseUserState.mockReturnValue({ state: {} });
});

describe("TeamPhasePanel (the whole body of /league/phases)", () => {
  it("renders league phases from the private contract, not from useApp", () => {
    mockUseDynastyData.mockReturnValue({ rows: ROWS, rawData: RAW, loading: false });
    render(<TeamPhasePanel />);
    // Both teams classified and listed.
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.getByText("Bravo")).toBeInTheDocument();
    expect(document.querySelectorAll("tbody tr").length).toBe(2);
  });

  it("shows a loading state instead of rendering nothing", () => {
    mockUseDynastyData.mockReturnValue({ rows: [], rawData: null, loading: true });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent.trim()).not.toBe("");
    expect(container.textContent).toMatch(/loading/i);
  });

  it("explains itself instead of rendering nothing when there is no league data", () => {
    mockUseDynastyData.mockReturnValue({ rows: [], rawData: null, loading: false });
    const { container } = render(<TeamPhasePanel />);
    expect(container.textContent.trim()).not.toBe("");
    expect(container.textContent).toMatch(/unavailable|sign in|no league/i);
  });
});
