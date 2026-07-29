"use client";

/**
 * /bdvm — Fundamentals: the BDVM projection-driven value board beside
 * the market, per-roster strategy capitals, and the double-positive
 * trade scan. Reads GET /api/bdvm/values|roster|trades (feature flag
 * `bdvm_engine`, default OFF — the page renders an explicit
 * flag-off state, Pattern B, never a generic error).
 *
 * Every number rendered here is backend-computed. Client code only
 * filters, sorts by backend-stamped columns, and formats.
 */

import { useMemo, useState } from "react";
import {
  Badge,
  Banner,
  Confidence,
  DataTable,
  EmptyState,
  InfoTip,
  Input,
  PageHeader,
  Panel,
  SegmentedControl,
  Select,
  SkeletonTable,
  StatTile,
  Tabs,
  tabId,
  tabPanelId,
} from "@/components/ds";
import { useBdvmEndpoint } from "@/components/useBdvm";
import {
  BDVM_STRATEGIES,
  BDVM_SURPLUS_MODES,
  bdvmDirectionTone,
  bdvmGroupOptions,
  bdvmSignalTone,
  buildBdvmPickRows,
  buildBdvmRosterRows,
  buildBdvmTradeRows,
  buildBdvmValueRows,
  formatBdvmDecimal,
  formatBdvmGap,
  formatBdvmValue,
} from "@/lib/bdvm";
import styles from "./bdvm.module.css";

const TABS = [
  { id: "values", label: "Value Board" },
  { id: "rosters", label: "Rosters" },
  { id: "trades", label: "Trade Scan" },
];

const SIGNAL_LABELS = {
  STRONG_BUY: "Strong buy",
  BUY: "Buy",
  HOLD: "Hold",
  SELL: "Sell",
  STRONG_SELL: "Strong sell",
  NO_MARKET: "No market",
};

/** Page-scale special states shared by all three endpoints. */
function BdvmFailure({ failure }) {
  if (!failure) return null;
  if (failure.kind === "disabled") {
    return (
      <EmptyState
        title="Fundamental values are switched off"
        description={
          "This engine is turned off for the site right now. Nothing else " +
          "changes while it is off — every other page prices players exactly " +
          "as before."
        }
      />
    );
  }
  if (failure.kind === "not_ready") {
    return (
      <Banner tone="warning" title="Data not ready for this league">
        {failure.message ||
          "The backend has no contract loaded for the selected league yet."}
      </Banner>
    );
  }
  if (failure.kind === "auth") {
    return (
      <Banner tone="warning" title="Sign in required">
        {failure.message}
      </Banner>
    );
  }
  return (
    <Banner tone="negative" title="Fundamentals unavailable">
      {failure.message}
    </Banner>
  );
}

