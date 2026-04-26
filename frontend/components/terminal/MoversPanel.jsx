"use client";

import { useEffect, useMemo, useState } from "react";

import Panel from "./Panel";
import { PlayerImage } from "@/components/ui";
import { useApp } from "@/components/AppShell";

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

const WINDOW_OPTIONS = [
  { days: 7, label: "7d" },
  { days: 14, label: "14d" },
  { days: 30, label: "30d" },
];

function MoverRow({ row, openPlayerPopup }) {
  const [expanded, setExpanded] = useState(false);
  const tone = row.delta > 0 ? "var(--green)" : "var(--red)";
  const arrow = row.delta > 0 ? "▲" : "▼";

  return (
    <div
      style={{
        borderBottom: "1px solid var(--border)",
        padding: "6px 4px",
        cursor: "pointer",
      }}
      onClick={() => setExpanded((v) => !v)}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <PlayerImage
          playerId={row.playerId}
          team={row.team}
          position={row.position}
          name={row.name}
          size={22}
        />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: "0.78rem", fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {row.name}
          </div>
          <div style={{ fontSize: "0.62rem", color: "var(--subtext)" }}>
            {row.position || "?"}
            {row.team ? ` · ${row.team}` : ""} · #{row.rankNow}
            {row.valueNow ? ` · ${row.valueNow.toLocaleString()}` : ""}
          </div>
        </div>
        <div
          style={{
            fontFamily: "var(--mono)",
            color: tone,
            fontWeight: 700,
            fontSize: "0.78rem",
            textAlign: "right",
            minWidth: 60,
          }}
          title={`Was #${row.rankThen}, now #${row.rankNow}`}
        >
          {arrow}{Math.abs(row.delta)}
          <div style={{ fontSize: "0.56rem", color: "var(--subtext)", fontWeight: 400 }}>
            from #{row.rankThen}
          </div>
        </div>
      </div>
      {expanded && row.currentSourceRanks && (
        <div
          style={{
            marginTop: 6,
            padding: "6px 4px",
            background: "rgba(8, 19, 44, 0.4)",
            borderRadius: 6,
            display: "flex",
            flexWrap: "wrap",
            gap: 4,
            fontSize: "0.62rem",
            fontFamily: "var(--mono)",
          }}
        >
          {Object.entries(row.currentSourceRanks).map(([src, rank]) => (
            <span
              key={src}
              style={{
                background: "rgba(255, 199, 4, 0.06)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                padding: "2px 6px",
              }}
              title={`${src}: rank ${rank}`}
            >
              <span style={{ color: "var(--subtext)" }}>{src}</span>{" "}
              <span style={{ color: "var(--cyan)" }}>#{rank}</span>
            </span>
          ))}
          {openPlayerPopup && (
            <button
              type="button"
              className="button-reset"
              onClick={(e) => {
                e.stopPropagation();
                // Look up the row in the live rankings + open the
                // popup so the user gets the full per-source detail.
                openPlayerPopup({ name: row.name });
              }}
              style={{
                marginLeft: "auto",
                color: "var(--cyan)",
                fontSize: "0.62rem",
                cursor: "pointer",
                textDecoration: "underline dotted",
              }}
            >
              Open player →
            </button>
          )}
        </div>
      )}
    </div>
  );
}

export default function MoversPanel() {
  const { openPlayerPopup } = useApp();
  const [windowDays, setWindowDays] = useState(14);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function run() {
      setLoading(true);
      setError(null);
      try {
        const url = `/api/movers?window=${windowDays}&threshold=15&limit=8`;
        const res = await fetch(url, { credentials: "include" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
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
  }, [windowDays]);

  const risers = data?.risers || [];
  const fallers = data?.fallers || [];

  return (
    <Panel
      title="Top movers"
      subtitle={`Rank deltas vs. ${windowDays}d ago · click a row for source breakdown`}
      actions={
        <div style={{ display: "flex", gap: 4 }}>
          {WINDOW_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              className="button"
              onClick={() => setWindowDays(opt.days)}
              style={{
                padding: "2px 8px",
                fontSize: "0.66rem",
                minHeight: "unset",
                borderColor: opt.days === windowDays ? "var(--cyan)" : "var(--border)",
                color: opt.days === windowDays ? "var(--cyan)" : "var(--subtext)",
              }}
            >
              {opt.label}
            </button>
          ))}
        </div>
      }
    >
      {loading && <div className="muted" style={{ fontSize: "0.72rem", padding: 8 }}>Loading…</div>}
      {error && <div style={{ fontSize: "0.72rem", color: "var(--red)", padding: 8 }}>{error}</div>}
      {!loading && !error && (
        <div className="row" style={{ gap: 12, alignItems: "stretch" }}>
          <div style={{ flex: "1 1 220px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--green)", fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>
              Risers — buy-low candidates
            </div>
            {risers.length === 0 ? (
              <div className="muted" style={{ fontSize: "0.7rem", padding: "6px 0" }}>
                No qualifying movers in this window.
              </div>
            ) : (
              risers.map((r) => (
                <MoverRow key={`up-${r.name}`} row={r} openPlayerPopup={openPlayerPopup} />
              ))
            )}
          </div>
          <div style={{ flex: "1 1 220px" }}>
            <div style={{ fontSize: "0.62rem", color: "var(--red)", fontWeight: 700, textTransform: "uppercase", marginBottom: 4 }}>
              Fallers — sell-high candidates
            </div>
            {fallers.length === 0 ? (
              <div className="muted" style={{ fontSize: "0.7rem", padding: "6px 0" }}>
                No qualifying movers in this window.
              </div>
            ) : (
              fallers.map((r) => (
                <MoverRow key={`down-${r.name}`} row={r} openPlayerPopup={openPlayerPopup} />
              ))
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
