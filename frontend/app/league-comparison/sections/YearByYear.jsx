"use client";

import { useState } from "react";

/**
 * YearByYear — collapsible per-season detail.  For each available
 * season, shows a per-position comparison table plus a flex line.
 */
const POSITIONS = ["QB", "RB", "WR", "TE"];

export default function YearByYear({ data }) {
  const bySeason = data?.bySeason || {};
  const seasons = Object.keys(bySeason).sort().reverse(); // newest first
  const [openSeason, setOpenSeason] = useState(seasons[0] || null);

  if (seasons.length === 0) {
    return (
      <div className="card">
        <p className="muted">No per-season data available.</p>
      </div>
    );
  }

  return (
    <div className="card">
      <h2 className="section-title">Year-by-Year Detail</h2>
      <p className="muted text-sm" style={{ marginTop: 6 }}>
        Each season is computed independently and then equally averaged for the
        combined view.  Click a season to expand its detailed breakdown.
      </p>
      <div style={{ marginTop: "var(--space-sm)", display: "flex", flexDirection: "column", gap: 8 }}>
        {seasons.map((season) => (
          <SeasonRow
            key={season}
            season={season}
            block={bySeason[season]}
            open={openSeason === season}
            onToggle={() => setOpenSeason(openSeason === season ? null : season)}
          />
        ))}
      </div>
    </div>
  );
}

function SeasonRow({ season, block, open, onToggle }) {
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: 6, overflow: "hidden" }}>
      <button
        type="button"
        onClick={onToggle}
        style={{
          width: "100%",
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "10px 14px",
          background: "rgba(255,255,255,0.04)",
          border: "none",
          color: "var(--text)",
          cursor: "pointer",
          fontSize: "1rem",
          fontWeight: 700,
        }}
      >
        <span>Season {season}</span>
        <span className="muted">{open ? "▼" : "▸"}</span>
      </button>
      {open && (
        <div style={{ padding: "var(--space-sm)" }}>
          <SeasonTables block={block} />
        </div>
      )}
    </div>
  );
}

function SeasonTables({ block }) {
  if (!block) return <p className="muted">No data for this season.</p>;
  const my = block.my || {};
  const base = block.baseline || {};
  return (
    <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr" }}>
      <SeasonSide title="My League" data={my} accent="cyan" />
      <SeasonSide title="Standard Baseline" data={base} accent="gold" />
    </div>
  );
}

function SeasonSide({ title, data, accent }) {
  const color = accent === "gold" ? "var(--gold, #FFC704)" : "var(--cyan)";
  const positions = data.positions || {};
  const flex = data.flex || {};
  const top = (data.topPlayers || []).slice(0, 8);
  return (
    <div>
      <div style={{ fontWeight: 700, color, marginBottom: 6 }}>{title}</div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Pos</th>
              <th style={{ textAlign: "right" }}>Avg</th>
              <th style={{ textAlign: "right" }}>Med</th>
              <th style={{ textAlign: "right" }}>P25</th>
              <th style={{ textAlign: "right" }}>P75</th>
              <th style={{ textAlign: "right" }}>Repl</th>
              <th style={{ textAlign: "right" }}>n</th>
            </tr>
          </thead>
          <tbody>
            {POSITIONS.map((pos) => {
              const m = positions[pos];
              if (!m) return null;
              return (
                <tr key={pos}>
                  <td style={{ fontWeight: 600 }}>{pos}</td>
                  <td style={mono()}>{fmt(m.average)}</td>
                  <td style={mono()}>{fmt(m.median)}</td>
                  <td style={mono()}>{fmt(m.p25)}</td>
                  <td style={mono()}>{fmt(m.p75)}</td>
                  <td style={mono()}>{fmt(m.replacementLevel)}</td>
                  <td style={mono()}>{m.sampleSize}</td>
                </tr>
              );
            })}
            <tr>
              <td style={{ fontWeight: 600 }}>FLEX</td>
              <td style={mono()}>{fmt(flex.average)}</td>
              <td style={mono()}>{fmt(flex.median)}</td>
              <td style={mono()}>{fmt(flex.p25)}</td>
              <td style={mono()}>{fmt(flex.p75)}</td>
              <td style={mono()}>{fmt(flex.replacementLevel)}</td>
              <td style={mono()}>{flex.sampleSize || 0}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {top.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
            Top players (this league's scoring)
          </div>
          <ol className="text-xs" style={{ marginTop: 4, paddingLeft: 20, lineHeight: 1.7 }}>
            {top.map((p) => (
              <li key={p.playerId}>
                <strong>{p.name}</strong>{" "}
                <span className="muted">({p.position})</span>{" "}
                <span style={{ fontFamily: "var(--mono)" }}>{fmt(p.totalPoints)} pts</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}

function fmt(v) { return v == null ? "—" : Number(v).toFixed(1); }
function mono() { return { textAlign: "right", fontFamily: "var(--mono)" }; }
