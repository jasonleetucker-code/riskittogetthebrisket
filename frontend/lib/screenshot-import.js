/**
 * screenshot-import — turn screenshot-extraction responses into a review the
 * user confirms, then into the two lists of board rows /trade imports.
 *
 * PRODUCT RULES (C3-IMPORT-IMAGE):
 *
 *   * A screenshot supplies asset IDENTITIES and SIDES only — never values.
 *     Every imported entry is one of the caller's own board rows, unchanged;
 *     the calculator stays the only engine.
 *   * Nothing is invented or silently substituted.  A player joins by the
 *     Sleeper id first, else by the EXACT board name the server returned.
 *     A pick joins by its exact board name; only a slot ("2026 Pick 1.06")
 *     or tier ("2027 Mid 1st") name may follow the backend's ``pickAliases``
 *     redirect (a suppressed tier alias -> its slot row), and that is marked
 *     ``viaAlias`` so the UI can say so.  A generic grade ("2027 Round 1")
 *     is looked up exactly — ``resolvePickRow`` would turn a bare "2027 1st"
 *     into a Mid/.06 guess, so raw OCR text is NEVER passed to it.
 *   * Ambiguous -> the user must choose; a candidate is never auto-picked,
 *     not even a lone one.  Unrecognised -> kept and shown, never dropped.
 *     Noise -> kept in an "ignored" list.
 *   * Repeats are real: the calculator's assets are hypothetical quantities
 *     (owner decision #1619, lib/trade-assets).  The only collapse is the
 *     screenshot-OVERLAP rule in ``mergeImages`` (the same run of >= 2
 *     resolved assets at the seam of two consecutive screenshots), and it is
 *     recorded with an undo.  Nothing is ever deduped by name.
 *
 * Every reducer is pure and returns a new state; the input is not mutated.
 */
import {
  isSuppressedGenericPickRow,
  isTradeableBoardRow,
  resolvePickRow,
} from "./trade-logic.js";
import { tradeEntryKey } from "./trade-assets.js";

export const UNASSIGNED = "unassigned";

// Board pick-row names that may follow a pickAliases redirect.
const SLOT_PICK_NAME = /^\d{4}\s+(?:pick\s+)?[1-6]\.\d{2}$/i;
const TIER_PICK_NAME =
  /^\d{4}\s+(?:early|mid|late)\s+(?:1st|2nd|3rd|4th|5th|6th)$/i;

/** True for a slot or tier pick name (never a generic "2027 Round 1"). */
export function isSlotOrTierPickName(name) {
  const s = String(name || "").trim();
  return SLOT_PICK_NAME.test(s) || TIER_PICK_NAME.test(s);
}

function lookup(map, key) {
  if (!map || key == null || key === "") return undefined;
  if (typeof map.get === "function") return map.get(key);
  return Object.prototype.hasOwnProperty.call(map, key) ? map[key] : undefined;
}

function tradeable(row) {
  return row && isTradeableBoardRow(row) ? row : null;
}

/**
 * The board row for one server-identified asset, or null.  Returns
 * ``{ row, viaAlias }``.
 */
export function resolveBoardRow(
  { kind, boardName, sleeperId },
  { rowByName, rowsByPlayerId, rowByLowerName, pickAliases } = {},
) {
  const name = boardName == null ? "" : String(boardName);
  if (kind !== "pick" && sleeperId) {
    const hit = lookup(rowsByPlayerId, String(sleeperId));
    const list = Array.isArray(hit) ? hit : hit ? [hit] : [];
    const usable = list.filter((r) => tradeable(r));
    // Two board rows on one Sleeper id (a two-way player) — the server's
    // board name says which one; otherwise the first.
    const row = usable.find((r) => r.name === name) || usable[0] || null;
    if (row) return { row, viaAlias: false };
  }
  const exact = tradeable(lookup(rowByName, name));
  if (exact) return { row: exact, viaAlias: false };
  // Redirect ONLY a slot/tier name the board itself aliases: one named in
  // ``pickAliases``, or one whose own row is a suppressed tier alias (the
  // same rule ``canonicalTradeEntry`` applies to saved trades).  A tier the
  // board does not carry at all stays unresolved — no slot is guessed.
  if (kind === "pick" && isSlotOrTierPickName(name)) {
    const own = lookup(rowByName, name);
    const aliased =
      Boolean(lookup(pickAliases, name)) || isSuppressedGenericPickRow(own);
    if (aliased) {
      const redirected = tradeable(
        resolvePickRow(name, rowByLowerName, pickAliases),
      );
      if (redirected)
        return { row: redirected, viaAlias: redirected.name !== name };
    }
  }
  return { row: null, viaAlias: false };
}

