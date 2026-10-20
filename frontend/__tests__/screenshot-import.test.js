/**
 * lib/screenshot-import — joining extraction responses to the board, merging
 * several screenshots, and the review reducers.
 */
import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  UNASSIGNED,
  addItem,
  alignImageSides,
  confirmCandidate,
  describeAlignment,
  describeImportError,
  describeWarning,
  emptyReview,
  importReady,
  isSlotOrTierPickName,
  joinToBoard,
  mergeImages,
  moveItem,
  removeItem,
  resolveBoardRow,
  reviewCounts,
  swapReviewSides,
  toImportedSides,
  undoMerge,
} from "@/lib/screenshot-import";

const player = (name, playerId, extra = {}) => ({
  name,
  playerId,
  pos: "WR",
  assetClass: "offense",
  values: { full: 5000 },
  rankDerivedValue: 5000,
  ...extra,
});
const pick = (name, extra = {}) => ({
  name,
  playerId: null,
  pos: "PICK",
  assetClass: "pick",
  values: { full: 3000 },
  rankDerivedValue: 3000,
  ...extra,
});

const ROWS = [
  player("Ja'Marr Chase", "7564"),
  player("Puka Nacua", "9493"),
  player("Josh Allen", "4984", { pos: "QB" }),
  player("Josh Allen (LB)", "1111", { pos: "LB", assetClass: "idp" }),
  player("Bijan Robinson", "9509", { pos: "RB" }),
  pick("2027 Round 1"),
  pick("2027 Mid 1st"),
  pick("2026 Pick 1.06"),
  // Suppressed tier alias: the board priced its slot sibling instead.
  pick("2026 Mid 1st", {
    pickGenericSuppressed: true,
    values: { full: 0 },
    rankDerivedValue: null,
  }),
];

function maps(rows = ROWS, pickAliases = { "2026 Mid 1st": "2026 Pick 1.06" }) {
  const rowByName = new Map(rows.map((r) => [r.name, r]));
  const rowByLowerName = new Map(rows.map((r) => [r.name.toLowerCase(), r]));
  const rowsByPlayerId = new Map();
  for (const r of rows) {
    if (!r.playerId) continue;
    if (!rowsByPlayerId.has(r.playerId)) rowsByPlayerId.set(r.playerId, []);
    rowsByPlayerId.get(r.playerId).push(r);
  }
  return { rowByName, rowByLowerName, rowsByPlayerId, pickAliases };
}
const M = maps();
const row = (name) => M.rowByName.get(name);

const item = (over) => ({
  raw: over.boardName || "raw",
  kind: "player",
  status: "resolved",
  boardName: null,
  sleeperId: null,
  candidates: [],
  suggestions: [],
  hints: { position: null, team: null },
  reason: null,
  lineIndex: 0,
  conf: 0.9,
  ...over,
});

function resp(imageIndex, sideItems, extra = {}) {
  return {
    ok: true,
    imageIndex,
    engine: { name: "tesseract", version: "5" },
    layout: { kind: "two_column", confidence: 0.9 },
    sides: sideItems.map((items, i) => ({
      label: i === 0 ? "Team Alpha" : "Team Beta",
      labelSource: "anchor",
      items,
    })),
    unassigned: [],
    ignored: [],
    warnings: [],
    ...extra,
  };
}

const resolved = (boardName, kind = "player", sleeperId = null) =>
  item({ boardName, kind, sleeperId, raw: boardName });

describe("isSlotOrTierPickName", () => {
  it("accepts slot and tier names, never a generic grade or raw OCR", () => {
    expect(isSlotOrTierPickName("2026 Pick 1.06")).toBe(true);
    expect(isSlotOrTierPickName("2026 1.06")).toBe(true);
    expect(isSlotOrTierPickName("2027 Mid 1st")).toBe(true);
    expect(isSlotOrTierPickName("2027 Round 1")).toBe(false);
    expect(isSlotOrTierPickName("2027 1st")).toBe(false);
    expect(isSlotOrTierPickName("Ja'Marr Chase")).toBe(false);
  });
});

