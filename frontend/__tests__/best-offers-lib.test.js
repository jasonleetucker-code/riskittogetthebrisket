import { describe, expect, it } from "vitest";
import {
  UNKNOWN,
  concentrationLine,
  fmtSignedInt,
  fmtSignedPct,
  lineupLine,
  mergeCards,
  summarizeCard,
} from "@/lib/best-offers";

const QUALIFIED = {
  team: "Them",
  status: "qualified",
  offer: {
    send: [{ name: "A" }],
    receive: [{ name: "B" }],
    packageSize: "1-for-1",
    canonical: { vaAdjustedGap: 1317, magnitude: "stretch" },
    external: { label: "KTC Market", opponentMarginPct: 4.2, result: "win" },
    confidence: "moderate",
    score: 0.6,
  },
};

describe("best offers display helpers", () => {
  it("summarises a qualified card from the server's numbers only", () => {
    expect(summarizeCard(QUALIFIED)).toMatchObject({
      qualified: true,
      send: ["A"],
      receive: ["B"],
      ourGap: 1317,
      calculator: "KTC Market",
      theirMarginPct: 4.2,
    });
  });

  it("a no-result card keeps the server's label and reason text", () => {
    const s = summarizeCard({
      team: "X",
      status: "no_result",
      noResultLabel: "No qualifying trade found under current constraints",
      noResultDetail: "A locked player is protected.",
    });
    expect(s.qualified).toBe(false);
    expect(s.label).toMatch(/under current constraints/);
    expect(s.detail).toMatch(/locked/);
  });

  it("an unknown number renders as unknown, never as zero", () => {
    expect(fmtSignedInt(null)).toBe(UNKNOWN);
    expect(fmtSignedPct(undefined)).toBe(UNKNOWN);
    expect(fmtSignedPct(0)).toBe("0.0%");
    const s = summarizeCard({ team: "T", offer: { ...QUALIFIED.offer, canonical: {}, external: {} } });
    expect(s.ourGap).toBeNull();
    expect(s.theirMarginPct).toBeNull();
  });

  it("merges a regenerated card without touching the others", () => {
    const full = { opponents: [QUALIFIED, { team: "Other", status: "no_result" }] };
    const fresh = { opponents: [{ team: "Them", status: "no_result", noResultLabel: "x" }] };
    const merged = mergeCards(full, fresh);
    expect(merged.opponents.map((o) => o.status)).toEqual(["no_result", "no_result"]);
    expect(merged.opponents[1]).toBe(full.opponents[1]);
  });

  it("states lineup impact and asset concentration honestly", () => {
    expect(lineupLine({ available: false })).toBe("Lineup impact unavailable");
    expect(lineupLine({ available: true, ourDelta: 3.25, theirDelta: -1 })).toMatch(/you \+3\.3, them -1\.0/);
    expect(concentrationLine({ outgoingAlsoOfferedTo: { A: 2 } })).toBe("A also headlines 2 other offers");
    expect(concentrationLine({})).toBeNull();
  });
});
