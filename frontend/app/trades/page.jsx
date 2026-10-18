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
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { PlayerImage } from "@/components/ui";
import { TRADE_ALPHA, packageModelReceipt } from "@/lib/trade-logic";
import {
  analyzeSleeperTradeHistory,
  buildCombinedPairTrade,
} from "@/lib/league-analysis";
import { useManagerScout } from "@/components/useManagerScout";
import {
  managerScoutCoverage,
  managerScoutRows,
  stateText,
} from "@/lib/manager-scout";
import { encodeTrade, SHARE_PARAM } from "@/lib/trade-share";
import { useTradeAsofGrades } from "@/components/useTradeAsofGrades";
import {
  AGING,
  AGING_LABEL,
  AGING_REASON_TEXT,
  AGING_STABLE_BAND_PRIOR,
  sideAging,
  tradeKey,
} from "@/lib/trade-history-grades";
import styles from "./trades.module.css";

// ── /trades — the trade ledger ────────────────────────────────────────
//
// Every analyzed league trade, the running winners/losers table, and
// per-manager tendencies.  Current grades come from lib/league-analysis
// (today's board), At-the-Time grades from the canonical ledger via
// POST /api/trades/asof-grades, and aging from lib/trade-history-grades —
// all three under the ONE active package model (owner 2026-10-17).  The
// tendencies come from the private Manager Scout owner
// (`/api/manager-scout`, src/intel/manager_scout.py — C6-MGR-01) and are
// only formatted here.  This file only arranges the results.

// ``unavailable`` is a rendered state, not an omission.  A trade whose
// at-the-time value could not be established must not silently look like a
// trade nobody graded — and it must never borrow one of the three verdicts.
const AGING_TONE = {
  [AGING.AGED_WELL]: "positive",
  [AGING.AGED_POORLY]: "negative",
  [AGING.STABLE]: "neutral",
  [AGING.UNAVAILABLE]: "neutral",
};

function fmtSigned(n) {
  const v = Math.round(Number(n) || 0);
  return `${v >= 0 ? "+" : "−"}${Math.abs(v).toLocaleString()}`;
}

// ── Winners & losers ──────────────────────────────────────────────────