describe("joinToBoard", () => {
  it("joins a player by Sleeper id first, ahead of the board name", () => {
    const review = joinToBoard(
      resp(0, [[resolved("Chase typo", "player", "7564")], []]),
      M,
    );
    expect(review.sides[0].items[0]).toMatchObject({
      status: "resolved",
      viaAlias: false,
    });
    expect(review.sides[0].items[0].row).toBe(row("Ja'Marr Chase"));
  });

  it("falls back to the EXACT board name when there is no id", () => {
    const review = joinToBoard(resp(0, [[resolved("Puka Nacua")], []]), M);
    expect(review.sides[0].items[0].row).toBe(row("Puka Nacua"));
    // case is not forgiven — no fuzzy join
    const miss = joinToBoard(resp(0, [[resolved("puka nacua")], []]), M);
    expect(miss.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "not_on_board",
      row: null,
    });
  });

  it("looks a generic pick grade up exactly (no Mid/.06 guess)", () => {
    const review = joinToBoard(
      resp(0, [[resolved("2027 Round 1", "pick")], []]),
      M,
    );
    expect(review.sides[0].items[0].row).toBe(row("2027 Round 1"));
    expect(review.sides[0].items[0].viaAlias).toBe(false);
    // A generic grade the board lacks stays unresolved even though a
    // tier-centre slot for that year exists.
    const miss = joinToBoard(
      resp(0, [[resolved("2026 Round 1", "pick")], []]),
      M,
    );
    expect(miss.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "not_on_board",
    });
  });

  it("follows a suppressed tier alias to its slot row and marks viaAlias", () => {
    const review = joinToBoard(
      resp(0, [[resolved("2026 Mid 1st", "pick")], []]),
      M,
    );
    expect(review.sides[0].items[0]).toMatchObject({
      status: "resolved",
      viaAlias: true,
    });
    expect(review.sides[0].items[0].row).toBe(row("2026 Pick 1.06"));
  });

  it("does not guess a slot for a tier the board does not carry", () => {
    const review = joinToBoard(
      resp(0, [[resolved("2027 Early 2nd", "pick")], []]),
      M,
    );
    expect(review.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "not_on_board",
    });
  });

  it("a resolved item with no tradeable row becomes not_on_board, never dropped", () => {
    const review = joinToBoard(resp(0, [[resolved("Nobody Known")], []]), M);
    expect(review.sides[0].items).toHaveLength(1);
    expect(review.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "not_on_board",
      raw: "Nobody Known",
    });
  });

  it("never auto-picks a candidate — not even a lone survivor", () => {
    const amb = item({
      raw: "J. Allen",
      status: "needs_confirmation",
      candidates: [
        {
          sleeperId: "4984",
          boardName: "Josh Allen",
          position: "QB",
          team: "BUF",
        },
        {
          sleeperId: "1111",
          boardName: "Josh Allen (LB)",
          position: "LB",
          team: "JAX",
        },
        {
          sleeperId: null,
          boardName: "Not On Board",
          position: null,
          team: null,
        },
      ],
    });
    const lone = item({
      raw: "Bijan",
      status: "needs_confirmation",
      candidates: [
        {
          sleeperId: "9509",
          boardName: "Bijan Robinson",
          position: "RB",
          team: "ATL",
        },
      ],
    });
    const review = joinToBoard(resp(0, [[amb, lone], []]), M);
    const [a, l] = review.sides[0].items;
    expect(a.status).toBe("needs_confirmation");
    expect(a.row).toBeNull();
    expect(a.candidates.map((c) => c.row.name)).toEqual([
      "Josh Allen",
      "Josh Allen (LB)",
    ]);
    expect(l.status).toBe("needs_confirmation");
    expect(l.row).toBeNull();
    expect(l.candidates).toHaveLength(1);
  });

  it("needs_confirmation with no candidate on the board becomes unresolved", () => {
    const amb = item({
      status: "needs_confirmation",
      candidates: [
        { sleeperId: null, boardName: "Ghost", position: null, team: null },
      ],
    });
    const review = joinToBoard(resp(0, [[amb], []]), M);
    expect(review.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "not_on_board",
    });
  });

  it("keeps unresolved items with their suggestions mapped to rows", () => {
    const un = item({
      raw: "Pukka Nakua",
      status: "unresolved",
      reason: "no_match",
      suggestions: [
        {
          sleeperId: "9493",
          boardName: "Puka Nacua",
          position: "WR",
          team: "LAR",
        },
      ],
    });
    const review = joinToBoard(resp(0, [[un], []]), M);
    expect(review.sides[0].items[0]).toMatchObject({
      status: "unresolved",
      reason: "no_match",
    });
    expect(review.sides[0].items[0].suggestions[0].row).toBe(row("Puka Nacua"));
  });

  it("carries unassigned, ignored and warnings with the source image", () => {
    const review = joinToBoard(
      resp(2, [[]], {
        unassigned: [resolved("Puka Nacua")],
        ignored: [{ raw: "Accept trade", reason: "ui_text" }],
        warnings: ["missing_side"],
      }),
      M,
    );
    expect(review.unassigned[0].sourceImage).toBe(2);
    expect(review.ignored).toEqual([
      { raw: "Accept trade", reason: "ui_text", sourceImage: 2 },
    ]);
    expect(review.warnings).toEqual([{ code: "missing_side", sourceImage: 2 }]);
    expect(review.sides).toHaveLength(1);
  });

  it("resolveBoardRow re-anchors a suppressed exact row even without an alias map (canonicalTradeEntry rule)", () => {
    expect(
      resolveBoardRow(
        { kind: "pick", boardName: "2026 Mid 1st" },
        maps(ROWS, {}),
      ).row,
    ).toBe(row("2026 Pick 1.06"));
    // Same suppressed row as a PLAYER kind: never redirected through picks.
    expect(
      resolveBoardRow({ kind: "player", boardName: "2026 Mid 1st" }, M).row,
    ).toBeNull();
  });
});

