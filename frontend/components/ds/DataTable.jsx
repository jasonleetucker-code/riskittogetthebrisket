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
 *     hideBelow: "sm"|"md"|"lg" — responsive priority (R1 wiring; class only)
 *   }
 *
 * Props:
 *   columns, rows                     (required)
 *   rowKey     string | (row,i)=>key  (default: row.id ?? index)
 *   caption    string — REQUIRED for a11y; visually hidden table summary
 *   density    "regular" | "compact"
 *   defaultSort {key, direction:"asc"|"desc"} — uncontrolled initial sort
 *   sort/onSortChange — controlled mode ({key,direction} | null)
 *   onRowClick (row)=>void — rows become keyboard-interactive
 *   maxHeight  CSS length — scrolling body with sticky header
 *   emptyState ReactNode — rendered instead of the table when rows empty
 *
 * Behavior:
 *   - First activation sorts numeric columns DESC (terminal convention:
 *     biggest number first), text columns ASC; activation again flips.
 *   - aria-sort is stamped on the active <th>; direction changes are
 *     announced via a polite live region.
 *   - Sort is stable; null/undefined always sink to the bottom.
 *   - Sticky header + horizontal scroll wrapper are built in — a bare
 *     unwrapped <table> can no longer happen.
 */
"use client";

import React, { useCallback, useMemo, useState } from "react";
import { Icon } from "./Icon";

function defaultRowKey(row, index) {
  return row?.id ?? index;
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
      const first = col.numeric ? "desc" : "asc";
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

  const sorted = useMemo(() => sortRows(rows, columns, sort), [rows, columns, sort]);

  const getKey = typeof rowKey === "string" ? (row, i) => row?.[rowKey] ?? i : rowKey;

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
                  className={col.numeric ? "ds-table__cell--num" : undefined}
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
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row, i) => {
            const interactive = typeof onRowClick === "function";
            return (
              <tr
                key={getKey(row, i)}
                className={interactive ? "ds-table__row--interactive" : undefined}
                tabIndex={interactive ? 0 : undefined}
                onClick={interactive ? () => onRowClick(row) : undefined}
                onKeyDown={
                  interactive
                    ? (e) => {
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
                    <td
                      key={col.key}
                      className={col.numeric ? "ds-table__cell--num" : undefined}
                    >
                      {col.render ? col.render(row, i) : acc(row)}
                    </td>
                  );
                })}
              </tr>
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
