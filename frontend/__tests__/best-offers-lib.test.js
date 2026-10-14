import { describe, expect, it } from "vitest";
import {
  UNKNOWN,
  concentrationLine,
  fmtSignedInt,
  fmtSignedPct,
  lineupLine,
  domId,
  factorRows,
  mergeCards,
  recomputeConcentration,
  summarizeCard,
  verdictLines,
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

  it("recounts concentration over the cards held after a single-card merge", () => {
    const card = (team, send) => ({ team, status: "qualified", offer: { send: send.map((name) => ({ name })) } });
    const full = recomputeConcentration({
      opponents: [card("T1", ["Star"]), card("T2", ["Star"]), card("T3", ["Star", "B"])],
    });
    expect(full.opponents[0].offer.outgoingAlsoOfferedTo).toEqual({ Star: 2 });
    expect(full.outgoingConcentration).toEqual({ Star: 3 });
    // The user excludes Star on T3: the fresh card no longer sends him.
    const merged = mergeCards(full, { opponents: [card("T3", ["B"])] });
    expect(merged.opponents[0].offer.outgoingAlsoOfferedTo).toEqual({ Star: 1 });
    expect(merged.opponents[2].offer.outgoingAlsoOfferedTo).toEqual({});
    expect(merged.outgoingConcentration).toEqual({ Star: 2 });
  });

  it("lists every calculator verdict, marking a contrary complete one", () => {
    const lines = verdictLines({
      externalAll: [
        { calculator: "k", label: "KTC Market", coverage: "complete", opponentMarginPct: -8.7, result: "loss" },
        { calculator: "i", label: "IDP Trade Calculator", coverage: "withheld" },
        { calculator: "x", label: "Other", coverage: "incomplete" },
      ],
    });
    expect(lines.map((l) => l.text)).toEqual([
      "KTC Market: them -8.7% (loss for them)",
      "IDP Trade Calculator: withheld as stale",
      "Other: does not price every asset",
    ]);
    expect(lines[0].contrary).toBe(true);
  });

  it("renders unknown factors as unknown, never zero", () => {
    const rows = factorRows({
      rankingFactors: { canonicalEdge: 0.5, lineupImpact: null, forcedDropCost: null },
      rankingImputations: { forcedDropCost: 0.2 },
    });
    const by = Object.fromEntries(rows.map((r) => [r.key, r]));
    expect(by.canonicalEdge.value).toBe("0.50");
    expect(by.lineupImpact.value).toBe(UNKNOWN);
    expect(by.lineupImpact.note).toBe("not available");
    expect(by.forcedDropCost.note).toMatch(/ranked as 0.20/);
  });

  it("makes whitespace-free, collision-resistant DOM ids", () => {
    expect(domId("offer", "The Big Team")).toMatch(/^offer-the-big-team-[a-z0-9]+$/);
    expect(domId("offer", "A B")).not.toEqual(domId("offer", "A-B"));
  });
});