function ValuesTab({ active, surplusMode, setSurplusMode }) {
  const params = useMemo(
    () => (surplusMode === "option" ? {} : { surplusMode }),
    [surplusMode],
  );
  // Kept mounted across tab switches (like the sibling tabs) so
  // strategy/filter state and the fetched payload survive; the hook
  // itself skips refetching on re-activation.
  const { loading, data, failure } = useBdvmEndpoint("/api/bdvm/values", {
    params,
    enabled: active,
  });
  const [strategy, setStrategy] = useState("balanced");
  const [group, setGroup] = useState("");
  const [query, setQuery] = useState("");

  const allRows = useMemo(
    () => (data?.status === "ok" ? buildBdvmValueRows(data, strategy) : []),
    [data, strategy],
  );
  const groups = useMemo(() => bdvmGroupOptions(allRows), [allRows]);
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    return allRows.filter(
      (r) =>
        (!group || r.group === group) &&
        (!q || r.name.toLowerCase().includes(q)),
    );
  }, [allRows, group, query]);
  const pickRows = useMemo(
    () => (data?.status === "ok" ? buildBdvmPickRows(data, strategy) : []),
    [data, strategy],
  );

  if (!active) return null;
  if (loading) {
    return (
      <Panel
        flush
        title={
          <>
            Fundamental value board
            <InfoTip label="fundamental values">
              <p>
                Fundamentals are computed with zero market inputs; the market
                column is compared strictly afterward.
              </p>
              <p>
                Values marked <strong>proxy</strong> come from the reconstructed
                baseline — realized production scored under this league&apos;s
                settings — not a forward projection source.
              </p>
            </InfoTip>
          </>
        }
      >
        <SkeletonTable rows={12} columns={8} />
      </Panel>
    );
  }
  if (failure) return <BdvmFailure failure={failure} />;
  if (data?.status === "no_projection_snapshot") {
    return (
      <EmptyState
        title="No projection snapshot yet"
        description={
          "Fundamental values are priced from a weekly projection snapshot, " +
          "and this season's hasn't been built yet. It refreshes " +
          "automatically — check back after the next run."
        }
      />
    );
  }

  const meta = data?.meta || {};
  const counts = meta.counts || {};
  const snapshot = meta.projectionSnapshot || {};

  const columns = [
    { key: "rank", header: "#", numeric: true, width: "3rem" },
    {
      key: "name",
      header: "Player",
      sortable: true,
      render: (r) => (
        <span className={styles.playerCell}>
          <span className={styles.playerName}>{r.name}</span>
          <Badge tone="outline">{r.position}</Badge>
          {r.anyProxy ? (
            <Badge
              tone="neutral"
              title="Priced from the reconstructed-baseline proxy, not a real projection source"
            >
              proxy
            </Badge>
          ) : null}
        </span>
      ),
    },
    {
      key: "age",
      header: "Age",
      numeric: true,
      sortable: true,
      hideBelow: "md",
      render: (r) => formatBdvmDecimal(r.age),
    },
    {
      key: "fpg",
      header: "FPG",
      headerInfo: "Projected fantasy points per game under this league's scoring",
      numeric: true,
      sortable: true,
      hideBelow: "sm",
      render: (r) => formatBdvmDecimal(r.fpg),
    },
    {
      key: "tradeValue",
      header: "Fundamental",
      headerInfo: "BDVM trade value in the selected strategy currency (0–10000)",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.tradeValue),
    },
    {
      key: "marketValue",
      header: "Market",
      headerInfo: "Market anchor (KTC / IDP TradeCalc)",
      numeric: true,
      sortable: true,
      hideBelow: "sm",
      render: (r) => formatBdvmValue(r.marketValue),
    },
    {
      key: "gap",
      header: "Gap",
      headerInfo: "Fundamental (balanced) minus market — positive means the market underprices",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmGap(r.gap),
    },
    {
      key: "signal",
      header: "Signal",
      sortable: true,
      render: (r) =>
        r.signal ? (
          <Badge tone={bdvmSignalTone(r.signal)} title={r.signalReason}>
            {SIGNAL_LABELS[r.signal] || r.signal}
          </Badge>
        ) : (
          "—"
        ),
    },
    {
      key: "score",
      header: "Score",
      headerInfo: "Percentile of balanced fundamental value among priced players (0–100)",
      numeric: true,
      sortable: true,
      hideBelow: "lg",
      render: (r) => formatBdvmDecimal(r.score, 0),
    },
    {
      key: "confidenceScore",
      header: "Conf",
      headerInfo: "Model confidence (provisional by policy in v1)",
      numeric: true,
      hideBelow: "lg",
      render: (r) => (
        <Confidence confidence={r.confidenceScore} showWhen="always" />
      ),
    },
  ];

  const pickColumns = [
    { key: "name", header: "Pick", sortable: true },
    {
      key: "ev",
      header: "EV",
      headerInfo: "Expected value of the pick's outcome distribution (selected strategy)",
      numeric: true,
      sortable: true,
      render: (r) =>
        r.unpriced ? (
          <span className={styles.cellNote}>{r.reason || "unpriced"}</span>
        ) : (
          formatBdvmValue(r.ev)
        ),
    },
    {
      key: "pHit",
      header: "P(hit)",
      numeric: true,
      hideBelow: "sm",
      render: (r) => (r.pHit == null ? "—" : `${Math.round(r.pHit * 100)}%`),
    },
    {
      key: "median",
      header: "Median",
      numeric: true,
      hideBelow: "md",
      render: (r) => formatBdvmValue(r.median),
    },
    {
      key: "marketValue",
      header: "Market",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.marketValue),
    },
  ];

  return (
    <>
      <div className={styles.statGrid}>
        <StatTile label="Players priced" value={String(counts.priced ?? "—")} />
        <StatTile
          label="Unpriced (honest)"
          value={String(counts.unpriced ?? "—")}
          meta="no projection / age"
        />
        <StatTile
          label="Snapshot"
          value={snapshot.asOf || "—"}
          meta={
            snapshot.recordCount ? `${snapshot.recordCount} records` : undefined
          }
        />
        <StatTile
          label="Model"
          value={meta.modelVersion || "—"}
          meta={meta.paramSetId}
        />
      </div>

      <Panel
        flush
        title={
          <>
            Fundamental value board
            <InfoTip label="fundamental values">
              <p>
                Fundamentals are computed with zero market inputs; the market
                column is compared strictly afterward.
              </p>
              <p>
                Values marked <strong>proxy</strong> come from the reconstructed
                baseline — realized production scored under this league&apos;s
                settings — not a forward projection source.
              </p>
            </InfoTip>
          </>
        }
      >
        <div className={styles.controls}>
          <SegmentedControl
            label="Strategy currency"
            options={BDVM_STRATEGIES}
            value={strategy}
            onChange={setStrategy}
          />
          <Select
            aria-label="Position group"
            className={styles.controlsSelect}
            value={group}
            onChange={(e) => setGroup(e.target.value)}
            options={[
              { value: "", label: "All positions" },
              ...groups.map((g) => ({ value: g, label: g })),
            ]}
          />
          <Select
            aria-label="Surplus model"
            className={styles.controlsSelect}
            value={surplusMode}
            onChange={(e) => setSurplusMode(e.target.value)}
            options={BDVM_SURPLUS_MODES}
          />
          <Input
            aria-label="Search players"
            className={styles.controlsSearch}
            placeholder="Search players…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <p className={styles.resultCount}>
            {rows.length} of {allRows.length}
          </p>
        </div>
        <DataTable
          caption="BDVM fundamental values vs market, per player"
          columns={columns}
          rows={rows}
          rowKey={(r) => r.playerId || r.name}
          density="compact"
          defaultSort={{ key: "tradeValue", direction: "desc" }}
          emptyState={
            <EmptyState
              title="No players match"
              description="Adjust the position filter or search."
            />
          }
        />
      </Panel>

      {pickRows.length > 0 ? (
        <Panel
          flush
          title="Rookie picks"
          subtitle="Priced as outcome distributions, not point values"
        >
          <DataTable
            caption="BDVM pick values by outcome distribution"
            columns={pickColumns}
            rows={pickRows}
            rowKey={(r) => r.name}
            density="compact"
            emptyState={<EmptyState title="No picks in the contract" />}
          />
        </Panel>
      ) : null}
    </>
  );
}

