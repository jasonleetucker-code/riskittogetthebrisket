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
 *   * Sides follow the screenshot's SIDE LABELS across screenshots: the
 *     server says which label each side carries (``anchorFamily`` /
 *     ``anchorSlot``), so a follow-up shot showing only "Team 2 gets..." is
 *     added to Team 2's side.  Without labels, or when labels disagree,
 *     sides fall back to their position and the review says so.  The label
 *     vocabulary lives on the server only — no label text is parsed here.
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
 *   [{label, labelSource, anchorFamily, anchorSlot, items}], unassigned,
 *   ignored, warnings }
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
      anchorFamily:
        typeof s?.anchorFamily === "string" && s.anchorFamily
          ? s.anchorFamily
          : null,
      anchorSlot:
        s?.anchorSlot === 0 || s?.anchorSlot === 1 ? s.anchorSlot : null,
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
  return {
    label: "",
    labelSource: "none",
    anchorFamily: null,
    anchorSlot: null,
    items: [],
  };
}

/** An empty review state (no screenshots read yet). */
export function emptyReview() {
  return {
    sides: [emptySide(), emptySide()],
    unassigned: [],
    ignored: [],
    warnings: [],
    mergeNotes: [],
    alignmentNotes: [],
    nextId: 0,
  };
}

/** The side label a side carries — ``{ family, slot }`` — or null. */
function anchorOf(side) {
  if (side?.labelSource !== "anchor") return null;
  const slot = side.anchorSlot;
  const family = side.anchorFamily;
  if ((slot !== 0 && slot !== 1) || typeof family !== "string" || !family) {
    return null;
  }
  return { family, slot };
}

function sameAnchor(a, b) {
  return Boolean(a && b && a.family === b.family && a.slot === b.slot);
}

/**
 * Where each side of ONE screenshot goes in the merged review.
 *
 * ``frame`` is the side label each merged side already carries
 * (``[anchor|null, anchor|null]``, from earlier screenshots).  A labelled
 * side goes to the merged side carrying the SAME label, else to the side
 * opposite its label's sibling ("Team 2 gets" opposite "Team 1 gets").  On
 * an empty frame a lone label takes its own slot (Team 2 -> Side B) and a
 * pair keeps this screenshot's order.  No label -> position (side i -> i).
 * Labels that contradict the frame (another label vocabulary, a taken
 * side, two sides onto one) -> position, with ``conflict`` named — never a
 * guess dressed as a label match.
 *
 * @returns {{ targets: number[], basis: "label"|"position",
 *   conflict: string|null }}
 */
export function alignImageSides(sides, frame = [null, null]) {
  const list = (Array.isArray(sides) ? sides : []).slice(0, 2);
  const identity = list.map((_, i) => i);
  const anchors = list.map(anchorOf);
  const byPosition = (conflict = null) => ({
    targets: identity,
    basis: "position",
    conflict,
  });
  if (!anchors.some(Boolean)) return byPosition();
  const frameKnown = frame.some(Boolean);
  const targets = anchors.map(() => null);
  for (let i = 0; i < list.length; i += 1) {
    const a = anchors[i];
    if (!a) continue;
    let t = frame.findIndex((f) => sameAnchor(f, a));
    if (t < 0) {
      const sibling = frame.findIndex((f) => f && f.family === a.family);
      if (sibling >= 0) t = 1 - sibling;
      else if (!frameKnown) t = list.length === 1 ? a.slot : i;
      else return byPosition("label_family_mismatch");
    }
    if (frame[t] && !sameAnchor(frame[t], a)) {
      return byPosition("label_side_taken");
    }
    targets[i] = t;
  }
  // An unlabelled side of a labelled screenshot takes the side left over.
  const free = [0, 1].filter((t) => !targets.includes(t));
  for (let i = 0; i < targets.length; i += 1) {
    if (targets[i] === null) targets[i] = free.length ? free.shift() : null;
  }
  if (targets.includes(null) || new Set(targets).size !== targets.length) {
    return byPosition("labels_collide");
  }
  return { targets, basis: "label", conflict: null };
}

/**
 * Combine per-image reviews (upload order) into one review state.
 *
 * Each screenshot's sides are placed by ``alignImageSides`` (side labels
 * first, position as the fallback) and recorded in ``alignmentNotes``.  A
 * screenshot placed by position while others carry labels gets warning
 * ``side_alignment_unverified``; one whose labels contradict the others,
 * ``side_alignment_conflict``.  Once the merged review has assets on BOTH
 * sides, the per-screenshot ``missing_side`` warnings are dropped — they
 * described one screenshot, and the trade now has both sides.
 *
 * Overlap at the seam of two consecutive screenshots (same merged side): a
 * run of >= 2 resolved assets — same board row, same order — ending image k
 * and starting image k+1 is the same pixels scrolled twice, so it is kept
 * once and recorded in ``mergeNotes`` (undoable).  A 1-asset match is NOT
 * merged (one repeated asset is an ordinary trade, #1619) but both items
 * are flagged ``possibleOverlap``.
 */
