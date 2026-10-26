"use client";

import { useEffect, useMemo, useState } from "react";

import {
  Movement,
  Panel,
  PlayerNameButton,
  SegmentedControl,
  SkeletonTable,
  canonicalPlayerId,
} from "@/components/ds";
import styles from "./terminal.module.css";
import { PlayerImage } from "@/components/ui";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";
import { classifyContractFailure } from "@/lib/contract-failure";
import { valuationBasisOf } from "@/lib/dynasty-data";

// Movers — buy-low / sell-high signals derived from rank-history.
//
// Pulls from ``/api/movers`` (server.py wrapper around
// ``data/rank_history.jsonl``), shows the top risers + fallers, and
// expands a per-source rank breakdown on click so the user can see
// WHICH sources drove the move.  Defaults to a 14-day window with a
// 15-rank threshold, both adjustable.
//
// Sits next to the existing ``PlayerMarketMovement`` (value-trend
// view) and ``BuySellHold`` (signal-engine view) — this widget is
// the rank-delta-with-source-attribution view.
//
// League scope (LI1842-DEFECT-03): the request carries the ACTIVE league's
// key, the same one ``useTerminal`` / ``useTeam`` send.  Without it the
// server resolves a league from saved user state, and now that ``/api/movers``
// follows the board's scoring-identity gate it answers 503 ``data_not_ready``
// for a league whose scoring is not proven identical to the loaded board's.
// That is a state of the data, not a failure of the panel, so it renders as
// "unavailable" with the server's reason instead of the raw status code.

const WINDOW_OPTIONS = [
  { days: 7, label: "7d" },
  { days: 14, label: "14d" },
  { days: 30, label: "30d" },
];

// Asset-class label used when the contract has no NFL position stamped
// (picks, or IDP/offense rows that have rolled off the live board).
// Keeps the meta line readable instead of showing a bare "?".
const ASSET_LABELS = {
  pick: "Pick",
  idp: "IDP",
  offense: "OFF",
};

function describePosition(row) {
  const pos = (row.position || "").trim().toUpperCase();
  if (pos) return pos;
  const ac = String(row.assetClass || "").trim().toLowerCase();
  return ASSET_LABELS[ac] || "—";
}

