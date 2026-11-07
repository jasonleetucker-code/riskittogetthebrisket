"use client";

// ── Weekly IDP Streaming — the streaming mode of /waiver-advisor ─────────
//
// Owner directive 2026-10-29 (docs/owner/IDP_STREAMING_DIRECTIVE_2026-10-29.md,
// Workstream G).  DISPLAY ONLY: every number comes from
// POST /api/waiver/streaming (src/waivers/streaming.py), which composes the
// league-scored weekly projections, the dynasty drop assessment, the exact
// lineup solver, the FAAB engine and roster capacity.  This file formats that
// payload; it projects, values, bids, optimizes and decides nothing (the
// no-frontend-engine rule).  Missing renders as its stated reason, never 0.
//
// Loaded with React.lazy from app/waiver-advisor/page.jsx so it costs that
// page's chunk nothing while the flag is off or the mode is unused.
//
// Advice only.  Nothing here submits, schedules or drafts a waiver claim.

import { useEffect, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  CollapsiblePanel,
  DataTable,
  EmptyState,
  FailureState,
  Field,
  Input,
  Meter,
  Panel,
  PlayerNameButton,
  SegmentedControl,
  Select,
  SkeletonTable,
  StatTile,
} from "@/components/ds";
import { useIdpStreaming } from "@/components/waivers/useIdpStreaming";
import {
  STREAMING_POSITION_OPTIONS,
  STREAMING_WEEK_OPTIONS,
  bidBasisText,
  bidText,
  budgetBindsText,
  capacityOptions,
  coverageText,
  curveRowStatus,
  dropClassBadge,
  dynastyChangeText,
  dynastyValueText,
  faabText,
  fmtDollars,
  fmtPoints,
  fmtSignedPoints,
  fmtValue,
  horizonOptions,
  moveSummary,
  noMoveReasonText,
  playerNameIndex,
  postureContextText,
  reasonText,
  recommendedCapacityText,
  releaseCostBasisText,
  solverStatusText,
  streamingLimits,
  weekCellText,
  weekRuleText,
  weightedProjectionText,
} from "@/lib/idp-streaming";
import styles from "@/app/waivers/waivers.module.css";

function Missing({ children }) {
  return <span className={styles.playerMeta}>{children}</span>;
}

function PlayerCell({ row }) {
  return (
    <span className={styles.playerCell}>
      <Badge tone="outline">{row.position || "?"}</Badge>
      <PlayerNameButton
        name={row.name}
        playerId={row.playerId}
        className={styles.playerName}
      />
      {row.team ? <span className={styles.playerMeta}>{row.team}</span> : null}
    </span>
  );
}

// ── controls ───────────────────────────────────────────────────────────

function Controls({ params, setParams, config, appliedCapacity }) {
  // Bounds come from the backend's own config once a payload is in hand.
  const limits = streamingLimits(config);
  // Capacity is not sent until the user picks one: the backend default
  // applies, and the control reflects the capacity the backend actually used.
  const shownCapacity =
    params.capacity ?? appliedCapacity ?? config?.defaultCapacity ?? null;
  const [budgetDraft, setBudgetDraft] = useState(String(params.dynastyBudget));
  const commitBudget = () => {
    const raw = budgetDraft.trim() === "" ? "0" : budgetDraft.trim();
    if (raw !== String(params.dynastyBudget)) {
      setParams((p) => ({ ...p, dynastyBudget: raw }));
    }
  };
  return (
    <div className={styles.controls} data-testid="streaming-controls">
      <Field label="Week" id="streaming-week">
        <Select
          id="streaming-week"
          value={params.week}
          onChange={(e) => setParams((p) => ({ ...p, week: e.target.value }))}
        >
          {STREAMING_WEEK_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </Select>
      </Field>
      <SegmentedControl
        label="Horizon"
        value={params.horizonWeeks}
        onChange={(v) => setParams((p) => ({ ...p, horizonWeeks: v }))}
        options={horizonOptions(config)}
      />
      <SegmentedControl
        label="Position"
        value={params.position}
        onChange={(v) => setParams((p) => ({ ...p, position: v }))}
        options={STREAMING_POSITION_OPTIONS}
      />
      <Field
        label="Streaming capacity"
        id="streaming-capacity"
        hint="Most adds this plan may make"
      >
        <Select
          id="streaming-capacity"
          value={shownCapacity == null ? "" : String(shownCapacity)}
          onChange={(e) =>
            setParams((p) => ({ ...p, capacity: Number(e.target.value) }))
          }
        >
          {shownCapacity == null ? <option value="">Default</option> : null}
          {capacityOptions(config).map((k) => (
            <option key={k} value={String(k)}>
              {k}
            </option>
          ))}
        </Select>
      </Field>
      <Field
        label="Dynasty loss budget"
        id="streaming-budget"
        hint="Board value you accept losing (default 0)"
      >
        <Input
          id="streaming-budget"
          type="number"
          inputMode="numeric"
          min={0}
          max={limits.maxDynastyBudget}
          step={50}
          data-numeric
          value={budgetDraft}
          onChange={(e) => setBudgetDraft(e.target.value)}
          onBlur={commitBudget}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitBudget();
          }}
        />
      </Field>
    </div>
  );
}