function RostersTab({ active }) {
  const { loading, data, failure } = useBdvmEndpoint("/api/bdvm/roster", {
    enabled: active,
  });
  const [expandedKey, setExpandedKey] = useState("");

  const rows = useMemo(
    () => (data?.status === "ok" ? buildBdvmRosterRows(data) : []),
    [data],
  );

  if (!active) return null;
  if (loading) {
    return (
      <Panel
      flush
      title={
        <>
          Roster strategy capitals
          <InfoTip label="strategy capitals">
            <p>
              Direction is league-relative — this roster&apos;s now/future ratio
              against the league median.
            </p>
            <p>
              Capitals sum each roster&apos;s player values in that
              strategy&apos;s own currency; picks are listed but not summed.
            </p>
          </InfoTip>
        </>
      }
    >
        <SkeletonTable rows={12} columns={7} />
      </Panel>
    );
  }
  if (failure) return <BdvmFailure failure={failure} />;
  if (data?.status && data.status !== "ok") {
    return (
      <EmptyState
        title="Roster analysis unavailable"
        description={data.message || `Status: ${data.status}`}
      />
    );
  }

  const columns = [
    { key: "name", header: "Team", sortable: true },
    {
      key: "direction",
      header: "Direction",
      sortable: true,
      render: (r) =>
        r.direction ? (
          <Badge tone={bdvmDirectionTone(r.direction)}>{r.direction}</Badge>
        ) : (
          "—"
        ),
    },
    {
      key: "contender",
      header: "Contender",
      headerInfo: "Roster capital in the contender currency",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.contender),
    },
    {
      key: "balanced",
      header: "Balanced",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.balanced),
    },
    {
      key: "rebuilder",
      header: "Rebuilder",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.rebuilder),
    },
    {
      key: "nowFutureRatio",
      header: "Now / Future",
      numeric: true,
      sortable: true,
      hideBelow: "md",
      render: (r) => formatBdvmDecimal(r.nowFutureRatio, 2),
    },
    {
      key: "valueWeightedAge",
      header: "V-Age",
      headerInfo: "Balanced-value-weighted roster age",
      numeric: true,
      sortable: true,
      hideBelow: "md",
      render: (r) => formatBdvmDecimal(r.valueWeightedAge),
    },
    {
      key: "starterFpg",
      header: "Starter FPG",
      numeric: true,
      sortable: true,
      hideBelow: "lg",
      render: (r) => formatBdvmDecimal(r.starterFpg),
    },
  ];

  return (
    <Panel
      flush
      title={
        <>
          Roster strategy capitals
          <InfoTip label="strategy capitals">
            <p>
              Direction is league-relative — this roster&apos;s now/future ratio
              against the league median.
            </p>
            <p>
              Capitals sum each roster&apos;s player values in that
              strategy&apos;s own currency; picks are listed but not summed.
            </p>
          </InfoTip>
        </>
      }
    >
      <DataTable
        caption="Per-roster BDVM capitals, direction, and shape"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        density="compact"
        defaultSort={{ key: "balanced", direction: "desc" }}
        onRowClick={(r) =>
          setExpandedKey((k) => (k === r.key ? "" : r.key))
        }
        renderAfterRow={(r) =>
          r.key === expandedKey ? (
            <tr>
              <td colSpan={columns.length} className={styles.drawerCell}>
                <p className={styles.drawerTitle}>
                  Top assets ({r.assetCount} matched, {r.pickCount} picks)
                </p>
                <ul className={styles.drawerList}>
                  {r.assets.slice(0, 12).map((a) => (
                    <li key={a.playerId || a.name}>
                      {a.name}{" "}
                      <span className={styles.drawerAssetValue}>
                        {formatBdvmValue(a?.tradeValue?.balanced)}
                      </span>
                    </li>
                  ))}
                </ul>
              </td>
            </tr>
          ) : null
        }
        emptyState={
          <EmptyState
            title="No rosters"
            description="The contract has no Sleeper teams for this league."
          />
        }
      />
    </Panel>
  );
}