describe("mergeImages", () => {
  const join = (r) => joinToBoard(r, M);

  it("appends sides across screenshots in upload order", () => {
    const merged = mergeImages([
      join(resp(0, [[resolved("Ja'Marr Chase")], [resolved("Puka Nacua")]])),
      join(resp(1, [[resolved("Bijan Robinson")], []])),
    ]);
    expect(merged.sides[0].items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
      "Bijan Robinson",
    ]);
    expect(merged.sides[1].items.map((i) => i.row.name)).toEqual([
      "Puka Nacua",
    ]);
    expect(merged.sides[0].label).toBe("Team Alpha");
    expect(merged.mergeNotes).toEqual([]);
  });

  it("collapses a >= 2 asset overlap at the seam once, and undo restores it", () => {
    const merged = mergeImages([
      join(
        resp(0, [
          [
            resolved("Ja'Marr Chase"),
            resolved("Puka Nacua"),
            resolved("Josh Allen", "player", "4984"),
          ],
          [],
        ]),
      ),
      join(
        resp(1, [
          [
            resolved("Puka Nacua"),
            resolved("Josh Allen", "player", "4984"),
            resolved("Bijan Robinson"),
          ],
          [],
        ]),
      ),
    ]);
    expect(merged.sides[0].items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
      "Puka Nacua",
      "Josh Allen",
      "Bijan Robinson",
    ]);
    expect(merged.mergeNotes).toHaveLength(1);
    expect(merged.mergeNotes[0]).toMatchObject({
      side: 0,
      count: 2,
      sourceImage: 1,
    });

    const undone = undoMerge(merged, 0);
    expect(undone.sides[0].items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
      "Puka Nacua",
      "Josh Allen",
      "Puka Nacua",
      "Josh Allen",
      "Bijan Robinson",
    ]);
    expect(undone.mergeNotes).toEqual([]);
    // input untouched
    expect(merged.sides[0].items).toHaveLength(4);
  });

  it("flags but does NOT merge a 1-asset overlap", () => {
    const merged = mergeImages([
      join(resp(0, [[resolved("Ja'Marr Chase"), resolved("Puka Nacua")], []])),
      join(resp(1, [[resolved("Puka Nacua"), resolved("Bijan Robinson")], []])),
    ]);
    const items = merged.sides[0].items;
    expect(items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
      "Puka Nacua",
      "Puka Nacua",
      "Bijan Robinson",
    ]);
    expect(items[1].possibleOverlap).toBe(true);
    expect(items[2].possibleOverlap).toBe(true);
    expect(items[0].possibleOverlap).toBe(false);
    expect(merged.mergeNotes).toEqual([]);
  });

  it("preserves repeated hypothetical picks inside one screenshot", () => {
    const merged = mergeImages([
      join(
        resp(0, [
          [
            resolved("2027 Round 1", "pick"),
            resolved("2027 Round 1", "pick"),
            resolved("2027 Round 1", "pick"),
          ],
          [],
        ]),
      ),
    ]);
    expect(merged.sides[0].items).toHaveLength(3);
    expect(merged.mergeNotes).toEqual([]);
  });

  it("never merges unresolved items, even with identical raw text", () => {
    const un = () =>
      item({ raw: "???", status: "unresolved", reason: "no_match" });
    const merged = mergeImages([
      join(resp(0, [[un(), un()], []])),
      join(resp(1, [[un(), un()], []])),
    ]);
    expect(merged.sides[0].items).toHaveLength(4);
  });

  it("concatenates unassigned, ignored and warnings", () => {
    const merged = mergeImages([
      join(
        resp(0, [[]], {
          ignored: [{ raw: "x", reason: "noise" }],
          warnings: ["possibly_cropped"],
        }),
      ),
      join(
        resp(1, [[]], {
          unassigned: [resolved("Puka Nacua")],
          warnings: ["missing_side"],
        }),
      ),
    ]);
    expect(merged.ignored).toHaveLength(1);
    expect(merged.unassigned).toHaveLength(1);
    expect(merged.warnings.map((w) => w.code)).toEqual([
      "possibly_cropped",
      "missing_side",
    ]);
  });
});