function MoverRow({ row, openPlayerPopup }) {
  const [expanded, setExpanded] = useState(false);
  const posLabel = describePosition(row);

  return (
    <div
      className={styles.moverRow}
      onClick={() => setExpanded((v) => !v)}
    >
      <div className={styles.moverMain}>
        <PlayerImage
          playerId={row.playerId}
          team={row.team}
          position={row.position}
          name={row.name}
          size={22}
        />
        <div className={styles.moverIdentity}>
          <div className={styles.moverName}>
            {/* #1337: canonical Player File link (keyed by the /api/movers
                row's playerId; no id → plain text). stopPropagation keeps
                the click from also toggling the row's source breakdown;
                the quick-view stays on the expanded "Open player" button. */}
            <PlayerNameButton
              name={row.name}
              playerId={canonicalPlayerId(row)}
              onClick={(e) => e.stopPropagation()}
            />
          </div>
          <div className={styles.moverMeta}>
            {posLabel}
            {row.team ? ` · ${row.team}` : ""} · #{row.rankNow}
            {row.valueNow ? ` · ${row.valueNow.toLocaleString()}` : ""}
          </div>
        </div>
        <div
          className={styles.moverDelta}
          title={`Was #${row.rankThen}, now #${row.rankNow}`}
        >
          <Movement
            delta={row.delta}
            srLabel={`${row.delta > 0 ? "up" : "down"} ${Math.abs(row.delta)} ranks, was #${row.rankThen}`}
          />
          <span className={styles.moverFrom}>from #{row.rankThen}</span>
        </div>
      </div>
      {expanded && row.currentSourceRanks && (
        <div className={styles.moverSources}>
          {Object.entries(row.currentSourceRanks).map(([src, rank]) => (
            <span key={src} className={styles.moverSourceChip} title={`${src}: rank ${rank}`}>
              <span className={styles.moverSourceName}>{src}</span>{" "}
              <span className={styles.moverSourceRank}>#{rank}</span>
            </span>
          ))}
          {openPlayerPopup && (
            <button
              type="button"
              className={styles.moverOpen}
              onClick={(e) => {
                e.stopPropagation();
                // Look up the row in the live rankings + open the
                // popup so the user gets the full per-source detail.
                // Pass ``assetClass`` so cross-universe name
                // collisions (offense vs IDP) resolve to the right
                // contract row downstream.
                openPlayerPopup({ name: row.name, assetClass: row.assetClass });
              }}
            >
              Open player
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function MoversPanel() {
  const { openPlayerPopup, rawData } = useApp();
  // Movers are MARKET rank deltas and cannot follow the league lens.
  //
  // This is a real divergence, not a missing label. `/api/movers` reads
  // `data/rank_history.jsonl`, a daily snapshot of the market board's
  // ranks. No league-adjusted rank history exists — the adjustment is
  // computed per request from the current rosters, and has never been
  // recorded over time. So on a league-adjusted board this panel is
  // reporting movement on a different board from the values beside it,
  // and there is no fix short of recording adjusted history.
  //
  // Say so. A "-14" next to an adjusted value that the user reads as
  // "this player fell 14 on my board" is a wrong conclusion the panel
  // invited.
  const marketOnlyNotice = valuationBasisOf(rawData) === "leagueAdjusted";
  const [windowDays, setWindowDays] = useState(14);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  // The server declined to serve movers for this league (503 data_not_ready):
  // an expected, explained state, distinct from a request that broke.
  const [unavailable, setUnavailable] = useState(null);
  const { selectedLeagueKey, loading: leagueLoading } = useLeague();

  useEffect(() => {
    // Hold the request until the league registry has resolved the active
    // key, so the first (and only) request already names its league.
    if (leagueLoading) return undefined;
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      setUnavailable(null);
      try {
        const params = new URLSearchParams({
          window: String(windowDays),
          threshold: "15",
          limit: "8",
        });
        if (selectedLeagueKey) params.set("leagueKey", selectedLeagueKey);
        const res = await fetch(`/api/movers?${params.toString()}`, { credentials: "include" });
        if (!res.ok) {
          let body = null;
          try {
            body = await res.json();
          } catch {
            body = null;
          }
          const failure = classifyContractFailure(res.status, body);
          if (!cancelled) {
            setData(null);
            if (failure.kind === "degraded") setUnavailable(failure.message);
            else setError(failure.message);
          }
          return;
        }
        const json = await res.json();
        if (!cancelled) setData(json);
      } catch (err) {
        if (!cancelled) setError(err.message || "fetch failed");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    run();
    return () => { cancelled = true; };
  }, [windowDays, selectedLeagueKey, leagueLoading]);

  const risers = data?.risers || [];
  const fallers = data?.fallers || [];

  return (
    <Panel
      title="Top movers"
      subtitle={
        marketOnlyNotice
          ? `Market rank deltas vs. ${windowDays}d ago · not adjusted for your league — no adjusted rank history exists`
          : `Rank deltas vs. ${windowDays}d ago · click a row for source breakdown`
      }
      actions={
        <SegmentedControl
          options={WINDOW_OPTIONS.map((o) => ({ value: o.days, label: o.label }))}
          value={windowDays}
          onChange={setWindowDays}
          label="Mover window"
        />
      }
    >
      {(loading || leagueLoading) && (
        // Sized to the settled two-column shape (up to 8 movers per
        // side) — the old 4-line text skeleton was ~10x too short and
        // the panel grew ~500px when data landed.
        <div className={styles.moverColumns}>
          <div className={styles.moverColumn}>
            <SkeletonTable rows={8} columns={2} />
          </div>
          <div className={styles.moverColumn}>
            <SkeletonTable rows={8} columns={2} />
          </div>
        </div>
      )}
      {error && <p className={styles.moverError}>{error}</p>}
      {unavailable && (
        <p className={styles.moverEmpty} role="status">
          Movers are unavailable for this league right now. {unavailable}
        </p>
      )}
      {!loading && !leagueLoading && !error && !unavailable && (
        <div className={styles.moverColumns}>
          <div className={styles.moverColumn}>
            {/* A riser's price has already gone UP, so it is a candidate to
                sell HIGH — not to buy low.  These two headings were the
                wrong way round (audit finding S-8): the panel instructed
                the user to buy what had just appreciated and sell what had
                just depreciated, the inverse of both phrases, on the
                terminal's most prominent movement widget. */}
            <h3 className={`${styles.moverColumnTitle} ${styles.moverColumnTitleUp}`}>
              Risers — sell-high candidates
            </h3>
            {risers.length === 0 ? (
              <p className={styles.moverEmpty}>No qualifying movers in this window.</p>
            ) : (
              risers.map((r) => (
                <MoverRow
                  key={`up-${r.name}::${r.assetClass || "x"}`}
                  row={r}
                  openPlayerPopup={openPlayerPopup}
                />
              ))
            )}
          </div>
          <div className={styles.moverColumn}>
            <h3 className={`${styles.moverColumnTitle} ${styles.moverColumnTitleDown}`}>
              Fallers — buy-low candidates
            </h3>
            {fallers.length === 0 ? (
              <p className={styles.moverEmpty}>No qualifying movers in this window.</p>
            ) : (
              fallers.map((r) => (
                <MoverRow
                  key={`down-${r.name}::${r.assetClass || "x"}`}
                  row={r}
                  openPlayerPopup={openPlayerPopup}
                />
              ))
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
