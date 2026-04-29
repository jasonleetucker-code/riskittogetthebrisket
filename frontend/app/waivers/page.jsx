"use client";

import { useMemo, useState } from "react";
import PageHeader from "@/components/ui/PageHeader";
import FilterBar from "@/components/ui/FilterBar";
import LoadingState from "@/components/ui/LoadingState";
import ErrorState from "@/components/ui/ErrorState";
import EmptyState from "@/components/ui/EmptyState";
import TeamSwitcher from "@/components/TeamSwitcher";
import { useApp } from "@/components/AppShell";
import { useAuthContext } from "@/app/AppShellWrapper";
import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { posBadgeClass } from "@/lib/display-helpers";

// ── /waivers — Add/Drop analysis page ─────────────────────────────────
//
// Compares every unrostered (and optionally every rookie-flagged)
// player against the user's selected team.  Surfaces:
//
//   • Best Add/Drop Moves       — top single-transaction upgrades
//   • Best Unique Upgrade Set   — multi-transaction greedy slate
//   • Droppable Players         — bottom of my roster, sorted by
//                                 obvious-drop confidence
//   • Addable Players           — full pool of beats-someone players
//
// Filters: position, rookie toggle, min net gain, upgrade strength.
//
// All comparison logic lives in ``frontend/lib/waiver-logic.js``;
// the hook in ``frontend/components/useWaiverAnalysis.js`` wires the
// pure logic to the app context.  This file is layout only.

const POSITION_OPTIONS = [
  { value: "ALL", label: "All positions" },
  { value: "QB",  label: "QB" },
  { value: "RB",  label: "RB" },
  { value: "WR",  label: "WR" },
  { value: "TE",  label: "TE" },
  { value: "DL",  label: "DL" },
  { value: "LB",  label: "LB" },
  { value: "DB",  label: "DB" },
];

const STRENGTH_OPTIONS = [
  { value: "all",         label: "All strengths" },
  { value: "considering", label: "Considering & up" },
  { value: "strong",      label: "Strong & up" },
  { value: "smash",       label: "Smash only" },
];

const TIER_LABELS = {
  smash: "Smash add",
  strong: "Strong add",
  considering: "Worth considering",
  marginal: "Marginal add",
};

const DROP_LABELS = {
  obvious: "Obvious drop",
  reasonable: "Reasonable drop",
  risky: "Risky drop",
  hold: "Hold unless needed",
};

const TIER_ACCENT = {
  smash: "var(--green, #34d399)",
  strong: "var(--cyan, #FFC704)",
  considering: "var(--muted, #c7b8dc)",
  marginal: "var(--muted, #c7b8dc)",
};

function fmtVal(v) {
  const n = Number(v) || 0;
  return n.toLocaleString();
}

function fmtGain(v) {
  const n = Math.round(Number(v) || 0);
  if (n <= 0) return `${n}`;
  return `+${n.toLocaleString()}`;
}

function PositionChip({ row }) {
  return <span className={posBadgeClass(row)}>{row?.pos || "?"}</span>;
}

function RookieBadge() {
  return (
    <span
      className="badge"
      style={{
        background: "rgba(251, 191, 36, 0.18)",
        color: "var(--amber, #fbbf24)",
        fontWeight: 700,
        fontSize: "0.62rem",
        padding: "1px 6px",
        marginLeft: 6,
      }}
    >
      ROOKIE
    </span>
  );
}

function PlayerCell({ row, isRookie, rosteredBy }) {
  return (
    <span>
      <span style={{ fontWeight: 600 }}>{row?.name || "—"}</span>
      {row?.team || row?.age ? (
        <span className="muted text-xs" style={{ marginLeft: 6 }}>
          {row?.team || ""}{row?.age ? `, ${row.age}` : ""}
        </span>
      ) : null}
      {isRookie ? <RookieBadge /> : null}
      {rosteredBy ? (
        <span className="muted text-xs" style={{ marginLeft: 6 }}>
          rostered by {rosteredBy}
        </span>
      ) : null}
    </span>
  );
}

// ── Summary cards ─────────────────────────────────────────────────────

