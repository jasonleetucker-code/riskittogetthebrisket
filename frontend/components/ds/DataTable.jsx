/**
 * DataTable — the table primitive. 55 hand-rolled tables migrate onto
 * this; in a market terminal the table IS the product, so this is the
 * most load-bearing component in the system.
 *
 * Column spec:
 *   {
 *     key:      string (required, unique)
 *     header:   ReactNode
 *     numeric:  boolean — right-aligns, data face, tabular-nums
 *     sortable: boolean — header becomes a real <button> with aria-sort
 *     accessor: (row) => any — value for render AND sort (default row[key])
 *     sortAccessor: (row) => any — override sort value only
 *     render:   (row, i) => ReactNode — custom cell (default accessor value)
 *     hideBelow: "sm"|"md"|"lg" — hides the column (header + body cells)
 *       below the canonical breakpoint: sm < 480px, md < 768px,
 *       lg < 1024px (media rules live in ds.css)
 *     headerInfo: node — column definition, shown in a tappable
 *       InfoTip beside the header (replaces the old `headerTitle`
 *       native tooltip, which touch and screen readers never saw)
 *     headerInfoLabel: string — override the InfoTip's accessible name
 *       when the header itself is an abbreviation
 *     firstDirection: "asc"|"desc" — override the first-activation sort
 *       direction (default: numeric → desc, text → asc)
 *     align: "center" — center-align this column (numeric wins if both)
 *   }
 *
 * Props:
 *   columns, rows                     (required)
 *   rowKey     string | (row,i)=>key  (default: row.id ?? original index)
 *              Provide a real id whenever cells render stateful content
 *              (inputs, expanded state): explicit identity is the only
 *              fully-safe key. The fallback uses each row's PRE-SORT
 *              index (stable identity map), so sorting never reattaches
 *              a key — and therefore React state — to a different row.
 *   caption    string — REQUIRED for a11y; visually hidden table summary
 *   density    "regular" | "compact"
 *   defaultSort {key, direction:"asc"|"desc"} — uncontrolled initial sort
 *   sort/onSortChange — controlled mode ({key,direction} | null)
 *   onRowClick (row)=>void — rows become keyboard-interactive
 *   maxHeight  CSS length — scrolling body with sticky header
 *   emptyState ReactNode — rendered instead of the table when rows empty
 *   presorted  boolean — trust the caller's row order (complex external
 *              sort pipelines, e.g. the rankings lens system). Headers
 *              still cycle direction + stamp aria-sort via
 *              sort/onSortChange; DataTable just skips its own sortRows.
 *   rowClassName (row,i)=>string — extra classes per body row
 *   renderBeforeRow (row,i)=>node — caller-authored <tr>(s) rendered
 *              BEFORE the row (tier/group separators). Not interactive.
 *   renderAfterRow (row,i)=>node — caller-authored <tr>(s) rendered
 *              AFTER the row (expansion panels). Not interactive.
 *
 * Behavior:
 *   - First activation sorts numeric columns DESC (terminal convention:
 *     biggest number first), text columns ASC; activation again flips.
 *   - aria-sort is stamped on the active <th>; direction changes are
 *     announced via a polite live region.
 *   - Sort is stable; null/undefined always sink to the bottom.
 *   - Sticky header + horizontal scroll wrapper are built in — a bare
 *     unwrapped <table> can no longer happen.
 *   - Row activation ignores events that originate inside interactive
 *     cell content (links, buttons, inputs, role=button/link,
 *     contenteditable) — cell renderers never need stopPropagation.
 */
"use client";

import React, {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Icon } from "./Icon";
import { InfoTip } from "./Help";

// useLayoutEffect warns during SSR; the freeze pass is a post-paint
// measurement that has no server equivalent, so fall back to a no-op.
const useIsomorphicLayoutEffect =
  typeof window === "undefined" ? () => {} : useLayoutEffect;

function defaultRowKey(row, index) {
  return row?.id ?? index;
}

/**
 * True when an event originated inside an interactive descendant of the
 * row (link, button, form control, custom widget). Cell renderers are part
 * of the column API — a Movement link or an inline input must not need
 * stopPropagation to avoid also activating the row.
 */
const INTERACTIVE_SELECTOR =
  'a,button,input,select,textarea,[role="button"],[role="link"],[contenteditable]';

