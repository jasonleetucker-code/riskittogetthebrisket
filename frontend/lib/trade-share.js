"use client";

/**
 * trade-share — encode / decode trade proposals as URL-safe strings.
 *
 * Round-trip schema:
 *
 *   encoded = base64url(JSON.stringify({
 *     v: 1,                          // schema version
 *     s: [                           // sides (typically 2, but N is allowed)
 *       { n: "Team A", p: ["Ja'Marr Chase", "2026 1.03"] },
 *       { n: "Team B", p: ["Josh Allen", "2027 Mid 1st", "2027 Mid 1st"],
 *         a: [null, null, "pick:dynasty_main:2027:r1:o4"],    // optional
 *         q: [4, 6, 8] },                                     // optional
 *     ],
 *
 *   ``p`` lists one name per LINE (a distinct name + owned-id pair, in
 *   first-occurrence order).  ``q`` (optional, aligned with ``p``) is that
 *   line's copy count; it is omitted when every line is a single copy, so
 *   a trade without repeats encodes exactly as it always did.  Links
 *   written before ``q`` existed repeat a name once per COPY instead, and
 *   still decode to the same copies.  Every calculator asset is repeatable
 *   (owner decision 2026-10-03), so Jefferson x4 + 2027 Mid 1st x6 + an
 *   owned pick x8 round-trips exactly.
 *   ``a`` (optional, aligned with ``p``) carries an owned league pick's
 *   canonical id from ``src/identity/picks.py``; it is absent on every
 *   link written before T-NEW-02 and on any side without an owned pick.
 *     t: "2026-04-23T14:00:00Z",    // optional creation timestamp
 *     c: "Testing a buy-low play",  // optional free-text note
 *   }))
 *
 * Goals:
 *   - Copy-paste share flow: send a link, recipient opens, trade is
 *     pre-loaded on the trade page with live valuations.
 *   - Survive URL mangling by messaging apps (Slack, iMessage) —
 *     base64url avoids ``+`` and ``/`` which some apps eat.
 *   - Ceiling ~2000 chars: most trade proposals are <10 assets per
 *     side so typical payloads fit in a single SMS.
 *   - No server state — every share URL is self-contained.  You can
 *     open a share link without an auth session and see the trade.
 *
 * Example:
 *
 *     const url = buildShareUrl({ sides: [{name: "Team A", players:
 *         ["Ja'Marr Chase"]}, {name: "Team B", players: ["Josh Allen"]}]});
 *     // → "https://.../trade?share=eyJ2IjoxLCJzIjpbeyJuIjoi..."
 *
 *     const state = parseShareParam(url);
 *     // → { sides: [...], note: "...", createdAt: "..." }
 */

export const SHARE_PARAM = "share";
export const SHARE_SCHEMA_VERSION = 1;

/**
 * Decode-side bound on ONE line's copy count in an untrusted link.
 *
 * This is input validation, not a calculator quantity cap: manual
 * construction and saved workspaces are unlimited.  A share link is
 * attacker-controllable text, and the one-entry-per-copy state model would
 * otherwise let ``q: [1e9]`` allocate a billion entries and hang the tab of
 * whoever opens it.  Far above any real trade.
 */
export const SHARE_MAX_COPIES_PER_LINE = 999;

function toBase64Url(bytes) {
  // ``btoa`` only accepts Latin-1; we need UTF-8 safe encoding.
  // Use the ``%``/``unescape`` trick that's been standard since
  // IE6 — still the shortest correct path in modern browsers too.
  if (typeof bytes === "string") {
    const utf8 = unescape(encodeURIComponent(bytes));
    return btoa(utf8)
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  }
  throw new TypeError("expected string");
}

function fromBase64Url(str) {
  // Reverse the URL-safe swaps, restore padding, then atob → UTF-8.
  const normal = String(str || "").replace(/-/g, "+").replace(/_/g, "/");
  const padded = normal + "===".slice(0, (4 - (normal.length % 4)) % 4);
  try {
    return decodeURIComponent(escape(atob(padded)));
  } catch {
    return null;
  }
}

/**
 * Encode a trade state object into a URL-safe parameter value.
 *
 * ``trade`` shape::
 *
 *     {
 *       sides: [
 *         { name?: "Team A", players: [string] },
 *         { name?: "Team B", players: [string] },
 *       ],
 *       note?: string,
 *     }
 */
