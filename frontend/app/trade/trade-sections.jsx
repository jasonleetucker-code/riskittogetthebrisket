"use client";

/**
 * trade-sections.jsx — presentational sections of the trade terminal.
 *
 * Extracted from app/trade/page.jsx in R4 so the page file holds state
 * and orchestration while these render it.  Every component here is
 * pure presentation: it receives already-computed values and handlers.
 *
 * NO trade math lives in this file.  Totals, gaps, adjustments, stack
 * effects and simulation results all arrive as props from lib/trade-logic
 * or the /api/trade/* responses.
 *
 * Sections that only render AFTER an interaction, or below the fold, live
 * in their own modules so the /trade page loads them on demand
 * (React.lazy in app/trade/page.jsx — see the note there):
 * ./trade-simulation-panel.jsx (Simulate impact result),
 * ./trade-ktc-import.jsx (Import KTC) and ./trade-suggestions-desk.jsx
 * (Trade suggestions).  Do not re-export them from here — a static
 * re-export puts them straight back into the page chunk.
 */

import { useEffect, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  Field,
  Icon,
  Panel,
  PlayerNameButton,
  Select,
  SkeletonText,
  canonicalPlayerId,
} from "@/components/ds";
import { PlayerImage } from "@/components/ui";
import {
  defaultDestination,
  effectiveValue,
  formatBoardValue,
  isUnpricedBoardRow,
  unpricedAssetsOnSide,
  getPlayerEdge,
} from "@/lib/trade-logic";
import {
  formatAssetAge,
  groupSideEntries,
  groupTradeSearchResults,
  packageCompositionText,
  tradeEntryKey,
  tradeEntryLabel,
} from "@/lib/trade-assets";
import { derivedPickDisclosure } from "@/lib/pick-provenance";
import { ValueAdjustmentTip } from "@/components/help/TradeHelp";
import { draftCapitalBudgetsUnavailableText } from "@/lib/draft-capital-budgets";
import styles from "./trade.module.css";

// ── Shared bits ───────────────────────────────────────────────────────

export const SUGGESTION_RAIL_LABELS = {
  // Hints describe what the generators in src/trade/suggestions.py actually
  // do. Neither one detects a value peak or an undervalued player: both
  // pair depth at a position you are deep in with a need elsewhere.
  sellHigh: { label: "Sell High", hint: "Move depth from a position you are deep at for help where you are thin." },
  buyLow: { label: "Buy Low", hint: "Target a starter at a position you need, paid for from your surplus." },
  consolidation: { label: "Consolidation", hint: "Trade a pile of assets for a single anchor." },
  positionalUpgrades: { label: "Upgrade", hint: "Direct positional swaps that net you value." },
};

export const SUGG_TYPES = [
  { key: "sellHigh", label: "Sell High" },
  { key: "buyLow", label: "Buy Low" },
  { key: "consolidation", label: "Consolidation" },
  { key: "positionalUpgrades", label: "Upgrades" },
];

/**
 * A search result row, shared by the per-side search and the phone sheet.
 * `activateOn="press"` (the inline dropdown) picks on mouse/touch DOWN so the
 * input never blurs and the dropdown never unmounts under the finger;
 * `"click"` (the phone sheet, TC-D2) picks on a completed tap, so a scroll
 * gesture that starts on a row in the sheet's long list adds nothing.
 */
