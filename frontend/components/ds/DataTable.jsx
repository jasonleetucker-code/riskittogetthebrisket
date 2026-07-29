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

import React, { Fragment, useCallback, useMemo, useState } from "react";
import { Icon } from "./Icon";
import { InfoTip } from "./Help";

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

  if (!rows || rows.length === 0) return emptyState;

  const activeCol = sort ? columns.find((c) => c.key === sort.key) : null;

  return (
    <div
      className="ds-table-wrap"
      style={maxHeight ? { maxHeight, overflowY: "auto" } : undefined}
    >
      <table
        className={[
          "ds-table",
          density === "compact" ? "ds-table--compact" : "",
          className,
        ]
          .filter(Boolean)
          .join(" ")}
      >
        {caption ? (
          <caption className="ds-visually-hidden">{caption}</caption>
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
                    <td key={col.key} className={cellClass(col)}>
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