export function encodeTrade(trade) {
  if (!trade || !Array.isArray(trade.sides)) {
    throw new TypeError("trade must have a sides array");
  }
  const payload = {
    v: SHARE_SCHEMA_VERSION,
    s: trade.sides.map((side) => {
      // Names and owned-pick ids travel as PAIRS until the final shape so
      // filtering an unusable name can never shift an id onto the wrong
      // asset.  Repeated pairs are copies and are all kept: they collapse
      // into one LINE with a count, so the 32-line URL cap bounds distinct
      // assets, never quantity.
      const ids = Array.isArray(side.assetIds) ? side.assetIds : [];
      const lines = [];
      const byKey = new Map();
      (Array.isArray(side.players) ? side.players : []).forEach((x, i) => {
        if (typeof x !== "string" || !x.trim()) return;
        const name = x.slice(0, 64);
        const rawId = ids[i];
        const id = typeof rawId === "string" && rawId.trim() ? rawId.trim().slice(0, 96) : null;
        const key = `${name}\u0000${id || ""}`;
        const existing = byKey.get(key);
        if (existing) {
          existing.count += 1;
          return;
        }
        const line = { name, id, count: 1 };
        byKey.set(key, line);
        lines.push(line);
      });
      const kept = lines.slice(0, 32); // hard cap on distinct lines (URL length)
      const out = { n: String(side.name || "").slice(0, 40), p: kept.map((l) => l.name) };
      // ``a`` is ADDITIVE and aligned with ``p``: an owned pick's canonical
      // id, or null.  Omitted entirely when a side has no owned pick, so a
      // trade without one encodes exactly as it always did, and a decoder
      // that predates ``a`` ignores it and loads the names as before.
      if (kept.some((l) => l.id)) out.a = kept.map((l) => l.id);
      // ``q`` is ADDITIVE the same way: omitted unless some line repeats.
      if (kept.some((l) => l.count > 1)) out.q = kept.map((l) => l.count);
      return out;
    }),
  };
  if (trade.note) {
    payload.c = String(trade.note).slice(0, 200);
  }
  // #842 Use Team Context: ADDITIVE, and only when OFF — a link made with the
  // default mode encodes exactly as it always did, and an older decoder that
  // predates ``m`` simply opens it in the default (Team context) mode.
  if (trade.teamContext === false) {
    payload.m = "asset";
  }
  payload.t = new Date().toISOString();
  return toBase64Url(JSON.stringify(payload));
}

/**
 * Decode a previously-encoded trade state.  Returns null on any
 * parsing error rather than throwing — the URL came from a user-
 * controlled link, so be defensive.
 */
export function decodeTrade(encoded) {
  if (!encoded) return null;
  const json = fromBase64Url(encoded);
  if (!json) return null;
  let parsed;
  try {
    parsed = JSON.parse(json);
  } catch {
    return null;
  }
  if (!parsed || typeof parsed !== "object") return null;
  const version = Number(parsed.v) || 1;
  if (version !== SHARE_SCHEMA_VERSION) return null;
  const sides = Array.isArray(parsed.s) ? parsed.s : [];
  return {
    sides: sides.map((s) => {
      const rawIds = Array.isArray(s?.a) ? s.a : [];
      const rawCounts = Array.isArray(s?.q) ? s.q : [];
      const pairs = [];
      (Array.isArray(s?.p) ? s.p : []).forEach((x, i) => {
        if (typeof x !== "string") return;
        // A line's copies expand back to one item per copy.  Absent or
        // invalid counts are one copy (every link written before ``q``).
        const c = Number(rawCounts[i]);
        const copies = Number.isInteger(c) && c >= 1 ? Math.min(c, SHARE_MAX_COPIES_PER_LINE) : 1;
        for (let k = 0; k < copies; k += 1) pairs.push([x, rawIds[i]]);
      });
      return {
        name: String(s?.n || ""),
        players: pairs.map(([x]) => x),
        // Aligned with ``players``; null where the link carries no owned
        // pick identity (every link written before T-NEW-02).
        assetIds: pairs.map(([, id]) => (typeof id === "string" && id.trim() ? id.trim() : null)),
      };
    }),
    note: String(parsed.c || "") || null,
    // Absent (every link before #842, and every Team-context link) is ON.
    teamContext: parsed.m !== "asset",
    createdAt: parsed.t ? String(parsed.t) : null,
  };
}

/**
 * Build a complete share URL given the trade state and an optional
 * base URL override.  Defaults to the current ``window.location``
 * origin + ``/trade`` path.
 */
export function buildShareUrl(trade, { baseUrl } = {}) {
  const encoded = encodeTrade(trade);
  const base = baseUrl
    ? baseUrl.replace(/\/+$/, "")
    : (typeof window !== "undefined" ? window.location.origin : "");
  return `${base}/trade?${SHARE_PARAM}=${encoded}`;
}

/**
 * Extract trade state from a URL (or a pre-parsed search-params
 * string).  Returns null when the URL has no ``?share=...``.
 */
export function parseShareParam(search) {
  if (typeof search !== "string") return null;
  let params;
  try {
    params = search.startsWith("?") || search.startsWith("http")
      ? new URL(search, "http://x").searchParams
      : new URLSearchParams(search);
  } catch {
    return null;
  }
  const encoded = params.get(SHARE_PARAM);
  if (!encoded) return null;
  return decodeTrade(encoded);
}
