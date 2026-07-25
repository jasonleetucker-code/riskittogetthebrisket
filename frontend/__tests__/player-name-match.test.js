import { describe, it, expect } from "vitest";
import {
  normalizePlayerNameKey,
  buildNewsIndexByPlayer,
  lookupPlayerNews,
  newsItemsForPlayer,
} from "@/lib/player-name-match";

describe("normalizePlayerNameKey", () => {
  it("mirrors the backend normalize_player_name cases", () => {
    // Cases lifted from src/utils/name_clean.py docs + tests.
    expect(normalizePlayerNameKey("T.J. Hockenson")).toBe("tj hockenson");
    expect(normalizePlayerNameKey("TJ Hockenson")).toBe("tj hockenson");
    expect(normalizePlayerNameKey("Ja'Marr Chase")).toBe("jamarr chase");
    expect(normalizePlayerNameKey("JaMarr Chase")).toBe("jamarr chase");
    expect(normalizePlayerNameKey("Kenneth Walker III")).toBe("kenneth walker");
    expect(normalizePlayerNameKey("Marvin Harrison Jr.")).toBe("marvin harrison");
    expect(normalizePlayerNameKey("  Bijan   Robinson  ")).toBe("bijan robinson");
    expect(normalizePlayerNameKey("D'Andre Swift")).toBe("dandre swift");
    // Curly apostrophe variant collides with the straight one.
    expect(normalizePlayerNameKey("Ja’Marr Chase")).toBe("jamarr chase");
    // ASCII fold.
    expect(normalizePlayerNameKey("José Ramírez")).toBe("jose ramirez");
  });

  it("returns empty string for null/empty input", () => {
    expect(normalizePlayerNameKey(null)).toBe("");
    expect(normalizePlayerNameKey(undefined)).toBe("");
    expect(normalizePlayerNameKey("")).toBe("");
  });
});

const ITEMS = [
  {
    id: "a1",
    ts: "2026-07-20T10:00:00+00:00",
    headline: "Older Chase note",
    players: [{ name: "Ja'Marr Chase" }],
  },
  {
    id: "a2",
    ts: "2026-07-24T10:00:00+00:00",
    headline: "Newer Chase note",
    players: [{ name: "JaMarr Chase" }, { name: "Tee Higgins" }],
  },
  {
    id: "a3",
    ts: "2026-07-22T10:00:00+00:00",
    headline: "Hockenson update",
    players: [{ name: "TJ Hockenson" }],
  },
  {
    id: "a4",
    ts: "2026-07-23T10:00:00+00:00",
    // impactedPlayers-only shape (enriched alias field).
    impactedPlayers: ["T.J. Hockenson"],
    headline: "Hockenson practice note",
    players: [],
  },
];

describe("buildNewsIndexByPlayer", () => {
  it("collects ALL items per player, newest first", () => {
    const index = buildNewsIndexByPlayer(ITEMS);
    const chase = lookupPlayerNews(index, "Ja'Marr Chase");
    expect(chase.map((i) => i.id)).toEqual(["a2", "a1"]);
  });

  it("merges name variants onto one key", () => {
    const index = buildNewsIndexByPlayer(ITEMS);
    // Straight-apostrophe, no-apostrophe, and dotted-initial variants
    // all resolve to the same lists.
    expect(lookupPlayerNews(index, "JaMarr Chase")).toHaveLength(2);
    expect(lookupPlayerNews(index, "T.J. Hockenson").map((i) => i.id)).toEqual([
      "a4",
      "a3",
    ]);
    expect(lookupPlayerNews(index, "TJ Hockenson")).toHaveLength(2);
  });

  it("indexes secondary mentions too", () => {
    const index = buildNewsIndexByPlayer(ITEMS);
    expect(lookupPlayerNews(index, "Tee Higgins").map((i) => i.id)).toEqual([
      "a2",
    ]);
  });

  it("dedupes repeated item ids per player", () => {
    const dup = [...ITEMS, { ...ITEMS[1] }];
    const index = buildNewsIndexByPlayer(dup);
    expect(lookupPlayerNews(index, "Tee Higgins")).toHaveLength(1);
  });

  it("returns empty structures on empty/invalid input", () => {
    expect(buildNewsIndexByPlayer(null).size).toBe(0);
    expect(buildNewsIndexByPlayer([]).size).toBe(0);
    expect(lookupPlayerNews(null, "Anyone")).toEqual([]);
    expect(lookupPlayerNews(buildNewsIndexByPlayer(ITEMS), "")).toEqual([]);
    expect(lookupPlayerNews(buildNewsIndexByPlayer(ITEMS), "Nobody Here")).toEqual([]);
  });
});

describe("newsItemsForPlayer", () => {
  it("is a one-shot filter for server-side use", () => {
    expect(newsItemsForPlayer(ITEMS, "TJ Hockenson").map((i) => i.id)).toEqual([
      "a4",
      "a3",
    ]);
    expect(newsItemsForPlayer([], "TJ Hockenson")).toEqual([]);
  });
});