function SummaryCards({ summary, includeRookies }) {
  const cards = [
    {
      label: "Best available",
      value: summary.bestAddable?.name || "—",
      sub: summary.bestAddable
        ? `value ${fmtVal(summary.bestAddable.rankDerivedValue || summary.bestAddable.values?.full)}`
        : "no upgrades vs roster",
    },
    {
      label: "Top net gain",
      value: summary.bestGain > 0 ? `+${fmtVal(summary.bestGain)}` : "—",
      sub: "single-transaction value swing",
    },
    {
      label: "Addable players",
      value: summary.addableCount.toLocaleString(),
      sub: "beat at least one roster player",
    },
    {
      label: "Droppable players",
      value: summary.droppableCount.toLocaleString(),
      sub: "beaten by at least one FA",
    },
  ];
  if (includeRookies) {
    cards.push({
      label: "Rookies in mix",
      value: summary.rookieAddCount.toLocaleString(),
      sub: "rookie-flagged among addables",
    });
  }
  return (
    <div className="waiver-summary-grid">
      {cards.map((c) => (
        <div key={c.label} className="card waiver-summary-card">
          <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: "0.04em" }}>
            {c.label}
          </div>
          <div style={{ fontSize: "1.4rem", fontWeight: 700, marginTop: 4 }}>
            {c.value}
          </div>
          <div className="muted text-xs" style={{ marginTop: 2 }}>
            {c.sub}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Best moves table ───────────────────────────────────────────────────

function BestMovesSection({ moves }) {
  if (moves.length === 0) {
    return (
      <section className="card waiver-section">
        <h2 className="waiver-section-title">Best Add/Drop Moves</h2>
        <EmptyState
          title="No upgrades match your filters"
          message="Try widening the position filter, dropping the min-gain slider, or toggling rookies on."
        />
      </section>
    );
  }
  return (
    <section className="card waiver-section">
      <h2 className="waiver-section-title">Best Add/Drop Moves</h2>
      <p className="muted text-xs" style={{ margin: "0 0 10px" }}>
        Each add appears once with its lowest-value beaten roster player as the realistic drop.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36, textAlign: "center" }}>#</th>
              <th>Add</th>
              <th>Drop</th>
              <th style={{ textAlign: "right", width: 90 }}>Net gain</th>
              <th style={{ width: 130 }}>Tier</th>
            </tr>
          </thead>
          <tbody>
            {moves.map((m, i) => (
              <tr key={`${m.add.name}::${m.drop.name}`}>
                <td style={{ textAlign: "center", color: "var(--cyan)", fontWeight: 700 }}>{i + 1}</td>
                <td>
                  <PlayerCell row={m.add} isRookie={m.isRookie} />
                  <span style={{ marginLeft: 8 }}>
                    <PositionChip row={m.add} />
                  </span>
                </td>
                <td>
                  <PlayerCell row={m.drop} />
                  <span style={{ marginLeft: 8 }}>
                    <PositionChip row={m.drop} />
                  </span>
                </td>
                <td
                  style={{
                    textAlign: "right",
                    color: TIER_ACCENT[m.upgradeTier],
                    fontWeight: 700,
                    fontFamily: "var(--mono)",
                  }}
                >
                  {fmtGain(m.netGain)}
                </td>
                <td>{TIER_LABELS[m.upgradeTier]}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Best unique upgrade set ────────────────────────────────────────────

function BestUniqueUpgradeSection({ set }) {
  if (set.length === 0) return null;
  return (
    <section className="card waiver-section">
      <h2 className="waiver-section-title">Best Unique Upgrade Set</h2>
      <p className="muted text-xs" style={{ margin: "0 0 10px" }}>
        If you could claim every worthwhile add, these are the {set.length} pairings you'd run — best add into worst drop, no reuse on either side.
      </p>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th style={{ width: 36, textAlign: "center" }}>#</th>
              <th>Add</th>
              <th>Drop</th>
              <th style={{ textAlign: "right", width: 90 }}>Net gain</th>
            </tr>
          </thead>
          <tbody>
            {set.map((m, i) => (
              <tr key={`${m.add.name}::${m.drop.name}`}>
                <td style={{ textAlign: "center", color: "var(--cyan)", fontWeight: 700 }}>{i + 1}</td>
                <td>
                  <PlayerCell row={m.add} isRookie={m.isRookie} />
                  <span style={{ marginLeft: 8 }}>
                    <PositionChip row={m.add} />
                  </span>
                </td>
                <td>
                  <PlayerCell row={m.drop} />
                  <span style={{ marginLeft: 8 }}>
                    <PositionChip row={m.drop} />
                  </span>
                </td>
                <td
                  style={{
                    textAlign: "right",
                    color: "var(--green, #34d399)",
                    fontWeight: 700,
                    fontFamily: "var(--mono)",
                  }}
                >
                  {fmtGain(m.netGain)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// ── Droppable players section ──────────────────────────────────────────

function DroppableSection({ rows }) {
  return (
    <section className="card waiver-section">
      <h2 className="waiver-section-title" style={{ color: "var(--red, #f87171)" }}>
        Droppable Players
      </h2>
      <p className="muted text-xs" style={{ margin: "0 0 10px" }}>
        Bottom of your roster, sorted by replacement gain.
      </p>
      {rows.length === 0 ? (
        <EmptyState
          title="No drop candidates"
          message="Every player on your roster outranks the available pool."
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th style={{ textAlign: "right", width: 80 }}>Value</th>
                <th style={{ textAlign: "center", width: 60 }}>Better avail.</th>
                <th>Best replacement</th>
                <th style={{ textAlign: "right", width: 90 }}>+gain</th>
                <th style={{ width: 130 }}>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => (
                <tr key={d.row.name}>
                  <td>
                    <PlayerCell row={d.row} />
                    <span style={{ marginLeft: 8 }}>
                      <PositionChip row={d.row} />
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtVal(d.value)}</td>
                  <td style={{ textAlign: "center" }}>{d.betterAvailableCount}</td>
                  <td>
                    <PlayerCell row={d.bestReplacement} />
                  </td>
                  <td
                    style={{
                      textAlign: "right",
                      color: "var(--green, #34d399)",
                      fontWeight: 700,
                      fontFamily: "var(--mono)",
                    }}
                  >
                    {fmtGain(d.netGain)}
                  </td>
                  <td>{DROP_LABELS[d.dropConfidence]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Addable players section ────────────────────────────────────────────

function AddableSection({ rows }) {
  return (
    <section className="card waiver-section">
      <h2 className="waiver-section-title" style={{ color: "var(--green, #34d399)" }}>
        Addable Players
      </h2>
      <p className="muted text-xs" style={{ margin: "0 0 10px" }}>
        Every available player ranked higher than at least one of yours.
      </p>
      {rows.length === 0 ? (
        <EmptyState
          title="No addable players"
          message="Toggle rookies on, widen the position filter, or lower the min-gain to surface options."
        />
      ) : (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Player</th>
                <th style={{ textAlign: "right", width: 80 }}>Value</th>
                <th style={{ textAlign: "center", width: 50 }}>Beats</th>
                <th>Best drop</th>
                <th style={{ textAlign: "right", width: 90 }}>+gain</th>
                <th style={{ width: 130 }}>Tier</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => (
                <tr
                  key={a.row.name}
                  style={a.rosteredBy ? { opacity: 0.7 } : undefined}
                >
                  <td>
                    <PlayerCell
                      row={a.row}
                      isRookie={a.isRookie}
                      rosteredBy={a.rosteredBy}
                    />
                    <span style={{ marginLeft: 8 }}>
                      <PositionChip row={a.row} />
                    </span>
                  </td>
                  <td style={{ textAlign: "right", fontFamily: "var(--mono)" }}>{fmtVal(a.value)}</td>
                  <td style={{ textAlign: "center" }}>{a.betterCount}</td>
                  <td>
                    {a.rosteredBy ? (
                      <span className="muted text-xs">— (read-only)</span>
                    ) : (
                      <PlayerCell row={a.bestDrop} />
                    )}
                  </td>
                  <td
                    style={{
                      textAlign: "right",
                      color: TIER_ACCENT[a.upgradeTier],
                      fontWeight: 700,
                      fontFamily: "var(--mono)",
                    }}
                  >
                    {a.rosteredBy ? "—" : fmtGain(a.netGain)}
                  </td>
                  <td>
                    {a.rosteredBy ? (
                      <span className="muted text-xs">— (rostered)</span>
                    ) : (
                      TIER_LABELS[a.upgradeTier]
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

// ── Page entry ─────────────────────────────────────────────────────────

export default function WaiversPage() {
  const { privateDataEnabled } = useApp();
  const { authenticated } = useAuthContext();
  const [includeRookies, setIncludeRookies] = useState(false);
  const [position, setPosition] = useState("ALL");
  const [minGain, setMinGain] = useState(0);
  const [upgradeStrength, setUpgradeStrength] = useState("all");

  const filters = useMemo(
    () => ({ position, minGain, upgradeStrength }),
    [position, minGain, upgradeStrength],
  );

  const {
    analysis,
    loading,
    error,
    leagueMismatch,
    hasTeam,
    teamCount,
    selectedLeagueName,
  } = useWaiverAnalysis({ includeRookies, filters });

  return (
    <main className="main-shell waivers-page">
      <PageHeader
        title="Waiver Add/Drop"
        subtitle={
          selectedLeagueName
            ? `Compare every unrostered player against your roster — ${selectedLeagueName}`
            : "Compare every unrostered player against your roster"
        }
      />

      {/* ── Filter rail ─────────────────────────────────────────── */}
      <FilterBar style={{ marginBottom: 12 }}>
        <TeamSwitcher variant="desktop" />

        <label
          className="waiver-filter-toggle"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 10px",
          }}
          title="Include rookie-flagged players (incl. those on other rosters as read-only comparisons)"
        >
          <input
            type="checkbox"
            checked={includeRookies}
            onChange={(e) => setIncludeRookies(e.target.checked)}
          />
          <span className="text-sm">Include rookies</span>
        </label>

        <select
          className="select"
          value={position}
          onChange={(e) => setPosition(e.target.value)}
          aria-label="Position filter"
        >
          {POSITION_OPTIONS.map((p) => (
            <option key={p.value} value={p.value}>{p.label}</option>
          ))}
        </select>

        <select
          className="select"
          value={upgradeStrength}
          onChange={(e) => setUpgradeStrength(e.target.value)}
          aria-label="Upgrade strength"
        >
          {STRENGTH_OPTIONS.map((s) => (
            <option key={s.value} value={s.value}>{s.label}</option>
          ))}
        </select>

        <label
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 10px",
            minWidth: 200,
          }}
          title="Hide pairings whose net value gain is below this threshold."
        >
          <span className="text-xs muted" style={{ whiteSpace: "nowrap" }}>
            Min gain {fmtVal(minGain)}
          </span>
          <input
            type="range"
            min={0}
            max={5000}
            step={100}
            value={minGain}
            onChange={(e) => setMinGain(Number(e.target.value) || 0)}
            style={{ flex: 1 }}
          />
        </label>
      </FilterBar>

      {/* ── Empty / loading / error states ──────────────────────── */}
      {authenticated === false || privateDataEnabled === false ? (
        <EmptyState
          title="Sign in to view waivers"
          message="Waiver analysis is a private league feature — sign in to see your team's add/drop board."
        />
      ) : loading ? (
        <LoadingState />
      ) : error ? (
        <ErrorState message={error} />
      ) : leagueMismatch ? (
        <EmptyState
          title="League data not ready"
          message="The selected league's roster data hasn't been loaded yet. Switch leagues or try again in a moment."
        />
      ) : !hasTeam ? (
        <EmptyState
          title={teamCount === 0 ? "No teams available" : "Pick your team"}
          message={
            teamCount === 0
              ? "This league hasn't been ingested yet."
              : "Select a team in the topbar (or from the filter rail above) to start comparing."
          }
        />
      ) : !analysis ? (
        <LoadingState />
      ) : (
        <>
          <SummaryCards summary={analysis.summary} includeRookies={includeRookies} />
          <BestMovesSection moves={analysis.bestMoves} />
          <BestUniqueUpgradeSection set={analysis.bestUniqueUpgradeSet} />
          <div className="waivers-split">
            <DroppableSection rows={analysis.droppable} />
            <AddableSection rows={analysis.addable} />
          </div>
        </>
      )}

      {/* ── Page-scoped CSS (responsive layout) ─────────────────── */}
      <style jsx>{`
        .waivers-page {
          padding-bottom: var(--space-xl, 32px);
        }
        .waiver-summary-grid {
          display: grid;
          grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
          gap: 12px;
          margin: 0 0 16px;
        }
        .waiver-summary-card {
          padding: 12px 14px;
        }
        .waiver-section {
          margin-bottom: 14px;
          padding: 14px;
        }
        .waiver-section-title {
          font-size: 1.05rem;
          margin: 0 0 6px;
          font-weight: 700;
        }
        .waivers-split {
          display: grid;
          grid-template-columns: 1fr 1fr;
          gap: 14px;
        }
        @media (max-width: 900px) {
          .waivers-split {
            grid-template-columns: 1fr;
          }
        }
      `}</style>
    </main>
  );
}
