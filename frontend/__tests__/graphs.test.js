import { describe, it, expect } from "vitest";
import { ageCurveFor } from "../components/graphs/AgeCurveOverlay.jsx";
import { buildFlows } from "../components/graphs/TradeFlowSankey.jsx";
import { bucketByDay, toDayKey } from "../components/graphs/ActivityHeatmap.jsx";

// ── AgeCurveOverlay::ageCurveFor ──────────────────────────────────

describe("ageCurveFor", () => {
  it("medians group by integer age", () => {
    const rows = [
      { pos: "RB", age: 25, rankDerivedValue: 5000 },
      { pos: "RB", age: 25, rankDerivedValue: 3000 },
      { pos: "RB", age: 25, rankDerivedValue: 7000 },
      { pos: "RB", age: 26, rankDerivedValue: 4000 },
      { pos: "WR", age: 25, rankDerivedValue: 9999 }, // filtered by pos
    ];
    const curve = ageCurveFor(rows, "RB", 24, 27);
    const byAge = Object.fromEntries(curve.map((p) => [p.age, p.median]));
    expect(byAge[25]).toBe(5000);
    expect(byAge[26]).toBe(4000);
    expect(byAge[24]).toBeNull();
    expect(byAge[27]).toBeNull();
  });

  it("ignores non-finite ages and values", () => {
    const rows = [
      { pos: "QB", age: 28, rankDerivedValue: 5000 },
      { pos: "QB", age: "bad", rankDerivedValue: 4000 },
      { pos: "QB", age: 28, rankDerivedValue: 0 },
      { pos: "QB", age: 28, rankDerivedValue: NaN },
    ];
    const curve = ageCurveFor(rows, "QB", 28, 28);
    expect(curve).toHaveLength(1);
    expect(curve[0].median).toBe(5000);
  });

  it("is case-insensitive for position", () => {
    const rows = [{ pos: "rb", age: 25, rankDerivedValue: 4000 }];
    const curve = ageCurveFor(rows, "RB", 25, 25);
    expect(curve[0].median).toBe(4000);
  });
});

// ── TradeFlowSankey::buildFlows ───────────────────────────────────

describe("buildFlows", () => {
  it("attributes each received asset to the sending side", () => {
    const trades = [
      {
        sides: [
          {
            ownerId: "A",
            displayName: "Alice",
            receivedAssets: [{ kind: "player", playerName: "Mahomes" }],
          },
          {
            ownerId: "B",
            displayName: "Bob",
            receivedAssets: [
              { kind: "player", playerName: "Najah" },
              { kind: "pick", playerName: "2026 1st" },
            ],
          },
        ],
      },
    ];
    const { flows, ownerNames } = buildFlows(trades);
    // A sent 2 assets to B (what B received).
    expect(flows.get("A").get("B")).toBe(2);
    // B sent 1 asset to A (what A received).
    expect(flows.get("B").get("A")).toBe(1);
    expect(ownerNames.get("A")).toBe("Alice");
    expect(ownerNames.get("B")).toBe("Bob");
  });

  it("splits a 3-team trade's received assets uniformly across senders", () => {
    const trades = [
      {
        sides: [
          {
            ownerId: "A",
            displayName: "Alice",
            receivedAssets: [{ kind: "player" }, { kind: "player" }],
          },
          { ownerId: "B", displayName: "Bob", receivedAssets: [] },
          { ownerId: "C", displayName: "Carol", receivedAssets: [] },
        ],
      },
    ];
    const { flows } = buildFlows(trades);
    // A received 2 from B and C combined → 1 each.
    expect(flows.get("B").get("A")).toBe(1);
    expect(flows.get("C").get("A")).toBe(1);
  });

  it("aggregates across multiple trades between the same pair", () => {
    const trades = [
      {
        sides: [
          { ownerId: "A", displayName: "A", receivedAssets: [{ kind: "player" }] },
          { ownerId: "B", displayName: "B", receivedAssets: [{ kind: "player" }] },
        ],
      },
      {
        sides: [
          { ownerId: "A", displayName: "A", receivedAssets: [{ kind: "player" }] },
          { ownerId: "B", displayName: "B", receivedAssets: [{ kind: "player" }, { kind: "player" }] },
        ],
      },
    ];
    const { flows } = buildFlows(trades);
    expect(flows.get("A").get("B")).toBe(3); // 1 + 2
    expect(flows.get("B").get("A")).toBe(2); // 1 + 1
  });

  it("returns empty flows for no trades", () => {
    const { flows, ownerNames } = buildFlows([]);
    expect(flows.size).toBe(0);
    expect(ownerNames.size).toBe(0);
  });

  it("skips malformed trades with <2 sides", () => {
    const trades = [{ sides: [{ ownerId: "A", receivedAssets: [] }] }];
    const { flows } = buildFlows(trades);
    expect(flows.size).toBe(0);
  });
});

// ── ActivityHeatmap::bucketByDay ──────────────────────────────────

describe("bucketByDay", () => {
  it("buckets seconds, milliseconds, and ISO dates into the same UTC day", () => {
    const ts = Date.UTC(2026, 3, 1, 12, 0, 0); // 2026-04-01 12:00 UTC
    const events = [
      { createdAt: ts / 1000 },        // seconds
      { createdAt: ts },               // milliseconds
      { createdAt: "2026-04-01" },     // ISO
      { createdAt: "2026-04-01T23:59:59Z" }, // ISO with time
    ];
    const counts = bucketByDay(events);
    expect(counts.get("2026-04-01")).toBe(4);
  });

  it("ignores unparseable timestamps", () => {
    const events = [
      { createdAt: "not-a-date" },
      { createdAt: null },
      {},
      { createdAt: 1712000000 },
    ];
    const counts = bucketByDay(events);
    // Only the numeric one gets through.
    expect(Array.from(counts.values()).reduce((a, b) => a + b, 0)).toBe(1);
  });

  it("toDayKey is timezone-stable on a known UTC timestamp", () => {
    const d = new Date(Date.UTC(2026, 0, 15, 0, 0, 0));
    expect(toDayKey(d)).toBe("2026-01-15");
  });
});
