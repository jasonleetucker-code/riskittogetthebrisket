"use client";

// LuckSection — "Luck Score" tab on /league.
//
// Reads the ``luck`` section of the public contract and renders:
//   * Luckiest / unluckiest headline cards (current season + career).
//   * A per-season sortable table with actual vs expected wins, luck
//     delta, and all-play win%.
//   * A cumulative luck-delta sparkline chart overlaying every owner
//     across the full snapshot history.
//
// All math lives in ``src/public_league/luck.py``; this component is a
// pure materializer.

import { useMemo, useState } from "react";
import {
  Avatar,
  Card,
  EmptyCard,
  SingleHighlight,
  fmtNumber,
  fmtPercent,
  nameFor,
} from "../shared.jsx";

// ── Shared helpers ───────────────────────────────────────────────────────
function fmtDelta(n) {
  if (n === null || n === undefined || Number.isNaN(Number(n))) return "—";
  const v = Number(n);
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}`;
}

function luckColor(delta) {
  if (delta === null || delta === undefined) return "var(--subtext)";
  if (delta > 0.5) return "#2ecc71";
  if (delta > 0.1) return "#7bdfb3";
  if (delta < -0.5) return "#ff6b6b";
  if (delta < -0.1) return "#ffab6b";
  return "var(--subtext)";
}

function luckLabel(delta) {
  if (delta === null || delta === undefined) return "—";
  if (delta > 1.0) return "Blessed";
  if (delta > 0.3) return "Lucky";
  if (delta > -0.3) return "Deserved";
  if (delta > -1.0) return "Unlucky";
  return "Cursed";
}

// ── Trail sparkline (inline SVG) ─────────────────────────────────────────
// Plots cumulative luck delta over game index, one line per owner.
// Hover state is cheap CSS so we don't pay for a tooltip system.
function LuckTrailChart({ trail, managers }) {
  const { lines, xMax, yMin, yMax } = useMemo(() => {
    const grouped = new Map();
    for (const t of trail) {
      if (!grouped.has(t.ownerId)) grouped.set(t.ownerId, []);
      grouped.get(t.ownerId).push(t);
    }
    let xMax = 0;
    let yMin = 0;
    let yMax = 0;
    const lines = [];
    for (const [ownerId, rows] of grouped) {
      const sorted = rows.slice().sort((a, b) => a.cumGames - b.cumGames);
      const points = sorted.map((r) => ({ x: r.cumGames, y: r.cumLuckDelta }));
      for (const p of points) {
        if (p.x > xMax) xMax = p.x;
        if (p.y < yMin) yMin = p.y;
        if (p.y > yMax) yMax = p.y;
      }
      lines.push({ ownerId, points });
    }
    // Enforce a minimum symmetric y-range so a "flat" chart doesn't
    // look like random noise.
    const yAbs = Math.max(1.0, Math.max(Math.abs(yMin), Math.abs(yMax)));
    return { lines, xMax, yMin: -yAbs, yMax: yAbs };
  }, [trail]);

  if (!lines.length || xMax < 2) return null;

  const W = 620;
  const H = 220;
  const padL = 32;
  const padR = 12;
  const padT = 12;
  const padB = 22;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  function px(x) {
    return padL + (x / xMax) * plotW;
  }
  function py(y) {
    return padT + (1 - (y - yMin) / (yMax - yMin)) * plotH;
  }

  // Generate a deterministic color per owner.
  function colorFor(ownerId) {
    const palette = [
      "#4fc3f7",
      "#ffa726",
      "#66bb6a",
      "#ef5350",
      "#ab47bc",
      "#26c6da",
      "#ffee58",
      "#8d6e63",
      "#ec407a",
      "#7e57c2",
      "#9ccc65",
      "#ff7043",
    ];
    let h = 0;
    for (let i = 0; i < ownerId.length; i++) {
      h = (h * 31 + ownerId.charCodeAt(i)) & 0xffff;
    }
    return palette[h % palette.length];
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        height={H}
        style={{ maxWidth: W, display: "block", margin: "0 auto" }}
        aria-label="Cumulative luck delta over time per manager"
      >
        {/* Gridlines at −2, −1, 0, 1, 2 when in range. */}
        {[-2, -1, 0, 1, 2].filter((v) => v >= yMin && v <= yMax).map((v) => (
          <g key={v}>
            <line
              x1={padL}
              x2={W - padR}
              y1={py(v)}
              y2={py(v)}
              stroke={v === 0 ? "var(--border-bright)" : "var(--border)"}
              strokeDasharray={v === 0 ? "" : "3 3"}
              opacity={v === 0 ? 0.9 : 0.5}
            />
            <text
              x={padL - 6}
              y={py(v) + 3}
              fontSize={9}
              textAnchor="end"
              fill="var(--subtext)"
              fontFamily="var(--mono)"
            >
              {v > 0 ? `+${v}` : v}
            </text>
          </g>
        ))}
        {/* X axis label. */}
        <text
          x={padL + plotW / 2}
          y={H - 4}
          fontSize={9}
          textAnchor="middle"
          fill="var(--subtext)"
        >
          Regular-season games played
        </text>
        {/* Lines. */}
        {lines.map((line) => {
          const d = line.points
            .map((p, i) => `${i === 0 ? "M" : "L"} ${px(p.x)} ${py(p.y)}`)
            .join(" ");
          return (
            <g key={line.ownerId}>
              <path
                d={d}
                fill="none"
                stroke={colorFor(line.ownerId)}
                strokeWidth={1.5}
                opacity={0.9}
              />
              {/* End marker + name */}
              {line.points.length > 0 && (() => {
                const last = line.points[line.points.length - 1];
                return (
                  <>
                    <circle
                      cx={px(last.x)}
                      cy={py(last.y)}
                      r={3}
                      fill={colorFor(line.ownerId)}
                    />
                    <text
                      x={px(last.x) + 6}
                      y={py(last.y) + 3}
                      fontSize={9}
                      fill={colorFor(line.ownerId)}
                      fontFamily="var(--mono)"
                    >
                      {nameFor(managers, line.ownerId).slice(0, 10)}
                    </text>
                  </>
                );
              })()}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── Table ────────────────────────────────────────────────────────────────
function LuckTable({ rows, managers, showSeason = false }) {
  if (!rows || !rows.length) return <EmptyCard label="Luck scores" />;
  return (
    <div className="table-wrap" style={{ overflowX: "auto" }}>
      <table className="table">
        <thead>
          <tr>
            <th style={{ width: 32 }}>#</th>
            <th>Manager</th>
            {showSeason && <th>Season</th>}
            <th style={{ textAlign: "right" }}>GP</th>
            <th style={{ textAlign: "right" }}>Actual W</th>
            <th style={{ textAlign: "right" }}>Expected W</th>
            <th style={{ textAlign: "right" }}>Luck Δ</th>
            <th style={{ textAlign: "right" }}>All-Play %</th>
            <th style={{ textAlign: "right", width: 96 }}>Verdict</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={`${r.ownerId}-${r.season || "career"}`}>
              <td style={{ fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                {i + 1}
              </td>
              <td>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <Avatar managers={managers} ownerId={r.ownerId} size={20} />
                  <span>
                    <div style={{ fontWeight: 600, lineHeight: 1.1 }}>
                      {nameFor(managers, r.ownerId)}
                    </div>
                    <div style={{ fontSize: "0.65rem", color: "var(--subtext)" }}>
                      {r.teamName}
                    </div>
                  </span>
                </span>
              </td>
              {showSeason && (
                <td style={{ fontFamily: "var(--mono)" }}>{r.season}</td>
              )}
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {r.gamesPlayed}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtNumber(r.actualWins, 1)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)", color: "var(--subtext)" }}>
                {fmtNumber(r.expectedWins, 1)}
              </td>
              <td
                style={{
                  textAlign: "right",
                  fontFamily: "var(--mono)",
                  color: luckColor(r.luckDelta),
                  fontWeight: 700,
                }}
              >
                {fmtDelta(r.luckDelta)}
              </td>
              <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>
                {fmtPercent(r.allPlayWinPct)}
              </td>
              <td style={{ textAlign: "right", color: luckColor(r.luckDelta), fontSize: "0.72rem" }}>
                {luckLabel(r.luckDelta)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Top-level section ────────────────────────────────────────────────────
export default function LuckSection({ data, managers }) {
  const [scope, setScope] = useState(
    data?.currentSeasonRanked?.length ? "current" : "career",
  );

  if (!data || (!data.byOwnerCareer?.length && !data.byOwnerSeason?.length)) {
    return <EmptyCard label="Luck Score" />;
  }

  const career = data.byOwnerCareer || [];
  const seasonRows = data.byOwnerSeason || [];
  const currentSeasonRows = data.currentSeasonRanked || [];
  const currentYear = data.currentSeason;

  const tableRows = scope === "career"
    ? career
    : scope === "current"
      ? currentSeasonRows
      : seasonRows.filter((r) => r.season === scope);

  const seasonOptions = Array.from(
    new Set(seasonRows.map((r) => r.season))
  ).sort((a, b) => Number(b) - Number(a));

  return (
    <section>
      {/* Headline cards */}
      <div
        className="card"
        style={{ marginTop: "var(--space-md)" }}
      >
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Luck Score</div>
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
          Actual wins vs expected wins from weekly all-play record. Regular season only.
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: 10,
          }}
        >
          {data.luckiestCurrent && (
            <SingleHighlight
              label={`${currentYear} · Most blessed`}
              value={`${nameFor(managers, data.luckiestCurrent.ownerId)} (${fmtDelta(data.luckiestCurrent.luckDelta)})`}
              sub={`${fmtNumber(data.luckiestCurrent.actualWins, 1)} actual vs ${fmtNumber(data.luckiestCurrent.expectedWins, 1)} expected`}
            />
          )}
          {data.unluckiestCurrent && (
            <SingleHighlight
              label={`${currentYear} · Most cursed`}
              value={`${nameFor(managers, data.unluckiestCurrent.ownerId)} (${fmtDelta(data.unluckiestCurrent.luckDelta)})`}
              sub={`${fmtNumber(data.unluckiestCurrent.actualWins, 1)} actual vs ${fmtNumber(data.unluckiestCurrent.expectedWins, 1)} expected`}
            />
          )}
          {data.luckiestCareer && (
            <SingleHighlight
              label="Career · Most blessed"
              value={`${nameFor(managers, data.luckiestCareer.ownerId)} (${fmtDelta(data.luckiestCareer.luckDelta)})`}
              sub={`${data.luckiestCareer.gamesPlayed} games, all-play ${fmtPercent(data.luckiestCareer.allPlayWinPct)}`}
            />
          )}
          {data.unluckiestCareer && (
            <SingleHighlight
              label="Career · Most cursed"
              value={`${nameFor(managers, data.unluckiestCareer.ownerId)} (${fmtDelta(data.unluckiestCareer.luckDelta)})`}
              sub={`${data.unluckiestCareer.gamesPlayed} games, all-play ${fmtPercent(data.unluckiestCareer.allPlayWinPct)}`}
            />
          )}
        </div>
      </div>

      {/* Trail chart */}
      <Card
        title="Cumulative luck delta over time"
        action={
          <span style={{ fontSize: "0.65rem", color: "var(--subtext)" }}>
            Above zero = lucky; below = unlucky
          </span>
        }
      >
        <LuckTrailChart trail={data.weeklyTrail || []} managers={managers} />
      </Card>

      {/* Ranked table */}
      <Card
        title="Manager ranking"
        action={
          <select
            className="input"
            value={scope}
            onChange={(e) => setScope(e.target.value)}
            style={{ minWidth: 140 }}
          >
            <option value="career">Career</option>
            {currentYear && (
              <option value="current">{currentYear} (current)</option>
            )}
            {seasonOptions
              .filter((s) => s !== currentYear)
              .map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
          </select>
        }
      >
        <LuckTable rows={tableRows} managers={managers} showSeason={scope !== "career" && scope !== "current"} />
      </Card>

      {/* Methodology */}
      <Card title="How this is computed">
        <p style={{ fontSize: "0.78rem", lineHeight: 1.5, color: "var(--subtext)" }}>
          Each week, every manager's score is compared against every other manager's score that same week.
          If your score beats <em>k</em> of the other <em>n−1</em> teams, your <strong>expected win share</strong> for that
          week is <code style={{ color: "var(--cyan)" }}>(k + ties·0.5) / (n−1)</code>.
          Add those shares up across the season and you get <strong>expected wins</strong>. Your actual
          wins are what the schedule-luck lottery assigned you. <strong>Luck Δ = actual − expected.</strong>
          Playoffs are excluded — bracket seeding is already a function of regular-season luck.
        </p>
      </Card>
    </section>
  );
}