// ── decision ───────────────────────────────────────────────────────────

function PlanFigures({ plan, weeks }) {
  const change = dynastyChangeText(plan.dynastyValueChange);
  return (
    <>
      <div className={styles.summaryGrid} data-testid="streaming-plan-figures">
        <StatTile
          label="Weekly lineup gain"
          value={`${fmtSignedPoints(plan.weeklyGainPoints) ?? "—"} pts`}
          meta={
            weeks.length > 1
              ? "weighted across the horizon"
              : "projected starting lineup"
          }
        />
        <StatTile
          label="Release cost"
          value={fmtValue(plan.releaseCost) ?? "—"}
          meta="dynasty value charged against your budget"
        />
        <StatTile
          label="Dynasty value change"
          value={change.text}
          meta={
            change.partial
              ? "total unknown — reported only"
              : "Σ adds − Σ drops, reported only"
          }
        />
        <StatTile
          label="FAAB"
          value={fmtDollars(plan.faabTotal) ?? "—"}
          meta="total of the claims"
        />
      </div>
      {weeks.length > 1 && Array.isArray(plan.gainByWeekPoints) ? (
        <p className={styles.note} data-testid="streaming-gain-by-week">
          Gain by week:{" "}
          {weeks
            .map(
              (w, i) =>
                `Week ${w} ${fmtSignedPoints(plan.gainByWeekPoints[i]) ?? "—"}`,
            )
            .join(" · ")}
        </p>
      ) : null}
    </>
  );
}

function MoveList({ plan }) {
  return (
    <div className={styles.contextGrid} data-testid="streaming-moves">
      <div className={styles.contextBlock}>
        <span className={styles.contextLabel}>Add</span>
        {(plan.addDetails || []).length ? (
          plan.addDetails.map((a) => (
            <span key={a.playerId} className={styles.contextValue}>
              <PlayerCell row={a} /> {bidText(a)} · {bidBasisText(a.bidBasis)} ·
              dynasty {dynastyValueText(a.dynastyValue, a.dynastyValueState)}
            </span>
          ))
        ) : (
          <span className={styles.contextValue}>No add</span>
        )}
      </div>
      <div className={styles.contextBlock}>
        <span className={styles.contextLabel}>Drop</span>
        {(plan.dropDetails || []).length ? (
          plan.dropDetails.map((d) => (
            <span key={d.playerId} className={styles.contextValue}>
              <PlayerCell row={d} />{" "}
              <Badge tone={dropClassBadge(d.dropClass).tone}>
                {dropClassBadge(d.dropClass).label}
              </Badge>{" "}
              release cost {fmtValue(d.releaseCost) ?? "unknown"}
              {releaseCostBasisText(d.releaseCostBasis)
                ? ` (${releaseCostBasisText(d.releaseCostBasis)})`
                : ""}
              {d.reasons?.[0]?.detail ? ` — ${d.reasons[0].detail}` : ""}
            </span>
          ))
        ) : (
          <span className={styles.contextValue}>
            No drop — an open roster spot is used
          </span>
        )}
      </div>
    </div>
  );
}

