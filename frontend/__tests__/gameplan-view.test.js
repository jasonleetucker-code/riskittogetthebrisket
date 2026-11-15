import { describe, it, expect } from "vitest";

import { gameplanView } from "@/lib/gameplan-view";

describe("gameplanView", () => {
  it("is unavailable for a missing or team-less payload", () => {
    expect(gameplanView(null).state).toBe("unavailable");
    expect(gameplanView({}).state).toBe("unavailable");
  });

  it("refuses another team's payload", () => {
    const v = gameplanView({ team: { ownerId: "a" } }, { ownerId: "b" });
    expect(v.state).toBe("unavailable");
    expect(v.reason).toBe("team_mismatch");
  });

  it("does not treat a missing tradeableSurplus as surplus or as zero depth", () => {
    const v = gameplanView({
      team: { ownerId: "a" },
      roster: { positions: { QB: { position: "QB" }, RB: { position: "RB", tradeableSurplus: 5 } } },
    });
    expect(v.strengths.items.map((s) => s.position)).toEqual(["RB"]);
  });

  it("keeps noCandidates as not-measured, never as nothing available", () => {
    const v = gameplanView({
      team: { ownerId: "a" },
      targetPositions: [{ position: "TE", viability: "noCandidates" }],
      targetPlayers: [],
    });
    expect(v.opportunities.positions).toEqual([]);
    expect(v.opportunities.notMeasured).toEqual(["TE"]);
  });

  it("shows no timestamp when the payload carries none (a hash is not freshness)", () => {
    const v = gameplanView({ team: { ownerId: "a" }, timing: { sourceStamp: "deadbeef" } });
    expect(v.asOf).toBeNull();
  });
});
