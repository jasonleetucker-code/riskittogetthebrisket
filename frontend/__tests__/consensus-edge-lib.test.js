import fs from "node:fs";
import path from "node:path";
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
  // `qualified` is stamped by the backend. These rows carry it because
  // the real payload does.
  const rows = [
    { playerKey: "a", position: "QB", label: "Buy", score: 40, qualified: true },
    { playerKey: "b", position: "QB", label: "Strong Buy", score: 70, qualified: true },
    { playerKey: "c", position: "RB", label: "Neutral", score: 10, qualified: false },
    { playerKey: "d", position: "WR", label: "Buy", score: 35, qualified: true },
    { playerKey: "e", position: "TE", label: "Sell", score: -50, qualified: true },
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

  it("reads the backend's qualified flag, not the label text", () => {
    // A row the backend disqualified must be excluded even if its label
    // string looks directional — this is what stops the frontend from
    // re-deriving qualification.
    const disqualified = [
      { playerKey: "x", position: "QB", label: "Buy", score: 90, qualified: false },
    ];
    expect(positionLeaders(disqualified, { direction: "buy" })).toEqual([]);
  });

  it("separates buy and sell directions by score sign", () => {
    const sells = positionLeaders(rows, { direction: "sell" });
    expect(sells.map((l) => l.position)).toEqual(["TE"]);
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

describe("no duplicated qualification logic", () => {
  // The frontend previously kept its own copy of the qualifying label
  // set, matched by English string against Python constants. Renaming a
  // label server-side silently emptied the position-leaders panel. This
  // is the same class of drift the client-side rank fallback caused, and
  // this guard is what stops it coming back.
  const source = fs.readFileSync(
    path.join(process.cwd(), "lib", "consensus-edge.js"),
    "utf8",
  );

  // Scoped to positionLeaders. Styling BY label is legitimate — that is
  // what labelTone does, and the frontend has to know label names to
  // colour them. What must never come back is label strings driving
  // QUALIFICATION, which is a backend decision.
  const positionLeadersBody = source.slice(
    source.indexOf("export function positionLeaders"),
  );

  it("does not decide qualification from label strings", () => {
    for (const label of ["Strong Buy", "Strong Sell", "Buy", "Sell"]) {
      expect(positionLeadersBody).not.toContain(`"${label}"`);
    }
  });

  it("reads the backend qualified flag instead", () => {
    expect(positionLeadersBody).toContain("row.qualified");
  });
});