describe("review reducers", () => {
  function base() {
    const amb = item({
      raw: "J. Allen",
      status: "needs_confirmation",
      candidates: [
        { sleeperId: "4984", boardName: "Josh Allen" },
        { sleeperId: "1111", boardName: "Josh Allen (LB)" },
      ],
    });
    return mergeImages([
      joinToBoard(
        resp(0, [[resolved("Ja'Marr Chase"), amb], [resolved("Puka Nacua")]], {
          unassigned: [resolved("Bijan Robinson")],
        }),
        M,
      ),
    ]);
  }

  it("moveItem moves between sides and the tray, appending", () => {
    let s = base();
    const bijan = s.unassigned[0].id;
    s = moveItem(s, bijan, 1);
    expect(s.unassigned).toEqual([]);
    expect(s.sides[1].items.map((i) => i.raw)).toEqual([
      "Puka Nacua",
      "Bijan Robinson",
    ]);
    const chase = s.sides[0].items[0].id;
    s = moveItem(s, chase, UNASSIGNED);
    expect(s.unassigned.map((i) => i.raw)).toEqual(["Ja'Marr Chase"]);
    expect(moveItem(s, "nope", 0)).toBe(s);
    expect(moveItem(s, chase, UNASSIGNED)).toBe(s);
  });

  it("swapReviewSides swaps items, labels and merge-note sides", () => {
    const s = {
      ...base(),
      mergeNotes: [{ side: 0, count: 2, sourceImage: 1, removed: [] }],
    };
    const w = swapReviewSides(s);
    expect(w.sides[0].items.map((i) => i.raw)).toEqual(["Puka Nacua"]);
    expect(w.sides[0].label).toBe("Team Beta");
    expect(w.mergeNotes[0].side).toBe(1);
    expect(swapReviewSides(w).sides[0].label).toBe("Team Alpha");
  });

  it("removeItem removes exactly one item", () => {
    const s = base();
    const r = removeItem(s, s.sides[0].items[0].id);
    expect(r.sides[0].items).toHaveLength(1);
    expect(s.sides[0].items).toHaveLength(2);
  });

  it("addItem appends a real board row (repeats allowed) and refuses a suppressed one", () => {
    let s = base();
    s = addItem(s, 1, row("Puka Nacua"));
    s = addItem(s, 1, row("Puka Nacua"));
    expect(s.sides[1].items.map((i) => i.row.name)).toEqual([
      "Puka Nacua",
      "Puka Nacua",
      "Puka Nacua",
    ]);
    expect(new Set(s.sides[1].items.map((i) => i.id)).size).toBe(3);
    expect(addItem(s, 0, row("2026 Mid 1st"))).toBe(s);
    expect(addItem(s, 2, row("Puka Nacua"))).toBe(s);
  });

  it("confirmCandidate resolves an ambiguous item to the chosen row", () => {
    const s = base();
    const amb = s.sides[0].items[1];
    const c = confirmCandidate(s, amb.id, amb.candidates[1].row);
    expect(c.sides[0].items[1]).toMatchObject({
      status: "resolved",
      confirmed: true,
    });
    expect(c.sides[0].items[1].row.name).toBe("Josh Allen (LB)");
  });

  it("reviewCounts reports what blocks the import", () => {
    expect(reviewCounts(base())).toEqual({
      assets: 3,
      resolved: 2,
      needsConfirmation: 1,
      unresolved: 0,
      unassigned: 1,
    });
  });
});