function choicesWithRows(list, kind, maps) {
  const out = [];
  const seen = new Set();
  for (const c of Array.isArray(list) ? list : []) {
    if (!c) continue;
    const { row, viaAlias } = resolveBoardRow(
      { kind, boardName: c.boardName, sleeperId: c.sleeperId },
      maps,
    );
    if (!row) continue; // a choice nobody can add is not a choice
    const key = tradeEntryKey(row);
    if (seen.has(key)) continue; // two candidates naming one row = one choice
    seen.add(key);
    out.push({ ...c, row, viaAlias });
  }
  return out;
}

function joinItem(item, maps, sourceImage, id) {
  const kind = item?.kind === "pick" ? "pick" : "player";
  const base = {
    id,
    raw: item?.raw == null ? "" : String(item.raw),
    kind,
    status: "unresolved",
    row: null,
    candidates: [],
    suggestions: choicesWithRows(item?.suggestions, kind, maps),
    reason: item?.reason || null,
    viaAlias: false,
    sourceImage,
    lineIndex: Number.isInteger(item?.lineIndex) ? item.lineIndex : null,
    hints: item?.hints || null,
    boardName: item?.boardName || null,
    possibleOverlap: false,
  };
  if (item?.status === "resolved") {
    const { row, viaAlias } = resolveBoardRow(
      { kind, boardName: item.boardName, sleeperId: item.sleeperId },
      maps,
    );
    if (row)
      return { ...base, status: "resolved", row, viaAlias, reason: null };
    return { ...base, status: "unresolved", reason: "not_on_board" };
  }
  if (item?.status === "needs_confirmation") {
    const candidates = choicesWithRows(item.candidates, kind, maps);
    if (candidates.length === 0) {
      return { ...base, status: "unresolved", reason: "not_on_board" };
    }
    // Never auto-picked — even a single surviving candidate waits for the user.
    return { ...base, status: "needs_confirmation", candidates };
  }
  return base;
}

/**
 * Join one extraction response onto the board.
 *
 * @param {object} resp - POST /api/trade/import-screenshot 200 body
 * @param {object} maps - { rowByName, rowsByPlayerId, rowByLowerName, pickAliases }
 * @returns per-image review: { imageIndex, layout, engine, sides:
 *   [{label, labelSource, items}], unassigned, ignored, warnings }
 */
export function joinToBoard(resp, maps = {}) {
  const imageIndex = Number.isInteger(resp?.imageIndex) ? resp.imageIndex : 0;
  let seq = 0;
  const nextId = () => `i${imageIndex}-${seq++}`;
  const join = (it) => joinItem(it, maps, imageIndex, nextId());
  const rawSides = Array.isArray(resp?.sides) ? resp.sides.slice(0, 2) : [];
  return {
    imageIndex,
    engine: resp?.engine || null,
    layout: resp?.layout || null,
    sides: rawSides.map((s) => ({
      label: s?.label ? String(s.label) : "",
      labelSource: s?.labelSource || "none",
      items: (Array.isArray(s?.items) ? s.items : []).map(join),
    })),
    unassigned: (Array.isArray(resp?.unassigned) ? resp.unassigned : []).map(
      join,
    ),
    ignored: (Array.isArray(resp?.ignored) ? resp.ignored : []).map((g) => ({
      raw: g?.raw == null ? "" : String(g.raw),
      reason: g?.reason || null,
      sourceImage: imageIndex,
    })),
    warnings: (Array.isArray(resp?.warnings) ? resp.warnings : []).map(
      (code) => ({
        code: String(code),
        sourceImage: imageIndex,
      }),
    ),
  };
}