/** Shared th/td class for a column: alignment + responsive hide. */
function cellClass(col) {
  return (
    [
      col.numeric ? "ds-table__cell--num" : "",
      !col.numeric && col.align === "center" ? "ds-table__cell--center" : "",
      col.hideBelow ? `ds-col-hide-${col.hideBelow}` : "",
    ]
      .filter(Boolean)
      .join(" ") || undefined
  );
}

function fromInteractiveDescendant(event) {
  const target = event.target;
  if (!target || typeof target.closest !== "function") return false;
  const hit = target.closest(INTERACTIVE_SELECTOR);
  return Boolean(
    hit && hit !== event.currentTarget && event.currentTarget.contains(hit)
  );
}

function compareValues(a, b) {
  const aNull = a == null || a === "";
  const bNull = b == null || b === "";
  if (aNull && bNull) return 0;
  if (aNull) return 1; // nulls sink regardless of direction sign handling
  if (bNull) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, {
    numeric: true,
    sensitivity: "base",
  });
}

export function sortRows(rows, columns, sort) {
  if (!sort) return rows;
  const col = columns.find((c) => c.key === sort.key);
  if (!col) return rows;
  const acc = col.sortAccessor || col.accessor || ((row) => row?.[col.key]);
  const sign = sort.direction === "desc" ? -1 : 1;
  return rows
    .map((row, i) => ({ row, i }))
    .sort((x, y) => {
      const a = acc(x.row);
      const b = acc(y.row);
      const aNull = a == null || a === "";
      const bNull = b == null || b === "";
      // nulls last in BOTH directions
      if (aNull || bNull) return compareValues(a, b) || x.i - y.i;
      return sign * compareValues(a, b) || x.i - y.i;
    })
    .map(({ row }) => row);
}

