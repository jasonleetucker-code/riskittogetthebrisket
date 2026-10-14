/**
 * #1337 — every appropriate player name converges on the canonical Player
 * File (`/players/[playerId]`) through ONE primitive, `PlayerNameButton`.
 *
 * This is a source-level RATCHET over the surfaces the 2026-10-07 adoption
 * pass covered (Game Day, the rankings rails, /edge and the terminal movers
 * were converted earlier and are pinned by player-name-link.test.jsx;
 * /rosters and /waivers belong to another lane and are out of this list).
 *
 * Three rules:
 *
 *   1. ADOPTED surfaces import the primitive and render it at least the
 *      pinned number of times.  Dropping it back to a hand-built name fails.
 *
 *   2. Every remaining RAW name render — `{x.name}`, `{x.playerName}`,
 *      `{x.displayName}`, `{x.player}` as a JSX child — is allowlisted per
 *      file and expression with an exact count and a REASON.  A new raw
 *      render fails (route it through the primitive, or add it here with a
 *      reason); a render that disappeared fails too, because an allowance
 *      nobody re-checks absorbs the next regression.
 *
 *      Most reasons are one of three, and they are not interchangeable:
 *        - NOT_A_PLAYER  — a team / manager / seat name.
 *        - NO_CANONICAL_ID — the payload carries no Sleeper playerId, or an
 *          id field that FALLS BACK TO A NAME (so it is not an id).  The
 *          primitive's identity rule forbids resolving a name to an id, so
 *          these stay plain text until the producer stamps the real id.
 *        - CONTROL — the name is the label of a selection / form control;
 *          a link inside it would be a nested interactive element.
 *
 *   3. PUBLIC and SELF-AUTHED pages never link into the private Player File.
 *      `/players/*` is behind the site login (lib/public-routes.js — not in
 *      PUBLIC_EXACT / PUBLIC_PREFIXES), so a link from the public /league
 *      hub or the auction room (its own auction session, no site login)
 *      would send that visitor to /login.  The public hub links its own
 *      public-safe journey, `/league/player/[playerId]`.
 */
import { describe, it, expect } from "vitest";
import fs from "node:fs";
import path from "node:path";

import { isPublicPath, isSelfAuthedPagePath } from "@/lib/public-routes";

const ROOT = path.resolve(__dirname, "..");
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), "utf8");

