"use client";

import { useMemo, useState } from "react";
import {
  Badge,
  Banner,
  DataTable,
  EmptyState,
  Field,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
  StatTile,
  ValueBasisNote,
} from "@/components/ds";
import TeamSwitcher from "@/components/TeamSwitcher";
import ManualAddDrop from "@/components/waivers/ManualAddDrop";
import { useApp } from "@/components/AppShell";
import { useAuthContext } from "@/app/AppShellWrapper";
import { useLeague } from "@/components/useLeague";
import { useTeam } from "@/components/useTeam";
import { useSettings } from "@/components/useSettings";
import { useWaiverAnalysis } from "@/components/useWaiverAnalysis";
import { computeFaabHint } from "@/lib/waiver-logic";
import styles from "./waivers.module.css";

// ── /waivers — the claim desk ─────────────────────────────────────────
//
// Compares every unrostered (and optionally every rookie-flagged) player
// against the user's selected team.  Surfaces:
//
//   • Manual add/drop calculator + the FAAB v2 bid desk (the headline —
//     see components/waivers/FaabRecommendation.jsx)
//   • Best Add/Drop Moves       — top single-transaction upgrades
//   • Best Unique Upgrade Set   — multi-transaction greedy slate
//   • Droppable / Addable       — the two sides of the pool
//
// All comparison logic lives in ``frontend/lib/waiver-logic.js``; the hook
// in ``frontend/components/useWaiverAnalysis.js`` wires the pure logic to
// the app context.  This file is layout only — it does no value math.

const POSITION_OPTIONS = [
  { value: "ALL", label: "All positions" },
  { value: "QB", label: "QB" },
  { value: "RB", label: "RB" },
  { value: "WR", label: "WR" },
  { value: "TE", label: "TE" },
  { value: "DL", label: "DL" },
  { value: "LB", label: "LB" },
  { value: "DB", label: "DB" },
];

const STRENGTH_OPTIONS = [
  { value: "all", label: "All strengths" },
  { value: "considering", label: "Considering & up" },
  { value: "strong", label: "Strong & up" },
  { value: "smash", label: "Smash only" },
];

const TIER_LABELS = {
  smash: "Smash add",
  strong: "Strong add",
  considering: "Worth considering",
  marginal: "Marginal add",
};

// Upgrade tiers are ranked judgments, so they map onto the semantic
// tones rather than decorative colors: smash/strong are actionable
// positives, the rest are neutral information.
const TIER_TONE = {
  smash: "positive",
  strong: "accent",
  considering: "neutral",
  marginal: "neutral",
};

const DROP_LABELS = {
  obvious: "Obvious drop",
  reasonable: "Reasonable drop",
  risky: "Risky drop",
  hold: "Hold unless needed",
};

const DROP_TONE = {
  obvious: "positive",
  reasonable: "neutral",
  risky: "warning",
  hold: "neutral",
};

function fmtVal(v) {
  return (Number(v) || 0).toLocaleString();
}

function fmtGain(v) {
  const n = Math.round(Number(v) || 0);
  return n > 0 ? `+${n.toLocaleString()}` : `${n}`;
}

function PlayerCell({ row, isRookie, rosteredBy }) {
  if (!row) return <span className={styles.playerMeta}>—</span>;
  const meta = [row?.team, row?.age].filter(Boolean).join(" · ");
  return (
    <span className={styles.playerCell}>
      <Badge tone="outline">{row?.pos || "?"}</Badge>
      <span className={styles.playerName}>{row?.name || "—"}</span>
      {meta ? <span className={styles.playerMeta}>{meta}</span> : null}
      {isRookie ? <Badge tone="accent">Rookie</Badge> : null}
      {rosteredBy ? (
        <span className={styles.playerMeta}>rostered by {rosteredBy}</span>
      ) : null}
    </span>
  );
}

// ── Sections ──────────────────────────────────────────────────────────

