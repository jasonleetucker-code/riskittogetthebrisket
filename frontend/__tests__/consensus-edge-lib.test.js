import { describe, expect, it } from "vitest";
import {
  classifyEdgeFailure,
  componentRows,
  formatPct,
  formatScore,
  labelTone,
  positionLeaders,
} from "@/lib/consensus-edge";

describe("classifyEdgeFailure", () => {
  it("returns null on success", () => {
    expect(classifyEdgeFailure(200, {})).toBeNull();
  });

  it("distinguishes the flag being off from a real error", () => {
    // These render as completely different UI states; collapsing them
    // into "error" would tell a user something is broken when the
    // feature is simply switched off.
    expect(classifyEdgeFailure(503, { error: "feature_disabled" }).kind).toBe("disabled");
    expect(classifyEdgeFailure(503, { error: "data_not_ready" }).kind).toBe("not_ready");
    expect(classifyEdgeFailure(500, { error: "boom" }).kind).toBe("error");
  });

  it("surfaces auth separately", () => {
    expect(classifyEdgeFailure(401, {}).kind).toBe("auth");
  });
});

describe("labelTone", () => {
  it("gives conflicted its own tone, distinct from neutral", () => {
    // The whole point of Conflicted is that it is NOT a mild reading.
    expect(labelTone("Conflicted")).not.toBe(labelTone("Neutral"));
  });

  it("gives insufficient evidence its own tone, distinct from neutral", () => {
    expect(labelTone("Insufficient Evidence")).not.toBe(labelTone("Neutral"));
  });

  it("separates strong from ordinary calls", () => {
    expect(labelTone("Strong Buy")).not.toBe(labelTone("Buy"));
    expect(labelTone("Strong Sell")).not.toBe(labelTone("Sell"));
  });
});

describe("componentRows", () => {
  const validation = {
    mispricing: { validated: true, note: "backtested" },
    sharpFlow: { validated: false, note: "no ledger" },
    opportunity: { validated: false, note: "no projections" },
  };

  it("marks an absent component as absent rather than zero", () => {
    const rows = componentRows(
      { components: { mispricing: 0.5, sharpFlow: null, opportunity: null } },
      validation,
    );
    const sharp = rows.find((r) => r.key === "sharpFlow");
    expect(sharp.absent).toBe(true);
    expect(sharp.value).toBeNull();
  });

  it("carries per-component validation standing", () => {
    const rows = componentRows({ components: { mispricing: 0.5 } }, validation);
    expect(rows.find((r) => r.key === "mispricing").validated).toBe(true);
    expect(rows.find((r) => r.key === "sharpFlow").validated).toBe(false);
  });

  it("returns components in a stable order", () => {
    const rows = componentRows({ components: {} }, validation);
    expect(rows.map((r) => r.key)).toEqual(["mispricing", "sharpFlow", "opportunity"]);
  });
});

describe("positionLeaders", () => {
  const rows = [
    { playerKey: "a", position: "QB", label: "Buy", score: 40 },
    { playerKey: "b", position: "QB", label: "Strong Buy", score: 70 },
    { playerKey: "c", position: "RB", label: "Neutral", score: 10 },
    { playerKey: "d", position: "WR", label: "Buy", score: 35 },
  ];

  it("picks the best qualifying player per position", () => {
    const leaders = positionLeaders(rows, { direction: "buy" });
    expect(leaders.find((l) => l.position === "QB").row.playerKey).toBe("b");
  });

  it("omits positions with no qualifying player rather than filling them", () => {
    // Promoting the least-bad candidate would label a Neutral player a
    // buy for a display reason.
    const leaders = positionLeaders(rows, { direction: "buy" });
    expect(leaders.map((l) => l.position)).not.toContain("RB");
  });

  it("returns nothing when no player qualifies", () => {
    expect(positionLeaders([{ position: "QB", label: "Neutral", score: 5 }])).toEqual([]);
  });
});

describe("formatting", () => {
  it("shows scores as signed integers, not false precision", () => {
    expect(formatScore(76.23)).toBe("+76");
    expect(formatScore(-12.7)).toBe("-13");
  });

  it("renders missing values as a dash rather than zero", () => {
    expect(formatScore(null)).toBe("—");
    expect(formatPct(undefined)).toBe("—");
  });
});
