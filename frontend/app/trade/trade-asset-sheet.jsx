"use client";

/**
 * trade-asset-sheet.jsx — the builder's bottom sheet on phones (TC-D2; UX
 * audit §7.3 "Add asset opens a bottom-sheet search per side").
 *
 * One search per side, in the ds Drawer re-anchored to the bottom edge (the
 * primitive's documented className override), so the phone layout carries no
 * second search bar and no sticky quick-add strip.  The sheet stays open
 * between additions -- typing on stays one tap away -- and names what each tap
 * added.  The search itself is the page's `searchAssets` (the one calculator
 * search, `searchCalculatorAssets`), rendered by the shared result list:
 * nothing here decides what a query matches or what an asset is worth.
 *
 * Loaded on demand (React.lazy in ./page.jsx): it renders only after a tap.
 */

import { useRef, useState } from "react";
import { Button, Drawer } from "@/components/ds";
import { tradeEntryLabel } from "@/lib/trade-assets";
import { SearchResultList } from "./trade-sections";
import styles from "./trade.module.css";

export function TradeAssetSheet({ side, sideIdx, searchAssets, settings, onAdd, onClose }) {
  const [query, setQuery] = useState("");
  const [added, setAdded] = useState([]);
  const inputRef = useRef(null);
  const label = side?.label || "A";
  const trimmed = query.trim();
  const results = trimmed ? searchAssets(query, sideIdx) : [];

  function pick(row) {
    onAdd(row, sideIdx);
    setAdded((prev) => [...prev, tradeEntryLabel(row)]);
    setQuery("");
    requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
  }

  return (
    <Drawer
      open
      onClose={onClose}
      title={`Add to Side ${label}`}
      className={styles.sheet}
      initialFocus={inputRef}
      closeLabel={`Close Side ${label} search`}
    >
      <div className={styles.sheetBody} data-testid="trade-asset-sheet">
        <div className="trade-side-search">
          <input
            ref={inputRef}
            className="input trade-side-search-input"
            placeholder={`Search players and picks for Side ${label}…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            inputMode="search"
            enterKeyHint="search"
            autoComplete="off"
            autoCorrect="off"
            spellCheck="false"
            aria-label={`Search to add a player to Side ${label}`}
          />
        </div>
        <p className={styles.sheetStatus} role="status">
          {added.length
            ? `Added ${added[added.length - 1]}${added.length > 1 ? ` (${added.length} this time)` : ""}.`
            : ""}
        </p>
        {trimmed ? (
          <div className={`trade-side-search-results ${styles.sheetResults}`}>
            {results.length === 0 ? (
              <div className="trade-side-search-empty muted">No matches.</div>
            ) : (
              <SearchResultList
                results={results}
                settings={settings}
                onPick={pick}
                keyPrefix={`sheet-${label}`}
                activateOn="click"
              />
            )}
          </div>
        ) : null}
        <Button variant="primary" className={styles.sheetAdd} onClick={onClose}>
          Done
        </Button>
      </div>
    </Drawer>
  );
}
