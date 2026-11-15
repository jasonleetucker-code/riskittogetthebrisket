/**
 * TradeTargetsCard — /rosters' Trade Targets, rendered from the canonical
 * need answer (C2-WEAK-01).
 *
 * The fixture is built so the RETIRED page rule and the canonical owner
 * disagree: by raw full-roster `byGroup` sums against the league average,
 * TE is this roster's weakest room, but the served weakness
 * (`src/roster_intel/weakness.py`, rung ladder over the meaningful core)
 * says RB is the need and TE clears its bar. Every assertion below that
 * names RB as the need fails on the pre-C2-WEAK-01 card, which computed
 * "Weakest" itself and could not see the served block at all.
 */
import { describe, it, expect } from "vitest";
import React from "react";
import { render, screen } from "@testing-library/react";

import TradeTargetsCard from "@/components/TradeTargetsCard";

const player = (name, group, meta) => ({
  name,
  pos: group,
  group,
  meta,
  playerId: "",
  team: "",
});

// Raw sums: "Mine" is far below average at TE (the retired rule's answer)
// and ABOVE average at RB.
const TEAMS = [
  {
    name: "Mine",
    byGroup: { QB: 9000, RB: 12000, WR: 9000, TE: 500 },
    players: [player("My QB", "QB", 6000), player("My WR", "WR", 4000), player("My RB", "RB", 3000)],
  },
  {
    name: "Deep RB",
    byGroup: { QB: 9000, RB: 8000, WR: 9000, TE: 6000 },
    players: [player("Seller RB", "RB", 5000), player("Cornerstone RB", "RB", 9500)],
  },
  {
    name: "Thin RB",
    byGroup: { QB: 9000, RB: 3000, WR: 9000, TE: 6000 },
    players: [player("Needed RB", "RB", 4500)],
  },
  {
    name: "Unmeasured",
    byGroup: { QB: 9000, RB: 9000, WR: 9000, TE: 6000 },
    players: [player("Mystery RB", "RB", 4800)],
  },
];

const SLEEPER = [
  { name: "Mine", ownerId: "me" },
  { name: "Deep RB", ownerId: "deep" },
  { name: "Thin RB", ownerId: "thin" },
  { name: "Unmeasured", ownerId: "unk" },
];

const need = (position, level, reasons = []) => ({
  position,
  level,
  priority: level === "none" ? 0 : 1,
  unfilledRungs: 0,
  unmetRungs: level === "none" ? 0 : 1,
  unknownRungs: 0,
  rungs: [],
  reasons,
});

function payload(overrides = {}) {
  return {
    team: {
      ownerId: "me",
      teamName: "Mine",
      strength: {
        available: true,
        positionOrder: ["QB", "RB", "WR", "TE"],
        byPosition: [
          { position: "QB", leagueRank: 2, value: 9000 },
          { position: "RB", leagueRank: 9, value: 5000 },
          { position: "WR", leagueRank: 4, value: 7000 },
          { position: "TE", leagueRank: 6, value: 2000 },
        ],
      },
      weakness: {
        available: true,
        unavailableReason: null,
        needs: [
          need("RB", "high", ["RB2 is 41 against a top-24 bar"]),
          need("QB", "none"),
          need("TE", "none"),
          need("WR", "none"),
        ],
        urgentPositions: ["RB"],
      },
    },
    leagueContext: [
      { ownerId: "me", teamName: "Mine", needLevelByPosition: { RB: "high", QB: "none", TE: "none", WR: "none" }, urgentPositions: ["RB"] },
      { ownerId: "deep", teamName: "Deep RB", needLevelByPosition: { RB: "none", QB: "none", TE: "critical", WR: "none" }, urgentPositions: ["TE"] },
      { ownerId: "thin", teamName: "Thin RB", needLevelByPosition: { RB: "high", QB: "none", TE: "none", WR: "none" }, urgentPositions: ["RB"] },
      { ownerId: "unk", teamName: "Unmeasured", needLevelByPosition: null, urgentPositions: null },
    ],
    ...overrides,
  };
}