describe("importReady truth table", () => {
  it("false for an empty review", () => {
    expect(importReady(emptyReview())).toBe(false);
    expect(importReady(null)).toBe(false);
  });

  it("false while anything needs confirmation, is unresolved, or needs a side", () => {
    const amb = item({
      status: "needs_confirmation",
      candidates: [{ sleeperId: "4984", boardName: "Josh Allen" }],
    });
    const un = item({ raw: "???", status: "unresolved" });
    const needs = mergeImages([
      joinToBoard(resp(0, [[resolved("Puka Nacua"), amb], []]), M),
    ]);
    expect(importReady(needs)).toBe(false);
    const unres = mergeImages([
      joinToBoard(resp(0, [[resolved("Puka Nacua"), un], []]), M),
    ]);
    expect(importReady(unres)).toBe(false);
    const tray = mergeImages([
      joinToBoard(
        resp(0, [[resolved("Puka Nacua")], []], {
          unassigned: [resolved("Bijan Robinson")],
        }),
        M,
      ),
    ]);
    expect(importReady(tray)).toBe(false);
  });

  it("true once every side item is resolved, even with an empty side", () => {
    const one = mergeImages([
      joinToBoard(resp(0, [[resolved("Puka Nacua")], []]), M),
    ]);
    expect(importReady(one)).toBe(true);
  });

  it("becomes true after the user resolves every blocker", () => {
    const amb = item({
      status: "needs_confirmation",
      candidates: [{ sleeperId: "4984", boardName: "Josh Allen" }],
    });
    const un = item({ raw: "???", status: "unresolved" });
    let s = mergeImages([
      joinToBoard(
        resp(0, [[amb, un], []], { unassigned: [resolved("Bijan Robinson")] }),
        M,
      ),
    ]);
    expect(importReady(s)).toBe(false);
    s = confirmCandidate(s, s.sides[0].items[0].id, row("Josh Allen"));
    expect(importReady(s)).toBe(false);
    s = confirmCandidate(s, s.sides[0].items[1].id, row("Puka Nacua"));
    expect(importReady(s)).toBe(false);
    s = moveItem(s, s.unassigned[0].id, 1);
    expect(importReady(s)).toBe(true);
  });
});

describe("toImportedSides", () => {
  it("returns the board rows per side, in order, repeats preserved", () => {
    let s = mergeImages([
      joinToBoard(
        resp(0, [
          [resolved("2027 Round 1", "pick"), resolved("2027 Round 1", "pick")],
          [resolved("Puka Nacua")],
        ]),
        M,
      ),
    ]);
    s = addItem(s, 1, row("Bijan Robinson"));
    const [a, b] = toImportedSides(s);
    expect(a).toEqual([row("2027 Round 1"), row("2027 Round 1")]);
    expect(a[0]).toBe(row("2027 Round 1")); // the board row itself — no value is copied or invented
    expect(b.map((r) => r.name)).toEqual(["Puka Nacua", "Bijan Robinson"]);
  });
});

describe("describeImportError", () => {
  it("maps every documented error code to plain words with the right retry advice", () => {
    expect(
      describeImportError(404, { error: "feature_disabled" }),
    ).toMatchObject({ retryable: false });
    expect(
      describeImportError(403, { error: "guest_read_only" }).message,
    ).toMatch(/Sign in/);
    const rl = describeImportError(429, { error: "rate_limited" }, "12");
    expect(rl).toMatchObject({ retryable: true });
    expect(rl.message).toMatch(/12 seconds/);
    expect(
      describeImportError(503, { error: "ocr_unavailable" }),
    ).toMatchObject({ retryable: false });
    expect(describeImportError(503, { error: "ocr_busy" })).toMatchObject({
      retryable: true,
    });
    expect(describeImportError(504, { error: "ocr_timeout" })).toMatchObject({
      retryable: true,
    });
    expect(describeImportError(0, null)).toMatchObject({
      code: "network",
      retryable: true,
    });
    expect(
      describeImportError(413, { error: "image_too_large" }),
    ).toMatchObject({ retryable: false });
    expect(
      describeImportError(415, { error: "unsupported_media_type" }).message,
    ).toMatch(/PNG, JPEG or WebP/);
    expect(
      describeImportError(400, { error: "bad_image", message: "Not an image." })
        .message,
    ).toBe("Not an image.");
    expect(describeImportError(500, {})).toMatchObject({ retryable: true });
  });
});

