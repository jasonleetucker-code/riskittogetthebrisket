/**
 * lib/trade-war-room.js — the Team Context layer's words (#842 / #843 / #840).
 * Display only: every input is a field of the analyze packet.
 */
import { describe, it, expect } from "vitest";
import {
  capacitySentence,
  contextEffectRows,
  postureLine,
  postureShift,
} from "@/lib/trade-war-room";

describe("team-context layer formatters", () => {
  it("states each side's final legal roster in words, both directions", () => {
    expect(capacitySentence({ state: "fits_cleanly" }, "You")).toBe("You fit it with no cut");
    expect(
      capacitySentence(
        { state: "cut_required", forcedDrops: [{ name: "Aaron Donald" }], candidatesTied: true },
        "Roy",
      ),
    ).toBe("Roy must cut 1 (likely Aaron Donald) — close call between cut candidates");
    expect(capacitySentence({ state: "reduces_overage", overLimitBefore: 3, overLimitAfter: 2 }, "You")).toBe(
      "You reduce the overage (3 → 2)",
    );
    // Missing stays missing — never "fits".
    expect(capacitySentence(null, "You")).toBeNull();
    expect(capacitySentence({ state: "unknown_limit" }, "You")).toBeNull();
  });

  it("names what team context changed versus raw value", () => {
    const rows = contextEffectRows({
      assetOnlyRecommendation: "LEAN_MAKE",
      teamContextRecommendation: "TOO_CLOSE",
      changed: true,
      changedBy: [{ dimension: "feasibility", from: "LEAN_MAKE", to: "TOO_CLOSE" }],
    });
    expect(rows.assetOnly).toBe("Lean make");
    expect(rows.withContext).toBe("Too close / depends");
    expect(rows.steps[0].text).toBe("Roster capacity / forced cut: Lean make → Too close / depends");
    expect(contextEffectRows(undefined)).toBeNull();
  });

  it("shows direction with its confidence and only a real shift", () => {
    expect(postureLine({ posture: "REBUILD", confidence: "MEDIUM" })).toBe("Rebuild · medium confidence");
    expect(postureLine(null)).toBeNull();
    expect(postureShift({ available: true, postureBefore: "HOLD", postureAfter: "PUSH" })).toBe("Hold → Push");
    expect(postureShift({ available: true, postureBefore: "HOLD", postureAfter: "HOLD" })).toBeNull();
    expect(postureShift({ available: false })).toBeNull();
  });
});
