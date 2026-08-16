"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useApp } from "@/components/AppShell";
import { useSettings } from "@/components/useSettings";
import {
  Badge,
  Banner,
  DataTable,
  EmptyState,
  Field,
  Input,
  Movement,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { PlayerImage } from "@/components/ui";
import { TRADE_ALPHA } from "@/lib/trade-logic";
import {
  analyzeSleeperTradeHistory,
  analyzeTradeTendencies,
  buildCombinedPairTrade,
} from "@/lib/league-analysis";
import { encodeTrade, SHARE_PARAM } from "@/lib/trade-share";
import { useRankHistory } from "@/components/useRankHistory";
import { buildHistoryLookup } from "@/lib/value-history";
import { gradeRetro } from "@/lib/trade-retro-value";
import styles from "./trades.module.css";

// ── /trades — the trade ledger ────────────────────────────────────────
//
// Every analyzed league trade, the running winners/losers table, and
// per-manager tendencies.  All grading, value, and retro math lives in
// lib/league-analysis + lib/trade-retro-value + lib/value-history; this
// file only arranges the results.

const RETRO_LABEL = {
  aged_well: "Aged well",
  aged_poorly: "Aged poorly",
  stable: "Stable",
};

const RETRO_TONE = {
  aged_well: "positive",
  aged_poorly: "negative",
  stable: "neutral",
};

function fmtSigned(n) {
  const v = Math.round(Number(n) || 0);
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString()}`;
}

// ── Winners & losers ──────────────────────────────────────────────────

function TeamScoresPanel({ teamScores, alpha }) {
  const rows = useMemo(
    () =>
      Object.entries(teamScores).map(([key, s]) => ({
        key,
        team: s.displayName || "Unknown",
        trades: s.trades,
        won: s.won,
        lost: s.lost,
        totalGain: s.totalGain,
        // Same de-scaling the legacy card did: undo the alpha exponent
        // so the number reads on the display value scale.
        netValue:
          Math.sign(s.totalGain) *
          Math.round(Math.pow(Math.abs(s.totalGain), 1 / alpha)),
      })),
    [teamScores, alpha],
  );

  const columns = useMemo(
    () => [
      {
        key: "team",
        header: "Team",
        sortable: true,
        accessor: (r) => r.team,
      },
      {
        key: "trades",
        header: "Trades",
        numeric: true,
        sortable: true,
        accessor: (r) => r.trades,
      },
      {
        key: "record",
        header: "W-L",
        align: "center",
        accessor: (r) => r.won,
        render: (r) => `${r.won}-${r.lost}`,
      },
      {
        key: "netValue",
        header: "Net value",
        numeric: true,
        sortable: true,
        accessor: (r) => r.netValue,
        render: (r) => (
          <Movement delta={r.netValue} format={(n) => n.toLocaleString()} />
        ),
      },
    ],
    [],
  );

  if (!rows.length) return null;

  return (
    <Panel
      flush
      title="Trade winners & losers"
      subtitle={`Cumulative net value across every analyzed trade (alpha=${alpha}).`}
    >
      <DataTable
        caption="Per-team cumulative trade net value, best first"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        density="compact"
        defaultSort={{ key: "netValue", direction: "desc" }}
      />
    </Panel>
  );
}

function TendenciesPanel({ tendencies }) {
  const columns = useMemo(
    () => [
      { key: "manager", header: "Manager", sortable: true, accessor: (t) => t.manager },
      { key: "trades", header: "Trades", numeric: true, sortable: true, accessor: (t) => t.trades },
      {
        key: "avgGiven",
        header: "Avg given",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.avgGiven,
        render: (t) => t.avgGiven.toLocaleString(),
      },
      {
        key: "avgGot",
        header: "Avg got",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.avgGot,
        render: (t) => t.avgGot.toLocaleString(),
      },
      {
        key: "net",
        header: "Net",
        numeric: true,
        sortable: true,
        accessor: (t) => t.net,
        render: (t) => <Movement delta={t.net} format={(n) => n.toLocaleString()} />,
      },
      { key: "tendency", header: "Tendency", accessor: (t) => t.tendency },
    ],
    [],
  );

  if (!tendencies.length) return null;

  return (
    <Panel flush title="Trade tendencies" subtitle="How each manager trades.">
      <DataTable
        caption="Per-manager trade tendencies"
        columns={columns}
        rows={tendencies}
        rowKey={(t) => t.id || t.manager}
        density="compact"
        defaultSort={{ key: "trades", direction: "desc" }}
      />
    </Panel>
  );
}

// ── Trade entry ───────────────────────────────────────────────────────

function AssetPill({ item }) {
  return (
    <span className={styles.assetPill}>
      <PlayerImage
        playerId={item.playerId}
        team={item.team}
        position={item.pos}
        name={item.name}
        size={20}
      />
      <Badge tone="outline">{item.isPick ? "PICK" : item.pos}</Badge>
      <span className={styles.assetPillName}>{item.name}</span>
      {/* `val` is null when the board cannot price the asset.  It used
          to be 0, which rendered as a confident "0" beside a real
          value — the display half of MISSING IS NEVER ZERO. */}
      <span className={styles.assetPillValue} title={item.unresolved ? "No board value for this asset — excluded from the totals" : undefined}>
        {typeof item.val === "number" ? item.val.toLocaleString() : "—"}
      </span>
    </span>
  );
}

function AssetGroup({ label, items, total }) {
  return (
    <div className={styles.assetGroup}>
      <span className={styles.assetLabel}>
        {label}{" "}
        <span className={styles.assetLabelTotal}>
          ({Math.round(total).toLocaleString()})
        </span>
      </span>
      {items.length === 0 ? (
        <span className={styles.assetEmpty}>Nothing</span>
      ) : (
        <div className={styles.assetPills}>
          {items.map((item, j) => (
            <AssetPill key={j} item={item} />
          ))}
        </div>
      )}
    </div>
  );
}

function TradeEntry({ analysis: a, retroSides = [] }) {
  // Headline reflects the largest grievance — winner OR loser, whichever
  // has the biggest magnitude pctGap.  Under ±3% the trade reads fair.
  const showBadge = a.pctGap >= 3 && a.headlineSide;
  const isLoserHeadline = showBadge && a.headlineDirection === "overpaid";

  // Build a /trade?share=... href so clicking pre-loads the calculator.
  // Each calculator side mirrors what that team RECEIVED — the natural
  // "show me this as a 2-team deal" visualization.
  const shareHref = useMemo(() => {
    try {
      const sides = (a.sides || []).map((side) => ({
        name: String(side?.team || "").slice(0, 40),
        players: (side.got || [])
          .map((it) => String(it?.name || "").trim())
          .filter(Boolean),
      }));
      if (sides.length < 2 || sides.every((s) => s.players.length === 0)) {
        return null;
      }
      return `/trade?${SHARE_PARAM}=${encodeTrade({ sides })}`;
    } catch {
      return null;
    }
  }, [a.sides]);

  const body = (
    <>
      <div className={styles.entryHeader}>
        <span className={styles.entryDate}>
          {a.combined
            ? `${a.teamA} ↔ ${a.teamB} · ${a.tradeCount} trade${a.tradeCount === 1 ? "" : "s"} combined`
            : `Week ${a.trade.week} · ${a.date}`}
        </span>
        {showBadge ? (
          <Badge tone={isLoserHeadline ? "negative" : "positive"}>
            {a.headlineSide.team}{" "}
            {isLoserHeadline ? "overpaid by" : "won by"} {a.pctGap.toFixed(1)}%
          </Badge>
        ) : (
          <Badge tone="neutral">Fair trade</Badge>
        )}
      </div>

      <div
        className={styles.sides}
        data-sides={a.sides.length > 2 ? "3" : "2"}
      >
        {a.sides.map((side, i) => {
          const retro = retroSides[i];
          const retroLabel = retro ? RETRO_LABEL[retro.verdict] : null;
          const retroDelta = Number.isFinite(retro?.verdictDelta)
            ? Math.round(retro.verdictDelta)
            : null;
          // The V13-adjusted net is the meaningful "did this team win"
          // quantity; VA contribution shown inline when it moved things.
          const net = side.netAdjusted ?? side.netValue;
          return (
            <div key={i} className={styles.side}>
              <div className={styles.sideHead}>
                <span className={styles.sideTeam}>{side.team}</span>
                {side.grade ? (
                  <>
                    <span className={styles.sideGrade}>{side.grade.grade}</span>
                    <span className={styles.entryDate}>{side.grade.label}</span>
                  </>
                ) : null}
              </div>
              <AssetGroup label="Gave" items={side.gave} total={side.gaveValue} />
              <AssetGroup label="Got" items={side.got} total={side.gotValue} />
              <div className={styles.sideNet}>
                <span>Net {fmtSigned(net)}</span>
                {side.vaNet != null && Math.abs(side.vaNet) >= 1 ? (
                  <span className={styles.sideNetVa}>
                    ({fmtSigned(side.vaNet)} VA)
                  </span>
                ) : null}
                {retroLabel ? (
                  <Badge tone={RETRO_TONE[retro.verdict] || "neutral"}>
                    {retroDelta != null
                      ? `${retroLabel} (${fmtSigned(retroDelta)})`
                      : retroLabel}
                  </Badge>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>

      {shareHref ? (
        <div className={styles.entryFooter}>Open in the trade calculator →</div>
      ) : null}
    </>
  );

  const entryClass = [
    styles.entry,
    showBadge ? (isLoserHeadline ? styles.entryLost : styles.entryWon) : "",
  ]
    .filter(Boolean)
    .join(" ");

  if (shareHref) {
    return (
      <Panel
        as={Link}
        href={shareHref}
        className={`${entryClass} ${styles.entryLink}`}
        aria-label={`Open the ${a.sides.map((s) => s.team).join(" / ")} trade in the calculator`}
      >
        {body}
      </Panel>
    );
  }

  return <Panel className={entryClass}>{body}</Panel>;
}

function CombinedSection({ combined, teamA, teamB }) {
  if (!combined) {
    return (
      <Panel>
        <EmptyState
          title="No head-to-head trades"
          description={`${teamA} and ${teamB} have never traded directly with each other (3+ team trades are not combined).`}
        />
      </Panel>
    );
  }
  if (combined.wash) {
    return (
      <Panel>
        <EmptyState
          title="Net wash"
          description={`Across ${combined.tradeCount} trade${
            combined.tradeCount === 1 ? "" : "s"
          }, every asset ${teamA} and ${teamB} swapped eventually came back — the combined trade nets to nothing.`}
        />
      </Panel>
    );
  }
  return (
    <div className={styles.ledger}>
      <TradeEntry analysis={combined} retroSides={[]} />
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────

export default function TradesPage() {
  const { rows, rawData, loading, error } = useApp();
  const { settings } = useSettings();
  const [teamFilter, setTeamFilter] = useState("");
  const [teamFilterB, setTeamFilterB] = useState("");
  const [playerQuery, setPlayerQuery] = useState("");

  const alpha = settings.alpha || TRADE_ALPHA;
  const windowDays = settings.tradeHistoryWindowDays || 365;
  const analysis = useMemo(
    () => analyzeSleeperTradeHistory(rawData, rows, windowDays, alpha),
    [rawData, rows, windowDays, alpha],
  );

  // Rank history lets each trade be valued at the date it happened.
  // ``useRankHistory`` is single-flight + cached for 60s.
  const { history: rankHistory } = useRankHistory({ days: 365 });
  const historyLookup = useMemo(() => buildHistoryLookup(rankHistory), [rankHistory]);

  const retroByTrade = useMemo(() => {
    if (!analysis?.analyzed?.length) return new Map();
    const out = new Map();
    for (const a of analysis.analyzed) {
      const ts =
        Number(a.trade?._statusUpdatedMs) || Date.parse(a.date) || Date.now();
      out.set(
        a.id,
        (a.sides || []).map((side) =>
          gradeRetro({
            side,
            currentNet: side.netValue,
            asOfMs: ts,
            historyLookup,
          }),
        ),
      );
    }
    return out;
  }, [analysis, historyLookup]);

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
      results = results.filter((a) => a.sides.some((s) => s.team === teamFilter));
    }
    if (q) {
      // Match any item name on either side — ``item.name`` covers both
      // players and picks, so one input does both.
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

  // Two distinct teams ⇒ collapse their head-to-head history into one
  // synthetic trade; assets that bounced back and forth cancel out.
  const combineMode = !!(teamFilter && teamFilterB && teamFilter !== teamFilterB);
  const combined = useMemo(() => {
    if (!combineMode) return null;
    return buildCombinedPairTrade(
      analysis,
      teamFilter,
      teamFilterB,
      rawData,
      rows,
      alpha,
    );
  }, [combineMode, analysis, teamFilter, teamFilterB, rawData, rows, alpha]);

  const tendencies = useMemo(
    () => analyzeTradeTendencies(rawData, rows),
    [rawData, rows],
  );

  const hasTrades = analysis.analyzed.length > 0;

  return (
    <main className={`main-shell ${styles.page} trades-page`}>
      <PageHeader
        eyebrow="Trades"
        title="Trade History"
        description={
          // The count comes from the contract, so it is only true once
          // the contract is actually here.  While loading (or after a
          // failed load) ``analysis.analyzed`` is empty for want of
          // data, and printing "0 trades in the last N days" states a
          // settled fact we do not have — the snapshot behind this page
          // routinely carries 100+ trades.  Say what is actually
          // happening instead; the skeleton / error banner below
          // carries the detail.
          loading
            ? `Grading trades from the last ${windowDays} days…`
            : error
              ? "Trade history unavailable — the board data failed to load."
              : combineMode
                ? `Combined head-to-head: ${teamFilter} ↔ ${teamFilterB} — assets that bounced back cancel out.`
                : `${analysis.analyzed.length} trades in the last ${windowDays} days, graded at alpha=${alpha}.`
        }
      />

      {loading ? (
        <Panel flush title="Trade History">
          <SkeletonTable rows={6} columns={4} />
        </Panel>
      ) : error ? (
        <Banner tone="negative" title="Couldn't load trade data">
          {error}
        </Banner>
      ) : !hasTrades ? (
        <Panel>
          <EmptyState
            title="No trades found"
            description="Load dynasty data with a Sleeper league to see trade history."
          />
        </Panel>
      ) : (
        <>
          <Panel dense className="trades-controls">
            <div className={styles.controls}>
              {!combineMode ? (
                <div className={styles.controlsSearch}>
                  <Field label="Search" id="trades-search">
                    <Input
                      id="trades-search"
                      type="search"
                      placeholder="Player or pick…"
                      value={playerQuery}
                      onChange={(e) => setPlayerQuery(e.target.value)}
                    />
                  </Field>
                </div>
              ) : null}
              {teams.length > 0 ? (
                <Field label="Team" id="trades-team">
                  <Select
                    id="trades-team"
                    value={teamFilter}
                    onChange={(e) => {
                      const v = e.target.value;
                      setTeamFilter(v);
                      // Clearing the first team, or matching the second,
                      // drops the combine selection.
                      if (!v || v === teamFilterB) setTeamFilterB("");
                    }}
                  >
                    <option value="">All teams</option>
                    {teams.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : null}
              {teams.length > 0 && teamFilter ? (
                <Field label="Combine with" id="trades-team-b">
                  <Select
                    id="trades-team-b"
                    value={teamFilterB}
                    onChange={(e) => setTeamFilterB(e.target.value)}
                  >
                    <option value="">— none —</option>
                    {teams
                      .filter((t) => t !== teamFilter)
                      .map((t) => (
                        <option key={t} value={t}>
                          vs {t}
                        </option>
                      ))}
                  </Select>
                </Field>
              ) : null}
            </div>
          </Panel>

          {combineMode ? (
            <CombinedSection
              combined={combined}
              teamA={teamFilter}
              teamB={teamFilterB}
            />
          ) : (
            <>
              <TeamScoresPanel teamScores={analysis.teamScores} alpha={alpha} />
              <TendenciesPanel tendencies={tendencies} />

              {filtered.length > 0 ? (
                <div className={styles.ledger}>
                  {filtered.map((a, idx) => (
                    <TradeEntry
                      key={a.id ?? idx}
                      analysis={a}
                      retroSides={retroByTrade.get(a.id) || []}
                    />
                  ))}
                </div>
              ) : null}

              {(teamFilter || playerQuery) && filtered.length === 0 ? (
                <Panel>
                  <EmptyState
                    title="No trades match"
                    description={
                      teamFilter && playerQuery
                        ? `No trades for ${teamFilter} involving "${playerQuery}".`
                        : playerQuery
                          ? `No trades involving "${playerQuery}".`
                          : `No trades found for ${teamFilter}.`
                    }
                  />
                </Panel>
              ) : null}
            </>
          )}
        </>
      )}
    </main>
  );
}