describe("describeWarning", () => {
  it("names the screenshot only when there are several", () => {
    expect(
      describeWarning({ code: "missing_side", sourceImage: 0 }, 1),
    ).toMatch(/^Only one side/);
    expect(
      describeWarning({ code: "possibly_cropped", sourceImage: 1 }, 2),
    ).toMatch(/^Screenshot 2: the image may be cropped/);
    expect(describeWarning({ code: "something_new", sourceImage: 0 }, 1)).toBe(
      "Something new",
    );
  });

  it("explains a full-page screenshot whose trade area was not found", () => {
    expect(
      describeWarning({ code: "trade_region_not_detected", sourceImage: 0 }, 1),
    ).toMatch(/^The trade area wasn't recognised, so nothing was placed/);
  });
});

describe("full-page screenshots (server-side trade region)", () => {
  const join = (r) => joinToBoard(r, M);
  const pageNoise = [
    { raw: "Bijan Robinson", reason: "outside_trade_region" },
    { raw: "Search for a player", reason: "search_placeholder" },
  ];

  it("keeps page furniture out of the sides and the needs-a-side tray", () => {
    const merged = mergeImages([
      join(
        resp(0, [[resolved("Ja'Marr Chase")], [resolved("Puka Nacua")]], {
          ignored: pageNoise,
        }),
      ),
    ]);
    expect(merged.sides[0].items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
    ]);
    expect(merged.sides[1].items.map((i) => i.row.name)).toEqual([
      "Puka Nacua",
    ]);
    expect(merged.unassigned).toEqual([]);
    expect(merged.ignored.map((g) => g.reason)).toEqual([
      "outside_trade_region",
      "search_placeholder",
    ]);
    expect(reviewCounts(merged).assets).toBe(2);
  });

  it("merges two scrolled full-page screenshots without duplicating assets", () => {
    const merged = mergeImages([
      join(
        resp(
          0,
          [
            [resolved("Ja'Marr Chase"), resolved("Puka Nacua")],
            [resolved("Bijan Robinson")],
          ],
          { ignored: pageNoise },
        ),
      ),
      join(
        resp(
          1,
          [
            [
              resolved("Ja'Marr Chase"),
              resolved("Puka Nacua"),
              resolved("Josh Allen", "player", "4984"),
            ],
            [],
          ],
          { ignored: pageNoise },
        ),
      ),
    ]);
    expect(merged.sides[0].items.map((i) => i.row.name)).toEqual([
      "Ja'Marr Chase",
      "Puka Nacua",
      "Josh Allen",
    ]);
    expect(merged.sides[1].items.map((i) => i.row.name)).toEqual([
      "Bijan Robinson",
    ]);
    expect(merged.mergeNotes).toHaveLength(1);
    expect(merged.unassigned).toEqual([]);
  });
});

// ── multi-screenshot side alignment (CQ-11) ─────────────────────────

/** A response whose sides carry real side labels (server anchor fields). */
function labelled(imageIndex, sides, extra = {}) {
  return {
    ok: true,
    imageIndex,
    engine: { name: "tesseract", version: "5" },
    layout: {
      kind: sides.length === 1 ? "single" : "stacked",
      confidence: 0.9,
    },
    sides: sides.map(([label, slot, items, family = "team 1/team 2"]) => ({
      label,
      labelSource: "anchor",
      anchorFamily: family,
      anchorSlot: slot,
      items,
    })),
    unassigned: [],
    ignored: [],
    warnings: sides.length === 1 ? ["missing_side"] : [],
    ...extra,
  };
}

const names = (side) => side.items.map((i) => i.row?.name ?? i.raw);