function sameResolvedAsset(a, b) {
  return (
    a?.status === "resolved" &&
    b?.status === "resolved" &&
    a.row &&
    b.row &&
    tradeEntryKey(a.row) === tradeEntryKey(b.row)
  );
}

/** Longest run where the tail of ``prev`` equals the head of ``next``. */
function overlapLength(prev, next) {
  const max = Math.min(prev.length, next.length);
  for (let n = max; n >= 1; n -= 1) {
    let ok = true;
    for (let j = 0; j < n; j += 1) {
      if (!sameResolvedAsset(prev[prev.length - n + j], next[j])) {
        ok = false;
        break;
      }
    }
    if (ok) return n;
  }
  return 0;
}

function emptySide() {
  return { label: "", labelSource: "none", items: [] };
}

/** An empty review state (no screenshots read yet). */
export function emptyReview() {
  return {
    sides: [emptySide(), emptySide()],
    unassigned: [],
    ignored: [],
    warnings: [],
    mergeNotes: [],
    nextId: 0,
  };
}

/**
 * Combine per-image reviews (upload order) into one review state.
 *
 * Side i of every screenshot appends to merged side i.  Overlap at the seam
 * of two consecutive screenshots (same side): a run of >= 2 resolved assets
 * — same board row, same order — ending image k and starting image k+1 is
 * the same pixels scrolled twice, so it is kept once and recorded in
 * ``mergeNotes`` (undoable).  A 1-asset match is NOT merged (one repeated
 * asset is an ordinary trade) but both items are flagged ``possibleOverlap``.
 */
export function mergeImages(perImageReviews) {
  const state = emptyReview();
  let prevTail = [null, null];
  for (const review of Array.isArray(perImageReviews) ? perImageReviews : []) {
    if (!review) continue;
    for (let s = 0; s < 2; s += 1) {
      const side = review.sides?.[s];
      if (!side) {
        prevTail[s] = null;
        continue;
      }
      const target = state.sides[s];
      if (
        side.labelSource === "anchor" &&
        target.labelSource !== "anchor" &&
        side.label
      ) {
        target.label = side.label;
        target.labelSource = "anchor";
      } else if (!target.label && side.label) {
        target.label = side.label;
        target.labelSource = side.labelSource || "none";
      }
      let incoming = (side.items || []).map((it) => ({ ...it }));
      const prev = prevTail[s];
      if (prev && prev.length && incoming.length) {
        const n = overlapLength(prev, incoming);
        if (n >= 2) {
          state.mergeNotes.push({
            side: s,
            count: n,
            sourceImage: review.imageIndex,
            removed: incoming.slice(0, n),
          });
          incoming = incoming.slice(n);
        } else if (n === 1) {
          prev[prev.length - 1].possibleOverlap = true;
          incoming[0].possibleOverlap = true;
        }
      }
      target.items.push(...incoming);
      if (incoming.length) prevTail[s] = incoming;
      else if (!prev) prevTail[s] = null;
    }
    state.unassigned.push(
      ...(review.unassigned || []).map((it) => ({ ...it })),
    );
    state.ignored.push(...(review.ignored || []));
    state.warnings.push(...(review.warnings || []));
  }
  return state;
}

// ── review reducers ──────────────────────────────────────────────────

function locate(state, id) {
  for (let s = 0; s < 2; s += 1) {
    const idx = state.sides[s].items.findIndex((it) => it.id === id);
    if (idx >= 0) return { area: s, idx };
  }
  const idx = state.unassigned.findIndex((it) => it.id === id);
  if (idx >= 0) return { area: UNASSIGNED, idx };
  return null;
}

function listOf(state, area) {
  return area === UNASSIGNED ? state.unassigned : state.sides[area].items;
}

