"use client";

/**
 * Manager Intelligence — Recent trades, Acquisitions, Activity and Draft
 * capital tabs (C6-MGR-02 Batches B1 + B2 + the unified feed + B3).  B3's
 * Tendencies section sits under Recent trades (it is counted from them).
 *
 * Mounted by ./page.jsx the first time one of these tabs opens (and kept
 * mounted after), so the activity lookup never delays the portfolio and
 * switching tabs never refetches.  Display layer only: every
 * value, total, package comparison, at-time grade and coverage state comes
 * from GET /api/manager-intel/activity (`src/intel/manager_activity.py`);
 * `lib/manager-intel.js` filters, labels and builds calculator links.  An
 * unpriced asset shows "—", an undated event says "Undated", and a league
 * that was not fully read is named in the coverage banner.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  DataTable,
  EmptyState,
  Field,
  Input,
  Panel,
  PlayerNameButton,
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import {
  ACTIVITY_WINDOWS,
  TRADE_DIRECTIONS,
  activityQuery,
  assetLabel,
  attributionNote,
  capitalCountsText,
  capitalValueText,
  coverageProblems,
  draftCapitalLeagues,
  draftYearsText,
  errorMessage,
  eventDateText,
  faabText,
  feedKindLabel,
  filterAcquisitions,
  filterFeed,
  filterTrades,
  formatBadge,
  formatDate,
  formatValue,
  methodDetail,
  methodLabel,
  pickMovementRows,
  pickOriginText,
  pickOwnershipText,
  rosterStatusText,
  seasonOptions,
  shapeRows,
  sideAssets,
  signedValue,
  stillHeldText,
  subsequentLabel,
  tradeCalculatorShare,
  tendencyFlowText,
  tendencySampleText,
  tradeCalculatorUrl,
  valueReasonText,
} from "@/lib/manager-intel";
import { encodeTrade } from "@/lib/trade-share";
import styles from "./managers.module.css";

function AssetRow({ asset }) {
  const reason = asset.value == null ? valueReasonText(asset.valueReason) : "";
  return (
    <li className={styles.assetRow}>
      <span className={styles.assetName}>
        {assetLabel(asset)}
        {asset.kind === "player" && asset.position ? (
          <span className={styles.muted}> {asset.position}</span>
        ) : null}
      </span>
      <span className={styles.assetValue} title={reason || undefined}>
        {formatValue(asset.value)}
        {reason ? <span className={styles.srOnly}> ({reason})</span> : null}
      </span>
    </li>
  );
}

function TradeSide({ side }) {
  const gets = sideAssets(side, "in");
  return (
    <div
      className={styles.tradeSide}
      data-manager={side.isManager || undefined}
    >
      <h4>
        {side.displayName || `Roster ${side.rosterId}`}
        {side.isManager ? (
          <span className={styles.muted}> · this manager</span>
        ) : null}
      </h4>
      <p className={styles.sideLabel}>Gets</p>
      {gets.length ? (
        <ul className={styles.assetList}>
          {gets.map((a) => (
            <AssetRow
              key={`${a.kind}:${a.playerId || a.pickId || a.label}`}
              asset={a}
            />
          ))}
        </ul>
      ) : (
        <p className={styles.muted}>No players or picks</p>
      )}
      {typeof side.faabIn === "number" ? (
        <p className={styles.muted}>+ {faabText(side.faabIn)}</p>
      ) : null}
      <dl className={styles.sideTotals}>
        <div>
          <dt>In</dt>
          <dd>{formatValue(side.incomingValue)}</dd>
        </div>
        <div>
          <dt>Out</dt>
          <dd>{formatValue(side.outgoingValue)}</dd>
        </div>
      </dl>
      {side.unpricedAssets?.length ? (
        <p className={styles.note}>
          Totals withheld: {side.unpricedAssets.map((u) => u.name).join(", ")}{" "}
          {side.unpricedAssets.length === 1 ? "has" : "have"} no current value.
        </p>
      ) : null}
    </div>
  );
}

function reasonText(reason) {
  const map = {
    history_ledger_missing: "no value history recorded",
    history_ledger_unreadable: "value history unreadable",
    no_historical_evidence:
      "no recorded value before the trade for every asset",
    invalid_trade_instant: "trade time unknown",
    unpriced_assets: "an asset has no current value",
    at_time_unavailable: "at-the-time grade unavailable",
    current_comparison_unavailable: "current comparison unavailable",
  };
  return map[reason] || reason || "unavailable";
}

function TradeCard({ trade, modelLabel }) {
  const partners = (trade.sides || [])
    .filter((s) => !s.isManager)
    .map((s) => s.displayName || `Roster ${s.rosterId}`);
  const pc = trade.packageComparison || {};
  const at = trade.atTime?.manager;
  const aging = trade.aging?.manager;
  const url = tradeCalculatorUrl(trade, encodeTrade);
  const share = tradeCalculatorShare(trade);
  const note = attributionNote(trade.attribution);
  return (
    <article
      className={styles.trade}
      aria-label={`Trade ${formatDate(trade.occurredAt)}`}
    >
      <header className={styles.tradeHead}>
        <span className={styles.tradeDate}>{eventDateText(trade)}</span>
        <span>{trade.leagueName || "Unnamed league"}</span>
        <span className={styles.muted}>{formatBadge(trade.format)}</span>
        <span className={styles.muted}>
          {trade.season} · week {trade.week ?? "—"}
        </span>
        {trade.teamCount > 2 ? (
          <Badge tone="outline">{trade.teamCount}-team</Badge>
        ) : null}
        <span className={styles.muted}>Complete</span>
      </header>
      <p className={styles.note}>With {partners.join(", ") || "—"}</p>
      {note ? <p className={styles.note}>{note}</p> : null}
      <div className={styles.tradeSides}>
        {(trade.sides || []).map((side) => (
          <TradeSide key={side.rosterId} side={side} />
        ))}
      </div>
      <dl className={styles.tradeVerdict}>
        <div>
          <dt>Today ({modelLabel})</dt>
          <dd>
            {pc.available && pc.manager
              ? `${signedValue(pc.manager.adjustedNet)} adjusted (raw ${signedValue(pc.manager.rawNet)}) · ${pc.manager.grade} ${pc.manager.label}`
              : `Unavailable — ${reasonText(pc.reason)}`}
          </dd>
        </div>
        <div>
          <dt>At the time</dt>
          <dd>
            {at?.available
              ? `${signedValue(at.adjustedNet)} adjusted · ${at.grade} ${at.label}`
              : `Unavailable — ${reasonText(at?.reason)}`}
          </dd>
        </div>
        <div>
          <dt>How it aged</dt>
          <dd>
            {aging?.available
              ? signedValue(aging.delta)
              : `Unavailable — ${reasonText(aging?.reason)}`}
          </dd>
        </div>
      </dl>
      {pc.note ? <p className={styles.note}>{pc.note}</p> : null}
      <p className={styles.tradeLinks}>
        {url ? (
          <a href={url} className={styles.link}>
            Open in Trade Calculator
          </a>
        ) : (
          <span className={styles.muted}>
            Not available in the Trade Calculator
          </span>
        )}
        {url && !share.complete ? (
          <span className={styles.muted}>
            {" "}
            · without{" "}
            {[...share.missing, ...(share.faabOmitted ? ["FAAB"] : [])].join(
              ", ",
            )}
          </span>
        ) : null}
      </p>
    </article>
  );
}

function CoverageBanner({ activity }) {
  const problems = coverageProblems(activity);
  const cov = activity?.coverage || {};
  return (
    <>
      {problems.length ? (
        <Banner tone="warning" title="Some leagues were not fully read">
          <ul className={styles.problemList}>
            {problems.map((p) => (
              <li key={p.leagueId}>
                {p.name}: {p.text}
              </li>
            ))}
          </ul>
          Activity from these leagues may be missing.
        </Banner>
      ) : null}
      {cov.budgetExhausted ? (
        <Banner tone="info" title="Lookup budget reached">
          This account has more activity than one lookup reads; narrow the
          window or pick one league.
        </Banner>
      ) : null}
      {cov.truncated ? (
        <Banner tone="info" title="Large account — partially shown">
          Only the first {cov.maxLeagues} leagues were read.
        </Banner>
      ) : null}
    </>
  );
}

function RecentTrades({ activity, league }) {
  const [query, setQuery] = useState("");
  const [direction, setDirection] = useState("any");
  const trades = useMemo(
    () => filterTrades(activity.trades, { league, query, direction }),
    [activity.trades, league, query, direction],
  );
  const modelLabel = activity.packageModel?.label || "active package model";
  return (
    <Panel
      title="Recent trades"
      subtitle={`${formatValue(trades.length)} of ${formatValue((activity.trades || []).length)} completed trades`}
    >
      <div className={styles.filters}>
        <Field label="Player or pick">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} />
        </Field>
        <Field label="Direction">
          <Select
            value={direction}
            onChange={(e) => setDirection(e.target.value)}
          >
            {TRADE_DIRECTIONS.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      {trades.length ? (
        <div className={styles.tradeList}>
          {trades.map((t) => (
            <TradeCard key={t.id} trade={t} modelLabel={modelLabel} />
          ))}
        </div>
      ) : (
        <EmptyState
          title={
            (activity.trades || []).length
              ? "No trades match"
              : "No completed trades"
          }
          description={
            (activity.trades || []).length
              ? "Clear a filter to see more."
              : "No completed trade in the leagues read for this window."
          }
        />
      )}
      <p className={styles.note}>{activity.valueBasis?.note}</p>
    </Panel>
  );
}

const FLOW_COLUMNS = [
  { key: "key", header: "Group", accessor: (row) => row.key },
  {
    key: "acquired",
    header: "Acquired",
    numeric: true,
    headerInfo:
      "Players received: count · summed current value of the priced ones.",
    accessor: (row) => row.acquired.count,
    render: (row) => tendencyFlowText(row.acquired),
  },
  {
    key: "sent",
    header: "Sent",
    numeric: true,
    headerInfo:
      "Players sent: count · summed current value of the priced ones.",
    accessor: (row) => row.sent.count,
    render: (row) => tendencyFlowText(row.sent),
  },
];

function SampleNote({ block, tendencies }) {
  return (
    <p
      className={styles.note}
      data-insufficient={block && !block.sufficientSample ? "true" : undefined}
    >
      {tendencySampleText(block, tendencies)}
    </p>
  );
}

function ShapeList({ block, tendencies, label }) {
  const rows = shapeRows(block?.counts);
  return (
    <div className={styles.tendencyBlock}>
      <h4>{label}</h4>
      <SampleNote block={block} tendencies={tendencies} />
      {block?.sufficientSample && rows.length ? (
        <ul className={styles.shapeList} aria-label={label}>
          {rows.map((r) => (
            <li key={r.key}>
              <span>{r.label}</span>
              <span className={styles.assetValue}>{r.count}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function FlowTable({ block, tendencies, label, caption }) {
  return (
    <div className={styles.tendencyBlock}>
      <h4>{label}</h4>
      <SampleNote block={block} tendencies={tendencies} />
      {block?.sufficientSample ? (
        <DataTable
          columns={FLOW_COLUMNS}
          rows={block.rows || []}
          rowKey={(row) => row.key}
          caption={caption}
          density="compact"
          emptyState={<EmptyState title="No players moved" />}
        />
      ) : null}
    </div>
  );
}

export function Tendencies({ tendencies }) {
  if (!tendencies) return null;
  return (
    <Panel
      title="Tendencies"
      subtitle={`${formatValue(tendencies.tradeCount)} trade${tendencies.tradeCount === 1 ? "" : "s"} counted`}
    >
      <p className={styles.note}>
        Counts from this manager&apos;s completed trades — evidence, not labels.
        A block with fewer than {tendencies.minSample} observations is marked
        insufficient.
        {tendencies.excludedUncertain
          ? ` ${tendencies.excludedUncertain} trade${tendencies.excludedUncertain === 1 ? "" : "s"} with uncertain attribution left out.`
          : ""}
      </p>
      <div className={styles.tendencyGrid}>
        <ShapeList
          block={tendencies.pickPlayer}
          tendencies={tendencies}
          label="Picks vs players"
        />
        <ShapeList
          block={tendencies.pieces}
          tendencies={tendencies}
          label="Piece counts"
        />
      </div>
      <FlowTable
        block={tendencies.positions}
        tendencies={tendencies}
        label="By position"
        caption="Players acquired and sent by trade, by position."
      />
      <FlowTable
        block={tendencies.ages}
        tendencies={tendencies}
        label="By age"
        caption="Players acquired and sent by trade, by current age."
      />
      <p className={styles.note}>
        Ages are current ages, not ages at the time of the trade.
      </p>
    </Panel>
  );
}

const PICK_COLUMNS = [
  {
    key: "pick",
    header: "Pick",
    accessor: (row) => row.label,
  },
  {
    key: "origin",
    header: "Origin",
    accessor: (row) => pickOriginText(row),
  },
  {
    key: "value",
    header: "Value",
    numeric: true,
    headerInfo:
      "Canonical board value at the generic season + round grade. — means unpriced.",
    accessor: (row) => row.value,
    render: (row) => (
      <span
        title={row.value == null ? valueReasonText(row.valueReason) : undefined}
      >
        {formatValue(row.value)}
      </span>
    ),
  },
];

function LeagueCapital({ entry }) {
  const unknown = pickOwnershipText(entry);
  return (
    <Panel
      title={entry.name || "Unnamed league"}
      subtitle={
        [formatBadge(entry.format), draftYearsText(entry.draftYears)]
          .filter(Boolean)
          .join(" · ") || undefined
      }
      dense
    >
      {unknown ? (
        <p className={styles.note} role="status">
          Pick ownership unavailable — {unknown}
        </p>
      ) : (
        <>
          <p className={styles.note}>
            {capitalCountsText(entry)} · value {capitalValueText(entry)}
          </p>
          <DataTable
            columns={PICK_COLUMNS}
            rows={entry.picks || []}
            rowKey={(row) => row.pickId || row.label}
            caption={`Picks held in ${entry.name || "this league"}`}
            density="compact"
            emptyState={
              <EmptyState
                title="Holds no picks"
                description="Every pick in the classes listed has been traded away."
              />
            }
          />
          {entry.ownPicksTradedAway?.length ? (
            <p className={styles.note}>
              Own picks traded away:{" "}
              {entry.ownPicksTradedAway
                .map(
                  (p) =>
                    `${p.label} (now ${p.currentOwnerName || `roster ${p.currentOwnerRosterId}`})`,
                )
                .join(", ")}
            </p>
          ) : null}
        </>
      )}
    </Panel>
  );
}

export function DraftCapital({ activity, league }) {
  const dc = activity?.draftCapital;
  if (!dc?.available) {
    return (
      <Panel title="Draft capital">
        <EmptyState
          title="Current season only"
          description="Draft capital is what a manager holds now, so it is shown for the current season only."
        />
      </Panel>
    );
  }
  const entries = draftCapitalLeagues(dc, league);
  const moves = pickMovementRows(dc, league);
  const t = dc.totals || {};
  return (
    <>
      <Panel title="Draft capital" subtitle="Picks held now, by league">
        <dl className={styles.analytics}>
          <div>
            <dt>Picks held</dt>
            <dd>
              {formatValue(t.picksHeld)} ({formatValue(t.acquiredHeld)}{" "}
              acquired)
            </dd>
          </div>
          <div>
            <dt>Own picks traded away</dt>
            <dd>{formatValue(t.ownTradedAway)}</dd>
          </div>
          <div>
            <dt>Value of priced picks</dt>
            <dd>
              {formatValue(t.pricedValue)}
              {t.unpricedPickCount
                ? ` · ${formatValue(t.unpricedPickCount)} unpriced`
                : ""}
            </dd>
          </div>
          <div>
            <dt>Leagues</dt>
            <dd>
              {formatValue(t.leaguesObserved)} read
              {t.leaguesUnavailable
                ? ` · ${formatValue(t.leaguesUnavailable)} unknown`
                : ""}
            </dd>
          </div>
        </dl>
        <p className={styles.note}>{dc.valueNote}</p>
      </Panel>
      {entries.length ? (
        entries.map((e) => <LeagueCapital key={e.leagueId} entry={e} />)
      ) : (
        <EmptyState
          title="No leagues"
          description="This manager holds no roster in a readable league of this type."
        />
      )}
      <Panel
        title="Pick movement"
        subtitle={`${formatValue(moves.length)} pick${moves.length === 1 ? "" : "s"} traded in this window`}
      >
        {moves.length ? (
          <ol className={styles.feed}>
            {moves.map((r) => (
              <li key={r.id} className={styles.feedRow}>
                <span className={styles.tradeDate}>{eventDateText(r)}</span>
                <span className={styles.feedKind}>
                  {r.direction === "acquired" ? "Acquired" : "Sent"}
                </span>
                <span className={styles.muted}>
                  {r.leagueName || "Unnamed league"}
                </span>
                <span className={styles.feedBody}>
                  {assetLabel(r.pick)} ({formatValue(r.pick?.value)})
                  {r.counterparty?.displayName
                    ? ` · ${r.direction === "acquired" ? "from" : "to"} ${r.counterparty.displayName}`
                    : ""}
                  {` · ${stillHeldText(r)}`}
                </span>
              </li>
            ))}
          </ol>
        ) : (
          <EmptyState
            title="No picks traded"
            description="No pick moved in a completed trade in this window."
          />
        )}
      </Panel>
    </>
  );
}

function Analytics({ analytics }) {
  if (!analytics) return null;
  const join = (obj, label = (k) => k) =>
    Object.entries(obj || {})
      .map(([k, n]) => `${label(k)} ${n}`)
      .join(" · ") || "—";
  return (
    <Panel title="Acquisition analytics" dense>
      <dl className={styles.analytics}>
        <div>
          <dt>Acquisitions</dt>
          <dd>
            {formatValue(analytics.acquisitionCount)} (
            {formatValue(analytics.pricedAcquisitions)} priced)
          </dd>
        </div>
        <div>
          <dt>By method</dt>
          <dd>{join(analytics.byMethod, methodLabel)}</dd>
        </div>
        <div>
          <dt>By position</dt>
          <dd>{join(analytics.byPosition)}</dd>
        </div>
        <div>
          <dt>Adds vs drops</dt>
          <dd>
            {formatValue(analytics.addsVsDrops?.adds)} added ·{" "}
            {formatValue(analytics.addsVsDrops?.drops)} dropped ·{" "}
            {formatValue(analytics.addsVsDrops?.tradedAway)} traded away
          </dd>
        </div>
        <div>
          <dt>Rookies · IDP</dt>
          <dd>
            {formatValue(analytics.rookies?.count)} rookies ·{" "}
            {formatValue(analytics.idp?.count)} IDP
          </dd>
        </div>
        <div>
          <dt>Later traded or dropped</dt>
          <dd>
            {formatValue((analytics.subsequentlyTradedOrDropped || []).length)}
          </dd>
        </div>
        <div>
          <dt>Most valuable</dt>
          <dd>
            {(analytics.mostValuable || [])
              .slice(0, 5)
              .map((m) => `${m.name} ${formatValue(m.value)}`)
              .join(" · ") || "—"}
          </dd>
        </div>
        <div>
          <dt>Repeat targets</dt>
          <dd>
            {(analytics.repeatTargets || [])
              .map(
                (r) =>
                  `${r.name} ×${r.timesAcquired} (${r.leagueCount} league${r.leagueCount === 1 ? "" : "s"})`,
              )
              .join(" · ") || "None"}
          </dd>
        </div>
      </dl>
    </Panel>
  );
}

const ACQ_COLUMNS = [
  {
    key: "date",
    header: "Date",
    sortable: true,
    accessor: (row) => row.occurredAt,
    render: (row) => eventDateText(row),
  },
  {
    key: "player",
    header: "Player",
    sortable: true,
    accessor: (row) => assetLabel(row.player),
    render: (row) => (
      <span className={styles.playerCell}>
        <PlayerNameButton
          name={assetLabel(row.player)}
          playerId={row.player.playerId}
        />
        <span className={styles.muted}>{row.player.position || ""}</span>
      </span>
    ),
  },
  {
    key: "method",
    header: "Method",
    sortable: true,
    accessor: (row) => methodDetail(row),
  },
  {
    key: "league",
    header: "League",
    sortable: true,
    hideBelow: "sm",
    accessor: (row) => row.leagueName || "—",
  },
  {
    key: "value",
    header: "Value",
    numeric: true,
    sortable: true,
    headerInfo:
      "Current canonical board value. — means the board does not price him.",
    accessor: (row) => row.player.value,
    render: (row) => formatValue(row.player.value),
  },
  {
    key: "rank",
    header: "Rank",
    numeric: true,
    sortable: true,
    hideBelow: "md",
    firstDirection: "asc",
    accessor: (row) => row.player.rank,
    render: (row) => formatValue(row.player.rank),
  },
  {
    key: "status",
    header: "Now",
    sortable: true,
    hideBelow: "sm",
    accessor: (row) => rosterStatusText(row),
  },
  {
    key: "gaveUp",
    header: "Gave up",
    hideBelow: "md",
    accessor: (row) => (row.gaveUp || []).map(assetLabel).join(", ") || "—",
  },
  {
    key: "later",
    header: "Later",
    sortable: true,
    hideBelow: "md",
    accessor: (row) => subsequentLabel(row.subsequent),
  },
];

const SUMMARY_COLUMNS = [
  {
    key: "name",
    header: "Player",
    sortable: true,
    accessor: (row) => row.name || row.playerId,
  },
  {
    key: "times",
    header: "Times",
    numeric: true,
    sortable: true,
    accessor: (row) => row.timesAcquired,
  },
  {
    key: "leagues",
    header: "Leagues",
    numeric: true,
    sortable: true,
    accessor: (row) => row.leagueCount,
  },
  {
    key: "methods",
    header: "Methods",
    hideBelow: "sm",
    accessor: (row) =>
      Object.entries(row.methods || {})
        .map(([m, n]) => `${methodLabel(m)} ${n}`)
        .join(" · "),
  },
  {
    key: "latest",
    header: "Latest",
    hideBelow: "md",
    sortable: true,
    accessor: (row) => row.latestAt,
    render: (row) => formatDate(row.latestAt),
  },
  {
    key: "value",
    header: "Value",
    numeric: true,
    sortable: true,
    accessor: (row) => row.value,
    render: (row) => formatValue(row.value),
  },
];

function Acquisitions({ activity, league }) {
  const [method, setMethod] = useState("");
  const [query, setQuery] = useState("");
  const rows = useMemo(
    () => filterAcquisitions(activity.acquisitions, { league, method, query }),
    [activity.acquisitions, league, method, query],
  );
  return (
    <>
      <Panel
        title="Acquisitions"
        subtitle={`${formatValue(rows.length)} of ${formatValue((activity.acquisitions || []).length)} players acquired`}
      >
        <div className={styles.filters}>
          <Field label="Search players">
            <Input value={query} onChange={(e) => setQuery(e.target.value)} />
          </Field>
          <Field label="Method">
            <Select value={method} onChange={(e) => setMethod(e.target.value)}>
              <option value="">All methods</option>
              {["TRADE", "WAIVER", "FREE_AGENT", "DRAFT", "OTHER"].map((m) => (
                <option key={m} value={m}>
                  {methodLabel(m)}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        <DataTable
          columns={ACQ_COLUMNS}
          rows={rows}
          rowKey={(row) => row.id}
          caption="Players this manager acquired, with method, current value, roster status and what was given up."
          density="compact"
          emptyState={
            <EmptyState
              title={
                (activity.acquisitions || []).length
                  ? "No acquisitions match"
                  : "No acquisitions"
              }
              description="Only completed transactions and draft picks count."
            />
          }
        />
        {activity.coverage?.excluded?.previous_owner_possible ? (
          <p className={styles.note}>
            {activity.coverage.excluded.previous_owner_possible} move
            {activity.coverage.excluded.previous_owner_possible === 1
              ? ""
              : "s"}{" "}
            made by someone other than the roster&apos;s current owners are not
            counted (see Activity).
          </p>
        ) : null}
      </Panel>
      <Analytics analytics={activity.analytics} />
      <Panel
        title="Player summary"
        subtitle="Across every league read"
        collapsible
        collapsed
      >
        <DataTable
          columns={SUMMARY_COLUMNS}
          rows={activity.playerSummary || []}
          rowKey={(row) => row.playerId}
          caption="Each acquired player once, with how often and where he was acquired."
          density="compact"
          emptyState={<EmptyState title="No players acquired" />}
        />
      </Panel>
    </>
  );
}

function ActivityFeed({ activity, league }) {
  const events = useMemo(
    () => filterFeed(activity.feed, { league }),
    [activity.feed, league],
  );
  return (
    <Panel title="Activity" subtitle={`${formatValue(events.length)} events`}>
      {events.length ? (
        <ol className={styles.feed}>
          {events.map((e) => (
            <li key={e.id} className={styles.feedRow}>
              <span className={styles.tradeDate}>{eventDateText(e)}</span>
              <span className={styles.feedKind}>{feedKindLabel(e.kind)}</span>
              <span className={styles.muted}>
                {e.leagueName || "Unnamed league"}
              </span>
              <span className={styles.feedBody}>
                {e.added?.length
                  ? `+ ${e.added.map(assetLabel).join(", ")}`
                  : null}
                {e.added?.length && e.dropped?.length ? " · " : null}
                {e.dropped?.length
                  ? `− ${e.dropped.map(assetLabel).join(", ")}`
                  : null}
                {typeof e.faabBid === "number" ? ` · $${e.faabBid} FAAB` : null}
                {e.partners?.length ? ` · with ${e.partners.join(", ")}` : null}
                {e.draft?.round != null && e.draft?.slot != null
                  ? ` · pick ${e.draft.round}.${String(e.draft.slot).padStart(2, "0")}`
                  : null}
              </span>
              {attributionNote(e.attribution) ? (
                <span className={styles.note}>
                  {attributionNote(e.attribution)}
                </span>
              ) : null}
            </li>
          ))}
        </ol>
      ) : (
        <EmptyState
          title="No activity"
          description="No completed transaction or draft pick in the leagues read for this window."
        />
      )}
    </Panel>
  );
}

export default function ManagerActivity({ username, scope, profile, tab }) {
  const currentSeason = profile?.season || "";
  const [win, setWin] = useState("30d");
  const [season, setSeason] = useState(currentSeason);
  const [league, setLeague] = useState("");
  const [state, setState] = useState({
    phase: "loading",
    data: null,
    error: null,
  });
  // League options come from the last answer read WITHOUT a league filter
  // (seeded from the profile), so picking one league — which narrows the
  // Sleeper reads — never shrinks the list.
  const [leagueOptions, setLeagueOptions] = useState(
    () => profile?.leagues || [],
  );
  const earlier = season && season !== currentSeason;

  useEffect(() => {
    let cancelled = false;
    setState((prev) => ({ phase: "loading", data: prev.data, error: null }));
    fetch(
      activityQuery(username, {
        window: earlier ? "season" : win,
        season: earlier ? season : "",
        league,
        scope,
      }),
      { cache: "no-store", credentials: "same-origin" },
    )
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (cancelled) return;
        if (!response.ok) {
          setState({
            phase: "error",
            data: null,
            error: errorMessage(response.status, body),
          });
          return;
        }
        setState({ phase: "ready", data: body, error: null });
        if (!league) setLeagueOptions(body?.leagues || []);
      })
      .catch(() => {
        if (!cancelled)
          setState({
            phase: "error",
            data: null,
            error: errorMessage(0, null),
          });
      });
    return () => {
      cancelled = true;
    };
  }, [username, scope, win, season, earlier, league]);

  const activity = state.data;
  const leagues = leagueOptions;

  return (
    <div className={styles.activity}>
      <div className={styles.filters}>
        <SegmentedControl
          label="Window"
          value={earlier ? "season" : win}
          onChange={(v) => {
            setWin(v);
            if (earlier) {
              setLeague("");
              setSeason(currentSeason);
            }
          }}
          options={ACTIVITY_WINDOWS}
        />
        <Field label="Season">
          <Select
            value={season}
            onChange={(e) => {
              // League ids change every season (Sleeper chains new ids).
              setLeague("");
              setSeason(e.target.value);
            }}
          >
            {seasonOptions(currentSeason).map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="League">
          <Select value={league} onChange={(e) => setLeague(e.target.value)}>
            <option value="">All leagues</option>
            {leagues.map((l) => (
              <option key={l.leagueId} value={l.leagueId}>
                {l.name || "Unnamed league"}
              </option>
            ))}
          </Select>
        </Field>
      </div>

      {state.phase === "error" ? (
        <Banner tone="negative" title="Activity unavailable">
          {state.error}
        </Banner>
      ) : null}

      {state.phase === "loading" && !activity ? (
        <Panel title="Reading activity">
          <p className={styles.note}>
            Reading every week of every league from Sleeper — this can take a
            few seconds.
          </p>
          <SkeletonTable rows={6} columns={5} />
        </Panel>
      ) : null}

      {activity ? (
        <>
          {state.phase === "loading" ? (
            <p className={styles.note} role="status">
              Refreshing…
            </p>
          ) : null}
          <CoverageBanner activity={activity} />
          {!activity.hasBoard ? (
            <Banner tone="info" title="Values unavailable">
              The canonical board is not loaded right now, so values show as —.
            </Banner>
          ) : null}
          {tab === "trades" ? (
            <>
              <RecentTrades activity={activity} league={league} />
              <Tendencies tendencies={activity.tendencies} />
            </>
          ) : null}
          {tab === "draft" ? (
            <DraftCapital activity={activity} league={league} />
          ) : null}
          {tab === "acquisitions" ? (
            <Acquisitions activity={activity} league={league} />
          ) : null}
          {tab === "activity" ? (
            <ActivityFeed activity={activity} league={league} />
          ) : null}
          <p className={styles.note}>
            {activity.windowApplied === "season"
              ? `Whole ${activity.season} season`
              : `Last ${activity.window.replace("d", " days")}`}{" "}
            · completed transactions and draft picks only · read from Sleeper at
            lookup time{activity.cached ? " (cached for up to 10 minutes)" : ""}
            .
          </p>
        </>
      ) : null}
    </div>
  );
}
