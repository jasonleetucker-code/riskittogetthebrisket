"use client";

/**
 * ManualAddDrop — trade-calculator-style add/drop selector for
 * the /waivers page.
 *
 * Lets the user pick a roster player to drop and an unrostered
 * pool player to add, then renders the same fairness bar +
 * per-vendor breakdown the trade calculator uses for any 2-side
 * comparison.  Sits ABOVE the existing FilterBar +
 * recommendation tables on /waivers; the bestMoves / addable /
 * droppable engine below is unchanged.
 *
 * Reuses (no duplication):
 *   - SharedTradeMeter        ← components/trade/TradeMeter
 *   - SharedTradeSourceBreakdown ← components/trade/TradeSourceBreakdown
 *   - effectiveValue + sideTotal + adjustedSideTotals from
 *     lib/trade-logic (KTC V13 Value Adjustment math)
 *   - ResilientSection wrapper for crash isolation
 *   - PlayerImage + posBadgeClass for the picker rows
 *
 * Why a purpose-built waiver picker (and not a generic
 * SideAssetList lifted from /trade)?  The trade page's side block
 * carries multi-team destination dropdowns, receiving sections,
 * focused-side state and 4 layers of conditional rendering.
 * Forcing all of that into a reusable component would either
 * regress the trade page or hand the waiver page complexity it
 * doesn't need.  This file keeps the picker simple — single-asset
 * select per side — and inherits the same ``trade-side-search-*``
 * styling so the look matches.
 */

import { useMemo, useRef, useState } from "react";

import {
  adjustedSideTotals,
  effectiveValue,
  sideTotal,
} from "@/lib/trade-logic";
import {
  buildOwnedNameSet,
  buildTopWaiverPool,
  normalizeName,
} from "@/lib/waiver-logic";
import { posBadgeClass } from "@/lib/display-helpers";
import ResilientSection from "@/components/ResilientSection";
import SharedTradeMeter from "@/components/trade/TradeMeter";
import SharedTradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import FaabRecommendation from "@/components/waivers/FaabRecommendation";
import { MonteCarloButton, PlayerImage } from "@/components/ui";

// ── helpers ────────────────────────────────────────────────────

export function normName(s) {
  return String(s || "")
    .toLowerCase()
    .replace(/[^a-z0-9]/g, "");
}

/**
 * Build the lookup map: roster name (string from selectedTeam.players)
 *   → row object from the public ``rows`` array.
 *
 * Skips players we can't price (no value) and picks (waiver
 * /add-drop applies to NFL players only).
 */
export function rosterRowsForTeam(rows, rosterNames) {
  if (!Array.isArray(rows) || !Array.isArray(rosterNames)) return [];
  const byName = new Map();
  for (const r of rows) {
    const k = normName(r?.name);
    if (k && !byName.has(k)) byName.set(k, r);
  }
  const out = [];
  const seen = new Set();
  for (const name of rosterNames) {
    const k = normName(name);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    const row = byName.get(k);
    if (!row) continue;
    if (row.assetClass === "pick") continue;
    if ((Number(row.values?.full) || 0) <= 0) continue;
    out.push(row);
  }
  // Sort lowest-value first so the natural drop candidates
  // surface at the top of the picker.
  return out.sort(
    (a, b) =>
      (Number(a.values?.full) || 0) - (Number(b.values?.full) || 0),
  );
}

/**
 * Lightweight typeahead picker.  Single-asset selection.
 *
 * Props:
 *   label         — accessibility + heading text ("Drop", "Add").
 *   accent        — border-left color for the selected card.
 *   pool          — array of row objects to search (already filtered).
 *   selected      — currently-selected row (or null).
 *   onSelect(row) — fired when the user picks a search result.
 *   onClear()     — fired when the user removes the selected row.
 *   emptyMsg      — copy shown when ``pool`` is empty.
 *   placeholder   — input placeholder.
 */