function renderCard(intelligence, props = {}) {
  return render(
    <TradeTargetsCard
      myTeam="Mine"
      myOwnerId="me"
      teams={TEAMS}
      sleeperTeams={SLEEPER}
      intelligence={intelligence}
      onPlayerClick={() => {}}
      {...props}
    />,
  );
}

describe("TradeTargetsCard — served need, not page math", () => {
  it("names the SERVED top need, not the raw-sum weakest room", () => {
    renderCard({ loading: false, data: payload(), failure: null });
    expect(screen.getByText("Top need: RB (High need)")).toBeInTheDocument();
    expect(screen.getByText(/Need: RB/)).toBeInTheDocument();
    // The retired rule's answer must not appear anywhere.
    expect(screen.queryByText(/Weakest/)).toBeNull();
    expect(screen.queryByText(/Need: TE/)).toBeNull();
    expect(screen.queryByText(/% of league avg/)).toBeNull();
  });

  it("shows the owner's own reason for the need", () => {
    renderCard({ loading: false, data: payload(), failure: null });
    expect(screen.getByText("RB2 is 41 against a top-24 bar")).toBeInTheDocument();
  });

  it("strongest comes from the served positional rank", () => {
    renderCard({ loading: false, data: payload(), failure: null });
    expect(screen.getByText("Strongest: QB (#2 in league)")).toBeInTheDocument();
  });

  it("offers sellers only from teams the owner rates as having no need there", () => {
    renderCard({ loading: false, data: payload(), failure: null });
    expect(screen.getByText("Seller RB")).toBeInTheDocument();
    // Their own served urgent need travels with the target.
    expect(screen.getByText(/need TE/)).toBeInTheDocument();
    // A team that NEEDS RB is not a seller; an unmeasured team is skipped,
    // never guessed; the listing window still excludes a cornerstone.
    expect(screen.queryByText("Needed RB")).toBeNull();
    expect(screen.queryByText("Mystery RB")).toBeNull();
    expect(screen.queryByText("Cornerstone RB")).toBeNull();
  });

  it("says so when the owner finds no need at all", () => {
    const calm = payload();
    calm.team.weakness.needs = calm.team.weakness.needs.map((n) => ({ ...n, level: "none" }));
    calm.team.weakness.urgentPositions = [];
    renderCard({ loading: false, data: calm, failure: null });
    expect(screen.getByText("No starting-slot need")).toBeInTheDocument();
    expect(screen.getByText(/no position is a need right now/)).toBeInTheDocument();
  });
});

describe("TradeTargetsCard — unavailable is explicit, never a fallback", () => {
  it("renders the backend's reason when weakness is unavailable", () => {
    const off = payload();
    off.team.weakness = { available: false, unavailableReason: "unknown_team_count", needs: [], urgentPositions: [] };
    renderCard({ loading: false, data: off, failure: null });
    expect(screen.getByText(/Need priority unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/team count is unknown/)).toBeInTheDocument();
    expect(screen.queryByText(/Top need/)).toBeNull();
    expect(screen.queryByText("Seller RB")).toBeNull();
  });

  it("renders the fetch failure instead of computing targets", () => {
    renderCard({ loading: false, data: null, failure: { kind: "not_ready", message: "No data loaded yet." } });
    expect(screen.getByText(/Need priority unavailable/)).toBeInTheDocument();
    expect(screen.getByText(/No data loaded yet/)).toBeInTheDocument();
    expect(screen.queryByText(/Need:/)).toBeNull();
  });

  it("shows a loading state while the answer is in flight", () => {
    renderCard({ loading: true, data: null, failure: null });
    expect(screen.getByRole("status")).toHaveTextContent("Loading need priority");
  });

  it("never renders another team's needs under this team", () => {
    const other = payload();
    other.team.ownerId = "deep";
    renderCard({ loading: false, data: other, failure: null });
    expect(screen.getByText(/different team/)).toBeInTheDocument();
    expect(screen.queryByText(/Top need/)).toBeNull();
  });
});
