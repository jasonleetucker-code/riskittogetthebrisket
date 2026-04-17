"use client";

// SuperlativesSection — public /league tab view.
// Extracted from page.jsx to keep the tab file lean.

import { Avatar, Card, EmptyCard } from "../shared.jsx";

function SuperlativesSection({ managers, data }) {
  if (!data) return <EmptyCard label="Superlatives" />;

  const blocks = [
    { key: "mostQbHeavy", label: "Most QB-heavy", caption: "Most quarterbacks rostered" },
    { key: "mostRbHeavy", label: "Most RB-heavy", caption: "Most running backs rostered" },
    { key: "mostWrHeavy", label: "Most WR-heavy", caption: "Most wide receivers rostered" },
    { key: "mostTeHeavy", label: "Most TE-heavy", caption: "Most tight ends rostered" },
    { key: "mostIdpHeavy", label: "Most IDP-heavy", caption: "Most defenders rostered" },
    { key: "mostPickHeavy", label: "Biggest pick stockpile", caption: "Highest weighted pick score" },
    { key: "mostRookieHeavy", label: "Most rookies", caption: "Most first-year players rostered" },
    { key: "mostBalanced", label: "Most balanced", caption: "Lowest variance across QB/RB/WR/TE" },
    { key: "mostActive", label: "Most active franchise", caption: "Most trades + waivers combined" },
    { key: "mostFutureFocused", label: "Most future-focused", caption: "Blend of pick stockpile + rookies" },
  ];

  return (
    <Card
      title="Superlatives"
      subtitle="Fun, public-safe roster-composition awards across the 2-season window"
    >
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 10 }}>
        {blocks.map((b) => {
          const block = data[b.key];
          if (!block || !block.winner) return null;
          const w = block.winner;
          return (
            <div
              key={b.key}
              style={{
                border: "1px solid var(--border)",
                borderRadius: "var(--radius)",
                padding: 12,
                background: "rgba(15, 28, 59, 0.45)",
              }}
            >
              <div
                style={{
                  fontSize: "0.62rem",
                  color: "var(--subtext)",
                  textTransform: "uppercase",
                  letterSpacing: "0.06em",
                }}
              >
                {b.label}
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
                <Avatar managers={managers} ownerId={w.ownerId} size={24} />
                <div style={{ fontWeight: 700, fontSize: "0.98rem" }}>{w.displayName}</div>
              </div>
              <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 2, marginBottom: 8 }}>
                {b.caption}
              </div>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 6,
                  fontSize: "0.7rem",
                  fontFamily: "var(--mono)",
                }}
              >
                <span>QB: {w.qb}</span>
                <span>RB: {w.rb}</span>
                <span>WR: {w.wr}</span>
                <span>TE: {w.te}</span>
                <span>IDP: {w.idp}</span>
                <span>Rook: {w.rookies}</span>
                <span>Trades: {w.trades}</span>
                <span>Picks: {w.weightedPickScore}</span>
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export default SuperlativesSection;