function TeamScoresPanel({ teamScores, alpha, modelLabel }) {
  // Default: Σ of each trade's adjusted net (raw + package adjustment) — the
  // same per-trade number the cards show, summed (owner package
  // 2026-10-17).  The alpha-weighted won/lost-only sum is a DIFFERENT
  // metric, kept only as an opt-in "legacy concentration index".
  const [metric, setMetric] = useState("adjusted");
  const rows = useMemo(
    () =>
      Object.entries(teamScores).map(([key, s]) => ({
        key,
        team: s.displayName || "Unknown",
        trades: s.trades,
        won: s.won,
        lost: s.lost,
        incompleteTrades: s.incompleteTrades || 0,
        netValue:
          metric === "legacy"
            ? // Undo the alpha exponent so the index reads on the display scale.
              Math.sign(s.totalGain) * Math.round(Math.pow(Math.abs(s.totalGain), 1 / alpha))
            : Math.round(s.netAdjustedTotal),
      })),
    [teamScores, alpha, metric],
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
        header: metric === "legacy" ? "Legacy index" : "Net value",
        numeric: true,
        sortable: true,
        accessor: (r) => r.netValue,
        render: (r) => (
          <span title={r.incompleteTrades ? `${r.incompleteTrades} trade(s) include an asset today's board cannot price` : undefined}>
            <Movement delta={r.netValue} format={(n) => n.toLocaleString()} />
            {r.incompleteTrades ? "*" : ""}
          </span>
        ),
      },
    ],
    [metric],
  );

  if (!rows.length) return null;

  return (
    <Panel
      flush
      title="Trade winners & losers"
      subtitle={
        metric === "legacy"
          ? `Legacy concentration index — alpha-weighted (alpha=${alpha}), won and lost trades only. A different metric from net value.`
          : `Sum of every trade's adjusted net (raw value + package adjustment, ${modelLabel}) at today's values. * = includes an asset today's board cannot price.`
      }
      actions={
        <SegmentedControl
          label="Winners & losers metric"
          value={metric}
          onChange={setMetric}
          options={[
            { value: "adjusted", label: "Net value" },
            { value: "legacy", label: "Legacy index" },
          ]}
        />
      }
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

// A count/value, or the reason there is none — never a fabricated 0.
function cell(value, state, format = (v) => v.toLocaleString()) {
  if (value === null || value === undefined) {
    return <span className={styles.muted}>{stateText(state)}</span>;
  }
  return format(value);
}

const FAILURE_COPY = {
  not_ready: "Tendencies load once this league's data is loaded.",
  league: "This league can't be profiled.",
  auth: "Sign in to see manager tendencies.",
  unavailable: "Manager Scout couldn't read its sources right now.",
};

function TendenciesPanel() {
  const { loading, data, failure } = useManagerScout();
  const rows = useMemo(() => managerScoutRows(data), [data]);
  const coverage = useMemo(() => managerScoutCoverage(data), [data]);

  const columns = useMemo(
    () => [
      { key: "manager", header: "Manager", sortable: true, accessor: (t) => t.manager },
      {
        key: "trades",
        header: "Trades",
        numeric: true,
        sortable: true,
        accessor: (t) => t.trades,
        render: (t) => cell(t.trades, t.tradeState),
      },
      // Today's canonical board, RAW value sum (not Value-Adjusted), per
      // trade — the backend's `valueAtToday`. Unpriced assets are excluded
      // from the sums and counted, never added as 0.
      {
        key: "gotPerTrade",
        header: "Avg got (today)",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.gotPerTrade,
        render: (t) => cell(t.gotPerTrade, t.valueState),
      },
      {
        key: "gavePerTrade",
        header: "Avg given (today)",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.gavePerTrade,
        render: (t) => cell(t.gavePerTrade, t.valueState),
      },
      {
        key: "netPerTrade",
        header: "Net (today)",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.netPerTrade,
        render: (t) =>
          t.netPerTrade === null ? (
            cell(null, t.valueState)
          ) : (
            <span>
              <Movement delta={t.netPerTrade} format={(n) => n.toLocaleString()} />
              {t.unpricedAssets ? (
                <span className={styles.muted}>{` · ${t.unpricedAssets} unpriced`}</span>
              ) : null}
            </span>
          ),
      },
      {
        key: "topPartner",
        header: "Top partner",
        accessor: (t) => t.topPartner,
        render: (t) => cell(t.topPartner, t.tradeState, (v) => v),
      },
      {
        key: "picks",
        header: "Picks in / out",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.picksIn,
        render: (t) =>
          t.picksIn === null
            ? cell(null, t.tradeState)
            : `${t.picksIn} / ${t.picksOut}`,
      },
      {
        key: "bought",
        header: "Bought",
        hideBelow: "md",
        accessor: (t) => t.bought,
        render: (t) => cell(t.bought, t.tradeState, (v) => v),
      },
      {
        key: "sold",
        header: "Sold",
        hideBelow: "lg",
        accessor: (t) => t.sold,
        render: (t) => cell(t.sold, t.tradeState, (v) => v),
      },
      {
        key: "claims",
        header: "Waiver claims",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.claims,
        render: (t) => cell(t.claims, t.waiverState),
      },
      {
        key: "faab",
        header: "Avg FAAB bid",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (t) => t.faabMeanPct,
        render: (t) =>
          t.faabMeanPct === null ? (
            cell(null, t.faabState)
          ) : (
            <span title={`${t.faabSample} resolved bids`}>
              {`${t.faabMeanPct.toFixed(1)}%`}
              {t.faabRatio !== null ? (
                <span className={styles.muted}>{` · ${t.faabRatio.toFixed(2)}× lg`}</span>
              ) : null}
            </span>
          ),
      },
    ],
    [],
  );

  const seasons = coverage.seasons.length
    ? coverage.seasons.length > 1
      ? `${coverage.seasons[0]}–${coverage.seasons[coverage.seasons.length - 1]}`
      : coverage.seasons[0]
    : null;
  const subtitle = [
    "Private · descriptive, from this league's recorded trades, waiver claims and FAAB bids",
    coverage.trades !== null ? `${coverage.trades} trades` : null,
    coverage.claims !== null ? `${coverage.claims} claims` : null,
    seasons,
    coverage.boardState === "available"
      ? "values at today's board, raw sum, not VA-adjusted"
      : null,
    coverage.lineupState === "not_applicable" ? "lineups n/a (best ball)" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  if (loading && !data) {
    return (
      <Panel flush title="Trade tendencies" subtitle="Loading manager profiles…">
        <SkeletonTable rows={4} columns={5} />
      </Panel>
    );
  }
  if (failure) {
    return (
      <Panel title="Trade tendencies">
        <Banner tone={failure.kind === "error" ? "negative" : "warning"} title="Tendencies unavailable">
          {FAILURE_COPY[failure.kind] || failure.message || "Request failed."}
        </Banner>
      </Panel>
    );
  }
  if (!rows.length) return null;

  return (
    <Panel flush title="Trade tendencies" subtitle={subtitle}>
      {coverage.ledgerState && coverage.ledgerState !== "available" ? (
        <Banner tone="warning" title="Transaction ledger not on this server">
          Trade and waiver tendencies are unavailable until the acquisition ledger is built.
        </Banner>
      ) : null}
      <DataTable
        caption="Per-manager trade, waiver and FAAB tendencies"
        columns={columns}
        rows={rows}
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

function GradeLine({ when, grade, testId }) {
  return (
    <span className={styles.entryDate} data-testid={testId}>
      {when}:{" "}
      {grade && grade.grade ? (
        <>
          <span className={styles.sideGrade}>{grade.grade}</span> {grade.label}
        </>
      ) : (
        <em>{grade?.label || "unavailable"}</em>
      )}
    </span>
  );
}

// ``atTimeSides`` / ``asofStatus`` come from the at-the-time endpoint;
// ``null`` sides mean "not graded at the time" (combined head-to-head
// trades span several dates, so they have no single at-the-time instant).
function TradeEntry({ analysis: a, atTimeSides = null, asofStatus = "idle", modelMatches = true }) {
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
          const atTime = atTimeSides ? atTimeSides[i] : null;
          const aging = atTimeSides
            ? sideAging(side, atTime, { modelMatches })
            : null;
          const agingDelta = Number.isFinite(aging?.delta) ? Math.round(aging.delta) : null;
          // The adjusted net (raw + package adjustment) is the "did this team
          // win" quantity; the adjustment is shown inline when it moved things.
          const net = side.netAdjusted ?? side.netValue;
          const atTimeGrade =
            asofStatus === "loading"
              ? { label: "loading…" }
              : atTime && atTime.available === true
                ? atTime.grade
                : { label: "unavailable" };
          return (
            <div key={i} className={styles.side}>
              <div className={styles.sideHead}>
                <span className={styles.sideTeam}>{side.team}</span>
                {side.grade ? (
                  <GradeLine when="Today" grade={side.grade} testId="trade-grade-today" />
                ) : null}
                {atTimeSides ? (
                  <GradeLine when="When traded" grade={atTimeGrade} testId="trade-grade-at-trade" />
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
                {aging && asofStatus !== "loading" ? (
                  <span
                    data-testid="trade-aging"
                    title={
                      aging.verdict === AGING.UNAVAILABLE
                        ? `Aging unavailable: ${AGING_REASON_TEXT[aging.reason] || aging.reason}.`
                        : `Change in adjusted net since the trade (today − when traded). Within ±${AGING_STABLE_BAND_PRIOR} reads Stable — a provisional band, not yet calibrated.`
                    }
                  >
                    <Badge tone={AGING_TONE[aging.verdict] || "neutral"}>
                      {agingDelta != null
                        ? `${AGING_LABEL[aging.verdict]} (${fmtSigned(agingDelta)})`
                        : AGING_LABEL[aging.verdict]}
                    </Badge>
                  </span>
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
      <TradeEntry analysis={combined} />
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

  // At-the-Time grades: the canonical ledger as of each trade's own instant,
  // one request for the whole window (src/api/trade_history_asof.py).
  const asof = useTradeAsofGrades(analysis.analyzed);
  const activeModel = useMemo(() => packageModelReceipt(), []);
  // Aging compares two nets, so both must come from the same package model.
  const modelMatches = !asof.packageModel || asof.packageModel.id === activeModel.id;
  const keyByEntry = useMemo(() => {
    const m = new Map();
    analysis.analyzed.forEach((a, i) => m.set(a, tradeKey(a, i)));
    return m;
  }, [analysis]);

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

  const hasTrades = analysis.analyzed.length > 0;

  return (
    <div className={`main-shell ${styles.page} trades-page`}>
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
                : `${analysis.analyzed.length} trades in the last ${windowDays} days, graded under ${activeModel.label}.`
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
              <TeamScoresPanel
                teamScores={analysis.teamScores}
                alpha={alpha}
                modelLabel={activeModel.label}
              />
              <TendenciesPanel />

              {filtered.length > 0 ? (
                <div className={styles.ledger}>
                  {filtered.map((a, idx) => {
                    const key = keyByEntry.get(a) ?? `f:${idx}`;
                    return (
                      <TradeEntry
                        key={key}
                        analysis={a}
                        atTimeSides={
                          asof.byTrade.get(key) ||
                          a.sides.map(() => ({ available: false, reason: asof.reason || "at_time_unavailable" }))
                        }
                        asofStatus={asof.status}
                        modelMatches={modelMatches}
                      />
                    );
                  })}
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
    </div>
  );
}
