import { describe, it, expect } from "vitest";
import {
  normalizePlayerNameKey,
  buildNewsIndexByPlayer,
  buildDigestIndex,
  lookupPlayerDigest,
  lookupPlayerNews,
  newsItemsForPlayer,
} from "@/lib/player-name-match";
import { buildPlayerMetaIndex } from "@/lib/news-filters";

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

  // ── Migrated from __tests__/dynasty-data.test.js ────────────────────
  // `lib/dynasty-data.js` exported a second "mirror of
  // normalize_player_name" that had drifted (no apostrophe rule) and had
  // no production callers.  It was deleted on 2026-07-29; its cases live
  // here, against the one verified mirror.  The apostrophe assertion the
  // old suite lacked — the exact case that let the drift survive — is in
  // the block above and in tests/fixtures/name_key_cases.json.

  it("collapses adjacent single-letter initials", () => {
    expect(normalizePlayerNameKey("T.J. Watt")).toBe("tj watt");
    expect(normalizePlayerNameKey("TJ Watt")).toBe("tj watt");
    expect(normalizePlayerNameKey("t j watt")).toBe("tj watt");
    expect(normalizePlayerNameKey("C.J. Stroud")).toBe(
      normalizePlayerNameKey("CJ Stroud"),
    );
    expect(normalizePlayerNameKey("D.J. Moore")).toBe(
      normalizePlayerNameKey("DJ Moore"),
    );
    expect(normalizePlayerNameKey("A.J. Brown")).toBe(
      normalizePlayerNameKey("AJ Brown"),
    );
  });

  it("strips generational suffixes", () => {
    expect(normalizePlayerNameKey("Marvin Harrison Jr.")).toBe(
      normalizePlayerNameKey("Marvin Harrison"),
    );
    expect(normalizePlayerNameKey("Kenneth Walker III")).toBe(
      normalizePlayerNameKey("Kenneth Walker"),
    );
    expect(normalizePlayerNameKey("Brian Thomas Jr")).toBe(
      normalizePlayerNameKey("Brian Thomas"),
    );
  });

  it("folds diacritics to ASCII", () => {
    expect(normalizePlayerNameKey("Juanyéh Thomas")).toBe(
      normalizePlayerNameKey("Juanyeh Thomas"),
    );
  });

  it("lowercases and collapses whitespace", () => {
    expect(normalizePlayerNameKey("  T.J.  WATT  ")).toBe("tj watt");
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

// ── Name-collision disambiguation ─────────────────────────────────
// The repo documents CJ Allen the LB vs C.J. Allen the WR
// (src/utils/name_clean.py): both normalize to "cj allen" and share
// one index key.  When an item's mention carries position/team
// metadata, the caller's row context must route it to the right
// identity; name-only mentions (the backend's current tagging) stay
// visible for both — the documented fallback, since over-filtering
// loses real news.
const COLLISION_ITEMS = [
  {
    id: "wr1",
    ts: "2026-07-24T10:00:00+00:00",
    headline: "Falcons WR camp riser",
    players: [{ name: "C.J. Allen", position: "WR", team: "ATL" }],
  },
  {
    id: "lb1",
    ts: "2026-07-23T10:00:00+00:00",
    headline: "Titans LB defensive rep count",
    players: [{ name: "CJ Allen", position: "LB", team: "TEN" }],
  },
  {
    id: "plain1",
    ts: "2026-07-22T10:00:00+00:00",
    headline: "Allen name-only note",
    players: [{ name: "CJ Allen" }],
  },
];

describe("lookupPlayerNews — collision disambiguation via row context", () => {
  const index = buildNewsIndexByPlayer(COLLISION_ITEMS);

  it("without context, both identities see all shared-key items", () => {
    expect(lookupPlayerNews(index, "CJ Allen").map((i) => i.id)).toEqual([
      "wr1",
      "lb1",
      "plain1",
    ]);
  });

  it("WR context keeps the WR-tagged item + the name-only fallback, drops the LB item", () => {
    const items = lookupPlayerNews(index, "C.J. Allen", {
      position: "WR",
      team: "ATL",
    });
    expect(items.map((i) => i.id)).toEqual(["wr1", "plain1"]);
  });

  it("LB context keeps the LB-tagged item + the name-only fallback, drops the WR item", () => {
    const items = lookupPlayerNews(index, "CJ Allen", {
      position: "LB",
      team: "TEN",
    });
    expect(items.map((i) => i.id)).toEqual(["lb1", "plain1"]);
  });

  it("family-only context works when the mention has no team stamp", () => {
    const idx = buildNewsIndexByPlayer([
      {
        id: "fam1",
        ts: "2026-07-24T10:00:00+00:00",
        headline: "Position-only tag",
        players: [{ name: "CJ Allen", position: "DL/EDGE" }],
      },
    ]);
    // Compound position collapses to its leading family.
    expect(
      lookupPlayerNews(idx, "CJ Allen", { position: "DL" }),
    ).toHaveLength(1);
    expect(
      lookupPlayerNews(idx, "CJ Allen", { position: "WR" }),
    ).toHaveLength(0);
  });

  it("context on a non-colliding player never drops name-only items", () => {
    const idx = buildNewsIndexByPlayer(ITEMS);
    const items = lookupPlayerNews(idx, "TJ Hockenson", {
      position: "TE",
      team: "MIN",
    });
    expect(items.map((i) => i.id)).toEqual(["a4", "a3"]);
  });

  it("newsItemsForPlayer forwards the context (server-side path)", () => {
    expect(
      newsItemsForPlayer(COLLISION_ITEMS, "C.J. Allen", {
        position: "WR",
        team: "ATL",
      }).map((i) => i.id),
    ).toEqual(["wr1", "plain1"]);
  });
});

describe("lookupPlayerNews — ambiguity suppression via the pool meta index", () => {
  // Live pool contains BOTH identities behind "cj allen", plus a
  // unique name for the contrast case.
  const POOL_META = buildPlayerMetaIndex([
    { name: "CJ Allen", pos: "LB", raw: { team: "TEN" } },
    { name: "C.J. Allen", pos: "WR", raw: { team: "ATL" } },
    { name: "Bijan Robinson", pos: "RB", raw: { team: "ATL" } },
  ]);
  const index = buildNewsIndexByPlayer(COLLISION_ITEMS);

  it("suppresses AMBIGUOUS name-only items from both player pages", () => {
    // Tradeoff, on purpose: with two distinct pool identities behind
    // the key and no mention metadata, a false negative on a player
    // page beats attributing the other player's news.
    const wr = lookupPlayerNews(index, "C.J. Allen", {
      position: "WR",
      team: "ATL",
      playerMeta: POOL_META,
    });
    expect(wr.map((i) => i.id)).toEqual(["wr1"]);
    const lb = lookupPlayerNews(index, "CJ Allen", {
      position: "LB",
      team: "TEN",
      playerMeta: POOL_META,
    });
    expect(lb.map((i) => i.id)).toEqual(["lb1"]);
  });

  it("enriched mentions still resolve end-to-end under ambiguity", () => {
    // The backend stamps position/team at aggregation time — those
    // items keep flowing to exactly the right identity.
    const wr = lookupPlayerNews(index, "C.J. Allen", {
      position: "WR",
      playerMeta: POOL_META,
    });
    expect(wr.map((i) => i.id)).toEqual(["wr1"]);
  });

  it("keeps name-only items for UNAMBIGUOUS names", () => {
    const idx = buildNewsIndexByPlayer([
      {
        id: "u1",
        ts: "2026-07-24T10:00:00+00:00",
        headline: "Unique-name note",
        players: [{ name: "Bijan Robinson" }],
      },
    ]);
    const items = lookupPlayerNews(idx, "Bijan Robinson", {
      position: "RB",
      team: "ATL",
      playerMeta: POOL_META,
    });
    expect(items.map((i) => i.id)).toEqual(["u1"]);
  });

  it("general feeds (no per-player context) still see ambiguous items", () => {
    // Suppression is scoped to per-player surfaces — an uncontexted
    // lookup (or the raw feed) keeps the item visible.
    expect(lookupPlayerNews(index, "CJ Allen").map((i) => i.id)).toContain(
      "plain1",
    );
  });

  it("tagger-flagged ambiguous mentions are treated as name-only", () => {
    // A colliding-slug article (e.g. from the PFK provider) carries
    // ONE mention flagged ambiguous — the flag wins even though the
    // mention names a specific display string, so the item is
    // suppressed from BOTH twins' player pages...
    const flagged = {
      id: "amb1",
      ts: "2026-07-25T10:00:00+00:00",
      headline: "Signal Or Noise Cj Allen",
      players: [{ name: "C.J. Allen", ambiguous: true }],
    };
    const idx = buildNewsIndexByPlayer([flagged]);
    expect(
      lookupPlayerNews(idx, "C.J. Allen", {
        position: "WR",
        team: "ATL",
        playerMeta: POOL_META,
      }),
    ).toEqual([]);
    expect(
      lookupPlayerNews(idx, "CJ Allen", {
        position: "LB",
        team: "TEN",
        playerMeta: POOL_META,
      }),
    ).toEqual([]);
    // ...but remains visible in general (uncontexted) feeds.
    expect(lookupPlayerNews(idx, "CJ Allen").map((i) => i.id)).toEqual([
      "amb1",
    ]);
  });

  it("an ambiguous flag overrides stray position/team fields", () => {
    // Defensive: even if a flagged mention somehow carries identity
    // fields, the flag says the identity is a guess — treat as
    // name-only.
    const flagged = {
      id: "amb2",
      ts: "2026-07-25T10:00:00+00:00",
      headline: "Flag wins",
      players: [{ name: "CJ Allen", position: "LB", team: "TEN", ambiguous: true }],
    };
    const idx = buildNewsIndexByPlayer([flagged]);
    expect(
      lookupPlayerNews(idx, "CJ Allen", {
        position: "LB",
        team: "TEN",
        playerMeta: POOL_META,
      }),
    ).toEqual([]);
  });
});

describe("digest index — buildDigestIndex + lookupPlayerDigest", () => {
  const DIGESTS = [
    { player: "Bijan Robinson", position: "RB", team: "ATL", storyCount: 2 },
    // Collision twins: distinct digest entries behind one name key.
    { player: "C.J. Allen", position: "WR", team: "ATL", storyCount: 2 },
    { player: "CJ Allen", position: "LB", team: "TEN", storyCount: 3 },
  ];
  const index = buildDigestIndex(DIGESTS);

  it("resolves a unique player's digest regardless of name variant", () => {
    expect(lookupPlayerDigest(index, "Bijan Robinson").storyCount).toBe(2);
    expect(lookupPlayerDigest(index, "bijan  robinson").storyCount).toBe(2);
  });

  it("collision twins resolve by position and never cross over", () => {
    const wr = lookupPlayerDigest(index, "C.J. Allen", { position: "WR" });
    expect(wr.team).toBe("ATL");
    const lb = lookupPlayerDigest(index, "CJ Allen", { position: "LB" });
    expect(lb.storyCount).toBe(3);
    // Ambiguous without a position → null, not a guess.
    expect(lookupPlayerDigest(index, "CJ Allen")).toBeNull();
    // Position that matches neither twin → null.
    expect(lookupPlayerDigest(index, "CJ Allen", { position: "QB" })).toBeNull();
  });

  it("is defensive about bad input", () => {
    expect(buildDigestIndex(null).size).toBe(0);
    expect(lookupPlayerDigest(null, "Anyone")).toBeNull();
    expect(lookupPlayerDigest(index, "")).toBeNull();
    expect(lookupPlayerDigest(index, "Nobody Here")).toBeNull();
  });
});