function Decision({ payload }) {
  const solver = solverStatusText(payload.solver);
  const weeks = payload.weeks || [];
  const rule = weekRuleText(payload.request?.weekRule);
  const weekLabel = `${
    weeks.length > 1
      ? `Weeks ${weeks[0]}–${weeks[weeks.length - 1]}`
      : `Week ${weeks[0] ?? "?"}`
  }${rule ? ` (${rule})` : ""}`;
  if (!payload.recommendMove || !payload.plan) {
    // Not recommended: the backend lists the best change it found as the
    // first alternative (plan is null).
    const bestFound = payload.plan || payload.alternatives?.[0] || null;
    return (
      <Panel
        title="No move — hold your roster"
        subtitle={`${weekLabel} · ${solver.label}`}
      >
        <div data-testid="streaming-no-move">
          <p className={styles.note}>
            {payload.noMoveReason === "dynasty_budget_binds"
              ? budgetBindsText(payload, playerNameIndex(payload))
              : noMoveReasonText(payload.noMoveReason)}
          </p>
          {bestFound && payload.noMoveReason === "below_materiality" ? (
            <p className={styles.note}>
              Best change found:{" "}
              {moveSummary(bestFound, playerNameIndex(payload))} (
              {fmtSignedPoints(bestFound.weeklyGainPoints) ?? "—"} pts) — below
              the {fmtPoints(payload.config?.materialityPoints) ?? "configured"}
              -point threshold.
            </p>
          ) : null}
        </div>
      </Panel>
    );
  }
  return (
    <Panel
      title="Recommended moves"
      subtitle={`${weekLabel} · ${solver.label}`}
      actions={
        <Badge tone={solver.tone}>{payload.solver?.status || "unknown"}</Badge>
      }
    >
      <div data-testid="streaming-recommendation">
        <PlanFigures plan={payload.plan} weeks={weeks} />
        <MoveList plan={payload.plan} />
        <p className={styles.note}>
          Advice only — nothing here submits a waiver claim.
        </p>
      </div>
    </Panel>
  );
}

function Alternatives({ payload, names }) {
  const rows = payload.alternatives || [];
  const columns = [
    { key: "moves", header: "Moves", accessor: (p) => moveSummary(p, names) },
    {
      key: "gain",
      header: "Lineup gain",
      numeric: true,
      accessor: (p) => p.weeklyGainPoints,
      render: (p) => fmtSignedPoints(p.weeklyGainPoints) ?? "—",
    },
    {
      key: "release",
      header: "Release cost",
      numeric: true,
      hideBelow: "sm",
      accessor: (p) => p.releaseCost,
      render: (p) => fmtValue(p.releaseCost) ?? "—",
    },
    {
      key: "dyn",
      header: "Dynasty change",
      hideBelow: "md",
      accessor: (p) => dynastyChangeText(p.dynastyValueChange).text,
    },
    {
      key: "faab",
      header: "FAAB",
      numeric: true,
      hideBelow: "sm",
      accessor: (p) => p.faabTotal,
      render: (p) => fmtDollars(p.faabTotal) ?? "—",
    },
  ];
  return (
    <Panel
      flush
      title="Alternatives"
      subtitle="Other legal combinations, best first"
    >
      <DataTable
        caption="Alternative add/drop combinations"
        columns={columns}
        rows={rows}
        rowKey={(p, i) =>
          `${(p.adds || []).join(",")}|${(p.drops || []).join(",")}|${i}`
        }
        density="compact"
        presorted
        emptyState={
          <EmptyState
            title="No alternatives"
            description="No other legal combination improves the lineup."
          />
        }
      />
    </Panel>
  );
}

function LargerBudget({ payload, names }) {
  const lb = payload.largerBudget || {};
  const plan = lb.plan;
  const budget = Number(payload.request?.dynastyBudget ?? 0);
  return (
    <Panel
      title="What a larger dynasty budget would buy"
      subtitle={`The best plan at this capacity with your ${fmtValue(budget) ?? "0"}-point budget lifted${
        lb.status === "bounded" ? " · bounded search" : ""
      }`}
    >
      <div data-testid="streaming-larger-budget">
        {plan ? (
          <p className={styles.note}>
            {moveSummary(plan, names)} —{" "}
            {fmtSignedPoints(plan.weeklyGainPoints) ?? "—"} pts for a release
            cost of {fmtValue(plan.releaseCost) ?? "—"} (dynasty change{" "}
            {dynastyChangeText(plan.dynastyValueChange).text}).
          </p>
        ) : (
          <p className={styles.note}>
            Nothing more — lifting the budget unlocks no better plan.
          </p>
        )}
      </div>
    </Panel>
  );
}

