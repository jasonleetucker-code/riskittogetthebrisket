"use client";

// DraftCapitalSection — public /league tab view.
// Shows the live auction-dollar draft capital board from /api/draft-capital.
// Purely public data (same endpoint powered the old /draft-capital page).
// When this tab is the default, /league mobile users land here.

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { LoadingState, EmptyState } from "@/components/ui";
import { EmptyCard } from "../shared.jsx";
import { effectiveAuctionPower } from "@/lib/auction-power";

// Dynamically import the trade simulator so its JS goes into a
// separate chunk (loaded on demand when DraftCapital tab renders)
// instead of inflating the /league page bundle.
const TradeSimulator = dynamic(() => import("./_trade-simulator.jsx"), {
  ssr: false,
});

// Same treatment as the simulator: its own chunk, loaded when this tab
// renders rather than inflating the /league bundle.
const PickProjectorPanel = dynamic(() => import("./_pick-projector.jsx"), {
  ssr: false,
});

function fmtDollar(v) {
  if (v == null) return "$0";
  const n = Number(v);
  if (!Number.isFinite(n)) return "$0";
  // Match the Google Sheet's display: currency format with 0 decimals
  // rounds half-dollars up ($1.5 → $2, $28.5 → $29).  The underlying
  // value the server returns stays half-dollar so team-totals math
  // remains accurate; only the per-cell display is rounded.
  return `$${Math.round(n)}`;
}

export default function DraftCapitalSection() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    async function load() {
      try {
        setLoading(true);
        const res = await fetch("/api/draft-capital");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!active) return;
        if (json.error) {
          setError(json.error);
        } else {
          setData(json);
        }
      } catch (err) {
        if (active) setError(err?.message || "Failed to load draft capital.");
      } finally {
        if (active) setLoading(false);
      }
    }
    load();
    return () => {
      active = false;
    };
  }, []);

  if (loading) return <LoadingState message="Loading draft capital..." />;
  if (error) {
    return (
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title="Draft capital unavailable" message={error} />
      </div>
    );
  }
  if (!data) return <EmptyCard label="Draft capital" />;

  // Picks for the season the header claims to be describing. Rows carry
  // `season`; when none do (the workbook path, one season only) this is the
  // whole list, so the filter is inert there rather than emptying the page.
  const currentSeasonPicks = (() => {
    const all = data.picks || [];
    const season = Number(data.season);
    if (!Number.isFinite(season)) return all;
    const scoped = all.filter((p) => Number(p?.season) === season);
    return scoped.length > 0 ? scoped : all;
  })();

  return (
    <>
      <div className="card" style={{ marginTop: "var(--space-md)" }}>
        <div style={{ fontWeight: 700, marginBottom: 4 }}>Draft Capital</div>
        <div
          style={{
            fontSize: "0.72rem",
            color: "var(--subtext)",
            marginBottom: 10,
          }}
        >
          {data.season} draft · {data.numTeams} teams · {data.draftRounds}{" "}
          rounds · ${data.totalBudget} total budget
        </div>
        <div
          style={{
            fontSize: "0.66rem",
            color: "var(--muted)",
            marginBottom: 10,
          }}
        >
          <span style={{ color: "var(--green)", fontWeight: 700 }}>green</span>{" "}
          = raw auction $ ·{" "}
          <span style={{ color: "var(--cyan)", fontWeight: 700 }}>▲ cyan</span>{" "}
          = effective auction power (stacking-adjusted, zero-sum)
        </div>
        <TeamTotalsChart
          teamTotals={data.teamTotals}
          picks={currentSeasonPicks}
          totalBudget={data.totalBudget}
          numTeams={data.numTeams}
          draftRounds={data.draftRounds}
          season={data.season}
        />
      </div>

      {/* The Sleeper-derived path builds BOTH the current season and the next
          into one flat picks array (it stamps `coveredPickYears` to say so),
          and every grid below groups by round with no season filter — so each
          round rendered twice, with duplicate "1.01" labels and a doubled
          round total. The workbook path carries one season and is unaffected,
          which is why nothing caught it. Filter once, here, and pass the
          current season's picks down. */}
      <PickValueGrid
        picks={currentSeasonPicks}
        draftRounds={data.draftRounds}
        numTeams={data.numTeams}
      />

      {/* Future picks — where they land, not what they are worth. The
          grid above is the current season's actual draft; this is the
          projection for the ones after it. */}
      <PickProjectorPanel />

      <TradeSimulator picks={currentSeasonPicks} teamTotals={data.teamTotals} />

      <PicksByRound picks={currentSeasonPicks} draftRounds={data.draftRounds} />
    </>
  );
}

