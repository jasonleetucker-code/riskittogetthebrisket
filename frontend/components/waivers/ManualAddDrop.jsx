"use client";

/**
 * ManualAddDrop — the single-transaction bench of the claim desk.
 *
 * Pick one roster player to drop and one pool player to add, then read
 * the same fairness bar + per-vendor breakdown the trade calculator
 * uses, plus the FAAB v2 bid desk (FaabRecommendation).
 *
 * Reuses (no duplication):
 *   - SharedTradeMeter        ← components/trade/TradeMeter
 *   - SharedTradeSourceBreakdown ← components/trade/TradeSourceBreakdown
 *   - effectiveValue + sideTotal + adjustedSideTotals from
 *     lib/trade-logic (KTC V13 Value Adjustment math)
 *   - ResilientSection wrapper for crash isolation
 *
 * Why a purpose-built waiver picker (and not a generic SideAssetList
 * lifted from /trade)?  The trade page's side block carries multi-team
 * destination dropdowns, receiving sections, focused-side state and
 * four layers of conditional rendering.  Forcing all of that into a
 * reusable component would either regress the trade page or hand the
 * waiver page complexity it doesn't need.  This file keeps the picker
 * simple — single asset per side.
 *
 * R4: migrated off the legacy `.card` + inline-style system onto ds
 * primitives and the waivers module CSS.  All value math is unchanged
 * and still lives in lib/trade-logic + lib/waiver-logic.
 */

import { useEffect, useMemo, useState } from "react";

import { adjustedSideTotals, effectiveValue, sideTotal } from "@/lib/trade-logic";
import {
  buildOwnedNameSet,
  buildTopWaiverPool,
  normalizeName,
  normalizeNameCompact,
} from "@/lib/waiver-logic";
import ResilientSection from "@/components/ResilientSection";
import SharedTradeMeter from "@/components/trade/TradeMeter";
import SharedTradeSourceBreakdown from "@/components/trade/TradeSourceBreakdown";
import FaabRecommendation, {
  DEFAULT_RISK_POSTURE,
} from "@/components/waivers/FaabRecommendation";
import { MonteCarloButton, PlayerImage } from "@/components/ui";
import { Badge, Button, Input, Panel, SkeletonTable, StatTile } from "@/components/ds";
import styles from "@/app/waivers/waivers.module.css";

// ── helpers ────────────────────────────────────────────────────
//
// Name keying in this file: there is no local normalizer.  Both keys
// come from lib/waiver-logic, and which one applies is decided by the
// consumer, not by taste:
//
//   normalizeNameCompact — this component's OWN joins and search
//       (rosterRowsForTeam, SidePicker typeahead).  Punctuation-
//       insensitive, because Sleeper roster strings and contract row
//       names disagree on it.
//   normalizeName        — the ``myRosterNameSet`` handed to
//       buildTopWaiverPool, which keys its rows with normalizeName
//       (backend parity).  A Set built with the compact key would
//       never be hit there, silently un-filtering your own roster
//       out of the add pool.

/**
 * Build the lookup map: roster name (string from selectedTeam.players)
 *   → row object from the public ``rows`` array.
 *
 * Skips players we can't price (no value) and picks (add/drop applies
 * to NFL players only).
 */
export function rosterRowsForTeam(rows, rosterNames) {
  if (!Array.isArray(rows) || !Array.isArray(rosterNames)) return [];
  const byName = new Map();
  for (const r of rows) {
    const k = normalizeNameCompact(r?.name);
    if (k && !byName.has(k)) byName.set(k, r);
  }
  const out = [];
  const seen = new Set();
  for (const name of rosterNames) {
    const k = normalizeNameCompact(name);
    if (!k || seen.has(k)) continue;
    seen.add(k);
    const row = byName.get(k);
    if (!row) continue;
    if (row.assetClass === "pick") continue;
    if ((Number(row.values?.full) || 0) <= 0) continue;
    out.push(row);
  }
  // Lowest value first so natural drop candidates surface at the top.
  return out.sort(
    (a, b) => (Number(a.values?.full) || 0) - (Number(b.values?.full) || 0),
  );
}

