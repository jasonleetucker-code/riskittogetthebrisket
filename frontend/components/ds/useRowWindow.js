/**
 * Row windowing for `DataTable` — mount only the rows near the viewport.
 *
 * WHY THE TABLE AND NOT CSS
 * ─────────────────────────
 * Every cheap intervention was ablated on the live board first (#760,
 * `docs/performance-optimization.md`), each with `!important` overrides and
 * the baseline re-measured either side so drift stayed visible:
 *
 *     suspect removed                              1x FPS
 *     baseline                                     26.5 / 22.8
 *     `position: sticky` (name cell, thead, all)   20.6 – 22.4
 *     `table-layout: fixed`                        24.2
 *     `content-visibility: auto` on rows           22.7
 *     `contain: layout paint style` on rows        23.4
 *     `visibility: hidden` rows 61+  (skips PAINT) 29.5
 *     `display: none`    rows 61+  (skips LAYOUT)  59.5
 *
 * The last two rows are the finding: skipping *paint* for 900 rows buys ~3
 * FPS, skipping *layout* buys 33. **No containment property reaches table
 * internals** — the spec excludes `table-row` / `table-row-group` from size
 * containment, which is why `content-visibility` and `contain` did nothing.
 * That closes "can CSS avoid virtualization here" with a measured no.
 *
 * WHY NOT `components/ui/VirtualList.jsx`
 * ──────────────────────────────────────
 * Its own docstring says div rows. This is a real `<table>`, and a `<div>`
 * cannot sit between `<tbody>` and `<tr>`.
 *
 * THE PREREQUISITE, AND WHY IT IS NOT OPTIONAL
 * ────────────────────────────────────────────
 * Under `table-layout: auto` a column is as wide as its widest CELL, so a
 * window would let columns resize as the user scrolls into a longer name.
 * `DataTable`'s `freezeColumnWidths` measures the widths the browser
 * already settled on and pins them with a `<colgroup>`. Windowing without
 * it is not "slightly jumpy", it is a table that reflows every frame — so
 * `DataTable` refuses to virtualize unless it is on.
 *
 * HEIGHTS ARE MEASURED, NOT ASSUMED
 * ─────────────────────────────────
 * The obvious shortcut — one constant row height — is wrong here in a way
 * that would be blamed on windowing rather than on the shortcut. The
 * rankings board injects two kinds of non-uniform row through
 * `renderBeforeRow` / `renderAfterRow`: tier separators (sparse, short) and
 * the expanded source-audit drawer (one at a time, tall). A uniform model
 * puts the spacer below them off by the difference, and the board jumps
 * under the user's cursor at exactly the moment they clicked something.
 *
 * Measuring those directly is not possible from here: they are
 * caller-authored `<tr>`s and this hook never owns them. So heights are
 * derived from GEOMETRY instead, which needs one ref per row and no
 * cooperation from the caller:
 *
 *   * every mounted row reports its `offsetTop`;
 *   * the distance between two consecutively-mounted rows is that row's
 *     whole BLOCK — its own height plus whatever the caller injected
 *     between them, measured rather than modelled;
 *   * which indices carry a before/after row is known separately, by
 *     CALLING the caller's render functions and checking for null (they
 *     are pure and return elements without mounting them). Splitting the
 *     observed block deltas by that classification yields a median plain
 *     row, a median tier separator and a median expansion — each learned
 *     from real pixels.
 *
 * An index never yet mounted contributes the median for its own
 * classification. The declared constants below are a bootstrap used only
 * until the first measurement of a kind exists; scrolling makes the map
 * strictly more accurate and it never regresses.
 *
 * MISSING IS NOT ZERO, HERE EITHER
 * ────────────────────────────────
 * An unmeasured index contributes the median of its kind, never 0. A zero
 * would collapse the spacer and let the browser settle the scroll position
 * somewhere it was never asked to go.
 */
"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/**
 * Rows to mount beyond each edge of the viewport.
 *
 * Not a tuning knob so much as the seam between "the user can flick" and
 * "the user sees blank". At 2400 px/s (the gesture the FPS harness drives)
 * and ~34 px rows, eight rows is ~110 ms of runway, and one commit at the
 * measured cost is well inside that.
 */
const DEFAULT_OVERSCAN = 8;

/** Bootstrap heights, in px, used only until something has been measured. */
const FALLBACK_HEIGHTS = { row: 34, before: 28, after: 320 };

/**
 * Cap on retained deltas per class.
 *
 * The medians want enough samples to shrug off a row that happened to
 * wrap, and nothing beyond that. A session that scrolls the whole board
 * repeatedly would otherwise grow these arrays without bound.
 */
const MAX_SAMPLES = 256;

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

