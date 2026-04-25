"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { TRADE_ALPHA } from "@/lib/trade-logic";
import {
  analyzeSleeperTradeHistory,
  analyzeTradeTendencies,
  POS_GROUP_COLORS,
} from "@/lib/league-analysis";
import { encodeTrade, SHARE_PARAM } from "@/lib/trade-share";

const POS_COLORS = {
  QB: "#e74c3c", RB: "#27ae60", WR: "#3498db", TE: "#e67e22",
  PICK: "var(--amber)", DL: "#9b59b6", LB: "#8e44ad", DB: "#16a085",
};

export default function TradesPage() {
  const { rows, rawData, loading, error } = useApp();
  const { settings } = useSettings();
  const [teamFilter, setTeamFilter] = useState("");
  const [playerQuery, setPlayerQuery] = useState("");

  const alpha = settings.alpha || TRADE_ALPHA;
  const windowDays = settings.tradeHistoryWindowDays || 365;

  const analysis = useMemo(
    () => analyzeSleeperTradeHistory(rawData, rows, windowDays, alpha),
    [rawData, rows, windowDays, alpha],
  );

  const teams = useMemo(() => {
    const set = new Set();
    for (const a of analysis.analyzed) {
      for (const s of a.sides) set.add(s.team);
    }
    return [...set].sort();
  }, [analysis]);

  const filtered = useMemo(() => {
    const q = playerQuery.trim().toLowerCase();
    let results = analysis.analyzed;
    if (teamFilter) {
      results = results.filter((a) =>
        a.sides.some((s) => s.team === teamFilter),
      );
    }
    if (q) {
      // Match against every item name on either side of the trade,
      // regardless of whether the player/pick was given or received.
      // ``item.name`` covers both players ("Patrick Mahomes") and
      // picks ("2026 Pick 1.06") so one query input does both.
      const itemMatches = (item) =>
        String(item?.name || "").toLowerCase().includes(q);
      results = results.filter((a) =>
        a.sides.some(
          (s) => (s.got || []).some(itemMatches) || (s.gave || []).some(itemMatches),
        ),
      );
    }
    return results;
  }, [analysis, teamFilter, playerQuery]);

  const tendencies = useMemo(
    () => analyzeTradeTendencies(rawData, rows),
    [rawData, rows],
  );

  if (loading) return <LoadingState message="Loading trade data..." />;
  if (error) return <div className="card"><EmptyState title="Error" message={error} /></div>;

  const hasTrades = analysis.analyzed.length > 0;

  return (
    <section>
      <div className="card">
        <PageHeader
          title="Trade History"
          subtitle={`Analyzing ${analysis.analyzed.length} trades in the last ${windowDays} days using alpha=${alpha}`}
          actions={
            hasTrades && (
              <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                <input
                  className="input"
                  type="search"
                  placeholder="Search player or pick..."
                  value={playerQuery}
                  onChange={(e) => setPlayerQuery(e.target.value)}
                  style={{ minWidth: 200 }}
                />
                {teams.length > 0 && (
                  <select
                    className="input"
                    value={teamFilter}
                    onChange={(e) => setTeamFilter(e.target.value)}
                    style={{ minWidth: 160 }}
                  >
                    <option value="">All teams</option>
                    {teams.map((t) => (
                      <option key={t} value={t}>{t}</option>
                    ))}
                  </select>
                )}
              </div>
            )
          }
        />
      </div>

      {!hasTrades && (
        <div className="card">
          <EmptyState
            title="No trades found"
            message="Load dynasty data with a Sleeper league to see trade history."
          />
        </div>
      )}

      {/* Winners & Losers stats card */}
      {hasTrades && <TeamScoresCard teamScores={analysis.teamScores} alpha={alpha} />}

      {/* Trade tendencies */}
      {hasTrades && tendencies.length > 0 && <TradeTendenciesCard tendencies={tendencies} />}

      {/* Trade list */}
      {filtered.length > 0 && (
        <div className="list" style={{ marginTop: "var(--space-md)" }}>
          {filtered.map((a, idx) => (
            <TradeCard key={idx} analysis={a} />
          ))}
        </div>
      )}

      {(teamFilter || playerQuery) && filtered.length === 0 && (
        <div className="card">
          <EmptyState
            title="No trades match"
            message={
              teamFilter && playerQuery
                ? `No trades for ${teamFilter} involving "${playerQuery}".`
                : playerQuery
                  ? `No trades involving "${playerQuery}".`
                  : `No trades found for ${teamFilter}.`
            }
          />
        </div>
      )}
    </section>
  );
}