export function mergeImages(perImageReviews) {
  const reviews = (
    Array.isArray(perImageReviews) ? perImageReviews : []
  ).filter(Boolean);
  const state = emptyReview();
  const frame = [null, null];
  const prevTail = [null, null];
  const anyLabelled = reviews.some((r) =>
    (r.sides || []).some((side) => anchorOf(side)),
  );
  for (const review of reviews) {
    const sides = (Array.isArray(review.sides) ? review.sides : []).slice(0, 2);
    const align = alignImageSides(sides, frame);
    if (sides.length) {
      state.alignmentNotes.push({
        sourceImage: review.imageIndex,
        targets: align.targets.slice(),
        basis: align.basis,
        conflict: align.conflict,
      });
    }
    if (align.conflict) {
      state.warnings.push({
        code: "side_alignment_conflict",
        sourceImage: review.imageIndex,
      });
    } else if (
      align.basis === "position" &&
      anyLabelled &&
      reviews.length > 1 &&
      sides.some((side) => side?.items?.length)
    ) {
      state.warnings.push({
        code: "side_alignment_unverified",
        sourceImage: review.imageIndex,
      });
    }
    if (align.basis === "label") {
      sides.forEach((side, i) => {
        const a = anchorOf(side);
        const t = align.targets[i];
        if (a && !frame[t]) frame[t] = a;
      });
    }
    const covered = new Set();
    sides.forEach((side, i) => {
      if (!side) return;
      const t = align.targets[i];
      covered.add(t);
      const target = state.sides[t];
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
      const a = anchorOf(side);
      if (a && align.basis === "label" && target.anchorFamily == null) {
        target.anchorFamily = a.family;
        target.anchorSlot = a.slot;
      }
      let incoming = (side.items || []).map((it) => ({ ...it }));
      const prev = prevTail[t];
      if (prev && prev.length && incoming.length) {
        const n = overlapLength(prev, incoming);
        if (n >= 2) {
          state.mergeNotes.push({
            side: t,
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
      if (incoming.length) prevTail[t] = incoming;
      else if (!prev) prevTail[t] = null;
    });
    for (let t = 0; t < 2; t += 1) if (!covered.has(t)) prevTail[t] = null;
    state.unassigned.push(
      ...(review.unassigned || []).map((it) => ({ ...it })),
    );
    state.ignored.push(...(review.ignored || []));
    state.warnings.push(...(review.warnings || []));
  }
  if (reviews.length > 1 && state.sides.every((side) => side.items.length)) {
    state.warnings = state.warnings.filter((w) => w.code !== "missing_side");
  }
  return state;
}

/**
 * One plain sentence per screenshot whose side labels moved its assets off
 * their position (e.g. a follow-up shot showing only "Team 2 gets..."), so
 * the review says why they landed where they did.
 */
export function describeAlignment(state, imageCount = 1) {
  const out = [];
  for (const note of state?.alignmentNotes || []) {
    if (note.basis !== "label") continue;
    if (note.targets.every((t, i) => t === i)) continue;
    const names = note.targets.map(
      (t) => state.sides[t]?.label || (t === 0 ? "Side A" : "Side B"),
    );
    const where =
      names.length === 1 ? names[0] : names.map((n) => `"${n}"`).join(" and ");
    const prefix =
      imageCount > 1 && Number.isInteger(note.sourceImage)
        ? `Screenshot ${note.sourceImage + 1}`
        : "This screenshot";
    out.push(
      names.length === 1
        ? `${prefix} shows only "${where}", so its assets were added to that side.`
        : `${prefix} lists its sides in the other order, so its assets were matched to ${where} by label.`,
    );
  }
  return out;
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

/** Swap Side A and Side B wholesale (labels, items, merge/alignment notes). */
export function swapReviewSides(state) {
  return {
    ...state,
    sides: [state.sides[1], state.sides[0]],
    mergeNotes: state.mergeNotes.map((n) => ({
      ...n,
      side: n.side === 0 ? 1 : 0,
    })),
    alignmentNotes: (state.alignmentNotes || []).map((n) => ({
      ...n,
      targets: n.targets.map((t) => (t === 0 ? 1 : 0)),
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
  side_alignment_unverified:
    "it shows no side labels, so its assets were placed on Side A / Side B by position — check that every asset is on the right side.",
  side_alignment_conflict:
    "its side labels don't match the other screenshots, so its assets were placed by position — check that every asset is on the right side.",
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