/** Strip comments so prose mentioning `/players/[id]` is not code. */
function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .split(/\r?\n/)
    .map((line) => line.replace(/(^|[^:"'`\\])\/\/.*$/, "$1"))
    .join("\n");
}

// A JSX child expression that is ONLY a member access ending in a name-ish
// field.  The lookbehind excludes attributes (`key={p.name}`), template
// literals (`${p.name}`) and string contexts.
//
// The optional tail also catches a FALLBACK render — `{x.name || "—"}`,
// `{row.displayName ?? row.assetId}` — which is still a raw name on
// screen. Those are keyed with a trailing ` ||` so an allowance says
// which form it covers.
const RAW_NAME = /(?<![=\w$"'`])\{\s*([A-Za-z_$][\w$]*(?:\??\.[A-Za-z_$][\w$]*)*\??\.(?:name|playerName|displayName|player))\s*((?:\|\||\?\?)(?:[^{}]|\$\{[^{}]*\})*)?\}/g;

function rawNameCounts(rel) {
  const counts = {};
  for (const m of stripComments(read(rel)).matchAll(RAW_NAME)) {
    const expr = m[1].replace(/\?\./g, ".") + (m[2] ? " ||" : "");
    counts[expr] = (counts[expr] || 0) + 1;
  }
  return counts;
}

const NOT_A_PLAYER = "NOT_A_PLAYER";
const NO_CANONICAL_ID = "NO_CANONICAL_ID";
const CONTROL = "CONTROL";

/** Surfaces that adopted the primitive, with the minimum render count. */
const ADOPTED = {
  // AssetRow + IncomingRow: players link to the Player File, picks keep
  // the quick-view popup (the primitive's onOpen fallback).
  "app/trade/trade-sections.jsx": 2,
  // Opportunities table (board rows carry raw.playerId).
  "app/arbitrage/page.jsx": 1,
  // Each compared player's heading.
  "app/players/compare/page.jsx": 1,
  // Player column; assetId IS the Sleeper id for players (sharpAssetPlayerId).
  "app/market/sharp-tracker/page.jsx": 1,
  "app/market/sharp-roster-percentage/page.jsx": 1,
};

/**
 * Raw renders still allowed: file -> { expression: [count, kind, reason] }.
 */
const ALLOWED_RAW = {
  "app/trade/page.jsx": {},
  "app/trade/trade-sections.jsx": {
    "t.name": [1, NOT_A_PLAYER, "team summary"],
    "selectedTeam.name": [1, NOT_A_PLAYER, "the user's team badge"],
  },
  // Split out of trade-sections.jsx (loaded on demand by /trade); the
  // allowances moved with the code, unchanged.
  "app/trade/trade-simulation-panel.jsx": {
    "d.name": [1, NO_CANONICAL_ID, "forced-drop list: roster_capacity's playerId falls back to the name (src/trade/roster_capacity.py _norm(name) / `playerId or name`)"],
    "m.name": [2, NO_CANONICAL_ID, "promoted/displaced lineup prose from the simulator; ids are not guaranteed canonical on that path — adopt once the producer stamps the Sleeper id"],
  },
  "app/trade/trade-suggestions-desk.jsx": {
    "t.name": [1, NOT_A_PLAYER, "team selector option"],
    "p.name": [2, NO_CANONICAL_ID, "suggestion cards: /api/trade/suggestions give/receive entries carry no playerId"],
  },
  "app/draft/page.jsx": {
    "player.name": [4, NO_CANONICAL_ID, "draft rows are keyed by playerSlug(name) (lib/draft-logic.js) — no Sleeper id"],
    "row.name": [2, NO_CANONICAL_ID, "draft rows are keyed by playerSlug(name) — no Sleeper id"],
    "p.name": [5, NO_CANONICAL_ID, "draft rows are keyed by playerSlug(name) — no Sleeper id"],
    "review.bestSteal.playerName": [1, NO_CANONICAL_ID, "auction review: pick playerId is the draft slug"],
    "review.worstOverpay.playerName": [1, NO_CANONICAL_ID, "auction review: pick playerId is the draft slug"],
    "r.playerName": [1, NO_CANONICAL_ID, "auction review table: pick playerId is the draft slug"],
    "t.name": [1, NOT_A_PLAYER, "draft team"],
    "t.name ||": [3, NOT_A_PLAYER, "draft team name with a `Team N` fallback"],
  },
  "components/draft/PerfectDraftPanel.jsx": {
    "r.name": [3, NO_CANONICAL_ID, "rookie pool rows are draft-slug keyed; roster-context playerId falls back to the name (src/draft/context.py `playerId or name`)"],
    "r.cut.name": [1, NO_CANONICAL_ID, "cut ladder playerId falls back to the name (src/draft/context.py)"],
    "t.name": [1, NOT_A_PLAYER, "team selector option"],
  },
  "app/angle/page.jsx": {
    "p.name": [1, NO_CANONICAL_ID, "/api/angle/* package players carry name/position only (src/trade/angle.py)"],
    "t.name": [2, NOT_A_PLAYER, "team selector options"],
    "targetTeam.name": [1, NOT_A_PLAYER, "target team heading"],
  },
  "app/arbitrage/page.jsx": {
    "a.name": [1, NO_CANONICAL_ID, "finder trade assets (src/trade/finder.py Asset.to_dict) carry no playerId"],
    "t.name": [2, NOT_A_PLAYER, "team selector options"],
  },
  "app/trades/page.jsx": {
    "item.name": [1, CONTROL, "each trade entry is a whole-card link into /trade (Panel as Link); a player link inside it would nest <a> in <a> — needs the entry restructured, which also moves the e2e hook `.trades-page a.ds-panel`"],
  },
  "app/bdvm/page.jsx": {
    "r.name": [1, NO_CANONICAL_ID, "BDVM playerId falls back to a name key (src/bdvm/service.py `playerId or name_key`; lib/bdvm.js `playerId ?? name`)"],
    "a.name": [1, NO_CANONICAL_ID, "BDVM roster assets: same name-key fallback"],
  },
  "app/news/page.jsx": {
    "digest.player": [1, NO_CANONICAL_ID, "news digests are name-keyed; keeps the quick-view popup, which resolves the name itself"],
    "m.name": [1, NO_CANONICAL_ID, "news mentions are name-only; keeps the quick-view popup"],
  },
  "app/market/sharp-tracker/page.jsx": {},
  "app/market/sharp-roster-percentage/page.jsx": {},
  "app/players/compare/page.jsx": {
    "r.name": [1, CONTROL, "the player-picker option button that selects whom to compare"],
  },
};

describe("#1337 player-name destination ratchet", () => {
  for (const [rel, min] of Object.entries(ADOPTED)) {
    it(`${rel} routes player names through PlayerNameButton`, () => {
      const src = stripComments(read(rel));
      expect(src).toMatch(/\bPlayerNameButton\b[\s\S]*from "@\/components\/ds"/);
      const uses = src.match(/<PlayerNameButton\b/g) || [];
      expect(uses.length).toBeGreaterThanOrEqual(min);
    });
  }

  for (const [rel, allowed] of Object.entries(ALLOWED_RAW)) {
    it(`${rel} has no unreviewed raw player-name render`, () => {
      const found = rawNameCounts(rel);
      const expected = Object.fromEntries(
        Object.entries(allowed).map(([expr, [count]]) => [expr, count]),
      );
      expect(
        found,
        `${rel}: a raw name render changed. Route a player name with a ` +
          "canonical id through PlayerNameButton; otherwise update ALLOWED_RAW " +
          "with the exact count and the reason it cannot link.",
      ).toEqual(expected);
    });
  }

  it("only the primitive builds a Player File URL (one owner, never from a name)", () => {
    // PlayerPopup's "Full profile" launcher used to build
    // `/players/${playerId || name}` itself — a second URL owner that
    // fell back to the display name. Every caller now goes through
    // playerProfileHref, which reads id fields only.
    const builders = [];
    for (const dir of ["app", "components", "lib"]) {
      for (const rel of listFiles(dir)) {
        const src = stripComments(read(rel));
        if (/`\/players\/\$\{|["']\/players\/["']\s*\+/.test(src)) builders.push(rel);
      }
    }
    expect(builders).toEqual(["components/ds/PlayerNameButton.jsx"]);
    // Reads every app/components/lib source file; generous under a
    // fully parallel suite where disk reads queue behind other workers.
  }, 60_000);

  it("every allowance names a kind and a reason", () => {
    for (const [rel, allowed] of Object.entries(ALLOWED_RAW)) {
      for (const [expr, [count, kind, reason]] of Object.entries(allowed)) {
        expect(count, `${rel} ${expr}`).toBeGreaterThan(0);
        expect([NOT_A_PLAYER, NO_CANONICAL_ID, CONTROL], `${rel} ${expr}`).toContain(kind);
        expect(String(reason || "").trim().length, `${rel} ${expr}`).toBeGreaterThanOrEqual(8);
      }
    }
  });
});

// ── 3. public / self-authed pages never link into the private Player File ──

function listFiles(dirRel) {
  const out = [];
  const walk = (abs) => {
    for (const ent of fs.readdirSync(abs, { withFileTypes: true })) {
      const p = path.join(abs, ent.name);
      if (ent.isDirectory()) walk(p);
      else if (/\.(jsx?|mjs)$/.test(ent.name)) out.push(path.relative(ROOT, p).split(path.sep).join("/"));
    }
  };
  walk(path.join(ROOT, dirRel));
  return out;
}

/** The URL path an app/ file serves, for the public-route predicate. */
function routeOf(rel) {
  const segs = rel.replace(/^app\//, "").split("/").slice(0, -1);
  return "/" + segs.filter((s) => !s.startsWith("(")).join("/");
}

describe("#1337 public/private boundary", () => {
  it("the Player File itself is a private route (the premise of this guard)", () => {
    expect(isPublicPath("/players/4984")).toBe(false);
    expect(isSelfAuthedPagePath("/players/4984")).toBe(false);
    expect(isPublicPath("/league/player/4984")).toBe(true);
  });

  const files = [
    ...listFiles("app/league").filter((rel) => isPublicPath(routeOf(rel))),
    ...listFiles("app/auction"),
    ...listFiles("components/auction"),
  ];

  it("scans a non-trivial set of public and self-authed files", () => {
    expect(files.some((f) => f.startsWith("app/league/sections/"))).toBe(true);
    expect(files).toContain("app/league/sections/award-standings.jsx");
    expect(files.some((f) => f.startsWith("app/auction/"))).toBe(true);
    // The private carve-out under /league is NOT scanned as public.
    expect(files.some((f) => f.startsWith("app/league/insider-trading/"))).toBe(false);
  });

  for (const rel of files) {
    it(`${rel} does not link into the private Player File`, () => {
      const src = stripComments(read(rel));
      expect(src, "imports the private-destination primitive").not.toMatch(
        /\b(PlayerNameButton|playerProfileHref)\b/,
      );
      expect(src, "builds a /players/ URL").not.toMatch(/["'`]\/players\//);
    });
  }
});