/* ── Team totals bar chart ─────────────────────────────────────────────── */
function TeamTotalsChart({
  teamTotals,
  picks,
  totalBudget,
  numTeams,
  draftRounds,
  season,
}) {
  const maxDollars = Math.max(
    ...(teamTotals || []).map((t) => t.auctionDollars),
    1,
  );

  // Effective auction power is a presentation lens computed client-side
  // from the raw per-team dollars (zero-sum; src/api/auction_power.py
  // is the source of truth).  No extra backend payload.
  const effectiveByTeam = effectiveAuctionPower(
    Object.fromEntries(
      (teamTotals || []).map((t) => [t.team, t.auctionDollars || 0]),
    ),
  );

  return (
    <div style={{ marginTop: "var(--space-md)" }}>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-sm)",
        }}
      >
        {(teamTotals || []).map((team, i) => {
          const pct = (team.auctionDollars / maxDollars) * 100;
          const effectiveDollars = effectiveByTeam[team.team];
          const teamPicks = (picks || []).filter(
            (p) => p.currentOwner === team.team,
          );
          const tradedCount = teamPicks.filter((p) => p.isTraded).length;

          return (
            <div
              key={team.team}
              style={{
                padding: "var(--space-sm) var(--space-md)",
                borderRadius: "var(--radius-sm)",
                background:
                  i % 2 === 0 ? "rgba(255,255,255,0.02)" : "transparent",
              }}
            >
              <div
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "var(--space-sm)",
                }}
              >
                <span
                  className="font-mono"
                  style={{
                    width: 22,
                    fontSize: "0.68rem",
                    color: "var(--muted)",
                    textAlign: "right",
                    flexShrink: 0,
                  }}
                >
                  {i + 1}
                </span>

                <span
                  className="truncate"
                  style={{
                    minWidth: 100,
                    maxWidth: 140,
                    fontSize: "0.82rem",
                    fontWeight: 600,
                  }}
                >
                  {team.team}
                </span>

                <div
                  style={{
                    flex: 1,
                    background: "var(--bg-soft)",
                    borderRadius: "var(--radius-sm)",
                    height: 20,
                    overflow: "hidden",
                    border: "1px solid rgba(255,255,255,0.04)",
                  }}
                >
                  <div
                    style={{
                      width: `${pct}%`,
                      height: "100%",
                      background:
                        "linear-gradient(90deg, var(--cyan), rgba(79, 155, 236, 0.6))",
                      borderRadius: "var(--radius-sm)",
                      transition: "width 0.4s ease-out",
                      boxShadow:
                        pct > 30 ? "0 0 12px rgba(79, 155, 236, 0.15)" : "none",
                    }}
                  />
                </div>

                <span
                  className="font-mono"
                  style={{
                    minWidth: 48,
                    textAlign: "right",
                    fontSize: "0.82rem",
                    fontWeight: 700,
                    color: "var(--green)",
                  }}
                >
                  {fmtDollar(team.auctionDollars)}
                </span>

                {Number.isFinite(effectiveDollars) &&
                  effectiveDollars !== team.auctionDollars && (
                    <span
                      className="font-mono"
                      title={
                        "Effective auction power: raw capital adjusted for stacking. " +
                        "A clearly-biggest stack is worth more than its linear sum " +
                        "(you can outbid the field for the #1 rookie); an " +
                        "already-dominant stack saturates (extra picks worth less). " +
                        "Zero-sum across the league."
                      }
                      style={{
                        minWidth: 52,
                        textAlign: "right",
                        fontSize: "0.74rem",
                        fontWeight: 600,
                        color:
                          effectiveDollars > team.auctionDollars
                            ? "var(--cyan)"
                            : "var(--muted)",
                      }}
                    >
                      {effectiveDollars > team.auctionDollars ? "▲" : "▼"}
                      {fmtDollar(effectiveDollars)}
                    </span>
                  )}

                <span
                  className="badge badge-cyan"
                  style={{ fontSize: "0.64rem", padding: "1px 6px" }}
                >
                  {teamPicks.length}pk
                </span>
              </div>

              <div
                style={{
                  marginTop: 3,
                  marginLeft: 30,
                  fontSize: "0.68rem",
                  color: "var(--muted)",
                  lineHeight: 1.6,
                }}
              >
                {teamPicks.map((p, j) => (
                  <span key={j}>
                    {j > 0 && (
                      <span style={{ margin: "0 2px", opacity: 0.3 }}>·</span>
                    )}
                    <span
                      style={p.isTraded ? { color: "var(--amber)" } : undefined}
                    >
                      {p.pick}
                      {p.isTraded ? "*" : ""}
                    </span>
                  </span>
                ))}
                {tradedCount > 0 && (
                  <span
                    style={{
                      marginLeft: 6,
                      color: "var(--amber)",
                      opacity: 0.7,
                    }}
                  >
                    ({tradedCount} traded)
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <div
        style={{
          marginTop: "var(--space-md)",
          padding: "var(--space-sm) var(--space-md)",
          fontSize: "0.72rem",
          color: "var(--muted)",
          borderTop: "1px solid var(--border)",
        }}
      >
        ${totalBudget} total budget across {numTeams} teams, {draftRounds}{" "}
        rounds ({season}). <span style={{ color: "var(--amber)" }}>*</span> =
        traded pick.
      </div>
    </div>
  );
}

function PickValueGrid({ picks, draftRounds, numTeams }) {
  if (!picks || !picks.length) return null;
  const rounds = [];
  for (let r = 1; r <= (draftRounds || 6); r++) {
    rounds.push((picks || []).filter((p) => p.round === r));
  }
  return (
    <div className="card" style={{ marginTop: "var(--space-md)" }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: "var(--space-sm)",
          marginBottom: "var(--space-sm)",
        }}
      >
        <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>
          Pick Values
        </span>
        <span className="text-xs muted">
          Adjusted values used for team totals (expansion picks 1 &amp; 2
          averaged)
        </span>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 70 }}>Round</th>
              {Array.from({ length: numTeams || 12 }, (_, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: "right",
                    fontSize: "0.72rem",
                    minWidth: 44,
                  }}
                >
                  Pk {i + 1}
                </th>
              ))}
              <th style={{ textAlign: "right", fontWeight: 700, minWidth: 50 }}>
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((rp, ri) => {
              const total = rp.reduce(
                (s, p) => s + (p.adjustedDollarValue ?? p.dollarValue ?? 0),
                0,
              );
              return (
                <tr key={ri}>
                  <td className="font-mono font-bold">R{ri + 1}</td>
                  {rp.map((p, j) => (
                    <td
                      key={j}
                      className="font-mono"
                      style={{
                        textAlign: "right",
                        fontSize: "0.76rem",
                        color: p.isExpansion ? "var(--amber)" : undefined,
                      }}
                    >
                      {fmtDollar(p.adjustedDollarValue ?? p.dollarValue)}
                    </td>
                  ))}
                  <td
                    className="font-mono font-bold text-green"
                    style={{ textAlign: "right" }}
                  >
                    {fmtDollar(total)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PicksByRound({ picks, draftRounds }) {
  const rounds = [];
  for (let round = 1; round <= (draftRounds || 4); round++) {
    const roundPicks = (picks || []).filter((p) => p.round === round);
    const roundTotal = roundPicks.reduce(
      (s, p) => s + (p.adjustedDollarValue ?? p.dollarValue ?? 0),
      0,
    );
    rounds.push({ round, picks: roundPicks, total: roundTotal });
  }

  return (
    <>
      {rounds.map(({ round, picks: roundPicks, total }) => (
        <div
          key={round}
          className="card"
          style={{ marginTop: "var(--space-md)" }}
        >
          <div
            style={{
              display: "flex",
              alignItems: "baseline",
              gap: "var(--space-sm)",
              marginBottom: "var(--space-sm)",
            }}
          >
            <span style={{ fontWeight: 700, fontSize: "0.88rem" }}>
              Round {round}
            </span>
            <span className="badge badge-green" style={{ fontSize: "0.64rem" }}>
              {fmtDollar(total)}
            </span>
            <span className="text-xs muted">{roundPicks.length} picks</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width: 70 }}>Pick</th>
                  <th style={{ width: 60 }}>Value</th>
                  <th>Owner</th>
                  <th>Original</th>
                </tr>
              </thead>
              <tbody>
                {roundPicks.map((pick, idx) => (
                  <tr key={idx}>
                    <td className="font-mono font-bold">{pick.pick}</td>
                    <td className="font-mono font-bold text-green">
                      {fmtDollar(pick.adjustedDollarValue ?? pick.dollarValue)}
                    </td>
                    <td style={{ fontWeight: 600 }}>{pick.currentOwner}</td>
                    <td>
                      {pick.isTraded ? (
                        <span
                          className="badge badge-amber"
                          style={{ fontSize: "0.64rem" }}
                        >
                          {pick.originalOwner}
                        </span>
                      ) : (
                        <span className="muted">&mdash;</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </>
  );
}