export function DataTable({
  columns,
  rows,
  rowKey = defaultRowKey,
  caption,
  density = "regular",
  defaultSort = null,
  sort: controlledSort,
  onSortChange,
  onRowClick,
  maxHeight,
  emptyState = null,
  className = "",
  presorted = false,
  rowClassName = null,
  renderBeforeRow = null,
  renderAfterRow = null,
  freezeColumnWidths = false,
}) {
  const [internalSort, setInternalSort] = useState(defaultSort);
  const sort = controlledSort !== undefined ? controlledSort : internalSort;

  const setSort = useCallback(
    (next) => {
      if (controlledSort === undefined) setInternalSort(next);
      onSortChange?.(next);
    },
    [controlledSort, onSortChange]
  );

  const handleSortClick = useCallback(
    (col) => {
      const first = col.firstDirection || (col.numeric ? "desc" : "asc");
      if (!sort || sort.key !== col.key) {
        setSort({ key: col.key, direction: first });
      } else {
        setSort({
          key: col.key,
          direction: sort.direction === "asc" ? "desc" : "asc",
        });
      }
    },
    [sort, setSort]
  );

  const sorted = useMemo(
    () => (presorted ? rows : sortRows(rows, columns, sort)),
    [rows, columns, sort, presorted]
  );

  // Pre-sort identity: each row's ORIGINAL index, computed once per rows
  // array. Fallback keys must never use the post-sort position, or a sort
  // would reattach keys (and any React state inside cells) to whichever
  // row happens to land at that position.
  const originalIndex = useMemo(() => {
    const map = new Map();
    rows?.forEach((row, i) => {
      if (!map.has(row)) map.set(row, i);
    });
    return map;
  }, [rows]);

  const getKey =
    typeof rowKey === "string" ? (row, i) => row?.[rowKey] ?? i : rowKey;

  // ── Column-width freeze (opt-in via `freezeColumnWidths`) ──────────
  //
  // A prerequisite for row virtualization, not a cosmetic option. Under
  // `table-layout: auto` a column is as wide as its widest CELL, so
  // rendering only a window of rows would let widths change as the user
  // scrolls. `table-layout: fixed` fixes that, but naively flipping it
  // is wrong here: this table is content-sized and horizontally
  // scrollable on narrow viewports (measured 604px inside a 376px wrap
  // at 390px), and `fixed` with no min-width would squeeze it to the
  // wrapper instead.
  //
  // So rather than hand-authoring widths per breakpoint — which the
  // `hideBelow` columns would make a maintenance trap, since the
  // visible set and therefore the correct min-width change per
  // breakpoint — we MEASURE the widths the browser already settled on
  // and then freeze exactly those. The frozen table is by construction
  // the same geometry the user sees today, at whatever breakpoint they
  // are at, and re-measures when the viewport changes.
  const tableRef = useRef(null);
  const [frozen, setFrozen] = useState(null);

  const measure = useCallback(() => {
    const table = tableRef.current;
    if (!table) return;
    const ths = Array.from(table.querySelectorAll("thead th"));
    if (ths.length === 0) return;
    // Measure with the freeze OFF, so we read the browser's own
    // content-driven answer rather than the widths we last imposed.
    const widths = ths.map((th) => {
      // A `hideBelow` column is display:none at this breakpoint. It has
      // no width to freeze and must not get one, or its <col> would
      // reserve space for a column nobody can see.
      if (th.offsetParent === null && th.getClientRects().length === 0) {
        return null;
      }
      return Math.round(th.getBoundingClientRect().width * 100) / 100;
    });
    const total = widths.reduce((sum, w) => sum + (w || 0), 0);
    if (total <= 0) return;
    setFrozen((prev) => {
      if (
        prev &&
        prev.total === total &&
        prev.widths.length === widths.length &&
        prev.widths.every((w, i) => w === widths[i])
      ) {
        return prev; // identical — don't churn a re-render
      }
      return { widths, total };
    });
  }, []);

  // Measure after paint, with the freeze removed for that one frame, so
  // the numbers come from the auto-layout pass. `frozen` is cleared
  // first on a resize (below) for the same reason.
  //
  // Deliberately NO dependency array. The obvious version — deps on
  // [freezeColumnWidths, frozen, columns] — silently fails whenever the
  // first render has no rows yet: the component returns `emptyState`, so
  // there is no <table> to measure, `measure()` bails on the null ref,
  // and when the rows finally arrive none of those deps has changed, so
  // the effect never runs again and the table stays on auto layout
  // forever. Running every render costs one `if` once frozen, and
  // `measure()` is idempotent — it self-terminates on the guard below.
  useIsomorphicLayoutEffect(() => {
    if (!freezeColumnWidths) return;
    if (frozen) return;
    measure();
  });

  // Re-measure on viewport change: a breakpoint crossing changes which
  // columns are visible, so both the widths AND the correct min-width
  // change. Clearing `frozen` drops back to auto layout for one frame,
  // which is what makes the next measurement honest.
  useEffect(() => {
    if (!freezeColumnWidths) return undefined;
    const table = tableRef.current;
    if (!table || typeof ResizeObserver === "undefined") return undefined;
    const target = table.parentElement || table;
    // Only react to a real WIDTH change. Freezing the table sets a
    // min-width, which changes the wrapper's scrollWidth — observing
    // size unconditionally would fire on our own change, clear the
    // freeze, re-measure, re-freeze, forever.
    let lastWidth = Math.round(target.getBoundingClientRect().width);
    let raf = 0;
    const ro = new ResizeObserver(() => {
      const width = Math.round(target.getBoundingClientRect().width);
      if (width === lastWidth) return;
      lastWidth = width;
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => setFrozen(null));
    });
    ro.observe(target);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [freezeColumnWidths]);

  // Columns changing (the board's source toggles add/remove columns)
  // invalidates the measurement for the same reason a resize does.
  //
  // The ref guard is load-bearing, not defensive: an unguarded effect
  // fires on MOUNT too, in the same commit where the layout effect above
  // has just set `frozen`. Passive effects run after layout effects, so
  // it clears the freeze, `frozen` ends the commit back at null, the
  // layout effect's deps are therefore unchanged on the next render, and
  // it never measures again. The table silently stayed on auto layout.
  const columnKeys = columns.map((c) => c.key).join("|");
  const lastColumnKeys = useRef(columnKeys);
  useEffect(() => {
    if (!freezeColumnWidths) return;
    if (lastColumnKeys.current === columnKeys) return;
    lastColumnKeys.current = columnKeys;
    setFrozen(null);
  }, [freezeColumnWidths, columnKeys]);

  if (!rows || rows.length === 0) return emptyState;

  const activeCol = sort ? columns.find((c) => c.key === sort.key) : null;

  return (
    <div
      className="ds-table-wrap"
      style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}
    >
      <table
        ref={tableRef}
        className={[
          "ds-table",
          density === "compact" ? "ds-table--compact" : "",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
        style={
          frozen
            ? {
                tableLayout: "fixed",
                // The measured total, so a content-sized horizontally
                // scrollable table keeps its width instead of being
                // squeezed into the wrapper by `fixed`.
                width: frozen.total,
                minWidth: frozen.total,
              }
            : undefined
        }
      >
        {caption ? (
          <caption className="ds-visually-hidden">{caption}</caption>
        ) : null}
        {frozen ? (
          // Only the VISIBLE columns get a <col>, and this is the whole
          // subtlety of the feature. `hideBelow` hides a column with
          // `display: none`, which removes it from the table's column
          // count in the fixed-layout algorithm — but <col> elements map
          // to columns by POSITION. Emitting a placeholder <col> for a
          // hidden column therefore shifted every width after it onto
          // the wrong column: at 390px the player name collapsed to 0
          // and the position column inherited its 296px.
          <colgroup>
            {frozen.widths.map((w, i) =>
              w == null ? null : (
                <col key={columns[i]?.key ?? i} style={{ width: w }} />
              ),
            )}
          </colgroup>
        ) : null}
        <thead>
          <tr>
            {columns.map((col) => {
              const isSorted = sort?.key === col.key;
              const ariaSort = isSorted
                ? sort.direction === "asc"
                  ? "ascending"
                  : "descending"
                : undefined;
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={cellClass(col)}
                  style={col.width ? { width: col.width } : undefined}
                >
                  {col.sortable ? (
                    <button
                      type="button"
                      className="ds-table__sort"
                      onClick={() => handleSortClick(col)}
                    >
                      <span>{col.header}</span>
                      <Icon
                        name="chevron-down"
                        size={8}
                        className="ds-table__sort-glyph"
                      />
                    </button>
                  ) : (
                    col.header
                  )}
                  {/* A column whose meaning needs explaining gets a
                      tappable InfoTip, not a native `title`.  These
                      definitions ("what is depth-adjusted spread?") are
                      the whole reason a column is legible, and a native
                      tooltip shows on neither touch nor a screen
                      reader — so on a phone the header was a two-word
                      abbreviation with no way to find out what it
                      meant. */}
                  {col.headerInfo ? (
                    <InfoTip label={col.headerInfoLabel || String(col.header)}>
                      {col.headerInfo}
                    </InfoTip>
                  ) : null}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const interactive = typeof onRowClick === "function";
            const stableIndex = originalIndex.get(row) ?? i;
            const extraClass = rowClassName ? rowClassName(row, i) : "";
            return (
              <Fragment key={getKey(row, stableIndex)}>
              {renderBeforeRow ? renderBeforeRow(row, i) : null}
              <tr
                className={
                  [interactive ? "ds-table__row--interactive" : "", extraClass]
                    .filter(Boolean)
                    .join(" ") || undefined
                }
                tabIndex={interactive ? 0 : undefined}
                onClick={
                  interactive
                    ? (e) => {
                        if (fromInteractiveDescendant(e)) return;
                        onRowClick(row);
                      }
                    : undefined
                }
                onKeyDown={
                  interactive
                    ? (e) => {
                        if (fromInteractiveDescendant(e)) return;
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick(row);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((col) => {
                  const acc = col.accessor || ((r) => r?.[col.key]);
                  return (
                    // ``data-col`` makes a cell addressable by its COLUMN
                    // KEY rather than by ordinal.  Several column sets here
                    // are built conditionally (the rankings board adds a
                    // Fund-gap column only while BDVM serves an ok payload,
                    // for one), so an ``nth-child`` selector in a test is
                    // correct until the day a column appears in front of
                    // it and then silently asserts the wrong column.
                    <td key={col.key} data-col={col.key} className={cellClass(col)}>
                      {col.render ? col.render(row, i) : acc(row)}
                    </td>
                  );
                })}
              </tr>
              {renderAfterRow ? renderAfterRow(row, i) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {/* polite announcement of sort changes for screen readers */}
      <span className="ds-visually-hidden" aria-live="polite">
        {activeCol
          ? `Sorted by ${typeof activeCol.header === "string" ? activeCol.header : activeCol.key}, ${
              sort.direction === "asc" ? "ascending" : "descending"
            }`
          : ""}
      </span>
    </div>
  );
}