/** Index of the last offset <= target. Offsets are ascending. */
function lastIndexAtOrBefore(offsets, target) {
  let lo = 0;
  let hi = offsets.length - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    if (offsets[mid] <= target) {
      best = mid;
      lo = mid + 1;
    } else {
      hi = mid - 1;
    }
  }
  return best;
}

/**
 * @param {object} opts
 * @param {number}  opts.rowCount
 * @param {boolean} opts.enabled          windowing is on
 * @param {object}  opts.tableRef         ref to the <table>
 * @param {object}  opts.scrollRef        ref to the scroll container, or null for the window
 * @param {(i:number)=>boolean} opts.hasBefore
 * @param {(i:number)=>boolean} opts.hasAfter
 * @returns {{start:number, end:number, padTop:number, padBottom:number,
 *            windowed:boolean, measure:(index:number,el:Element|null)=>void}}
 */
export function useRowWindow({
  rowCount,
  enabled,
  tableRef,
  scrollRef = null,
  hasBefore,
  hasAfter,
  overscan = DEFAULT_OVERSCAN,
}) {
  // ── Measurement buffers ───────────────────────────────────────────
  //
  // `burst` holds the `offsetTop` of every row mounted in ONE layout. It
  // is drained and cleared on the next animation frame, which is what
  // keeps it single-layout: an `offsetTop` is only comparable with
  // another taken while the same spacer heights were in place, and the
  // spacers change every time the window moves. Deltas within a burst are
  // safe (both rows shift by the same spacer amount); deltas ACROSS
  // bursts are not, and mixing them would corrupt the map with a number
  // that looks like a very tall row.
  const burst = useRef(new Map());
  // Drained deltas, classified. These accumulate: a height learned at the
  // top of the board is still true at the bottom, so the map only ever
  // gets better.
  const samples = useRef({ plain: [], before: [], after: [] });
  const [measureEpoch, setMeasureEpoch] = useState(0);
  const drainPending = useRef(false);

  // ── The window itself ─────────────────────────────────────────────
  //
  // State, and it changes RARELY. That is the point.
  //
  // The obvious shape — keep the scroll offset in state and derive the
  // range during render — re-renders the table on every scroll frame,
  // and at 2400 px/s that is ~60 renders per second of 39 rows x ~30
  // cells, each running the caller's `render` functions. Measured on the
  // live board it capped the whole feature at 33 FPS: the DOM was 95%
  // smaller and React was doing the work instead.
  //
  // So the scroll offset lives in a ref, the range is computed inside the
  // scroll handler, and `setRange` is called ONLY when the slice actually
  // moves — which, with `overscan` rows of runway either side, is once
  // every several hundred pixels rather than once per frame.
  const [range, setRange] = useState({ start: 0, end: 0, padTop: 0, padBottom: 0 });
  const viewportRef = useRef({ top: 0, height: 0 });
  const geometryRef = useRef(null);
  const rangeRef = useRef(range);
  rangeRef.current = range;

  const blockKinds = useMemo(() => {
    if (!enabled) return null;
    const before = new Uint8Array(rowCount);
    const after = new Uint8Array(rowCount);
    for (let i = 0; i < rowCount; i += 1) {
      before[i] = hasBefore(i) ? 1 : 0;
      after[i] = hasAfter(i) ? 1 : 0;
    }
    return { before, after };
  }, [enabled, rowCount, hasBefore, hasAfter]);
  const blockKindsRef = useRef(blockKinds);
  blockKindsRef.current = blockKinds;

  const geometry = useMemo(() => {
    if (!enabled || !blockKinds) return null;

    const plainH = median(samples.current.plain) ?? FALLBACK_HEIGHTS.row;
    // Extras are the EXCESS over a plain row, because the delta that
    // taught us about them also contained a plain row. Clamped at 0: a
    // negative would mean the sample was noise, and letting it shrink
    // the map would put the spacer above content that exists.
    const beforeMedian = median(samples.current.before);
    const afterMedian = median(samples.current.after);
    const beforeH =
      beforeMedian != null
        ? Math.max(0, beforeMedian - plainH)
        : FALLBACK_HEIGHTS.before;
    const afterH =
      afterMedian != null
        ? Math.max(0, afterMedian - plainH)
        : FALLBACK_HEIGHTS.after;

    // offsets[i] = distance from the first row's top to block i's top.
    // One extra entry so offsets[rowCount] is the total height.
    const offsets = new Float64Array(rowCount + 1);
    for (let i = 0; i < rowCount; i += 1) {
      let h = plainH;
      if (blockKinds.before[i]) h += beforeH;
      if (blockKinds.after[i]) h += afterH;
      offsets[i + 1] = offsets[i] + h;
    }
    return { offsets, total: offsets[rowCount] };
    // `samples.current` is deliberately absent from the deps — it is a
    // ref, so mutating it cannot trigger anything. `measureEpoch` is the
    // republish signal, and it ticks at most once per frame.
  }, [enabled, blockKinds, rowCount, measureEpoch]);
  geometryRef.current = geometry;

  /** Recompute the slice from the current scroll offset; commit only if it moved. */
  const syncRange = useCallback(() => {
    const geo = geometryRef.current;
    if (!geo || rowCount === 0) return;
    const { offsets, total } = geo;
    const { top, height } = viewportRef.current;
    const first = lastIndexAtOrBefore(offsets, Math.max(0, top));
    const last = lastIndexAtOrBefore(offsets, Math.max(0, top) + Math.max(0, height));
    const start = Math.max(0, first - overscan);
    const end = Math.min(rowCount, last + overscan + 1);
    const prev = rangeRef.current;
    if (prev.start === start && prev.end === end) return;
    setRange({
      start,
      end,
      padTop: offsets[start],
      padBottom: Math.max(0, total - offsets[end]),
    });
  }, [rowCount, overscan]);

  /** Record a mounted row's offset. Called from each row's ref. */
  const measure = useCallback((index, el) => {
    // Unmounting is not a measurement going away — the height it taught
    // us is still true of the layout, and it lives in `samples`.
    if (!el) return;
    burst.current.set(index, el.offsetTop);
    if (drainPending.current) return;
    drainPending.current = true;
    requestAnimationFrame(() => {
      drainPending.current = false;
      const kinds = blockKindsRef.current;
      const entries = burst.current;
      burst.current = new Map();
      if (!kinds || entries.size < 2) return;

      const seen = [...entries.keys()].sort((a, b) => a - b);
      let added = false;
      for (let k = 0; k + 1 < seen.length; k += 1) {
        const i = seen[k];
        // Only CONSECUTIVE indices give a usable delta: with a gap
        // between them the distance spans rows nobody measured.
        if (seen[k + 1] !== i + 1) continue;
        const delta = entries.get(i + 1) - entries.get(i);
        if (!(delta > 0)) continue;
        // The delta covers row i plus everything rendered before row
        // i+1 — so it is classified by i's own after-row and i+1's
        // before-row. Deltas carrying BOTH are discarded rather than
        // guessed apart; they are rare (one expansion at a time) and a
        // wrong split would poison two medians instead of none.
        const hasB = kinds.before[i + 1] === 1;
        const hasA = kinds.after[i] === 1;
        if (hasB && hasA) continue;
        const bucket = hasB ? "before" : hasA ? "after" : "plain";
        const arr = samples.current[bucket];
        arr.push(delta);
        // Bounded so a long session cannot grow these without limit.
        if (arr.length > MAX_SAMPLES) arr.shift();
        added = true;
      }
      if (added) setMeasureEpoch((n) => n + 1);
    });
  }, []);

  // Track scroll position of whichever element actually scrolls. The
  // rankings board scrolls the WINDOW (the table has no maxHeight), so a
  // listener bound to the wrapper would never fire and the window would
  // stay frozen at the top — rendering 40 rows and nothing else, which
  // looks exactly like a broken board rather than a broken listener.
  useEffect(() => {
    if (!enabled) return undefined;
    const scroller = scrollRef?.current || null;
    let frame = 0;
    const read = () => {
      frame = 0;
      const table = tableRef.current;
      if (!table) return;
      if (scroller) {
        viewportRef.current = {
          top: scroller.scrollTop,
          height: scroller.clientHeight,
        };
      } else {
        // Window scrolling: express the viewport in the table's own
        // coordinate space, so the arithmetic is identical either way.
        const rect = table.getBoundingClientRect();
        viewportRef.current = { top: -rect.top, height: window.innerHeight };
      }
      syncRange();
    };
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(read);
    };
    read();
    const target = scroller || window;
    target.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll, { passive: true });
    return () => {
      if (frame) cancelAnimationFrame(frame);
      target.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
    };
  }, [enabled, scrollRef, tableRef, syncRange]);

  // A new geometry (rows changed, heights learned) can invalidate the
  // slice without the user scrolling at all — a filter that shortens the
  // board, or the first real height measurement replacing the bootstrap.
  useEffect(() => {
    if (enabled) syncRange();
  }, [enabled, geometry, syncRange]);

  if (!enabled || !geometry || rowCount === 0) {
    return {
      start: 0,
      end: rowCount,
      padTop: 0,
      padBottom: 0,
      measure,
      windowed: false,
    };
  }

  // `end === 0` only before the first `syncRange` has run. Rendering an
  // empty body there would flash a blank board on the commit that turns
  // windowing on, so fall back to a viewport's worth of rows.
  if (range.end === 0) {
    const seed = Math.min(rowCount, overscan * 4);
    return {
      start: 0,
      end: seed,
      padTop: 0,
      padBottom: Math.max(0, geometry.total - geometry.offsets[seed]),
      measure,
      windowed: true,
    };
  }

  return { ...range, measure, windowed: true };
}