function SearchResultRow({
  row,
  settings,
  onPick,
  keyPrefix,
  activateOn = "press",
  optionId,
  active = false,
}) {
  const handlers =
    activateOn === "click"
      ? { onClick: () => onPick(row) }
      : {
          onMouseDown: (e) => {
            // Prevent input blur so focus stays in the search field after a
            // tap — the mobile keyboard doesn't dismiss between additions.
            e.preventDefault();
            onPick(row);
          },
          onTouchStart: (e) => {
            e.preventDefault();
            onPick(row);
          },
        };
  return (
    <button
      key={`${keyPrefix}-${tradeEntryKey(row)}`}
      type="button"
      className="trade-side-search-result button-reset"
      // The inline dropdown is a combobox listbox (TC-E): the input keeps
      // focus and points at the active row with aria-activedescendant, so a
      // row is an option and leaves the tab order.  The phone sheet keeps
      // plain buttons, reached with Tab inside the dialog.
      {...(optionId
        ? { id: optionId, role: "option", "aria-selected": active, tabIndex: -1 }
        : {})}
      data-active={active || undefined}
      {...handlers}
    >
      <PlayerImage
        playerId={row.raw?.playerId}
        team={row.team}
        position={row.pos}
        name={row.name}
        size={26}
      />
      <div className="trade-side-search-result-body">
        <div className="trade-side-search-result-name">{tradeEntryLabel(row)}</div>
        <div className="trade-side-search-result-meta">
          <Badge tone="outline">{row.pos}</Badge>
          {row.assetId ? <Badge tone="accent">Owned pick</Badge> : null}
          <span className="muted">
            {row.blendedSourceRank != null ? `#${row.blendedSourceRank.toFixed(1)}` : "—"}
            {" · "}
            {formatBoardValue(row, settings)}
          </span>
        </div>
      </div>
    </button>
  );
}

/**
 * A search result list, market references first and owned picks second
 * (``groupTradeSearchResults``).  Headings render only when both groups
 * are present, so a plain player search looks exactly as before.  Keys
 * carry the group so a row offered in both groups cannot collide.
 */
export function SearchResultList({
  results,
  settings,
  onPick,
  keyPrefix,
  activateOn,
  optionIdPrefix,
  activeIndex = -1,
}) {
  // Options are numbered in RENDERED order (market group, then owned picks),
  // the order ArrowDown walks (`orderedSearchResults`).
  let index = -1;
  return groupTradeSearchResults(results).map((group) => (
    <div key={`${keyPrefix}-${group.key}`} role="group" aria-label={group.label || undefined}>
      {group.label ? (
        <div className={styles.searchGroupLabel} aria-hidden={optionIdPrefix ? true : undefined}>
          {group.label}
        </div>
      ) : null}
      {group.entries.map((r) => {
        index += 1;
        return (
          <SearchResultRow
            key={`${keyPrefix}-${group.key}-${tradeEntryKey(r)}`}
            row={r}
            settings={settings}
            onPick={onPick}
            keyPrefix={`${keyPrefix}-${group.key}`}
            activateOn={activateOn}
            optionId={optionIdPrefix ? `${optionIdPrefix}-${index}` : undefined}
            active={index === activeIndex}
          />
        );
      })}
    </div>
  ));
}

/** The search results in the order SearchResultList renders them. */
export function orderedSearchResults(results) {
  return groupTradeSearchResults(results).flatMap((g) => g.entries);
}

// ── Proactive suggestion rail ─────────────────────────────────────────

/**
 * Height-stable stand-in for ``ProactiveSuggestionsRail``.
 *
 * The rail's fetch is debounced 500ms and then round-trips, so it
 * always mounts well after the rest of /trade has painted.  Rendering
 * nothing until then inserted the whole 213px panel above the trade
 * controls and meter, pushing them down 229px.
 *
 * Reuses the REAL Panel with the REAL title/subtitle so the 59px
 * header is byte-identical between states; only the 152px card body
 * is skeleton bones.  Same reserve-then-collapse contract as the
 * dashboard's TopSignalsRail: if the fetch resolves with no ideas,
 * this unmounts and the slot collapses once (a one-time settle).
 */
