import { describe, expect, it } from "vitest";
import { postureSummary } from "@/lib/trade-war-room";

describe("postureSummary — labels only, every number the packet's", () => {
  it("names why posture is missing instead of rendering a neutral HOLD", () => {
    expect(postureSummary(undefined)).toEqual({ available: false, reasonText: "Unavailable" });
    expect(
      postureSummary({ available: false, unavailableReason: "league_bundle_not_warm" }).reasonText,
    ).toBe("League roster intelligence is still loading");
  });

  it("formats fractions as shares and keeps unknown own-pick ownership unknown", () => {
    const s = postureSummary({
      available: true,
      detail: {
        label: "HOLD",
        confidence: 0.44,
        probabilities: { PUSH: 0.24, HOLD: 0.44, RETOOL: 0.27, REBUILD: 0.05 },
        components: { timing: { phase: "regular", week: 5, tradeDeadlineWeek: 13 } },
      },
    });
    expect(s.confidence).toBe("44%");
    expect(s.split.map((x) => x.label)).toEqual(["PUSH", "HOLD", "RETOOL", "REBUILD"]);
    expect(s.timing).toBe("Week 5 of a week-13 deadline");
    expect(s.ownFirst).toBe("Own first-round pick: unknown");
  });
});