function SidePicker({
  label,
  accent,
  pool,
  selected,
  onSelect,
  onClear,
  emptyMsg,
  placeholder,
  valueMode,
  settings,
}) {
  const [q, setQ] = useState("");
  const [focused, setFocused] = useState(false);
  const inputRef = useRef(null);

  const results = useMemo(() => {
    const term = normName(q);
    if (!term) {
      // No query: show top-of-pool entries (already pre-sorted).
      return pool.slice(0, 8);
    }
    return pool
      .filter((r) => normName(r?.name).includes(term))
      .slice(0, 8);
  }, [q, pool]);

  const showResults = focused && results.length >= 0 && !selected;

  return (
    <div
      className="trade-side"
      style={{
        flex: 1,
        minWidth: 0,
        background: "var(--surface, rgba(255,255,255,0.03))",
        border: "1px solid var(--border, rgba(255,255,255,0.08))",
        borderLeft: `3px solid ${accent}`,
        borderRadius: 10,
        padding: "10px 12px",
      }}
    >
      <div
        className="label"
        style={{
          fontSize: "0.7rem",
          letterSpacing: "0.05em",
          color: accent,
          marginBottom: 8,
        }}
      >
        {label}
      </div>

      {selected ? (
        <SelectedCard
          row={selected}
          valueMode={valueMode}
          settings={settings}
          onClear={onClear}
        />
      ) : (
        <div className="trade-side-search" style={{ position: "relative" }}>
          <input
            ref={inputRef}
            className="input trade-side-search-input"
            type="text"
            value={q}
            placeholder={placeholder}
            aria-label={`Search ${label.toLowerCase()} candidates`}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              // Slight delay so a tap/click on a result registers
              // before the dropdown collapses.  Mirrors the trade
              // page's pattern.
              setTimeout(() => setFocused(false), 120);
            }}
          />
          {showResults && (
            <div className="trade-side-search-results">
              {pool.length === 0 ? (
                <div className="trade-side-search-empty muted">{emptyMsg}</div>
              ) : results.length === 0 ? (
                <div className="trade-side-search-empty muted">No matches.</div>
              ) : (
                results.map((r) => (
                  <button
                    key={`pick-${label}-${r.name}`}
                    type="button"
                    className="trade-side-search-result button-reset"
                    onMouseDown={(e) => {
                      e.preventDefault();
                      onSelect(r);
                      setQ("");
                    }}
                    onTouchStart={(e) => {
                      e.preventDefault();
                      onSelect(r);
                      setQ("");
                    }}
                  >
                    <PlayerImage
                      playerId={r.raw?.playerId}
                      team={r.team}
                      position={r.pos}
                      name={r.name}
                      size={26}
                    />
                    <div className="trade-side-search-result-body">
                      <div className="trade-side-search-result-name">
                        {r.name}
                      </div>
                      <div className="trade-side-search-result-meta">
                        <span className={posBadgeClass(r)}>{r.pos}</span>
                        <span className="muted">
                          {r.blendedSourceRank != null
                            ? `#${r.blendedSourceRank.toFixed(1)}`
                            : "—"}
                          {" · "}
                          {Math.round(
                            effectiveValue(r, valueMode, settings) || 0,
                          ).toLocaleString()}
                        </span>
                      </div>
                    </div>
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SelectedCard({ row, valueMode, settings, onClear }) {
  const v = Math.round(effectiveValue(row, valueMode, settings) || 0);
  return (
    <div className="asset-row">
      <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.team}
          position={row.pos}
          name={row.name}
          size={28}
        />
        <div style={{ minWidth: 0 }}>
          <div className="asset-name">{row.name}</div>
          <div className="asset-meta">
            <span className={posBadgeClass(row)}>{row.pos}</span>
            {" · "}
            {row.blendedSourceRank != null
              ? `#${row.blendedSourceRank.toFixed(1)}`
              : "—"}
            {" · "}
            {v.toLocaleString()}
          </div>
        </div>
      </div>
      <button
        type="button"
        className="button trade-remove-btn"
        onClick={onClear}
        aria-label="Clear selection"
      >
        Remove
      </button>
    </div>
  );
}

// ── main component ─────────────────────────────────────────────

/**
 * ManualAddDrop — top-level entry rendered ABOVE the FilterBar
 * on /waivers.
 *
 * Props:
 *   rows             — public-contract player rows (from useApp).
 *   selectedTeam     — selected fantasy team object (from useTeam).
 *                      Must have ``.players`` (array of names).
 *   sleeperTeams     — array of sleeper team objects (from
 *                      rawData.sleeper.teams).  Used to compute the
 *                      league-wide owned name set for the add pool.
 *   idpEnabled       — whether the league has IDP positions (from
 *                      selectedLeague.idpEnabled).
 *   includeRookies   — whether to surface rookies in the add pool
 *                      (mirrors the page's ``Include rookies``
 *                      toggle).
 *   valueMode        — "full" / "rookie" / etc. (defaults "full").
 *   settings         — settings context for value-adjustment math.
 *
 * If anything's missing (no team, empty rows), the component
 * returns a compact info banner instead of crashing.
 */
export default function ManualAddDrop({
  rows,
  selectedTeam,
  sleeperTeams,
  idpEnabled = true,
  includeRookies = false,
  valueMode = "full",
  settings,
  leagueKey,
}) {
  const [dropRow, setDropRow] = useState(null);
  const [addRow, setAddRow] = useState(null);

  const dropPool = useMemo(
    () => rosterRowsForTeam(rows, selectedTeam?.players),
    [rows, selectedTeam?.players],
  );

  // Add side: top-50 league-wide pool with position minimums.  This
  // is intentionally roster-INDEPENDENT — the user might want to
  // evaluate a strong waiver target who doesn't strictly upgrade
  // their lowest-value bench filler but still represents a real
  // option.  The fairness bar / source breakdown / Monte Carlo
  // tell the truth about whether the trade is even.
  const addPoolResult = useMemo(() => {
    const ownedNameSet = buildOwnedNameSet(sleeperTeams);
    const myRosterNameSet = new Set(
      (selectedTeam?.players || [])
        .map(normalizeName)
        .filter(Boolean),
    );
    return buildTopWaiverPool(rows, ownedNameSet, {
      limit: 50,
      minPerPosition: 3,
      includeRookies,
      idpEnabled,
      myRosterNameSet,
    });
  }, [rows, sleeperTeams, selectedTeam?.players, includeRookies, idpEnabled]);
  const addPool = addPoolResult.players;

  const sides = useMemo(
    () => [
      { id: 0, label: "Drop", assets: dropRow ? [dropRow] : [] },
      { id: 1, label: "Add", assets: addRow ? [addRow] : [] },
    ],
    [dropRow, addRow],
  );

  // sideTotals: when both sides are populated we want the full
  // KTC V13 Value Adjustment.  When only one (or neither) is
  // populated, fall back to a flat sum so the meter still renders
  // a sensible "0 vs N" preview.
  const sideTotals = useMemo(() => {
    const both = sides[0].assets.length > 0 && sides[1].assets.length > 0;
    if (both) {
      const [a, b] = adjustedSideTotals(
        sides[0].assets,
        sides[1].assets,
        valueMode,
        settings,
      );
      return [a, b];
    }
    return sides.map((s) => {
      const raw = sideTotal(s.assets, valueMode, settings);
      return { raw, adjustment: 0, adjusted: raw };
    });
  }, [sides, valueMode, settings]);

  const noTeam = !selectedTeam;

  return (
    <section
      className="card"
      style={{ padding: 16, marginBottom: 16 }}
      aria-label="Manual add/drop calculator"
    >
      <header style={{ marginBottom: 10 }}>
        <h2 className="card-title" style={{ margin: 0, fontSize: "1.05rem" }}>
          Manual add/drop calculator
        </h2>
        <p
          className="muted"
          style={{ margin: "4px 0 0", fontSize: "0.78rem" }}
        >
          Pick one player from your roster to drop and one off the waiver
          wire to add — the same fairness bar and per-vendor breakdown the
          trade calculator uses, applied to a single transaction.
        </p>
      </header>

      {noTeam ? (
        <div className="muted" style={{ padding: 8 }}>
          Select a team in the filter bar below to use the manual
          add/drop calculator.
        </div>
      ) : (
        <>
          <div
            style={{
              display: "flex",
              gap: 12,
              flexWrap: "wrap",
              marginBottom: 10,
            }}
          >
            <SidePicker
              label="DROP"
              accent="var(--red, #ef4444)"
              pool={dropPool}
              selected={dropRow}
              onSelect={setDropRow}
              onClear={() => setDropRow(null)}
              emptyMsg="No droppable players on your roster."
              placeholder="Search your roster…"
              valueMode={valueMode}
              settings={settings}
            />
            <SidePicker
              label="ADD"
              accent="var(--green, #34d399)"
              pool={addPool}
              selected={addRow}
              onSelect={setAddRow}
              onClear={() => setAddRow(null)}
              emptyMsg="No addable players on the waiver wire."
              placeholder={
                addPoolResult.cap > 0
                  ? `Top ${addPoolResult.cap} waivers${
                      addPoolResult.injectedCount > 0
                        ? ` + ${addPoolResult.injectedCount} position-coverage`
                        : ""
                    }…`
                  : "Search free agents…"
              }
              valueMode={valueMode}
              settings={settings}
            />
          </div>

          {/* Fairness bar.  Renders an "Even — 0 vs 0" placeholder
              before any selection so the user sees the surface
              they'll get once both sides are filled. */}
          <ResilientSection name="Manual add/drop fairness bar">
            <SharedTradeMeter sides={sides} sideTotals={sideTotals} />
          </ResilientSection>

          {/* Per-vendor breakdown only renders meaningfully when
              both sides are populated; the underlying component
              already guards on empty assets and returns null. */}
          <ResilientSection name="Manual add/drop per-source breakdown">
            <SharedTradeSourceBreakdown sides={sides} settings={settings} />
          </ResilientSection>

          {/* FAAB bid recommendation panel — fires when an add is
              selected (drop optional).  Wrapped in ResilientSection
              so a recommender API failure can't take down the
              calculator. */}
          {addRow && (
            <ResilientSection name="Manual add/drop FAAB recommendation">
              <FaabRecommendation
                addPlayer={addRow}
                dropPlayer={dropRow}
                leagueKey={leagueKey}
                ownerId={selectedTeam?.ownerId}
              />
            </ResilientSection>
          )}

          {/* Monte Carlo simulator — disabled when either side is
              empty (the underlying button computes a no-op state).
              Wrapped in ResilientSection so an MC failure can't
              take down the calculator. */}
          {dropRow && addRow && (
            <ResilientSection name="Manual add/drop Monte Carlo">
              <MonteCarloButton sides={sides} />
            </ResilientSection>
          )}
        </>
      )}
    </section>
  );
}