describe("multi-screenshot side alignment", () => {
  const join = (r) => joinToBoard(r, M);

  it("joinToBoard carries which side label each side is", () => {
    const review = join(labelled(0, [["Team 2 gets", 1, []]]));
    expect(review.sides[0]).toMatchObject({
      anchorFamily: "team 1/team 2",
      anchorSlot: 1,
    });
    // a positional side never claims a label
    const pos = join(resp(0, [[], []]));
    expect(pos.sides[0].anchorSlot).toBeNull();
    expect(pos.sides[0].anchorFamily).toBeNull();
  });

  it("a follow-up shot showing only 'Team 2 gets' lands on Team 2's side", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          ["Team 2 gets", 1, [resolved("Puka Nacua")]],
        ]),
      ),
      join(labelled(1, [["Team 2 gets", 1, [resolved("Bijan Robinson")]]])),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase"]);
    expect(names(merged.sides[1])).toEqual(["Puka Nacua", "Bijan Robinson"]);
    expect(merged.alignmentNotes[1]).toMatchObject({
      sourceImage: 1,
      targets: [1],
      basis: "label",
      conflict: null,
    });
    // both sides are populated now: the per-shot missing_side is moot
    expect(merged.warnings).toEqual([]);
    expect(describeAlignment(merged, 2)).toEqual([
      'Screenshot 2 shows only "Team 2 gets", so its assets were added to that side.',
    ]);
  });

  it("a lone second-side label in the FIRST shot still goes to Side B", () => {
    const merged = mergeImages([
      join(labelled(0, [["Team 2 gets", 1, [resolved("Bijan Robinson")]]])),
      join(
        labelled(1, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          ["Team 2 gets", 1, [resolved("Puka Nacua")]],
        ]),
      ),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase"]);
    expect(names(merged.sides[1])).toEqual(["Bijan Robinson", "Puka Nacua"]);
    expect(merged.sides[1].label).toBe("Team 2 gets");
  });

  it("a shot listing its sides in the other order is matched by label, not position", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["You give", 0, [resolved("Ja'Marr Chase")], "you give/you get"],
          ["You get", 1, [resolved("Puka Nacua")], "you give/you get"],
        ]),
      ),
      join(
        labelled(1, [
          ["You get", 1, [resolved("Bijan Robinson")], "you give/you get"],
          [
            "You give",
            0,
            [resolved("2027 Round 1", "pick")],
            "you give/you get",
          ],
        ]),
      ),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase", "2027 Round 1"]);
    expect(names(merged.sides[1])).toEqual(["Puka Nacua", "Bijan Robinson"]);
    expect(merged.alignmentNotes[1].targets).toEqual([1, 0]);
    expect(describeAlignment(merged, 2)[0]).toMatch(/other order/);
  });

  it("collapses a >= 2 seam overlap on the label-aligned side, with undo", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          [
            "Team 2 gets",
            1,
            [resolved("Puka Nacua"), resolved("Josh Allen", "player", "4984")],
          ],
        ]),
      ),
      join(
        labelled(1, [
          [
            "Team 2 gets",
            1,
            [
              resolved("Puka Nacua"),
              resolved("Josh Allen", "player", "4984"),
              resolved("Bijan Robinson"),
            ],
          ],
        ]),
      ),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase"]);
    expect(names(merged.sides[1])).toEqual([
      "Puka Nacua",
      "Josh Allen",
      "Bijan Robinson",
    ]);
    expect(merged.mergeNotes).toHaveLength(1);
    expect(merged.mergeNotes[0]).toMatchObject({
      side: 1,
      count: 2,
      sourceImage: 1,
    });
    const undone = undoMerge(merged, 0);
    expect(names(undone.sides[1])).toEqual([
      "Puka Nacua",
      "Josh Allen",
      "Puka Nacua",
      "Josh Allen",
      "Bijan Robinson",
    ]);
    expect(names(undone.sides[0])).toEqual(["Ja'Marr Chase"]);
  });

  it("flags but never merges a 1-asset seam match on the aligned side (#1619)", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          ["Team 2 gets", 1, [resolved("Puka Nacua")]],
        ]),
      ),
      join(
        labelled(1, [
          [
            "Team 2 gets",
            1,
            [resolved("Puka Nacua"), resolved("Bijan Robinson")],
          ],
        ]),
      ),
    ]);
    const items = merged.sides[1].items;
    expect(names(merged.sides[1])).toEqual([
      "Puka Nacua",
      "Puka Nacua",
      "Bijan Robinson",
    ]);
    expect(items[0].possibleOverlap).toBe(true);
    expect(items[1].possibleOverlap).toBe(true);
    expect(merged.mergeNotes).toEqual([]);
    // Side A's seam was broken by a shot that did not show it.
    expect(merged.sides[0].items[0].possibleOverlap).toBe(false);
  });

  it("labels from another vocabulary fall back to position and say so", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          ["Team 2 gets", 1, [resolved("Puka Nacua")]],
        ]),
      ),
      join(
        labelled(1, [
          ["You get", 1, [resolved("Bijan Robinson")], "you give/you get"],
        ]),
      ),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase", "Bijan Robinson"]);
    expect(merged.alignmentNotes[1]).toMatchObject({
      basis: "position",
      conflict: "label_family_mismatch",
    });
    const codes = merged.warnings.map((w) => [w.code, w.sourceImage]);
    expect(codes).toContainEqual(["side_alignment_conflict", 1]);
    expect(
      describeWarning({ code: "side_alignment_conflict", sourceImage: 1 }, 2),
    ).toMatch(/^Screenshot 2: its side labels don't match/);
  });

  it("an unlabelled shot among labelled ones is placed by position, flagged unverified", () => {
    const merged = mergeImages([
      join(
        labelled(0, [
          ["Team 1 gets", 0, [resolved("Ja'Marr Chase")]],
          ["Team 2 gets", 1, [resolved("Puka Nacua")]],
        ]),
      ),
      join({
        ...resp(1, [[resolved("Bijan Robinson")], []]),
        sides: [
          {
            label: "Side A",
            labelSource: "position",
            items: [resolved("Bijan Robinson")],
          },
          { label: "Side B", labelSource: "position", items: [] },
        ],
      }),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase", "Bijan Robinson"]);
    expect(merged.warnings.map((w) => [w.code, w.sourceImage])).toEqual([
      ["side_alignment_unverified", 1],
    ]);
  });

  it("keeps missing_side when the merged trade still has one empty side", () => {
    const merged = mergeImages([
      join(labelled(0, [["Team 1 gets", 0, [resolved("Ja'Marr Chase")]]])),
      join(labelled(1, [["Team 1 gets", 0, [resolved("Puka Nacua")]]])),
    ]);
    expect(names(merged.sides[0])).toEqual(["Ja'Marr Chase", "Puka Nacua"]);
    expect(merged.sides[1].items).toEqual([]);
    expect(merged.warnings.map((w) => w.code)).toEqual([
      "missing_side",
      "missing_side",
    ]);
  });

  it("swapReviewSides flips the alignment notes with the sides", () => {
    const merged = mergeImages([
      join(labelled(0, [["Team 2 gets", 1, [resolved("Bijan Robinson")]]])),
    ]);
    expect(merged.alignmentNotes[0].targets).toEqual([1]);
    const swapped = swapReviewSides(merged);
    expect(swapped.alignmentNotes[0].targets).toEqual([0]);
    expect(names(swapped.sides[0])).toEqual(["Bijan Robinson"]);
  });

  it("alignImageSides: no labels -> position; colliding labels -> position + conflict", () => {
    const side = (labelSource, anchorFamily, anchorSlot) => ({
      labelSource,
      anchorFamily,
      anchorSlot,
      items: [],
    });
    expect(
      alignImageSides([
        side("position", null, null),
        side("position", null, null),
      ]),
    ).toEqual({ targets: [0, 1], basis: "position", conflict: null });
    // a half-stated label is no label
    expect(alignImageSides([side("anchor", null, 1)]).basis).toBe("position");
    const frame = [
      { family: "team 1/team 2", slot: 0 },
      { family: "team 1/team 2", slot: 1 },
    ];
    expect(
      alignImageSides(
        [
          side("anchor", "team 1/team 2", 1),
          side("anchor", "team 1/team 2", 1),
        ],
        frame,
      ),
    ).toMatchObject({
      targets: [0, 1],
      basis: "position",
      conflict: "labels_collide",
    });
    expect(
      alignImageSides(
        [side("anchor", "team a/team b", 0)],
        [
          { family: "team 1/team 2", slot: 0 },
          { family: "team a/team b", slot: 0 },
        ],
      ),
    ).toMatchObject({ basis: "label", targets: [1] });
  });
});