function TeamScoresCard({ teamScores, alpha }) {
  // Iterate Object.entries so each card's React key matches the
  // aggregation key (ownerId-first).  Using rosterId alone collides
  // in the orphan-takeover case where two owners share a rosterId.
  const sorted = useMemo(
    () => Object.entries(teamScores).sort((a, b) => b[1].totalGain - a[1].totalGain),
    [teamScores],
  );

  if (!sorted.length) return null;

  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>
        Trade Winners & Losers
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))", gap: 8 }}>
        {sorted.map(([key, s]) => {
          const teamName = s.displayName || "Unknown";
          const netVal = Math.round(Math.pow(Math.abs(s.totalGain), 1 / alpha));
          const netSign = s.totalGain >= 0 ? "+" : "-";
          const netColor = s.totalGain >= 0 ? "var(--green)" : "var(--red)";
          const borderColor = s.totalGain >= 0 ? "var(--green)" : s.totalGain < -50 ? "var(--red)" : "var(--border)";

          return (
            <div
              key={key}
              style={{
                border: "1px solid var(--border)",
                borderLeft: `3px solid ${borderColor}`,
                borderRadius: 6,
                padding: "10px 14px",
              }}
            >
              <div style={{ fontWeight: 700, fontSize: "0.78rem" }}>{teamName}</div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.68rem", color: "var(--subtext)", margin: "2px 0" }}>
                {s.trades} trades &middot; {s.won}W-{s.lost}L
              </div>
              <div style={{ fontFamily: "var(--mono)", fontSize: "0.75rem", fontWeight: 700, color: netColor }}>
                {netSign}{netVal.toLocaleString()} net value
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TradeTendenciesCard({ tendencies }) {
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div style={{ fontWeight: 700, fontSize: "0.82rem", marginBottom: 10 }}>
        Trade Tendencies
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Manager</th>
              <th style={{ textAlign: "right" }}>Trades</th>
              <th style={{ textAlign: "right" }}>Avg Given</th>
              <th style={{ textAlign: "right" }}>Avg Got</th>
              <th style={{ textAlign: "right" }}>Net</th>
              <th>Tendency</th>
            </tr>
          </thead>
          <tbody>
            {tendencies.map((t) => {
              const netColor = t.net >= 0 ? "var(--green)" : "var(--red)";
              const netSign = t.net >= 0 ? "+" : "";
              return (
                <tr key={t.id || t.manager}>
                  <td style={{ fontWeight: 600 }}>{t.manager}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.trades}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.avgGiven.toLocaleString()}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{t.avgGot.toLocaleString()}</td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontWeight: 700, color: netColor }}>
                    {netSign}{t.net.toLocaleString()}
                  </td>
                  <td style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>{t.tendency}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AssetPill({ item }) {
  const posLabel = item.isPick ? "PICK" : item.pos;
  const posColor = item.isPick ? POS_COLORS.PICK : (POS_COLORS[item.pos] || "#9b59b6");
  return (
    <span
      style={{
        fontSize: "0.66rem",
        padding: "2px 6px",
        border: "1px solid var(--border)",
        borderRadius: 4,
        background: "var(--bg-soft)",
      }}
    >
      <span style={{ color: posColor, fontWeight: 700, fontSize: "0.58rem" }}>{posLabel}</span>{" "}
      {item.name}{" "}
      <span style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>{item.val.toLocaleString()}</span>
    </span>
  );
}

function AssetRow({ label, items, total }) {
  return (
    <div style={{ marginBottom: 4 }}>
      <div style={{ fontSize: "0.6rem", color: "var(--subtext)", fontWeight: 600, marginBottom: 2 }}>
        {label} <span style={{ fontFamily: "var(--mono)", fontWeight: 400 }}>({Math.round(total).toLocaleString()})</span>
      </div>
      {items.length === 0 ? (
        <div style={{ fontSize: "0.62rem", color: "var(--subtext)", fontStyle: "italic" }}>—</div>
      ) : (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {items.map((item, j) => (
            <AssetPill key={j} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function TradeCard({ analysis: a }) {
  // Headline reflects the largest grievance — winner OR loser,
  // whichever has the biggest magnitude pctGap.  If no side clears
  // ±3%, the trade reads as fair on both the card header and the
  // per-side grades.
  const showBadge = a.pctGap >= 3 && a.headlineSide;
  const isLoserHeadline = showBadge && a.headlineDirection === "overpaid";
  const badgeBg = isLoserHeadline ? "var(--red-soft)" : "var(--green-soft)";
  const badgeColor = isLoserHeadline ? "var(--red)" : "var(--green)";
  const borderColor = isLoserHeadline ? "var(--red)" : "var(--green)";

  // Build a /trade?share=... href so clicking the card pre-loads the
  // trade in the calculator.  Each calculator side mirrors what that
  // historical team RECEIVED, which is the natural visualization
  // ("show me what this trade looked like as a 2-team deal").  Picks
  // and players come through with their canonical names so the
  // calculator's rowByName lookup resolves them on hydration.
  const shareHref = useMemo(() => {
    try {
      const teamPlayerNames = (items) =>
        (items || [])
          .map((it) => String(it?.name || "").trim())
          .filter(Boolean);
      const sides = (a.sides || []).map((side) => ({
        name: String(side?.team || "").slice(0, 40),
        players: teamPlayerNames(side.got),
      }));
      // ``encodeTrade`` rejects empty sides arrays; defensively
      // fall back to a non-clickable card if the data is malformed.
      if (sides.length < 2 || sides.every((s) => s.players.length === 0)) {
        return null;
      }
      const encoded = encodeTrade({ sides });
      return `/trade?${SHARE_PARAM}=${encoded}`;
    } catch {
      return null;
    }
  }, [a.sides]);

  const cardContent = (
    <>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <span style={{ fontSize: "0.68rem", color: "var(--subtext)" }}>
          Week {a.trade.week} &middot; {a.date}
        </span>
        {showBadge ? (
          <span className="badge" style={{ background: badgeBg, color: badgeColor }}>
            {a.headlineSide.team}{" "}
            {a.headlineDirection === "overpaid" ? "overpaid by" : "won by"}{" "}
            {a.pctGap.toFixed(1)}%
          </span>
        ) : (
          <span className="badge" style={{ background: "var(--green-soft)", color: "var(--green)" }}>
            Fair trade
          </span>
        )}
      </div>

      {/* Sides: each shows Gave + Got + Net so 3+ team trades are legible. */}
      <div
        className="grid-responsive"
        style={{
          display: "grid",
          gridTemplateColumns: a.sides.length > 2 ? "1fr 1fr 1fr" : "1fr 1fr",
          gap: 12,
        }}
      >
        {a.sides.map((side, i) => {
          const grade = side.grade;
          const netColor = side.pctGap >= 3
            ? "var(--green)"
            : side.pctGap <= -3
              ? "var(--red)"
              : "var(--subtext)";
          const netSign = side.netValue >= 0 ? "+" : "−";
          return (
            <div key={i}>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                <span style={{ fontWeight: 600, fontSize: "0.74rem" }}>{side.team}</span>
                {grade && (
                  <>
                    <span style={{ fontSize: "0.72rem", fontWeight: 800, color: grade.color }}>{grade.grade}</span>
                    <span style={{ fontSize: "0.52rem", color: "var(--subtext)" }}>{grade.label}</span>
                  </>
                )}
              </div>
              <AssetRow label="Gave" items={side.gave} total={side.gaveValue} />
              <AssetRow label="Got" items={side.got} total={side.gotValue} />
              <div style={{
                fontFamily: "var(--mono)",
                fontSize: "0.62rem",
                color: netColor,
                fontWeight: 600,
                marginTop: 2,
              }}>
                Net: {netSign}{Math.abs(Math.round(side.netValue)).toLocaleString()}
                {" "}({side.pctGap >= 0 ? "+" : ""}{side.pctGap.toFixed(1)}%)
              </div>
            </div>
          );
        })}
      </div>

      {/* Click-to-import affordance — hint at bottom so users learn
          the card is interactive without forcing them to discover it. */}
      {shareHref && (
        <div style={{
          marginTop: 8,
          paddingTop: 8,
          borderTop: "1px dashed var(--border)",
          fontSize: "0.62rem",
          color: "var(--subtext)",
          textAlign: "right",
          fontStyle: "italic",
        }}>
          Click to open in trade calculator →
        </div>
      )}
    </>
  );

  // When a valid share URL was built, wrap the card content in a
  // Next ``Link`` so click navigates the user to ``/trade?share=...``
  // with the trade pre-loaded.  The trade page's existing share-URL
  // hydration code (frontend/app/trade/page.jsx, "Share-URL decoder")
  // resolves the player names against ``rowByName`` and populates
  // both sides on mount.  Falls back to a plain card when the trade
  // can't be encoded (malformed data, empty sides, etc.).
  const cardStyle = {
    borderLeft: `3px solid ${borderColor}`,
    cursor: shareHref ? "pointer" : "default",
    // Inherit the card's normal text color even when wrapped in a
    // <Link> (which would otherwise paint everything in the link
    // accent color).
    color: "inherit",
    textDecoration: "none",
    display: "block",
  };

  if (shareHref) {
    return (
      <Link
        href={shareHref}
        className="card"
        style={cardStyle}
        aria-label={`Open this trade in the calculator`}
      >
        {cardContent}
      </Link>
    );
  }

  return (
    <div className="card" style={{ borderLeft: `3px solid ${borderColor}` }}>
      {cardContent}
    </div>
  );
}
