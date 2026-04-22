"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { resolvedRank } from "@/lib/dynasty-data";

/**
 * Global search overlay — keyboard-first player/pick finder.
 * Triggered by "/" shortcut or search icon in nav.
 *
 * Props:
 *   rows       — All player rows from buildRows()
 *   isOpen     — Whether the search overlay is visible
 *   onClose    — Callback to close
 *   onSelect   — Callback when a player is selected: (row) => void
 */
export default function GlobalSearch({ rows = [], isOpen, onClose, onSelect }) {
  const [query, setQuery] = useState("");
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);
  const listRef = useRef(null);

  // Focus input when opening
  useEffect(() => {
    if (isOpen) {
      setQuery("");
      setSelectedIdx(0);
      // Small delay to ensure overlay is rendered
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [isOpen]);

  // Filter results
  const results = query.trim().length > 0
    ? rows
        .filter((r) => r.name.toLowerCase().includes(query.trim().toLowerCase()))
        .slice(0, 30)
    : [];

  // Keyboard navigation
  const onKeyDown = useCallback(
    (e) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose?.();
        return;
      }
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.min(prev + 1, results.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIdx((prev) => Math.max(prev - 1, 0));
        return;
      }
      if (e.key === "Enter" && results[selectedIdx]) {
        e.preventDefault();
        onSelect?.(results[selectedIdx]);
        onClose?.();
      }
    },
    [results, selectedIdx, onClose, onSelect],
  );

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.children[selectedIdx];
    el?.scrollIntoView?.({ block: "nearest" });
  }, [selectedIdx]);

  // Reset selection when query changes
  useEffect(() => { setSelectedIdx(0); }, [query]);

  if (!isOpen) return null;

  return (
    <div className="picker-overlay" onClick={onClose} style={{ zIndex: 1200 }}>
      <div
        className="picker-sheet"
        onClick={(e) => e.stopPropagation()}
        style={{ maxWidth: 500, width: "92vw", maxHeight: "70dvh", display: "flex", flexDirection: "column" }}
      >
        <div className="global-search-input-row">
          <span
            style={{ fontSize: "1.1rem", opacity: 0.4 }}
            aria-hidden="true"
          >
            /
          </span>
          <input
            ref={inputRef}
            className="input global-search-input"
            type="text"
            placeholder="Search players and picks..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            autoComplete="off"
            aria-label="Search players and picks"
          />
          <button
            className="button global-search-close"
            onClick={onClose}
            aria-label="Close search"
            title="Close search (ESC)"
          >
            ESC
          </button>
        </div>

        {query.trim().length > 0 && (
          <div ref={listRef} style={{ marginTop: 10, overflow: "auto", flex: 1 }}>
            {results.length === 0 && (
              <div className="muted" style={{ padding: "12px 0", textAlign: "center" }}>
                No results for &ldquo;{query}&rdquo;
              </div>
            )}
            {results.map((r, i) => {
              const rank = resolvedRank(r);
              const isSelected = i === selectedIdx;
              return (
                <button
                  key={r.name}
                  className="asset-row button-reset"
                  onClick={() => { onSelect?.(r); onClose?.(); }}
                  style={{
                    width: "100%", textAlign: "left", cursor: "pointer",
                    background: isSelected ? "rgba(255, 199, 4,0.08)" : undefined,
                    borderLeft: isSelected ? "2px solid var(--cyan)" : "2px solid transparent",
                    paddingLeft: 8,
                  }}
                  onMouseEnter={() => setSelectedIdx(i)}
                >
                  <div style={{ flex: 1 }}>
                    <div className="asset-name">{r.name}</div>
                    <div className="asset-meta">
                      {r.pos}
                      {r.raw?.team ? ` · ${r.raw.team}` : ""}
                      {rank < Infinity ? ` · #${rank}` : ""}
                    </div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div style={{ fontWeight: 600, fontSize: "0.82rem" }}>{Math.round(r.values?.full || 0).toLocaleString()}</div>
                    {r.siteCount > 0 && (
                      <div className="muted" style={{ fontSize: "0.66rem" }}>{r.siteCount} sources</div>
                    )}
                  </div>
                </button>
              );
            })}
          </div>
        )}

        {query.trim().length === 0 && (
          <div className="muted" style={{ padding: "16px 0", textAlign: "center", fontSize: "0.78rem" }}>
            Start typing to search players and picks.
            <br />
            <span style={{ fontSize: "0.7rem" }}>
              Use <kbd style={{ padding: "1px 4px", border: "1px solid var(--border)", borderRadius: 3 }}>&uarr;</kbd>{" "}
              <kbd style={{ padding: "1px 4px", border: "1px solid var(--border)", borderRadius: 3 }}>&darr;</kbd> to navigate,{" "}
              <kbd style={{ padding: "1px 4px", border: "1px solid var(--border)", borderRadius: 3 }}>Enter</kbd> to select
            </span>
          </div>
        )}
      </div>
    </div>
  );
}
