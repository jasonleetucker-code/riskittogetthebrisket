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
 *   - effectiveValue + adjustedSideTotals from
 *     lib/trade-logic (active package Value Adjustment math)
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

import { useEffect, useId, useMemo, useRef, useState } from "react";

import { adjustedSideTotals, effectiveValue } from "@/lib/trade-logic";
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

// ── league FAAB analytics read ─────────────────────────────────
//
// The read of `/api/public/league/faabAnalytics` has four states, kept
// apart on purpose: "no data yet" and "no data to be had" are different
// facts, and neither is a $0.  `data` is only ever the section body the
// backend served (src/api/faab_analytics.py) -- this component derives
// nothing from it beyond display rounding.
const FEED_IDLE = Object.freeze({ status: "idle", data: null, reason: null });
const FEED_LOADING = Object.freeze({ status: "loading", data: null, reason: null });
const feedUnavailable = (reason) => ({ status: "unavailable", data: null, reason });
const feedReady = (data) => ({ status: "ready", data, reason: null });

/**
 * Always-visible FAAB context -- what the league usually pays, and (with
 * a team selected) what that team has left to spend.
 *
 * The two halves are independent.  The league figures are a property of
 * the LEAGUE (`faabAnalytics` is fetched by `leagueKey`), so they render
 * whether or not a fantasy team is selected; only "Your FAAB" needs a
 * team, and without one it stays unknown ("—"), never $0 (V1-56 / #1151).
 */
function FaabHeaderStat({ selectedTeam, leagueFaab, feed }) {
  const hasTeam = Boolean(selectedTeam);
  const remaining = selectedTeam?.faabRemaining;
  const budget = selectedTeam?.faabBudget ?? leagueFaab?.leagueBudget;
  const avg = leagueFaab?.leagueAvgWinningBid;
  const median = leagueFaab?.leagueMedianWinningBid;

  // MISSING != ZERO.  These tiles used to gate on `avg > 0` / `median > 0`,
  // which displayed a MEASURED zero exactly like an absent observation.
  // That is not a hypothetical: `src/api/faab_analytics.py:278-288`
  // deliberately KEEPS $0 bids, because dropping them overstated the
  // median by ~200x when 41-77% of adds cost nothing in a season. "The
  // median winning bid is $0" is this league's most common answer, and
  // the strip was hiding it.
  //
  // The value alone cannot disambiguate — the backend emits 0.0 both for
  // an empty pool and a genuinely-zero one — so gate on the evidence
  // count it publishes for exactly this purpose.  `!= null` rather than
  // truthiness, so a legitimately-zero count is still a count.
  const analyzed = leagueFaab?.totalBidsAnalyzed;
  const hasBidHistory =
    analyzed != null
      ? analyzed > 0
      : // Older or partial payloads may omit the count. A nonzero mean or
        // median cannot arise from zero samples, so it is safe to infer
        // that observations exist — but a zero with no count stays
        // ambiguous, and ambiguous renders as unknown rather than as $0.
        (avg != null && avg > 0) || (median != null && median > 0);

  // One league tile.  Every non-measured outcome is "—" PLUS the reason,
  // so an unavailable figure never reads as a zero and never silently
  // vanishes (UI contract §9: loading / unavailable / missing / zero are
  // distinct states).
  const leagueBid = (v) => {
    if (feed.status === "idle") return { value: "—", meta: "waiting for league" };
    if (feed.status === "loading") return { value: "—", meta: "loading…" };
    if (feed.status === "unavailable") {
      return { value: "—", meta: `unavailable: ${feed.reason}` };
    }
    if (hasBidHistory) {
      return v != null
        ? { value: `$${Math.round(v)}`, meta: "winning bids" }
        : { value: "—", meta: "not reported" };
    }
    return {
      value: "—",
      meta: analyzed === 0 ? "no winning bids on record" : "bid count not reported",
    };
  };
  const avgTile = leagueBid(avg);
  const medianTile = leagueBid(median);

  // `budget != null`, not truthiness: a $0 budget is a real setting, and
  // hiding the line would be the same defect one tile over.  Without a
  // team there is no balance to show -- unknown, with the reason stated.
  let yourMeta = null;
  if (!hasTeam) yourMeta = "select a team";
  else if (remaining == null) yourMeta = "balance not reported";
  else if (budget != null) yourMeta = `of $${budget.toLocaleString()}`;

  return (
    <div
      className={styles.faabStrip}
      role="group"
      aria-label="League FAAB context"
      data-faab-state={
        feed.status === "ready" ? (hasBidHistory ? "measured" : "no-history") : feed.status
      }
    >
      <StatTile
        label="Your FAAB"
        value={remaining != null ? `$${remaining.toLocaleString()}` : "—"}
        meta={yourMeta}
      />
      <StatTile label="League average bid" value={avgTile.value} meta={avgTile.meta} />
      <StatTile label="League median bid" value={medianTile.value} meta={medianTile.meta} />
    </div>
  );
}