function CapacityCurve({ payload, names }) {
  const rows = payload.capacityCurve;
  if (!Array.isArray(rows) || !rows.length) return null;
  const rec = payload.recommendedCapacity;
  const selected = payload.request?.capacity;
  // Bar length is presentation scaling over the backend's own numbers.
  const top = Math.max(...rows.map((r) => Number(r.bestGainPoints) || 0), 0);
  const columns = [
    {
      key: "capacity",
      header: "Spots",
      numeric: true,
      accessor: (r) => r.capacity,
      render: (r) => (
        <span>
          {r.capacity}
          {r.capacity === rec ? (
            <>
              {" "}
              <Badge tone="accent">Recommended</Badge>
            </>
          ) : null}
          {r.capacity === selected ? (
            <>
              {" "}
              <Badge tone="outline">Selected</Badge>
            </>
          ) : null}
        </span>
      ),
    },
    {
      key: "gain",
      header: "Best lineup gain",
      accessor: (r) => r.bestGainPoints,
      render: (r) => (
        <Meter
          value={Number(r.bestGainPoints) || 0}
          max={top || 1}
          label={`Best lineup gain with ${r.capacity} streaming spot${r.capacity === 1 ? "" : "s"}`}
          format={(v) => `${fmtPoints(v)} pts`}
        />
      ),
    },
    {
      key: "marginal",
      header: "Marginal",
      numeric: true,
      hideBelow: "sm",
      accessor: (r) => r.marginalGainPoints,
      render: (r) => fmtSignedPoints(r.marginalGainPoints) ?? "—",
    },
    {
      key: "loss",
      header: "Release cost",
      numeric: true,
      hideBelow: "md",
      accessor: (r) => r.netDynastyLoss,
      render: (r) => fmtValue(r.netDynastyLoss) ?? "—",
    },
    {
      key: "status",
      header: "Search",
      headerInfo:
        "Proven: the search finished. Bounded: the search hit its limit, so this row is the best found, not proven best.",
      accessor: (r) => curveRowStatus(r).label,
      render: (r) => {
        const st = curveRowStatus(r);
        return <Badge tone={st.tone}>{st.label}</Badge>;
      },
    },
    {
      key: "moves",
      header: "Moves",
      hideBelow: "lg",
      accessor: (r) => moveSummary(r, names),
    },
  ];
  return (
    <Panel
      flush
      title="Streaming capacity"
      subtitle={recommendedCapacityText(payload)}
    >
      <div data-testid="streaming-capacity-curve">
        <DataTable
          caption="Best lineup gain by streaming capacity"
          columns={columns}
          rows={rows}
          rowKey={(r) => String(r.capacity)}
          density="compact"
          presorted
        />
      </div>
    </Panel>
  );
}

// ── boards ─────────────────────────────────────────────────────────────

function WeekDetail({ weeks }) {
  return (
    <div className={styles.contextGrid}>
      {(weeks || []).map((w) => (
        <div key={w.week} className={styles.contextBlock}>
          <span className={styles.contextLabel}>Week {w.week}</span>
          <span className={styles.contextValue}>
            {weekCellText(w)}
            {w.opponent ? ` vs ${w.opponent}` : ""}
            {w.injuryStatus ? ` · ${w.injuryStatus}` : ""}
          </span>
          <span className={styles.contextValue}>{coverageText(w)}</span>
          {w.combineMethod ? (
            <span className={styles.contextValue}>
              {reasonText(w.combineMethod)}
              {w.familyCount != null
                ? ` · ${w.familyCount} source famil${w.familyCount === 1 ? "y" : "ies"}`
                : ""}
            </span>
          ) : null}
        </div>
      ))}
    </div>
  );
}