/**
 * Always-visible FAAB context — what the user has to spend and what
 * the league usually pays, before any player is picked.
 */
function FaabHeaderStat({ selectedTeam, leagueFaab }) {
  const remaining = selectedTeam?.faabRemaining;
  const budget = selectedTeam?.faabBudget ?? leagueFaab?.leagueBudget;
  const avg = leagueFaab?.leagueAvgWinningBid;
  const median = leagueFaab?.leagueMedianWinningBid;
  if (remaining == null && avg == null) return null;
  return (
    <div className={styles.faabStrip}>
      <StatTile
        label="Your FAAB"
        value={remaining != null ? `$${remaining.toLocaleString()}` : "—"}
        meta={budget ? `of $${budget.toLocaleString()}` : null}
      />
      <StatTile
        label="League average bid"
        value={avg != null && avg > 0 ? `$${Math.round(avg)}` : "—"}
        meta="winning bids"
      />
      <StatTile
        label="League median bid"
        value={median != null && median > 0 ? `$${Math.round(median)}` : "—"}
        meta="winning bids"
      />
    </div>
  );
}

/**
 * Lightweight typeahead picker.  Single-asset selection.
 */
function SidePicker({
  label,
  variant,
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

  const results = useMemo(() => {
    const term = normalizeNameCompact(q);
    if (!term) return pool.slice(0, 8);
    return pool
      .filter((r) => normalizeNameCompact(r?.name).includes(term))
      .slice(0, 8);
  }, [q, pool]);

  const showResults = focused && !selected;

  return (
    <div
      className={`${styles.side} ${
        variant === "drop" ? styles.sideDrop : styles.sideAdd
      }`}
    >
      <span className={styles.sideLabel}>{label}</span>

      {selected ? (
        <SelectedCard
          row={selected}
          valueMode={valueMode}
          settings={settings}
          onClear={onClear}
        />
      ) : (
        <div className={`${styles.sideSearch} trade-side-search`}>
          <Input
            className="trade-side-search-input"
            type="text"
            value={q}
            placeholder={placeholder}
            aria-label={`Search ${label.toLowerCase()} candidates`}
            onChange={(e) => setQ(e.target.value)}
            onFocus={() => setFocused(true)}
            onBlur={() => {
              // Slight delay so a tap/click on a result registers before
              // the dropdown collapses.
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
                      <div className="trade-side-search-result-name">{r.name}</div>
                      <div className="trade-side-search-result-meta">
                        <Badge tone="outline">{r.pos}</Badge>
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
    <div className={styles.selectedCard}>
      <div className={styles.selectedBody}>
        <PlayerImage
          playerId={row.raw?.playerId}
          team={row.team}
          position={row.pos}
          name={row.name}
          size={28}
        />
        <div style={{ minWidth: 0 }}>
          <div className={styles.selectedName}>{row.name}</div>
          <div className={styles.selectedMeta}>
            <Badge tone="outline">{row.pos}</Badge>
            <span>
              {row.blendedSourceRank != null
                ? `#${row.blendedSourceRank.toFixed(1)}`
                : "—"}
            </span>
            <span className={styles.selectedValue}>{v.toLocaleString()}</span>
          </div>
        </div>
      </div>
      <Button variant="ghost" size="sm" onClick={onClear} aria-label="Clear selection">
        Remove
      </Button>
    </div>
  );
}

// ── main component ─────────────────────────────────────────────

export default function ManualAddDrop({
  rows,
  selectedTeam,
  sleeperTeams,
  idpEnabled = true,
  includeRookies = false,
  valueMode = "full",
  settings,
  leagueKey,
  teamLoading = false,
  // Owned by /waivers (persisted in useSettings) and passed straight
  // through to the bid desk — this component has no opinion on it.
  riskPosture = DEFAULT_RISK_POSTURE,
}) {
  const [dropRow, setDropRow] = useState(null);
  const [addRow, setAddRow] = useState(null);
  const [leagueFaab, setLeagueFaab] = useState(null);

  // Fetch league FAAB analytics once per leagueKey.  Lazy public-league
  // section, cached client-side until the key changes.  On failure the
  // context panel simply stays hidden — the bid pills still work
  // because the recommender does its own analytics lookup server-side.
  useEffect(() => {
    if (!leagueKey) {
      setLeagueFaab(null);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch(
          `/api/public/league/faabAnalytics?leagueKey=${encodeURIComponent(leagueKey)}`,
        );
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        // The /api/public/league/{section} endpoint wraps the builder
        // output as ``{section, body}`` so unwrap.
        setLeagueFaab(data?.body || data || null);
      } catch {
        // Silent failure — context panel just stays hidden.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [leagueKey]);

  const dropPool = useMemo(
    () => rosterRowsForTeam(rows, selectedTeam?.players),
    [rows, selectedTeam?.players],
  );

  // Add side: top-50 league-wide pool with position minimums.  Roster-
  // INDEPENDENT on purpose — a strong waiver target is worth evaluating
  // even when it doesn't strictly upgrade the lowest bench filler.
  const addPoolResult = useMemo(() => {
    const ownedNameSet = buildOwnedNameSet(sleeperTeams);
    // normalizeName (NOT the compact key) on purpose — buildTopWaiverPool
    // keys its rows with normalizeName, so this Set must match it.
    const myRosterNameSet = new Set(
      (selectedTeam?.players || []).map(normalizeName).filter(Boolean),
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

  // Both sides populated ⇒ full KTC V13 Value Adjustment.  Otherwise a
  // flat sum so the meter still renders a sensible "0 vs N" preview.
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

  return (
    <Panel
      title="Manual add/drop calculator"
      subtitle="One player out, one in — the trade calculator's fairness bar and per-vendor breakdown, applied to a single transaction."
      aria-label="Manual add/drop calculator"
    >
      {!selectedTeam && teamLoading ? (
        // Hold the settled calculator's height while team identity
        // resolves.  Rendering the short "select a team" message here
        // and then expanding to the full calculator grew this panel
        // 150px -> 646px and pushed the entire page down — the whole
        // of /waivers' 0.22 CLS.
        <SkeletonTable rows={12} columns={3} />
      ) : !selectedTeam ? (
        <p className="muted">
          Select a team below to use the manual add/drop calculator.
        </p>
      ) : (
        <div className={styles.calc}>
          <FaabHeaderStat selectedTeam={selectedTeam} leagueFaab={leagueFaab} />

          <div className={styles.sides}>
            <SidePicker
              label="DROP"
              variant="drop"
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
              variant="add"
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

          {/* Fairness bar — renders an "Even — 0 vs 0" placeholder before
              any selection so the surface is visible up front. */}
          <ResilientSection name="Manual add/drop fairness bar">
            <SharedTradeMeter sides={sides} sideTotals={sideTotals} />
          </ResilientSection>

          {/* Per-vendor breakdown guards on empty assets internally. */}
          <ResilientSection name="Manual add/drop per-source breakdown">
            <SharedTradeSourceBreakdown sides={sides} settings={settings} />
          </ResilientSection>

          {/* FAAB bid desk — fires when an add is selected (drop
              optional).  Isolated so a recommender failure can't take
              down the calculator. */}
          {addRow && (
            <ResilientSection name="Manual add/drop FAAB recommendation">
              <FaabRecommendation
                addPlayer={addRow}
                dropPlayer={dropRow}
                leagueKey={leagueKey}
                ownerId={selectedTeam?.ownerId}
                selectedTeam={selectedTeam}
                leagueFaab={leagueFaab}
                riskPosture={riskPosture}
              />
            </ResilientSection>
          )}

          {/* Monte Carlo — the underlying button computes a no-op state
              when either side is empty. */}
          {dropRow && addRow && (
            <ResilientSection name="Manual add/drop Monte Carlo">
              <MonteCarloButton sides={sides} />
            </ResilientSection>
          )}
        </div>
      )}
    </Panel>
  );
}