/**
 * Typeahead picker — a WAI-ARIA combobox + listbox.  Single-asset selection.
 *
 * Why not the ds ``Combobox``: its options are a text label + one line of
 * description, while a pick here has to show the headshot, the position
 * badge, the source rank and the board value the meter will use; and it
 * lists every option, where the add pool runs past fifty.  So this mirrors
 * the calculator's own inline search (app/trade/trade-sections.jsx, TC-E)
 * and its ``.trade-side-search-*`` styles, ``[data-active]`` ring included.
 *
 * Keyboard (the defect this fixed: results answered only mouse-down and
 * touch, and the list closed 120 ms after focus left the INPUT, so a
 * keyboard user could neither reach nor activate a result):
 *   - focus stays in the input and points at the active option with
 *     ``aria-activedescendant``; ArrowDown / ArrowUp move it (Home / End
 *     stay with the text caret, as on /trade), Enter picks it, Escape
 *     closes the list;
 *   - every option also answers a plain ``click`` (keyboard activation and
 *     screen-reader virtual-cursor activation send a click with no
 *     mouse-down);
 *   - the list closes only when focus leaves the WHOLE picker, never on a
 *     timer, so moving focus onto an option cannot unmount it;
 *   - after a pick focus moves to that side's clear button, and after a
 *     clear it returns to the search input — it is never dropped on <body>.
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
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const pickerRef = useRef(null);
  // Where focus goes after the next selection change: the clear button
  // after a pick, the search input after a clear.  Null when the change
  // did not come from this picker (e.g. the parent resetting it).
  const focusAfterChange = useRef(null);
  const baseId = useId();
  const listId = `${baseId}-list`;
  const optionId = (i) => `${baseId}-opt-${i}`;
  const sideName = String(label || "").toLowerCase();
  const sideTitle = sideName.charAt(0).toUpperCase() + sideName.slice(1);

  const results = useMemo(() => {
    const term = normalizeNameCompact(q);
    if (!term) return pool.slice(0, 8);
    return pool
      .filter((r) => normalizeNameCompact(r?.name).includes(term))
      .slice(0, 8);
  }, [q, pool]);

  const showResults = open && !selected;
  const hasOptions = showResults && results.length > 0;
  const activeIndex = hasOptions && active >= 0 && active < results.length ? active : -1;

  useEffect(() => {
    const target = focusAfterChange.current;
    if (!target) return;
    focusAfterChange.current = null;
    const el = pickerRef.current?.querySelector(
      target === "clear" ? "[data-picker-clear]" : "input",
    );
    el?.focus();
  }, [selected]);

  useEffect(() => {
    if (activeIndex < 0) return;
    // Optional call: jsdom has no scrollIntoView.
    document
      .getElementById(`${baseId}-opt-${activeIndex}`)
      ?.scrollIntoView?.({ block: "nearest" });
  }, [activeIndex, baseId]);

  const choose = (r) => {
    if (!r) return;
    focusAfterChange.current = "clear";
    onSelect(r);
    setQ("");
    setOpen(false);
    setActive(-1);
  };

  const clear = () => {
    focusAfterChange.current = "input";
    onClear();
  };

  const onKeyDown = (e) => {
    const n = results.length;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!n) return;
      e.preventDefault();
      if (!showResults) {
        setOpen(true);
        setActive(e.key === "ArrowDown" ? 0 : n - 1);
        return;
      }
      if (e.key === "ArrowDown") setActive(activeIndex < 0 ? 0 : Math.min(activeIndex + 1, n - 1));
      else setActive(activeIndex <= 0 ? n - 1 : activeIndex - 1);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      choose(results[activeIndex]);
    } else if (e.key === "Escape" && showResults) {
      e.preventDefault();
      setOpen(false);
      setActive(-1);
    }
  };

  return (
    <div
      ref={pickerRef}
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
          onClear={clear}
          clearLabel={`Clear ${sideName} selection`}
        />
      ) : (
        <div
          className={`${styles.sideSearch} trade-side-search`}
          onBlur={(e) => {
            // Close only when focus leaves the whole picker (input AND
            // list).  A press on an option keeps focus in the input
            // (mouse-down is prevented), and focus that does land on an
            // option stays inside this container — neither closes it.
            if (!e.currentTarget.contains(e.relatedTarget)) {
              setOpen(false);
              setActive(-1);
            }
          }}
        >
          <Input
            className="trade-side-search-input"
            type="text"
            value={q}
            placeholder={placeholder}
            aria-label={`Search ${sideName} candidates`}
            role="combobox"
            aria-autocomplete="list"
            aria-expanded={hasOptions}
            aria-controls={hasOptions ? listId : undefined}
            aria-activedescendant={activeIndex >= 0 ? optionId(activeIndex) : undefined}
            autoComplete="off"
            onChange={(e) => {
              setQ(e.target.value);
              setOpen(true);
              setActive(-1);
            }}
            onFocus={() => setOpen(true)}
            onClick={() => setOpen(true)}
            onKeyDown={onKeyDown}
          />
          {showResults && (
            pool.length === 0 || results.length === 0 ? (
              <div className="trade-side-search-results">
                <div className="trade-side-search-empty muted" role="status">
                  {pool.length === 0 ? emptyMsg : "No matches."}
                </div>
              </div>
            ) : (
              <div
                className="trade-side-search-results"
                role="listbox"
                id={listId}
                aria-label={`${sideTitle} candidates`}
              >
                {results.map((r, i) => (
                  <button
                    key={`pick-${label}-${r.name}`}
                    id={optionId(i)}
                    type="button"
                    role="option"
                    aria-selected={i === activeIndex}
                    tabIndex={-1}
                    data-active={i === activeIndex || undefined}
                    className="trade-side-search-result button-reset"
                    onMouseDown={(e) => {
                      // Keep focus in the input so the list stays put
                      // under the pointer, and pick on the press.
                      e.preventDefault();
                      choose(r);
                    }}
                    // Keyboard, assistive-technology AND touch activation
                    // arrive as a click.  There is deliberately no
                    // ``onTouchStart`` pick: React attaches touchstart as a
                    // passive listener, so its preventDefault was ignored —
                    // starting to scroll the list by touch picked the row
                    // under the finger, and the tap's compatibility click
                    // then landed on whatever replaced the list.  Picking
                    // the same row twice is idempotent.
                    onClick={() => choose(r)}
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
                ))}
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}

function SelectedCard({ row, valueMode, settings, onClear, clearLabel = "Clear selection" }) {
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
      {/* One name per side ("Clear drop selection" / "Clear add selection"):
          two identical "Clear selection" buttons were indistinguishable in a
          screen reader's button list.  The visible word is part of the name
          (WCAG 2.5.3, label in name), so voice control can say "Clear". */}
      <Button
        variant="ghost"
        size="sm"
        onClick={onClear}
        aria-label={clearLabel}
        data-picker-clear="true"
      >
        Clear
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
  const [faabFeed, setFaabFeed] = useState(() =>
    leagueKey ? FEED_LOADING : FEED_IDLE,
  );
  // The section body (or null) -- the shape FaabRecommendation consumes.
  const leagueFaab = faabFeed.data;

  // Fetch league FAAB analytics once per leagueKey.  Lazy public-league
  // section, independent of team selection.  A failure is STATED on the
  // league tiles (unavailable + reason) rather than hidden or zeroed --
  // the bid pills still work because the recommender does its own
  // analytics lookup server-side.
  useEffect(() => {
    if (!leagueKey) {
      setFaabFeed(FEED_IDLE);
      return;
    }
    let cancelled = false;
    // Another league's figures are not "useful prior content" for this
    // one -- drop them rather than show them under the new league's name.
    setFaabFeed(FEED_LOADING);
    (async () => {
      try {
        const res = await fetch(
          `/api/public/league/faabAnalytics?leagueKey=${encodeURIComponent(leagueKey)}`,
        );
        if (cancelled) return;
        if (!res.ok) {
          setFaabFeed(feedUnavailable(`HTTP ${res.status}`));
          return;
        }
        const data = await res.json();
        if (cancelled) return;
        // The /api/public/league/{section} endpoint wraps the builder
        // output as ``{contractVersion, league, section, data}`` — the
        // body is under ``data``, never ``body``.  Unwrapping ``body``
        // and falling through to the envelope itself put every field
        // this strip reads (leagueBudget, leagueAvgWinningBid,
        // leagueMedianWinningBid) one level too high, so the tiles
        // rendered an em-dash against a response carrying the real
        // numbers — indistinguishable from a league with no FAAB
        // history (W11-F006).  No ``|| data`` fallback: a payload
        // without ``data`` has no section body, and pretending the
        // envelope is one is what produced the silent failure.
        const body = data?.data;
        setFaabFeed(
          body && typeof body === "object"
            ? feedReady(body)
            : feedUnavailable("response carried no analytics"),
        );
      } catch {
        if (!cancelled) setFaabFeed(feedUnavailable("request failed"));
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

  // Always the package model's own totals (active model).  With one side
  // empty the Value Adjustment is 0, so the meter still reads "0 vs N" -- and
  // every total carries its package `utility`, which the fairness band's base
  // reads (fairness_bands_v2).  A hand-built flat-sum total here had no
  // utility, so the meter's base was refused as soon as ONE side was picked.
  const sideTotals = useMemo(
    () => adjustedSideTotals(sides[0].assets, sides[1].assets, valueMode, settings),
    [sides, valueMode, settings],
  );

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
        // League-level FAAB context is a property of the league, not of a
        // team (V1-56 / #1151): it renders here too.  Only the add/drop
        // controls need a selected team.
        <div className={styles.calc}>
          <FaabHeaderStat selectedTeam={null} leagueFaab={leagueFaab} feed={faabFeed} />
          <p className="muted">
            Select a team below to use the manual add/drop calculator.
          </p>
        </div>
      ) : (
        <div className={styles.calc}>
          <FaabHeaderStat
            selectedTeam={selectedTeam}
            leagueFaab={leagueFaab}
            feed={faabFeed}
          />

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