function SummaryTiles({ summary, includeRookies }) {
  const tiles = [
    {
      label: "Best available",
      value: summary.bestAddable?.name || "—",
      meta: summary.bestAddable
        ? `value ${fmtVal(
            summary.bestAddable.rankDerivedValue || summary.bestAddable.values?.full,
          )}`
        : "no upgrades vs roster",
    },
    {
      label: "Top net gain",
      value: summary.bestGain > 0 ? `+${fmtVal(summary.bestGain)}` : "—",
      meta: "single-transaction swing",
    },
    {
      label: "Addable players",
      value: summary.addableCount.toLocaleString(),
      meta: "beat at least one of yours",
    },
    {
      label: "Droppable players",
      value: summary.droppableCount.toLocaleString(),
      meta: "beaten by at least one FA",
    },
  ];
  if (includeRookies) {
    tiles.push({
      label: "Rookies in mix",
      value: summary.rookieAddCount.toLocaleString(),
      meta: "rookie-flagged addables",
    });
  }
  return (
    <div className={styles.summaryGrid} data-cols={String(tiles.length)}>
      {tiles.map((t) => (
        <StatTile key={t.label} label={t.label} value={t.value} meta={t.meta} />
      ))}
    </div>
  );
}

function BestMovesPanel({ moves }) {
  // FAAB hint baseline, calibrated against the strongest add in this
  // batch so a row reads as "what share of budget does this command?".
  // The full recommender (league analytics + contention + team cap) runs
  // only for the user's selected pair on the bid desk above.
  const topAddValue = useMemo(
    () =>
      moves.reduce((acc, m) => {
        const v = Number(m.addValue || m.add?.rankDerivedValue || m.add?.values?.full || 0);
        return v > acc ? v : acc;
      }, 0),
    [moves],
  );

  const columns = useMemo(
    () => [
      {
        key: "rank",
        header: "#",
        numeric: true,
        align: "center",
        render: (_row, i) => i + 1,
      },
      {
        key: "add",
        header: "Add",
        accessor: (m) => m.add?.name,
        render: (m) => <PlayerCell row={m.add} isRookie={m.isRookie} />,
      },
      {
        key: "drop",
        header: "Drop",
        accessor: (m) => m.drop?.name,
        render: (m) => <PlayerCell row={m.drop} />,
      },
      {
        key: "netGain",
        header: "Net gain",
        numeric: true,
        sortable: true,
        accessor: (m) => m.netGain,
        render: (m) => fmtGain(m.netGain),
      },
      {
        key: "faab",
        header: "FAAB hint",
        numeric: true,
        hideBelow: "md",
        accessor: (m) =>
          computeFaabHint(
            Number(m.addValue || m.add?.rankDerivedValue || m.add?.values?.full || 0),
            { leagueBudget: 100, topValueInPool: topAddValue },
          ).reasonable,
        render: (m) => {
          const hint = computeFaabHint(
            Number(m.addValue || m.add?.rankDerivedValue || m.add?.values?.full || 0),
            { leagueBudget: 100, topValueInPool: topAddValue },
          );
          return `$${hint.reasonable}`;
        },
        headerInfo: "Quick baseline share of a $100 budget — use the bid desk for a league-aware recommendation.",
      },
      {
        key: "tier",
        header: "Tier",
        accessor: (m) => m.upgradeTier,
        render: (m) => (
          <Badge tone={TIER_TONE[m.upgradeTier] || "neutral"}>
            {TIER_LABELS[m.upgradeTier]}
          </Badge>
        ),
      },
    ],
    [topAddValue],
  );

  return (
    <Panel
      flush
      title="Best add/drop moves"
      subtitle="Each add appears once, paired with its lowest-value beaten roster player."
    >
      <DataTable
        caption="Top single-transaction add/drop upgrades, best net gain first"
        columns={columns}
        rows={moves}
        rowKey={(m) => `${m.add?.name}::${m.drop?.name}`}
        density="compact"
        presorted
        emptyState={
          <EmptyState
            title="No upgrades match your filters"
            description="Widen the position filter, lower the min-gain threshold, or include rookies."
          />
        }
      />
    </Panel>
  );
}