function streamingBoardColumns(weekNumbers) {
  return [
    {
      key: "name",
      header: "Player",
      accessor: (r) => r.name,
      render: (r) => <PlayerCell row={r} />,
    },
    {
      key: "gain",
      header: "Lineup gain",
      headerInfo:
        "Points this player adds to your projected starting lineup on his own, with no drop. The board's order.",
      numeric: true,
      accessor: (r) => r.soloLineupGainPoints,
      render: (r) => fmtSignedPoints(r.soloLineupGainPoints) ?? "—",
    },
    {
      key: "proj",
      header: "Proj.",
      headerInfo:
        "Projected points across the horizon, weighted by week. The board's tiebreak after lineup gain.",
      numeric: true,
      hideBelow: "md",
      accessor: (r) => r.weightedProjectedPoints,
      render: (r) => {
        const w = weightedProjectionText(r);
        return w.complete ? (
          w.text
        ) : (
          <span>
            {w.text} <Missing>({w.known})</Missing>
          </span>
        );
      },
    },
    ...weekNumbers.map((wk, i) => ({
      key: `wk${wk}`,
      header: `Wk ${wk}`,
      numeric: true,
      hideBelow: i === 0 ? undefined : "md",
      accessor: (r) => r.weeks?.[i]?.points ?? null,
      render: (r) => weekCellText(r.weeks?.[i]),
    })),
    {
      key: "opp",
      header: "Opp",
      hideBelow: "md",
      accessor: (r) => r.weeks?.[0]?.opponent || "",
      render: (r) => r.weeks?.[0]?.opponent || <Missing>—</Missing>,
    },
    {
      key: "sources",
      header: "Sources",
      hideBelow: "lg",
      accessor: (r) => coverageText(r.weeks?.[0]),
    },
    {
      key: "dyn",
      header: "Dynasty",
      numeric: true,
      hideBelow: "sm",
      accessor: (r) => r.dynastyValue,
      render: (r) => fmtValue(r.dynastyValue) ?? <Missing>Unknown</Missing>,
    },
    {
      key: "bid",
      header: "Bid",
      numeric: true,
      headerInfo:
        "The FAAB engine's bid, or a $0 claim when the engine does not price him (the reason is in the row detail).",
      accessor: (r) => r.bid,
      render: (r) => <span title={bidBasisText(r.bidBasis)}>{bidText(r)}</span>,
    },
    {
      key: "state",
      header: "State",
      hideBelow: "lg",
      accessor: (r) =>
        r.excluded ? reasonText(r.excluded) : r.weeks?.[0]?.state || "",
      render: (r) =>
        r.excluded ? (
          <Badge tone="warning">{reasonText(r.excluded)}</Badge>
        ) : (
          reasonText(r.weeks?.[0]?.state)
        ),
    },
  ];
}

function StreamingBoard({ payload }) {
  const [expanded, setExpanded] = useState("");
  const rows = payload.streamingBoard || [];
  const columns = useMemo(
    () => streamingBoardColumns(payload.weeks || []),
    [payload.weeks],
  );
  return (
    <Panel
      flush
      title="Weekly IDP streaming board"
      subtitle="Available defenders ranked by what each adds to your lineup — not by dynasty value"
    >
      <div data-testid="streaming-board">
        <DataTable
          caption="Available IDP players ranked by projected weekly lineup gain"
          columns={columns}
          rows={rows}
          rowKey={(r) => r.playerId}
          density="compact"
          presorted
          onRowClick={(r) =>
            setExpanded((k) => (k === r.playerId ? "" : r.playerId))
          }
          isRowExpanded={(r) => r.playerId === expanded}
          rowExpandLabel={(r) => `Weekly projection detail for ${r.name}`}
          renderAfterRow={(r) =>
            r.playerId === expanded ? (
              <tr>
                <td colSpan={columns.length}>
                  <p className={styles.note}>
                    Bid: {bidText(r)} — {bidBasisText(r.bidBasis)} · dynasty{" "}
                    {dynastyValueText(r.dynastyValue, r.dynastyValueState)}
                  </p>
                  <WeekDetail weeks={r.weeks} />
                </td>
              </tr>
            ) : null
          }
          emptyState={
            <EmptyState
              title="No projected defenders available"
              description="No available player at this filter has a weekly projection."
            />
          }
        />
      </div>
    </Panel>
  );
}

const DROP_COLUMNS = [
  {
    key: "name",
    header: "Player",
    accessor: (r) => r.name,
    render: (r) => <PlayerCell row={r} />,
  },
  {
    key: "class",
    header: "Status",
    accessor: (r) => r.dropClass,
    render: (r) => {
      const b = dropClassBadge(r.dropClass);
      return <Badge tone={b.tone}>{b.label}</Badge>;
    },
  },
  {
    key: "dyn",
    header: "Dynasty",
    numeric: true,
    hideBelow: "sm",
    accessor: (r) => r.dynastyValue,
    render: (r) => fmtValue(r.dynastyValue) ?? <Missing>Unpriced</Missing>,
  },
  {
    key: "release",
    header: "Release cost",
    headerInfo:
      "Dynasty board value lost by releasing him, against the free agents who would replace him.",
    numeric: true,
    accessor: (r) => r.releaseCost,
    render: (r) =>
      fmtValue(r.releaseCost) ?? (
        <Missing>
          {r.dropClass === "protected" ? "Not droppable" : "Unknown"}
        </Missing>
      ),
  },
  {
    key: "wk",
    header: "This week",
    numeric: true,
    hideBelow: "md",
    accessor: (r) => r.weeks?.[0]?.points ?? null,
    render: (r) => weekCellText(r.weeks?.[0]),
  },
  {
    key: "why",
    header: "Why",
    hideBelow: "lg",
    accessor: (r) => r.reasons?.[0]?.detail || reasonText(r.reasons?.[0]?.code),
  },
];