function TradesTab({ active }) {
  const { loading, data, failure } = useBdvmEndpoint("/api/bdvm/trades", {
    enabled: active,
  });
  const [team, setTeam] = useState("");

  const allRows = useMemo(
    () => (data?.status === "ok" ? buildBdvmTradeRows(data) : []),
    [data],
  );
  const teams = useMemo(() => {
    const names = new Set();
    for (const r of allRows) {
      if (r.aName) names.add(r.aName);
      if (r.bName) names.add(r.bName);
    }
    return [...names].sort();
  }, [allRows]);
  const rows = useMemo(
    () =>
      team
        ? allRows.filter((r) => r.aName === team || r.bName === team)
        : allRows,
    [allRows, team],
  );

  if (!active) return null;
  if (loading) {
    return (
      <Panel
      flush
      title={
        <>
          Double-positive trade scan
          <InfoTip label="the double-positive scan">
            <p>
              Each side&apos;s gain is priced in its own strategy currency, so a
              trade only shows up here if BOTH sides come out ahead by their own
              measure.
            </p>
            <p>
              Market fairness never sums KTC and IDP TradeCalc raw values on one
              side — mixed-market packages fall back to the model&apos;s
              trade-clearing basis.
            </p>
          </InfoTip>
        </>
      }
    >
        <SkeletonTable rows={8} columns={5} />
      </Panel>
    );
  }
  if (failure) return <BdvmFailure failure={failure} />;
  if (data?.status && data.status !== "ok") {
    return (
      <EmptyState
        title="Trade scan unavailable"
        description={data.message || `Status: ${data.status}`}
      />
    );
  }

  const columns = [
    {
      key: "aName",
      header: "Side A sends",
      sortable: true,
      render: (r) => (
        <span className={styles.packageSide}>
          <span className={styles.packageTeam}>
            {r.aName} <Badge tone="outline">{r.aStrategy}</Badge>
          </span>
          <span className={styles.packageAssets}>{r.aGives.join(" + ")}</span>
        </span>
      ),
    },
    {
      key: "aGain",
      header: "A gains",
      headerInfo: "Side A's gain in its OWN strategy currency",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.aGain),
    },
    {
      key: "bName",
      header: "Side B sends",
      sortable: true,
      render: (r) => (
        <span className={styles.packageSide}>
          <span className={styles.packageTeam}>
            {r.bName} <Badge tone="outline">{r.bStrategy}</Badge>
          </span>
          <span className={styles.packageAssets}>{r.bGives.join(" + ")}</span>
        </span>
      ),
    },
    {
      key: "bGain",
      header: "B gains",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.bGain),
    },
    {
      key: "minGain",
      header: "Min gain",
      headerInfo: "The smaller side's gain — how double-positive the package is",
      numeric: true,
      sortable: true,
      render: (r) => formatBdvmValue(r.minGain),
    },
    {
      key: "fairnessPct",
      header: "Fairness",
      headerInfo: "Market-value imbalance of the package (single-market when both sides share one market)",
      numeric: true,
      sortable: true,
      hideBelow: "md",
      render: (r) =>
        r.fairnessPct == null ? "—" : `${formatBdvmDecimal(r.fairnessPct)}%`,
    },
  ];

  return (
    <Panel
      flush
      title={
        <>
          Double-positive trade scan
          <InfoTip label="the double-positive scan">
            <p>
              Each side&apos;s gain is priced in its own strategy currency, so a
              trade only shows up here if BOTH sides come out ahead by their own
              measure.
            </p>
            <p>
              Market fairness never sums KTC and IDP TradeCalc raw values on one
              side — mixed-market packages fall back to the model&apos;s
              trade-clearing basis.
            </p>
          </InfoTip>
        </>
      }
    >
      <div className={styles.controls}>
        <Select
          aria-label="Filter by team"
          className={styles.controlsSelect}
          value={team}
          onChange={(e) => setTeam(e.target.value)}
          options={[
            { value: "", label: "All teams" },
            ...teams.map((t) => ({ value: t, label: t })),
          ]}
        />
        <p className={styles.resultCount}>
          {rows.length} of {allRows.length} packages
          {typeof data?.scanned === "number"
            ? ` · ${data.scanned.toLocaleString()} scanned`
            : ""}
        </p>
      </div>
      <DataTable
        caption="Trades where each side gains in its own strategy currency"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.key}
        density="compact"
        defaultSort={{ key: "minGain", direction: "desc" }}
        emptyState={
          <EmptyState
            title="No double-positive packages found"
            description="With current rosters and values, no scanned package clears both sides' gain thresholds and the market-fairness gate."
          />
        }
      />
    </Panel>
  );
}

export default function BdvmPage() {
  const [tab, setTab] = useState("values");
  const [surplusMode, setSurplusMode] = useState("option");

  return (
    <section className={styles.page}>
      <PageHeader
        eyebrow="Rankings"
        title="Fundamental Values"
        description="BDVM projection-driven dynasty values — fundamentals first, market strictly after. A second value concept beside the market board, never merged into it."
      />
      <Tabs
        idPrefix="bdvm"
        label="Fundamental Values sections"
        tabs={TABS}
        active={tab}
        onChange={setTab}
      />
      <div
        role="tabpanel"
        id={tabPanelId("bdvm", tab)}
        aria-labelledby={tabId("bdvm", tab)}
        className={styles.page}
      >
        <ValuesTab
          active={tab === "values"}
          surplusMode={surplusMode}
          setSurplusMode={setSurplusMode}
        />
        <RostersTab active={tab === "rosters"} />
        <TradesTab active={tab === "trades"} />
      </div>
    </section>
  );
}