function UniqueUpgradePanel({ set }) {
  const columns = useMemo(
    () => [
      {
        key: "rank",
        header: "#",
        numeric: true,
        align: "center",
        render: (_row, i) => i + 1,
      },
      {
        key: "add",
        header: "Add",
        accessor: (m) => m.add?.name,
        render: (m) => <PlayerCell row={m.add} isRookie={m.isRookie} />,
      },
      {
        key: "drop",
        header: "Drop",
        accessor: (m) => m.drop?.name,
        render: (m) => <PlayerCell row={m.drop} />,
      },
      {
        key: "netGain",
        header: "Net gain",
        numeric: true,
        sortable: true,
        accessor: (m) => m.netGain,
        render: (m) => fmtGain(m.netGain),
      },
    ],
    [],
  );

  if (!set.length) return null;

  return (
    <Panel
      flush
      title="Best unique upgrade set"
      subtitle={`If every claim landed, these are the ${set.length} pairings you'd run — no player reused on either side.`}
    >
      <DataTable
        caption="Non-overlapping add/drop slate, best net gain first"
        columns={columns}
        rows={set}
        rowKey={(m) => `${m.add?.name}::${m.drop?.name}`}
        density="compact"
        presorted
      />
    </Panel>
  );
}

function DroppablePanel({ rows }) {
  const columns = useMemo(
    () => [
      {
        key: "player",
        header: "Player",
        accessor: (d) => d.row?.name,
        render: (d) => <PlayerCell row={d.row} />,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        sortable: true,
        accessor: (d) => d.value,
        render: (d) => fmtVal(d.value),
      },
      {
        key: "betterAvailableCount",
        header: "Better avail.",
        numeric: true,
        sortable: true,
        align: "center",
        hideBelow: "md",
        accessor: (d) => d.betterAvailableCount,
      },
      {
        key: "replacement",
        header: "Best replacement",
        hideBelow: "lg",
        accessor: (d) => d.bestReplacement?.name,
        render: (d) => <PlayerCell row={d.bestReplacement} />,
      },
      {
        key: "netGain",
        header: "+gain",
        numeric: true,
        sortable: true,
        accessor: (d) => d.netGain,
        render: (d) => fmtGain(d.netGain),
      },
      {
        key: "confidence",
        header: "Confidence",
        accessor: (d) => d.dropConfidence,
        render: (d) => (
          <Badge tone={DROP_TONE[d.dropConfidence] || "neutral"}>
            {DROP_LABELS[d.dropConfidence]}
          </Badge>
        ),
      },
    ],
    [],
  );

  return (
    <Panel
      flush
      title="Droppable"
      subtitle="Bottom of your roster, sorted by replacement gain."
    >
      <DataTable
        caption="Roster players beaten by the available pool"
        columns={columns}
        rows={rows}
        rowKey={(d) => d.row?.name}
        density="compact"
        presorted
        emptyState={
          <EmptyState
            title="No drop candidates"
            description="Every player on your roster outranks the available pool."
          />
        }
      />
    </Panel>
  );
}

function AddablePanel({ rows }) {
  const columns = useMemo(
    () => [
      {
        key: "player",
        header: "Player",
        accessor: (a) => a.row?.name,
        render: (a) => (
          <PlayerCell row={a.row} isRookie={a.isRookie} rosteredBy={a.rosteredBy} />
        ),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        sortable: true,
        accessor: (a) => a.value,
        render: (a) => fmtVal(a.value),
      },
      {
        key: "betterCount",
        header: "Beats",
        numeric: true,
        sortable: true,
        align: "center",
        hideBelow: "md",
        accessor: (a) => a.betterCount,
      },
      {
        key: "bestDrop",
        header: "Best drop",
        hideBelow: "lg",
        accessor: (a) => a.bestDrop?.name,
        render: (a) =>
          a.rosteredBy ? (
            <span className={styles.playerMeta}>read-only</span>
          ) : (
            <PlayerCell row={a.bestDrop} />
          ),
      },
      {
        key: "netGain",
        header: "+gain",
        numeric: true,
        sortable: true,
        accessor: (a) => (a.rosteredBy ? null : a.netGain),
        render: (a) => (a.rosteredBy ? "—" : fmtGain(a.netGain)),
      },
      {
        key: "tier",
        header: "Tier",
        accessor: (a) => a.upgradeTier,
        render: (a) =>
          a.rosteredBy ? (
            <Badge tone="neutral">Rostered</Badge>
          ) : (
            <Badge tone={TIER_TONE[a.upgradeTier] || "neutral"}>
              {TIER_LABELS[a.upgradeTier]}
            </Badge>
          ),
      },
    ],
    [],
  );

  return (
    <Panel
      flush
      title="Addable"
      subtitle="Every available player ranked above at least one of yours."
    >
      <DataTable
        caption="Available players that beat someone on your roster"
        columns={columns}
        rows={rows}
        rowKey={(a) => a.row?.name}
        density="compact"
        presorted
        rowClassName={(a) => (a.rosteredBy ? styles.rosteredRow : "")}
        emptyState={
          <EmptyState
            title="No addable players"
            description="Include rookies, widen the position filter, or lower the min-gain threshold."
          />
        }
      />
    </Panel>
  );
}