function SafeToDrop({ payload }) {
  const [expanded, setExpanded] = useState("");
  const rows = payload.safeToDrop?.players || [];
  const counts = payload.safeToDrop?.summary?.counts || null;
  return (
    <Panel
      flush
      title="Safe-to-drop board"
      subtitle={
        counts
          ? `${counts.churn ?? "—"} churn · ${counts.conditional ?? "—"} conditional · ${counts.protected ?? "—"} protected`
          : "Rostered defenders by expendability and developmental protection"
      }
    >
      <div data-testid="streaming-safe-to-drop">
        <DataTable
          caption="Rostered IDP players classified by drop safety"
          columns={DROP_COLUMNS}
          rows={rows}
          rowKey={(r) => r.playerId}
          density="compact"
          presorted
          onRowClick={(r) =>
            setExpanded((k) => (k === r.playerId ? "" : r.playerId))
          }
          isRowExpanded={(r) => r.playerId === expanded}
          rowExpandLabel={(r) =>
            `Why ${r.name} is ${dropClassBadge(r.dropClass).label.toLowerCase()}`
          }
          renderAfterRow={(r) =>
            r.playerId === expanded ? (
              <tr>
                <td colSpan={DROP_COLUMNS.length}>
                  <div className={styles.contextGrid}>
                    <div className={styles.contextBlock}>
                      <span className={styles.contextLabel}>
                        {r.dropClass === "protected"
                          ? "Why he is protected"
                          : "Why"}
                      </span>
                      {(r.reasons || []).map((reason) => (
                        <span key={reason.code} className={styles.contextValue}>
                          {reason.detail || reasonText(reason.code)}
                        </span>
                      ))}
                      {(r.developmentFlags || []).length ? (
                        <span className={styles.contextValue}>
                          Development:{" "}
                          {r.developmentFlags.map(reasonText).join(", ")}
                        </span>
                      ) : null}
                      {releaseCostBasisText(r.releaseCostBasis) ? (
                        <span className={styles.contextValue}>
                          Release cost basis:{" "}
                          {releaseCostBasisText(r.releaseCostBasis)}
                        </span>
                      ) : null}
                      {(r.locks || []).length ? (
                        <span className={styles.contextValue}>
                          Your protections lock him ({r.locks.length})
                        </span>
                      ) : null}
                    </div>
                    <WeekDetail weeks={r.weeks} />
                  </div>
                </td>
              </tr>
            ) : null
          }
          emptyState={
            <EmptyState
              title="No rostered defenders at this filter"
              description="Nothing on your roster matches this position filter."
            />
          }
        />
      </div>
    </Panel>
  );
}

