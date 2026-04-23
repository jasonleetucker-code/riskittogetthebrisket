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
 *       { n: "Team B", p: ["Josh Allen"] },
 *     ],
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
    s: trade.sides.map((side) => ({
      n: String(side.name || "").slice(0, 40),
      p: (Array.isArray(side.players) ? side.players : [])
        .filter((x) => typeof x === "string" && x.trim())
        .slice(0, 32)  // hard cap to avoid pathologically long URLs
        .map((x) => x.slice(0, 64)),
    })),
  };
  if (trade.note) {
    payload.c = String(trade.note).slice(0, 200);
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
    sides: sides.map((s) => ({
      name: String(s?.n || ""),
      players: Array.isArray(s?.p)
        ? s.p.filter((x) => typeof x === "string")
        : [],
    })),
    note: String(parsed.c || "") || null,
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