// ── Page ──────────────────────────────────────────────────────────────

export default function WaiversPage() {
  const { privateDataEnabled, rows, rawData } = useApp();
  const { authenticated } = useAuthContext();
  const { selectedLeague } = useLeague();
  const { selectedTeam } = useTeam();
  const { settings } = useSettings();
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

  const signedOut = authenticated === false || privateDataEnabled === false;

  function renderBody() {
    if (signedOut) {
      return (
        <EmptyState
          title="Sign in to view waivers"
          description="Waiver analysis is a private league feature — sign in to see your team's claim desk."
        />
      );
    }
    if (error) return <Banner tone="negative" title="Waiver analysis failed">{error}</Banner>;
    if (leagueMismatch) {
      return (
        <EmptyState
          title="League data not ready"
          description="The selected league's rosters haven't loaded yet. Switch leagues or try again in a moment."
        />
      );
    }
    if (loading || !analysis) {
      return (
        <Panel flush title="Best add/drop moves">
          <SkeletonTable rows={8} columns={6} />
        </Panel>
      );
    }
    if (!hasTeam) {
      return (
        <EmptyState
          title={teamCount === 0 ? "No teams available" : "Pick your team"}
          description={
            teamCount === 0
              ? "This league hasn't been ingested yet."
              : "Select a team above to start comparing the pool against your roster."
          }
        />
      );
    }
    return (
      <>
        <SummaryTiles summary={analysis.summary} includeRookies={includeRookies} />
        <BestMovesPanel moves={analysis.bestMoves} />
        <UniqueUpgradePanel set={analysis.bestUniqueUpgradeSet} />
        <div className={styles.split}>
          <DroppablePanel rows={analysis.droppable} />
          <AddablePanel rows={analysis.addable} />
        </div>
      </>
    );
  }

  return (
    <main className={`main-shell ${styles.page} waivers-page`}>
      <PageHeader
        eyebrow="My Team"
        title="Waivers"
        description={
          selectedLeagueName
            ? `Every unrostered player measured against your roster — ${selectedLeagueName}`
            : "Every unrostered player measured against your roster"
        }
      />

      <ValueBasisNote contract={rawData} />

      {!signedOut && !leagueMismatch ? (
        <ManualAddDrop
          rows={rows}
          selectedTeam={selectedTeam}
          sleeperTeams={rawData?.sleeper?.teams}
          idpEnabled={Boolean(selectedLeague?.idpEnabled)}
          includeRookies={includeRookies}
          settings={settings}
          leagueKey={selectedLeague?.key}
        />
      ) : null}

      <Panel dense className="waivers-controls">
        <div className={styles.controls}>
          <TeamSwitcher variant="desktop" />

          <Field label="Position" id="waiver-pos">
            <Select
              id="waiver-pos"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            >
              {POSITION_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Upgrade strength" id="waiver-strength">
            <Select
              id="waiver-strength"
              value={upgradeStrength}
              onChange={(e) => setUpgradeStrength(e.target.value)}
            >
              {STRENGTH_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
          </Field>

          <div className={styles.controlsGain}>
            <label className={styles.controlsGainLabel} htmlFor="waiver-min-gain">
              <span>Min net gain</span>
              <span className="ds-mono">{fmtVal(minGain)}</span>
            </label>
            <input
              id="waiver-min-gain"
              type="range"
              min={0}
              max={5000}
              step={100}
              value={minGain}
              onChange={(e) => setMinGain(Number(e.target.value) || 0)}
            />
          </div>

          <label className={styles.controlsToggle}>
            <input
              type="checkbox"
              checked={includeRookies}
              onChange={(e) => setIncludeRookies(e.target.checked)}
            />
            <span>Include rookies</span>
          </label>
        </div>
      </Panel>

      {renderBody()}
    </main>
  );
}
