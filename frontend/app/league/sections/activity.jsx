"use client";

// ActivitySection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { useMemo, useState } from "react";
import { Avatar, Card, EmptyCard, Stat, nameFor } from "../shared.jsx";

function ActivitySection({ managers, data, onNavigate }) {
  const feed = data?.feed || [];
  const [filter, setFilter] = useState("");
  if (!feed.length && !data?.totalCount) return <EmptyCard label="Trade activity" />;

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    if (!q) return feed;
    return feed.filter((t) => {
      const tokens = [
        t.season,
        t.week,
        ...(t.sides || []).map((s) => s.displayName),
        ...(t.sides || []).flatMap((s) => (s.receivedAssets || []).map((a) => a.playerName || "")),
      ].filter(Boolean).join(" ").toLowerCase();
      return tokens.includes(q);
    });
  }, [feed, filter]);

  return (
    <>
      <Card title="Trade activity" subtitle={`${data.totalCount} completed trades across the last 2 seasons`}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10, marginBottom: 12 }}>
          <Stat label="Picks moved" value={data.picksMovedCount || 0} />
          <Stat label="Players moved" value={data.playersMovedCount || 0} />
          <Stat
            label="Most active trader"
            value={data.mostActiveTrader?.displayName || "—"}
            sub={data.mostActiveTrader ? `${data.mostActiveTrader.trades} trades` : ""}
          />
          <Stat
            label="Top partner pair"
            value={data.mostFrequentPartnerPair?.displayNames?.join(" + ") || "—"}
            sub={data.mostFrequentPartnerPair ? `${data.mostFrequentPartnerPair.trades} deals` : ""}
          />
        </div>
      </Card>

      {data.biggestBlockbusters && data.biggestBlockbusters.length > 0 && (
        <Card title="Biggest blockbusters" subtitle="Sorted by total assets moved">
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))", gap: 10 }}>
            {data.biggestBlockbusters.map((t) => (
              <TradeCard key={t.transactionId} trade={t} managers={managers} onNavigate={onNavigate} />
            ))}
          </div>
        </Card>
      )}

      {data.positionMixMoved && Object.keys(data.positionMixMoved).length > 0 && (
        <Card title="Position mix moved" subtitle="Players moved by position in completed trades">
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            {Object.entries(data.positionMixMoved).sort(([, a], [, b]) => b - a).map(([pos, n]) => (
              <div
                key={pos}
                style={{
                  border: "1px solid var(--border)",
                  padding: "6px 12px",
                  borderRadius: 6,
                  fontSize: "0.78rem",
                }}
              >
                <strong>{pos}</strong>: {n}
              </div>
            ))}
          </div>
        </Card>
      )}

      <Card
        title="Trade timeline"
        subtitle="Filter by team name, player, or season"
        action={
          <input
            className="input"
            placeholder="Filter trades..."
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            style={{ minWidth: 220 }}
          />
        }
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {filtered.map((t) => (
            <TradeCard key={t.transactionId} trade={t} managers={managers} onNavigate={onNavigate} />
          ))}
          {filtered.length === 0 && (
            <div style={{ fontSize: "0.74rem", color: "var(--subtext)" }}>
              No trades match that filter.
            </div>
          )}
        </div>
      </Card>
    </>
  );
}

function TradeCard({ trade, managers, onNavigate }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius)", padding: 10 }}>
      <div style={{ fontSize: "0.64rem", color: "var(--subtext)" }}>
        {trade.season} · Week {trade.week ?? "—"} · {trade.totalAssets} assets
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: `repeat(${Math.max(1, (trade.sides || []).length)}, 1fr)`,
          gap: 8,
          marginTop: 6,
        }}
      >
        {(trade.sides || []).map((side, i) => (
          <div key={i} style={{ minWidth: 0 }}>
            <div
              style={{ display: "flex", alignItems: "center", gap: 6, fontWeight: 700, fontSize: "0.86rem" }}
              onClick={() => onNavigate && side.ownerId && onNavigate("franchise", { owner: side.ownerId })}
            >
              <Avatar managers={managers} ownerId={side.ownerId} size={20} />
              <span style={{ cursor: side.ownerId ? "pointer" : "default", color: side.ownerId ? "var(--cyan)" : "var(--text)" }}>
                {side.displayName || side.teamName || nameFor(managers, side.ownerId)}
              </span>
            </div>
            <div style={{ fontSize: "0.68rem", color: "var(--subtext)", marginTop: 2 }}>Received:</div>
            <ul style={{ paddingInlineStart: 16, margin: "4px 0 0", fontSize: "0.72rem" }}>
              {(side.receivedAssets || []).map((a, j) => (
                <li key={j}>
                  {a.kind === "player" ? (
                    <>
                      {a.playerName || "Player"}
                      <span style={{ color: "var(--subtext)", marginLeft: 4 }}>({a.position || "?"})</span>
                    </>
                  ) : (
                    <>{a.label || `${a.season} R${a.round}`}</>
                  )}
                </li>
              ))}
              {(side.receivedAssets || []).length === 0 && (
                <li style={{ color: "var(--subtext)" }}>—</li>
              )}
            </ul>
          </div>
        ))}
      </div>
    </div>
  );
}

export default ActivitySection;