function HowComputed({ payload }) {
  const sources = payload.sources || [];
  const excluded = Object.keys(payload.excludedFreeAgents || {}).length;
  return (
    <CollapsiblePanel title="How this is computed" defaultCollapsed>
      <ul className={styles.notes} data-testid="streaming-methodology">
        <li className={styles.note}>
          Solver: {solverStatusText(payload.solver).label}
          {payload.solver?.nodes != null
            ? ` · ${payload.solver.nodes} nodes searched`
            : ""}
          {payload.solver?.requestWorkBudget != null
            ? ` · work ${payload.solver.workUsed ?? "?"} of ${payload.solver.requestWorkBudget}`
            : ""}
        </li>
        {(payload.solver?.unsearchedCapacities || []).length ? (
          <li className={styles.note}>
            Capacities {payload.solver.unsearchedCapacities.join(", ")} were not
            searched (the request's work budget ran out); their curve rows are
            lower bounds.
          </li>
        ) : null}
        <li className={styles.note}>
          Lineup slots: {(payload.lineup?.slots || []).length} from{" "}
          {reasonText(payload.lineup?.source)}
        </li>
        {sources.map((s) => (
          <li key={s.week} className={styles.note}>
            Week {s.week} projections: scoring{" "}
            {reasonText(s.scoringEvidenceState)}
            {(s.sourceStates || []).length
              ? ` · ${s.sourceStates.map((x) => `${x.sourceKey} ${reasonText(x.state)}`).join(", ")}`
              : " · no source states"}
          </li>
        ))}
        {excluded ? (
          <li className={styles.note}>
            {excluded} available player{excluded === 1 ? "" : "s"} excluded from
            the search (reason on each board row)
          </li>
        ) : null}
        {payload.config?.version ? (
          <li className={styles.note}>Config {payload.config.version}</li>
        ) : null}
        {(payload.notes || []).map((n) => (
          <li key={n} className={styles.note}>
            {n}
          </li>
        ))}
      </ul>
    </CollapsiblePanel>
  );
}

function Context({ payload }) {
  const faab = faabText(payload.faab);
  const posture = postureContextText(payload.posture);
  return (
    <div className={styles.summaryGrid} data-testid="streaming-context">
      <StatTile label="FAAB" value={faab.value} meta={faab.note} />
      <StatTile
        label="Open roster spots"
        value={
          payload.openSpots != null ? String(payload.openSpots) : "Unknown"
        }
        meta={
          payload.openSpots != null ? "before any move" : "roster limit unknown"
        }
      />
      <StatTile
        label="Competitive posture"
        value={posture.label}
        meta={posture.note}
      />
      <StatTile
        label="Rosters"
        value={payload.rosterSource === "live_overlay" ? "Live" : "Contract"}
        meta={payload.rostersAsOf ? `as of ${payload.rostersAsOf}` : undefined}
      />
    </div>
  );
}

// ── panel ──────────────────────────────────────────────────────────────

// `capacity: null` is not sent: the backend's configured default applies and
// the control then shows the capacity the backend used (`request.capacity`).
export const DEFAULT_STREAMING_PARAMS = {
  week: "",
  horizonWeeks: 1,
  position: "ALL",
  capacity: null,
  dynastyBudget: "0",
};

export default function IdpStreamingPanel({ leagueKey, ownerId }) {
  const [params, setParams] = useState(DEFAULT_STREAMING_PARAMS);
  const { payload, failure, loading } = useIdpStreaming({
    leagueKey,
    ownerId,
    params,
  });
  const names = useMemo(() => playerNameIndex(payload), [payload]);
  // The last answer keeps the controls' bounds (config) and applied capacity
  // stable across a refresh or a failed request.
  const [last, setLast] = useState(null);
  useEffect(() => {
    if (payload) setLast(payload);
  }, [payload]);

  return (
    <div
      className={styles.page}
      data-testid="idp-streaming"
      aria-busy={loading ? "true" : "false"}
    >
      <Panel dense>
        <Controls
          params={params}
          setParams={setParams}
          config={last?.config}
          appliedCapacity={last?.request?.capacity}
        />
      </Panel>

      {failure ? (
        failure.code === "team_required" ? (
          <EmptyState
            title="Pick your team"
            description="Every number here is roster-specific, so a team is never guessed."
          />
        ) : (
          <FailureState failure={failure} context="Weekly IDP streaming" />
        )
      ) : null}

      {loading && !payload && !failure ? (
        <SkeletonTable rows={8} columns={6} />
      ) : null}

      {payload && !failure ? (
        <>
          {(payload.unprojectedRosterPlayers || []).length ? (
            <Banner
              tone="warning"
              title="Roster defenders without a projection"
            >
              {payload.unprojectedRosterPlayers
                .map((p) =>
                  (p.missingWeeks || []).length
                    ? `${p.name} (week ${p.missingWeeks.join(", ")})`
                    : p.name,
                )
                .join("; ")}{" "}
              — no weekly projection for those weeks, so the lineup math cannot
              place them there (unknown, not a guessed number).
            </Banner>
          ) : null}
          <Decision payload={payload} />
          <Context payload={payload} />
          <Alternatives payload={payload} names={names} />
          <LargerBudget payload={payload} names={names} />
          <CapacityCurve payload={payload} names={names} />
          <StreamingBoard payload={payload} />
          <SafeToDrop payload={payload} />
          <HowComputed payload={payload} />
        </>
      ) : null}
    </div>
  );
}