export function SuggestionsRailPlaceholder() {
  return (
    <Panel
      dense
      title="Recommended right now"
      subtitle="Top idea per category — activate a card to load it into the builder."
      headingLevel={2}
    >
      <div className={styles.railGrid} aria-hidden="true">
        {[0, 1, 2].map((i) => (
          <div key={i} className={styles.railCard} style={{ minHeight: 120 }}>
            <SkeletonText lines={4} />
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function ProactiveSuggestionsRail({ suggestions, onApply }) {
  const cards = [];
  for (const [key, meta] of Object.entries(SUGGESTION_RAIL_LABELS)) {
    const list = suggestions[key] || [];
    if (list.length === 0) continue;
    cards.push({ key, meta, top: list[0], remaining: list.length - 1 });
  }
  if (cards.length === 0) return null;

  return (
    <Panel
      dense
      title="Recommended right now"
      subtitle="Top idea per category — activate a card to load it into the builder."
      headingLevel={2}
    >
      <div className={styles.railGrid}>
        {cards.map((c) => (
          <button
            key={c.key}
            type="button"
            className={styles.railCard}
            onClick={() => onApply(c.top)}
            title={c.meta.hint}
          >
            <span className={styles.railHead}>
              <Badge tone="accent">{c.meta.label}</Badge>
              {c.remaining > 0 ? (
                <span className={styles.railHint}>+{c.remaining} more</span>
              ) : null}
            </span>
            <span className={styles.railLine}>
              <span className={styles.railLineLabel}>Give: </span>
              {(c.top.give || []).map((p) => p.name).join(" + ") || "—"}
            </span>
            <span className={styles.railLine}>
              <span className={styles.railLineLabel}>Get: </span>
              {(c.top.receive || []).map((p) => p.name).join(" + ") || "—"}
            </span>
            <span className={styles.railHint}>{c.meta.hint}</span>
          </button>
        ))}
      </div>
    </Panel>
  );
}



// ── Pick-team selectors ───────────────────────────────────────────────

export function PickTeamSelectors({
  sides,
  sleeperTeams,
  sideTeamNames,
  onSetTeam,
  stackGateUnmet,
  stackBudgetsUnavailable = null,
}) {
  return (
    <Panel
      dense
      title="Draft-capital stacks"
      headingLevel={2}
      subtitle="Picks are in this trade. Select the team on each side to see the draft-capital stack note (not included in the verdict)."
    >
      <div className={styles.pickTeams}>
        {sides.map((s, i) => (
          <Field key={s.id ?? i} label={`Side ${s.label}`} id={`pick-team-${i}`}>
            <Select
              id={`pick-team-${i}`}
              value={sideTeamNames[i] ?? ""}
              onChange={(e) => onSetTeam(i, e.target.value || null)}
            >
              <option value="">— select team —</option>
              {sleeperTeams.map((t) => (
                <option key={t.name} value={t.name}>
                  {t.name}
                </option>
              ))}
            </Select>
          </Field>
        ))}
      </div>
      {stackGateUnmet ? (
        <Banner tone="info">
          Assign a team to every side a pick is traded to or from to see the
          draft-capital stack note. The verdict does not use it.
        </Banner>
      ) : null}
      {stackBudgetsUnavailable ? (
        <Banner tone="info">
          {draftCapitalBudgetsUnavailableText(stackBudgetsUnavailable)} The draft-capital
          stack note is off for this league.
        </Banner>
      ) : null}
    </Panel>
  );
}

// ── Side card ─────────────────────────────────────────────────────────

function AssetRow({
  row,
  count = 1,
  sideIdx,
  sides,
  side,
  valueMode,
  settings,
  valueOverrides,
  onOpenPlayer,
  onSetValueOverride,
  onClearValueOverride,
  onRemove,
  onAddCopy,
  onSetDestination,
}) {
  const edge = getPlayerEdge(row);
  const age = formatAssetAge(row);
  // A pick priced by a declared-prior derivation (no market row) says so on
  // the row (TC-B / TCM-B04) -- the generic "2027 Round 1" grade above all,
  // whose slot is not yet known.
  const derived = derivedPickDisclosure(row);
  // One line per IDENTITY (lib/trade-assets): any repeated asset is one
  // line with a quantity, two owned picks that share a label are two
  // lines.  Routing, overrides and removal all key on the line identity,
  // so every copy on a line shares that line's destination.
  const key = tradeEntryKey(row);
  const label = tradeEntryLabel(row);
  // 3+-team trades give every asset an explicit destination so the
  // fairness bar can compute per-team NET flow.  For 2-team trades the
  // other side is implicit and the dropdown is hidden.
  const storedDest = side.destinations?.[key];
  const parsedDest = Number(storedDest);
  const currentDest =
    Number.isInteger(parsedDest) &&
    parsedDest >= 0 &&
    parsedDest < sides.length &&
    parsedDest !== sideIdx
      ? parsedDest
      : defaultDestination(sideIdx, sides.length);

  return (
    // A routed row (3+ teams) carries a destination select; on a phone its
    // actions wrap under the name instead of clipping the name away (UI
    // contract §6: never clip player names into ambiguity).
    <div
      className={
        sides.length > 2 ? `${styles.assetRow} ${styles.assetRowRouted}` : styles.assetRow
      }
    >
      <div className={styles.assetMain}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.team}
          position={row.pos}
          name={row.name}
          size={28}
        />
        <div className={styles.assetBody}>
          <span className={styles.assetName}>
            {/* #1337: a player with a canonical id opens his Player File;
                a pick (no id) keeps the quick-view popup. */}
            <PlayerNameButton
              name={label}
              row={row}
              playerId={canonicalPlayerId(row)}
              onOpen={onOpenPlayer}
              className={styles.assetNameButton}
            />
            {count > 1 ? (
              <Badge tone="outline" title={`${count} copies, each counted in the totals`}>
                ×{count}
              </Badge>
            ) : null}
            {row.assetId ? (
              <Badge tone="accent" title={row.assetId}>
                Owned pick
              </Badge>
            ) : null}
            {derived ? (
              <Badge
                tone="outline"
                data-testid="trade-asset-derived-pick"
                title={`No market row: derived from ${derived.basis || "board values"}${
                  derived.isPrior ? " (a declared prior, not a market price)" : ""
                }.`}
              >
                {derived.label}
                {derived.isPrior ? " (prior)" : ""}
              </Badge>
            ) : null}
            {edge.signal ? (
              <Badge tone={edge.signal === "BUY" ? "positive" : "negative"}>
                {edge.signal} {edge.edgePct}%
              </Badge>
            ) : null}
          </span>
          <span className={styles.assetMeta}>
            <span className={styles.assetMetaText}>
              {row.pos}
              {age ? ` · ${age}` : ""} · Consensus{" "}
              {row.blendedSourceRank != null ? row.blendedSourceRank.toFixed(1) : "—"}
              {" · "}
              {Number.isFinite(row.sourceCount) ? row.sourceCount : 0} src
            </span>
            {row.confidenceBucket && row.confidenceBucket !== "high" ? (
              /* W08-F011 (V1-92): the trade builder priced every asset
                 with no visible signal for how thin the evidence behind
                 that price is. `confidenceBucket` already folds
                 freshness in as one of its five axes (see
                 src/api/confidence.py — freshness cannot be read alone
                 per-row, so the bucket IS the backend's per-row
                 freshness-aware truth), so surfacing it here needs no
                 new Date.now()-based staleness invented on the client.
                 Silent for "high" — the expected default — to avoid
                 badging every row in a trade. */
              <Badge
                tone={row.confidenceBucket === "medium" ? "warning" : "negative"}
                title={row.confidenceLabel || undefined}
              >
                {row.confidenceBucket === "none"
                  ? "no confidence data"
                  : `${row.confidenceBucket} confidence`}
              </Badge>
            ) : null}
            <input
              type="number"
              className="asset-value-override-input"
              value={valueOverrides[key] != null ? valueOverrides[key] : ""}
              placeholder={
                isUnpricedBoardRow(row)
                  ? "—"
                  : String(Math.round(effectiveValue(row, valueMode, settings)))
              }
              onChange={(e) => onSetValueOverride(key, e.target.value)}
              onBlur={(e) => {
                if (e.target.value === "") onClearValueOverride(key);
              }}
              aria-label={`Override ${label}'s value for this trade`}
              title={
                count > 1
                  ? "Override this asset's per-copy value for this trade only"
                  : "Override this player's value for this trade only"
              }
            />
            {/* No per-player reset affordance (owner intake #781, TC-B /
                TCM-D14): an override is visually silent and is cleared by the
                ONE top-level "Reset Values", by emptying the input, or by
                removing the asset. */}
          </span>
        </div>
      </div>
      <div className={styles.assetActions}>
        {sides.length > 2 ? (
          <label className={styles.assetDest}>
            <span className="ds-visually-hidden">Destination for {label}</span>
            <Icon name="arrow-right" aria-hidden="true" />
            <Select
              className="trade-dest-select"
              value={currentDest}
              onChange={(e) => onSetDestination(sideIdx, key, e.target.value)}
              aria-label={`Send ${label} to which side`}
            >
              {sides.map((s, i) =>
                i === sideIdx ? null : (
                  <option key={i} value={i}>
                    Side {s.label}
                  </option>
                ),
              )}
            </Select>
          </label>
        ) : null}
        {/* Quantity control on EVERY line (owner decision 2026-10-03:
            every calculator asset is repeatable, players and owned picks
            included).  "+" adds one copy with no maximum; "−" removes
            exactly one copy, and at quantity 1 it removes the line. */}
        <span className={styles.assetQuantity} role="group" aria-label={`${label} quantity`}>
          <Button
            variant="ghost"
            size="sm"
            className={styles.assetQuantityButton}
            onClick={() => onRemove(key, sideIdx)}
            aria-label={
              count > 1
                ? `Remove one ${label} from Side ${side.label}`
                : `Remove ${label} from Side ${side.label}`
            }
          >
            −
          </Button>
          <span
            className={styles.assetQuantityCount}
            aria-live="polite"
            data-testid="trade-asset-quantity"
          >
            {count}
          </span>
          <Button
            variant="ghost"
            size="sm"
            className={styles.assetQuantityButton}
            onClick={() => onAddCopy?.(row, sideIdx)}
            aria-label={`Add another ${label} to Side ${side.label}`}
          >
            +
          </Button>
        </span>
      </div>
    </div>
  );
}

function IncomingRow({ asset, fromSideIdx, sides, valueMode, settings, valueOverrides, onOpenPlayer }) {
  const edge = getPlayerEdge(asset);
  return (
    <div className={`${styles.assetRow} ${styles.assetRowIncoming}`}>
      <div className={styles.assetMain}>
        <PlayerImage
          playerId={asset.raw?.playerId}
          team={asset.team}
          position={asset.pos}
          name={asset.name}
          size={24}
        />
        <div className={styles.assetBody}>
          <span className={styles.assetName}>
            <PlayerNameButton
              name={tradeEntryLabel(asset)}
              row={asset}
              playerId={canonicalPlayerId(asset)}
              onOpen={onOpenPlayer}
              className={styles.assetNameButton}
            />
            {edge.signal ? (
              <Badge tone={edge.signal === "BUY" ? "positive" : "negative"}>
                {edge.signal} {edge.edgePct}%
              </Badge>
            ) : null}
          </span>
          <span className={styles.assetMeta}>
            {asset.pos} · from Side {sides[fromSideIdx]?.label || "?"} ·{" "}
            {valueOverrides[tradeEntryKey(asset)] == null && isUnpricedBoardRow(asset)
              ? "not priced"
              : Math.round(
                  valueOverrides[tradeEntryKey(asset)] ??
                    effectiveValue(asset, valueMode, settings),
                ).toLocaleString()}
          </span>
        </div>
      </div>
    </div>
  );
}

export function SideCard({
  side,
  sideIdx,
  sides,
  total,
  isMySide,
  selectedTeam,
  sideQuery,
  isFocused,
  searchResults,
  settings,
  valueMode,
  valueOverrides,
  incoming,
  balancers,
  onSideQueryChange,
  onSideFocus,
  onSideBlur,
  onAddFromSearch,
  onOpenPlayer,
  onSetValueOverride,
  onClearValueOverride,
  onRemoveAsset,
  onAddCopy,
  onSetDestination,
  onRemoveTeam,
  onAddBalancer,
  registerInputRef,
  canRemoveTeam,
  sheetMode = false,
  onOpenSheet,
}) {
  const showResults = isFocused && (sideQuery || "").trim().length > 0;
  // Keyboard path for the inline search (TC-E, WAI-ARIA combobox): ArrowDown /
  // ArrowUp move the active option, Enter adds it, Escape clears the query.
  // Focus never leaves the input, so the dropdown cannot unmount under a Tab
  // (it closes on blur) and a keyboard pick works like a tap.
  const [activeIdx, setActiveIdx] = useState(-1);
  const [lastAdded, setLastAdded] = useState("");
  useEffect(() => {
    setActiveIdx(-1);
  }, [sideQuery, isFocused]);
  const listboxId = `trade-search-${side.label}-listbox`;
  const optionIdPrefix = `trade-search-${side.label}-opt`;
  const ordered = showResults ? orderedSearchResults(searchResults) : [];
  const active = activeIdx >= 0 && activeIdx < ordered.length ? activeIdx : -1;
  useEffect(() => {
    if (active < 0 || typeof document === "undefined") return;
    document.getElementById(`${optionIdPrefix}-${active}`)?.scrollIntoView?.({ block: "nearest" });
  }, [active, optionIdPrefix]);
  const pickFromSearch = (row) => {
    setLastAdded(`Added ${tradeEntryLabel(row)} to Side ${side.label}.`);
    onAddFromSearch(row, sideIdx);
  };
  const onSearchKeyDown = (e) => {
    if (e.key === "ArrowDown" && ordered.length) {
      e.preventDefault();
      setActiveIdx(active < 0 ? 0 : Math.min(active + 1, ordered.length - 1));
    } else if (e.key === "ArrowUp" && ordered.length) {
      e.preventDefault();
      setActiveIdx(active <= 0 ? ordered.length - 1 : active - 1);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pickFromSearch(ordered[active]);
    } else if (e.key === "Escape" && (sideQuery || "").length) {
      e.preventDefault();
      onSideQueryChange(sideIdx, "");
    }
  };
  // Assets the board declined to price contribute 0 to this side's
  // total — a legitimate arithmetic neutral inside the sum, but not
  // something a published total may stay quiet about. 282 of 1,094 live
  // rows are unpriced; without this the side reads as a complete
  // valuation of pieces we never valued.
  const unpriced = unpricedAssetsOnSide(side.assets);
  // A total that includes a user override is not the canonical total; say so
  // on the total itself (TC-A, UX audit P0-7).
  const overriddenCount = (side.assets || []).filter(
    (r) => valueOverrides?.[tradeEntryKey(r)] != null,
  ).length;

  return (
    <Panel className={isMySide ? styles.mySide : undefined} id={`trade-side-${side.label}`}>
      <div className={styles.sideHeader}>
        <div className={styles.sideHeaderLeft}>
          <h3 style={{ margin: 0 }}>Side {side.label}</h3>
          {isMySide && selectedTeam?.name ? (
            <Badge tone="accent">You · {selectedTeam.name}</Badge>
          ) : null}
          {canRemoveTeam ? (
            <Button
              variant="ghost"
              size="sm"
              onClick={() => onRemoveTeam(sideIdx)}
              aria-label={`Remove Side ${side.label}`}
            >
              Remove side
            </Button>
          ) : null}
        </div>
        {/* Exact numbers for production arithmetic checks
            (tests/e2e/specs/prod-auth/trade-stack-withdrawn.spec.js):
            adjusted = raw + adjustment, nothing else. */}
        <div
          className={styles.sideTotals}
          data-side-total={total.adjusted}
          data-side-raw={total.raw}
          data-side-va={total.adjustment}
        >
          <div className={styles.sideTotal}>
            {Math.round(total.adjusted).toLocaleString()}
          </div>
          {/* The headline total is raw + VA -- nothing else (adjustedSideTotals;
              the draft-capital stack effect is informational only and is shown
              separately under the meter).  VA is shown as the difference of the
              rounded figures, so the visible parts always add up to the headline.
              The retired `title=` said VA was a roster-spot bonus for the side
              with fewer pieces — the package model (packageAdjustPair; geometric
              q = 0.78 since 2026-10-17) credits concentration, fires on
              equal counts too, and a hover title never reached touch users. */}
          <div className={styles.sideTotalMeta}>
            Raw {Math.round(total.raw).toLocaleString()}
            {total.adjustment > 0
              ? ` + VA ${(Math.round(total.adjusted) - Math.round(total.raw)).toLocaleString()}`
              : ""}
            {total.adjustment > 0 ? <ValueAdjustmentTip /> : null}
          </div>
          {overriddenCount ? (
            <div className={styles.sideTotalMeta} data-testid="side-total-edited">
              Includes {overriddenCount} edited value{overriddenCount === 1 ? "" : "s"}
            </div>
          ) : null}
          {unpriced.length ? (
            <div
              className={styles.sideTotalMeta}
              title={`The board has no value for ${unpriced
                .map((r) => r.name)
                .join(", ")}. They are counted as 0 in this total, which is not the same as being worth 0.`}
            >
              Incomplete — {unpriced.length} unpriced
            </div>
          ) : null}
        </div>
      </div>

      {sheetMode ? (
        /* Phones (TC-D2): one bottom-sheet search per side instead of an
           inline dropdown that runs under the keyboard. */
        <Button
          className={styles.sheetAdd}
          icon={<Icon name="search" size={14} />}
          onClick={() => onOpenSheet?.(sideIdx)}
          aria-haspopup="dialog"
        >
          Add to Side {side.label}
        </Button>
      ) : (
        <>
          {/* Inline search — type 2-3 letters, a compact dropdown of the top
              matches appears, tap one to add and keep typing. */}
          <div className="trade-side-search">
            <input
              ref={(el) => registerInputRef(sideIdx, el)}
              className="input trade-side-search-input"
              placeholder={`Search to add to Side ${side.label}…`}
              value={sideQuery || ""}
              onChange={(e) => onSideQueryChange(sideIdx, e.target.value)}
              onFocus={() => onSideFocus(sideIdx)}
              onBlur={() => onSideBlur(sideIdx)}
              onKeyDown={onSearchKeyDown}
              aria-label={`Search to add a player to Side ${side.label}`}
              role="combobox"
              aria-autocomplete="list"
              aria-expanded={showResults && ordered.length > 0}
              aria-controls={showResults && ordered.length > 0 ? listboxId : undefined}
              aria-activedescendant={active >= 0 ? `${optionIdPrefix}-${active}` : undefined}
              autoComplete="off"
            />
            {showResults ? (
              /* Bounded + scrollable (globals.css) so the market group stays
                 reachable above an open phone keyboard. */
              searchResults.length === 0 ? (
                <div className="trade-side-search-results">
                  <div className="trade-side-search-empty muted" role="status">
                    No matches.
                  </div>
                </div>
              ) : (
                <div
                  className="trade-side-search-results"
                  role="listbox"
                  id={listboxId}
                  aria-label={`Results for Side ${side.label}`}
                >
                  <SearchResultList
                    results={searchResults}
                    settings={settings}
                    onPick={pickFromSearch}
                    keyPrefix={`search-${side.label}`}
                    optionIdPrefix={optionIdPrefix}
                    activeIndex={active}
                  />
                </div>
              )
            ) : null}
            <span className="ds-visually-hidden" role="status">
              {lastAdded}
            </span>
          </div>
        </>
      )}

      {sides.length > 2 ? (
        <div className={styles.sideGroupLabel}>Giving</div>
      ) : null}

      {/* Position mix of what this side sends, one count per copy (TC-B /
          TCM-A02).  Display only. */}
      {side.assets.length ? (
        <div className={styles.sideTotalMeta} data-testid="trade-side-composition">
          {packageCompositionText(side.assets)}
        </div>
      ) : null}

      <div className={styles.assetList}>
        {groupSideEntries(side.assets).map((g) => (
          <AssetRow
            key={`${side.label}-${g.key}`}
            row={g.entry}
            count={g.count}
            side={side}
            sideIdx={sideIdx}
            sides={sides}
            valueMode={valueMode}
            settings={settings}
            valueOverrides={valueOverrides}
            onOpenPlayer={onOpenPlayer}
            onSetValueOverride={onSetValueOverride}
            onClearValueOverride={onClearValueOverride}
            onRemove={onRemoveAsset}
            onAddCopy={onAddCopy}
            onSetDestination={onSetDestination}
          />
        ))}
        {side.assets.length === 0 ? (
          <span className={styles.assetEmpty}>No assets yet.</span>
        ) : null}
      </div>

      {/* Receiving — 3+-team mode only, so each card answers both "what
          am I giving up?" and "what am I getting back?" in one place. */}
      {sides.length > 2 ? (
        <>
          <div className={styles.sideGroupLabel}>Receiving</div>
          <div className={styles.assetList}>
            {(incoming || []).length > 0 ? (
              incoming.map(({ asset, fromSideIdx }, idx) => (
                <IncomingRow
                  key={`recv-${side.label}-${fromSideIdx}-${tradeEntryKey(asset)}-${idx}`}
                  asset={asset}
                  fromSideIdx={fromSideIdx}
                  sides={sides}
                  valueMode={valueMode}
                  settings={settings}
                  valueOverrides={valueOverrides}
                  onOpenPlayer={onOpenPlayer}
                />
              ))
            ) : (
              <span className={styles.assetEmpty}>
                Nothing incoming. Assign a destination on another side to route here.
              </span>
            )}
          </div>
        </>
      ) : null}

      {balancers ? (
        <div
          className={styles.balancers}
          id={`trade-side-${side.label}-balancers`}
          aria-busy={balancers.pending ? "true" : undefined}
        >
          <span className={styles.balancerLabel}>{balancers.label}</span>
          {balancers.list.map((b) => (
            <Button
              key={b.key || b.name}
              variant="ghost"
              size="sm"
              onClick={() => onAddBalancer(b, sideIdx)}
              /* The suggestion says what it LANDS ON, not just what it
                 is worth.  ``imbalanceAfter`` is measured through the
                 same adjusted-gap path the meter renders, so the number
                 here is checkable against the meter after the click
                 (defect #800). */
              title={
                Number.isFinite(b.imbalanceAfter)
                  ? `Leaves a gap of ${Math.round(b.imbalanceAfter).toLocaleString()} (now ${Math.round(b.imbalanceBefore).toLocaleString()})`
                  : undefined
              }
            >
              {b.isCombo ? "Both: " : ""}
              {b.label || b.name} ({b.pos}) · {b.value.toLocaleString()}
              {Number.isFinite(b.imbalanceAfter) ? (
                <span className={styles.balancerResidual}>
                  {" "}
                  → {Math.round(b.imbalanceAfter).toLocaleString()}
                </span>
              ) : null}
            </Button>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}