// ── the owner's regression trade, replayed from REAL OCR output ──────

describe("owner regression: Team 1 gets Jaxson Dart, Team 2 gets De'Von Achane", () => {
  // Committed real-tesseract payloads of two SYNTHETIC phone screenshots of
  // the owner's trade (tests/fixtures/screenshot_import/mobile390_multishot_*;
  // never an owner screenshot).  test_real_tesseract.py fails when a fresh
  // read drifts from these recordings.
  const FIXTURES = path.resolve(
    __dirname,
    "..",
    "..",
    "tests",
    "fixtures",
    "screenshot_import",
  );
  const recorded = (name) =>
    JSON.parse(
      fs.readFileSync(path.join(FIXTURES, name, "extraction.json"), "utf8"),
    );
  const OWNER_ROWS = [
    player("Jaxson Dart", "12508", { pos: "QB" }),
    player("De'Von Achane", "9226", { pos: "RB" }),
    player("Bryce Young", "9228", { pos: "QB" }),
    player("Omarion Hampton", "12507", { pos: "RB" }),
  ];
  const OM = maps(OWNER_ROWS, {});
  const shots = () => [
    recorded("mobile390_multishot_1"),
    recorded("mobile390_multishot_2"),
  ];

  it("imports Dart to Team 1 and Achane to Team 2, nothing else", () => {
    const merged = mergeImages(shots().map((r) => joinToBoard(r, OM)));
    expect(merged.sides.map((s) => s.label)).toEqual([
      "Team 1 gets",
      "Team 2 gets",
    ]);
    expect(
      toImportedSides(merged).map((side) => side.map((r) => r.name)),
    ).toEqual([["Jaxson Dart"], ["De'Von Achane"]]);
    expect(merged.unassigned).toEqual([]);
    expect(importReady(merged)).toBe(true);
    expect(merged.warnings).toEqual([]);
    // The insights widget's players are ignored as page furniture.
    const ignored = Object.fromEntries(
      merged.ignored.map((g) => [g.raw, g.reason]),
    );
    expect(ignored["Bryce Young"]).toBe("outside_trade_region");
    expect(ignored["Omarion Hampton"]).toBe("outside_trade_region");
  });

  it("would have put both players on Team 1 if sides were aligned by position", () => {
    // The pre-CQ-11 behaviour, reproduced by withholding the label fields:
    // the follow-up shot's only side is its FIRST side.
    const positional = shots().map((r) => ({
      ...r,
      sides: r.sides.map(({ anchorFamily, anchorSlot, ...side }) => side),
    }));
    const merged = mergeImages(positional.map((r) => joinToBoard(r, OM)));
    expect(
      toImportedSides(merged).map((side) => side.map((r) => r.name)),
    ).toEqual([["Jaxson Dart", "De'Von Achane"], []]);
  });
});