function withList(state, area, items) {
  if (area === UNASSIGNED) return { ...state, unassigned: items };
  const sides = state.sides.map((s, i) => (i === area ? { ...s, items } : s));
  return { ...state, sides };
}

function updateItem(state, id, fn) {
  const at = locate(state, id);
  if (!at) return state;
  const items = listOf(state, at.area).slice();
  items[at.idx] = fn(items[at.idx]);
  return withList(state, at.area, items);
}

/** Move an item to side 0 / 1 or to the "needs a side" tray (appended). */
export function moveItem(state, id, to) {
  const target = to === UNASSIGNED ? UNASSIGNED : Number(to);
  if (target !== UNASSIGNED && target !== 0 && target !== 1) return state;
  const at = locate(state, id);
  if (!at || at.area === target) return state;
  const from = listOf(state, at.area).slice();
  const [item] = from.splice(at.idx, 1);
  const next = withList(state, at.area, from);
  return withList(next, target, [...listOf(next, target), item]);
}

/** Swap Side A and Side B wholesale (labels, items, merge notes). */
export function swapReviewSides(state) {
  return {
    ...state,
    sides: [state.sides[1], state.sides[0]],
    mergeNotes: state.mergeNotes.map((n) => ({
      ...n,
      side: n.side === 0 ? 1 : 0,
    })),
  };
}

/** Remove one item (one copy) from wherever it sits. */
export function removeItem(state, id) {
  const at = locate(state, id);
  if (!at) return state;
  const items = listOf(state, at.area).slice();
  items.splice(at.idx, 1);
  return withList(state, at.area, items);
}

/** Add an asset the screenshot missed — a real board row, appended. */
export function addItem(state, sideIdx, row) {
  if ((sideIdx !== 0 && sideIdx !== 1) || !tradeable(row)) return state;
  const item = {
    id: `m${state.nextId}`,
    raw: "",
    kind: row.assetClass === "pick" ? "pick" : "player",
    status: "resolved",
    row,
    candidates: [],
    suggestions: [],
    reason: null,
    viaAlias: false,
    sourceImage: null,
    lineIndex: null,
    hints: null,
    boardName: row.name,
    possibleOverlap: false,
    manual: true,
  };
  const next = withList(state, sideIdx, [...state.sides[sideIdx].items, item]);
  return { ...next, nextId: state.nextId + 1 };
}

/**
 * The user's choice for an ambiguous or unrecognised item.  Any tradeable
 * board row is accepted (a candidate, a suggestion, or a search result).
 */
export function confirmCandidate(state, id, row) {
  if (!tradeable(row)) return state;
  return updateItem(state, id, (it) => ({
    ...it,
    status: "resolved",
    row,
    viaAlias: false,
    reason: null,
    confirmed: true,
  }));
}

/** Put back the assets an overlap merge collapsed. */
export function undoMerge(state, noteIdx) {
  const note = state.mergeNotes[noteIdx];
  if (!note) return state;
  const items = state.sides[note.side].items.slice();
  let at = items.findIndex((it) => it.sourceImage === note.sourceImage);
  if (at < 0) at = items.length;
  items.splice(at, 0, ...note.removed.map((it) => ({ ...it })));
  const next = withList(state, note.side, items);
  return {
    ...next,
    mergeNotes: state.mergeNotes.filter((_, i) => i !== noteIdx),
  };
}

/** Counts the review UI reports. */
export function reviewCounts(state) {
  const sideItems = [...state.sides[0].items, ...state.sides[1].items];
  const all = [...sideItems, ...state.unassigned];
  return {
    assets: sideItems.length,
    resolved: sideItems.filter((it) => it.status === "resolved" && it.row)
      .length,
    needsConfirmation: all.filter((it) => it.status === "needs_confirmation")
      .length,
    unresolved: all.filter((it) => it.status === "unresolved").length,
    unassigned: state.unassigned.length,
  };
}

/**
 * True only when the import can go through with nothing guessed: at least
 * one asset, every side item resolved to a board row, nothing waiting for a
 * side.
 */
export function importReady(state) {
  if (!state) return false;
  const c = reviewCounts(state);
  return (
    c.assets >= 1 &&
    c.resolved === c.assets &&
    c.needsConfirmation === 0 &&
    c.unresolved === 0 &&
    c.unassigned === 0
  );
}

/** The two lists of board rows to hand to ``applyImportedSides``. */
export function toImportedSides(state) {
  return [0, 1].map((s) =>
    state.sides[s].items.filter((it) => it.row).map((it) => it.row),
  );
}

// ── plain-language copy for server answers ───────────────────────────

/**
 * One failed extraction, in plain words.  ``retryable`` says whether the
 * same image may succeed on a second try (busy, rate-limited, timed out,
 * network) — a wrong file type or a switched-off feature will not.
 *
 * @param {number} status - HTTP status (0 for a network failure)
 * @param {object} body - parsed error body ({ error, message })
 * @param {string|null} retryAfter - Retry-After header value, if any
 */
export function describeImportError(status, body, retryAfter = null) {
  const code =
    String(body?.error || "") || (status === 0 ? "network" : `http_${status}`);
  const seconds = Number.parseInt(retryAfter, 10);
  const wait =
    Number.isFinite(seconds) && seconds > 0
      ? ` Try again in ${seconds} seconds.`
      : "";
  switch (code) {
    case "feature_disabled":
      return {
        code,
        retryable: false,
        message: "Screenshot import is turned off.",
      };
    case "guest_read_only":
      return {
        code,
        retryable: false,
        message: "Sign in to import trades from screenshots.",
      };
    case "rate_limited":
      return {
        code,
        retryable: true,
        message: `Too many screenshots in a short time.${wait || " Try again in a moment."}`,
      };
    case "ocr_unavailable":
      return {
        code,
        retryable: false,
        message: "Screenshot reading isn't set up on the server yet.",
      };
    case "ocr_busy":
      return {
        code,
        retryable: true,
        message: `The screenshot reader is busy.${wait || " Try again in a moment."}`,
      };
    case "ocr_timeout":
      return {
        code,
        retryable: true,
        message:
          "Reading took too long. Try again, or crop the screenshot to just the trade.",
      };
    case "network":
      return {
        code,
        retryable: true,
        message:
          "Couldn't reach the server. Check your connection and try again.",
      };
    default:
      break;
  }
  if (status === 413) {
    return {
      code,
      retryable: false,
      message: "That image is too large. Crop it to the trade and try again.",
    };
  }
  if (status === 415) {
    return {
      code,
      retryable: false,
      message: "Use a PNG, JPEG or WebP screenshot.",
    };
  }
  if (status === 400) {
    return {
      code,
      retryable: false,
      message: body?.message
        ? String(body.message)
        : "That image could not be read.",
    };
  }
  return {
    code,
    retryable: status >= 500 || status === 0,
    message: body?.message
      ? String(body.message)
      : `Reading failed (HTTP ${status}).`,
  };
}

const WARNING_COPY = {
  missing_side:
    "only one side of the trade was found. Add the other side by hand or upload another screenshot.",
  low_layout_confidence:
    "the side layout is unclear — check that every asset is on the right side.",
  possibly_cropped:
    "the image may be cropped, so assets at the edge could be missing.",
  pick_owner_not_established:
    "pick owners aren't shown, so picks import as market picks with no team owner.",
  no_assets_found: "no trade assets were found.",
  trade_region_not_detected:
    "the trade area wasn't recognised, so nothing was placed on a side. Move each asset to the side it belongs to.",
};

/** A server warning, prefixed with the screenshot it came from. */
export function describeWarning(warning, imageCount = 1) {
  const code = String(warning?.code || "");
  const text = WARNING_COPY[code] || code.replace(/_/g, " ");
  const prefix =
    imageCount > 1 && Number.isInteger(warning?.sourceImage)
      ? `Screenshot ${warning.sourceImage + 1}: `
      : "";
  const body = prefix ? text : text.charAt(0).toUpperCase() + text.slice(1);
  return `${prefix}${body}`;
}
