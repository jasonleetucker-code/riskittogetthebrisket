"use client";

// ── Roster Construction V1 — the body of /roster-construction ────────────
//
// Owner directive 2026-10-30.  DISPLAY ONLY: every number comes from
// GET /api/roster-construction (src/roster_intel/construction.py), which
// solves every team-week with the existing exact lineup solver.  This file
// formats that payload; it scores, ranks, values, optimizes and decides
// nothing (the no-frontend-engine rule).  Missing renders as "—" or its
// stated reason, never 0.
//
// Two measures are shown side by side and are NEVER blended: production
// (realized points of players who entered the season's optimal legal
// lineups) and dynasty value (today's canonical board values on today's
// rosters).  They have different rosters, different dates and different
// rank denominators; each carries its own.
//
// Loaded with React.lazy from app/roster-construction/page.jsx so it costs
// that page's chunk nothing while the flag is off.
//
// Reports, never recommends a transaction.  NO ACTION is a valid result.

import { useMemo, useState } from "react";
import {
  Badge,
  Banner,
  CollapsiblePanel,
  DataTable,
  EmptyState,
  Field,
  Panel,
  PlayerNameButton,
  Select,
  SkeletonTable,
  Sparkline,
  StatTile,
  FailureState,
} from "@/components/ds";
import { useRosterConstruction } from "@/components/roster-construction/useRosterConstruction";
import {
  diagnosisState,
  evidenceRows,
  fmtCountOf,
  fmtPercentile,
  fmtPoints,
  fmtRank,
  fmtRatio,
  fmtShare,
  fmtSpells,
  fmtValue,
  exclusionText,
  fmtWeeks,
  humanizeCode,
  lineupBasisText,
  marginalUnavailableText,
  mismatchRows,
  overallVerdictText,
  playerNameIndex,
  poolScopeText,
  reasonText,
  ruleTitle,
  rulesEvaluated,
  rulesNotEvaluated,
  scenarioText,
  slotLabel,
  sortPositions,
  tagLabel,
} from "@/lib/roster-construction";
import styles from "@/app/roster-construction/roster-construction.module.css";

function Missing({ children = "—" }) {
  return <span className={styles.meta}>{children}</span>;
}

function PosBadge({ position }) {
  return <Badge tone="outline">{position || "?"}</Badge>;
}

/** A DataTable whose rows expand into a caller-rendered detail row. */
function ExpandTable({
  caption,
  columns,
  rows,
  rowKey,
  renderDetail,
  rowLabel,
  emptyState,
  defaultSort,
}) {
  const [open, setOpen] = useState("");
  const keyOf = (r, i) => String(rowKey(r, i));
  return (
    <DataTable
      caption={caption}
      columns={columns}
      rows={rows}
      rowKey={rowKey}
      density="compact"
      defaultSort={defaultSort}
      onRowClick={(r, i) => {
        const k = keyOf(r, i);
        setOpen((cur) => (cur === k ? "" : k));
      }}
      isRowExpanded={(r, i) => keyOf(r, i) === open}
      rowExpandLabel={rowLabel}
      renderAfterRow={(r, i) =>
        keyOf(r, i) === open ? (
          <tr>
            <td colSpan={columns.length}>{renderDetail(r)}</td>
          </tr>
        ) : null
      }
      emptyState={emptyState}
    />
  );
}

function DetailBlock({ label, children }) {
  return (
    <div className={styles.detailBlock}>
      <span className={styles.detailLabel}>{label}</span>
      {children}
    </div>
  );
}

// ── header ─────────────────────────────────────────────────────────────

function Summary({ payload, validWeeks }) {
  const basis = lineupBasisText(payload);
  const posture = payload.team?.posture;
  const cov = payload.coverage || {};
  const included = Array.isArray(cov.weeksIncluded) ? cov.weeksIncluded.length : null;
  const excludedWeeks = Array.isArray(cov.weeksExcluded) ? cov.weeksExcluded.length : 0;
  const teamExclusions = Array.isArray(cov.teamWeeksExcluded)
    ? cov.teamWeeksExcluded
    : Array.isArray(payload.team?.excludedWeeks)
      ? payload.team.excludedWeeks
      : [];
  const excludedTeamWeeks = teamExclusions.length;
  const ownWeeks = Array.isArray(payload.team?.validWeeks)
    ? payload.team.validWeeks.length
    : validWeeks;
  const overall = overallVerdictText(payload.overall);
  return (
    <>
      <div className={styles.summaryGrid} data-testid="rc-summary">
        <StatTile
          label="Team"
          value={payload.team?.label || payload.team?.managerLabel || `Roster ${payload.team?.rosterId}`}
          meta={`${payload.season} season rosters`}
        />
        <StatTile
          label="Overall read"
          value={overall.label}
          meta={overall.note}
        />
        <StatTile
          label="Lineup basis"
          value={basis.label}
          meta={[
            payload.rules?.teamCount ? `${payload.rules.teamCount} teams` : null,
            payload.rules?.starterSlots?.length
              ? `${payload.rules.starterSlots.length} starting slots`
              : null,
            basis.hypothetical && payload.team?.observedSubmittedWeeks != null
              ? `${payload.team.observedSubmittedWeeks} weeks with an observed submitted lineup`
              : null,
          ]
            .filter(Boolean)
            .join(" · ") || undefined}
        />
        <StatTile
          label="Weeks counted"
          value={ownWeeks != null ? String(ownWeeks) : included != null ? String(included) : "—"}
          meta={
            excludedWeeks || excludedTeamWeeks
              ? `${excludedWeeks} league week${excludedWeeks === 1 ? "" : "s"} and ${excludedTeamWeeks} team-week${excludedTeamWeeks === 1 ? "" : "s"} excluded`
              : "no exclusions"
          }
        />
      </div>
      {basis.hypothetical ? (
        <Banner tone="warning" title="Hypothetical optimal lineups">
          {basis.detail}
        </Banner>
      ) : null}
      <Banner tone="info" title="Two independent measures">
        Production is realized fantasy points from the {payload.season} season&rsquo;s
        rosters. Value is today&rsquo;s canonical dynasty value on today&rsquo;s
        rosters. They are calculated separately, use different rank denominators
        and are never combined. Competitive posture:{" "}
        {posture?.label
          ? `${posture.label} (${humanizeCode(posture.source || "unstated").toLowerCase()})`
          : `unavailable${posture?.reason ? ` — ${reasonText(posture.reason)}` : ""}`}
        .
      </Banner>
    </>
  );
}

// ── production ─────────────────────────────────────────────────────────

function ProductionDetail({ row, names, hypothetical }) {
  const p = row.production || {};
  const alloc = Object.entries(p.slotAllocation || {});
  return (
    <div className={styles.detailGrid} data-testid="rc-production-detail">
      <DetailBlock label="Slots these points came from">
        {alloc.length === 0 ? (
          <span className={styles.detailValue}>Not stated</span>
        ) : (
          alloc.map(([slot, v]) => (
            <span key={slot} className={styles.detailValue}>
              {slotLabel(slot)}:{" "}
              <span className={styles.detailNum}>{v?.starts ?? "—"}</span> starts ·{" "}
              <span className={styles.detailNum}>{fmtPoints(v?.points) ?? "—"}</span> pts
            </span>
          ))
        )}
        <span className={styles.meta}>
          A {row.position} in a FLEX slot counts as {row.position} production exactly once.
        </span>
      </DetailBlock>
      <DetailBlock label="Top contributors">
        {(p.topContributors || []).length === 0 ? (
          <span className={styles.detailValue}>None</span>
        ) : (
          p.topContributors.map((c) => (
            <span key={c.playerId || c.name} className={styles.detailValue}>
              <PlayerNameButton
                name={c.name || names.get(String(c.playerId)) || String(c.playerId)}
                playerId={c.playerId}
                className={styles.playerName}
              />{" "}
              <span className={styles.detailNum}>{fmtPoints(c.points) ?? "—"}</span> pts ·{" "}
              {c.starts ?? "—"} starts
            </span>
          ))
        )}
      </DetailBlock>
      <DetailBlock label="Comparison">
        <span className={styles.detailValue}>
          League mean <span className={styles.detailNum}>{fmtPoints(p.leagueMean) ?? "—"}</span> ·
          median <span className={styles.detailNum}>{fmtPoints(p.leagueMedian) ?? "—"}</span>
        </span>
        <span className={styles.detailValue}>
          Points-per-week rank{" "}
          <span className={styles.detailNum}>{fmtRank(p.ppgRank, p.of) ?? "—"}</span>
          {p.partialWeeks ? " — this team has fewer counted weeks than the league maximum" : ""}
          {p.tiedWith ? ` — tied with ${p.tiedWith} other team${p.tiedWith === 1 ? "" : "s"}` : ""}
        </span>
        {p.ppg != null ? (
          <span className={styles.detailValue}>
            <span className={styles.detailNum}>{fmtPoints(p.ppg)}</span> pts per counted week
          </span>
        ) : null}
        {hypothetical ? (
          <span className={styles.detailValue}>
            Observed submitted lineups:{" "}
            <span className={styles.detailNum}>
              {fmtPoints(p.observedSubmittedPoints) ?? "—"}
            </span>{" "}
            pts (separate from the hypothetical optimal figure)
          </span>
        ) : null}
        <span className={styles.detailValue}>
          {p.appearances ?? "—"} starter appearances by{" "}
          {p.distinctContributors ?? "—"} distinct players
        </span>
      </DetailBlock>
    </div>
  );
}

function ProductionPanel({ payload }) {
  const names = useMemo(() => playerNameIndex(payload.players), [payload.players]);
  const hypothetical = lineupBasisText(payload).hypothetical;
  const rows = useMemo(
    () => sortPositions(payload.positions).filter((r) => r.production),
    [payload.positions],
  );
  const columns = useMemo(
    () => [
      {
        key: "position",
        header: "Position",
        accessor: (r) => r.position,
        render: (r) => <PosBadge position={r.position} />,
      },
      {
        key: "points",
        header: hypothetical ? "Hypothetical optimal pts" : "Optimal starter pts",
        headerInfo: hypothetical
          ? "Fantasy points of the optimal legal lineup this roster could have started each week (this league sets lineups manually), attributed to real position. Not what was submitted."
          : "Fantasy points scored by players who entered this team's optimal legal lineup each week, attributed to their real position.",
        numeric: true,
        sortable: true,
        accessor: (r) => r.production.points ?? null,
        render: (r) => fmtPoints(r.production.points) ?? <Missing />,
      },
      ...(hypothetical
        ? [
            {
              key: "submitted",
              header: "Submitted pts",
              headerInfo:
                "Points of the lineups actually submitted, where the host recorded them. A different quantity from the hypothetical optimal column; the two are never mixed.",
              numeric: true,
              hideBelow: "sm",
              accessor: (r) => r.production.observedSubmittedPoints ?? null,
              render: (r) => fmtPoints(r.production.observedSubmittedPoints) ?? <Missing />,
            },
          ]
        : []),
      {
        key: "rank",
        header: "Rank",
        headerInfo: "Rank among the teams in this league's season. Ties share a rank.",
        numeric: true,
        sortable: true,
        firstDirection: "asc",
        accessor: (r) => r.production.rank ?? null,
        render: (r) => fmtRank(r.production.rank, r.production.of) ?? <Missing />,
      },
      {
        key: "percentile",
        header: "Percentile",
        headerInfo: "Share of league teams this group out-produced (higher is better).",
        numeric: true,
        hideBelow: "sm",
        accessor: (r) => r.production.percentile ?? null,
        render: (r) => fmtPercentile(r.production.percentile) ?? <Missing />,
      },
      {
        key: "mean",
        header: "League avg",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.production.leagueMean ?? null,
        render: (r) => fmtPoints(r.production.leagueMean) ?? <Missing />,
      },
      {
        key: "median",
        header: "League median",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.production.leagueMedian ?? null,
        render: (r) => fmtPoints(r.production.leagueMedian) ?? <Missing />,
      },
      {
        key: "contributors",
        header: "Players",
        headerInfo: "Distinct players who contributed starter points.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.production.distinctContributors ?? null,
        render: (r) => r.production.distinctContributors ?? <Missing />,
      },
      {
        key: "top",
        header: "Top contributors",
        hideBelow: "lg",
        accessor: (r) =>
          r.production.topContributors?.[0]?.name ||
          names.get(String(r.production.topContributors?.[0]?.playerId)) ||
          "",
        render: (r) => {
          const top = (r.production.topContributors || []).slice(0, 2);
          return top.length ? (
            <span className={styles.contributors}>
              {top.map((c) => (
                <span key={c.playerId || c.name}>
                  {c.name || names.get(String(c.playerId)) || c.playerId} ·{" "}
                  {fmtPoints(c.points) ?? "—"}
                </span>
              ))}
            </span>
          ) : (
            <Missing />
          );
        },
      },
      {
        key: "weekly",
        header: "Weekly",
        headerInfo: "Points this position group contributed in each counted week.",
        hideBelow: "md",
        accessor: () => "",
        render: (r) => {
          const vals = (r.production.weekly || [])
            .map((w) => w?.points)
            .filter((v) => Number.isFinite(Number(v)) && v != null)
            .map(Number);
          return vals.length >= 2 ? (
            <Sparkline
              values={vals}
              label={`${r.position} weekly starter points, ${vals.length} weeks`}
              width={96}
              height={24}
            />
          ) : (
            <Missing />
          );
        },
      },
    ],
    [names, hypothetical],
  );
  return (
    <Panel
      flush
      title="Production by position"
      subtitle={
        hypothetical
          ? `Realized points of the hypothetical optimal lineups — ${payload.season} season rosters. Submitted lineups are shown separately. Select a row for slots, contributors and weekly points.`
          : `Realized points of optimal-lineup starters — ${payload.season} season rosters. Select a row for slots, contributors and weekly points.`
      }
    >
      <ExpandTable
        caption={`${payload.season} ${hypothetical ? "hypothetical " : ""}optimal starter points by position, with league rank`}
        columns={columns}
        rows={rows}
        rowKey={(r) => r.position}
        rowLabel={(r) => `Production detail for ${r.position}`}
        renderDetail={(r) => <ProductionDetail row={r} names={names} hypothetical={hypothetical} />}
        emptyState={
          <EmptyState
            title="No production rows"
            description="The backend returned no position groups for this team."
          />
        }
      />
    </Panel>
  );
}

// ── dynasty value ──────────────────────────────────────────────────────

function ValuePanel({ payload }) {
  const rows = useMemo(
    () => sortPositions(payload.positions).filter((r) => r.value),
    [payload.positions],
  );
  const vb = payload.valueBlock || null;
  const asOf = vb?.asOf || rows.find((r) => r.value?.asOf)?.value?.asOf || null;
  const columns = useMemo(
    () => [
      {
        key: "position",
        header: "Position",
        accessor: (r) => r.position,
        render: (r) => <PosBadge position={r.position} />,
      },
      {
        key: "total",
        header: "Dynasty value",
        headerInfo:
          "Sum of canonical board values of priced players at this position on today's roster.",
        numeric: true,
        sortable: true,
        accessor: (r) => r.value.total ?? null,
        render: (r) => fmtValue(r.value.total) ?? <Missing>Unpriced</Missing>,
      },
      {
        key: "rank",
        header: "Rank",
        headerInfo: "Rank among the teams on today's board. A different denominator from production.",
        numeric: true,
        sortable: true,
        firstDirection: "asc",
        accessor: (r) => r.value.rank ?? null,
        render: (r) => fmtRank(r.value.rank, r.value.of) ?? <Missing>Unranked</Missing>,
      },
      {
        key: "percentile",
        header: "Percentile",
        numeric: true,
        hideBelow: "sm",
        accessor: (r) => r.value.percentile ?? null,
        render: (r) => fmtPercentile(r.value.percentile) ?? <Missing />,
      },
      {
        key: "priced",
        header: "Priced",
        headerInfo: "Players with a board value. Unpriced players are listed, never counted as zero.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.value.pricedCount ?? null,
        render: (r) =>
          r.value.pricedCount != null ? (
            <span>
              {r.value.pricedCount}
              {r.value.unpricedCount ? (
                <span className={styles.meta}> + {r.value.unpricedCount} unpriced</span>
              ) : null}
            </span>
          ) : (
            <Missing />
          ),
      },
      {
        key: "top1",
        header: "Top holder",
        headerInfo: "Share of this position's value held by its single most valuable player.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.value.top1Share ?? null,
        render: (r) => fmtShare(r.value.top1Share) ?? <Missing />,
      },
    ],
    [],
  );
  return (
    <Panel
      flush
      title="Dynasty value by position"
      subtitle={
        asOf
          ? `Today's canonical values on today's rosters, as of ${asOf}.`
          : "Today's canonical values on today's rosters."
      }
    >
      {vb && vb.available === false ? (
        <Banner tone="warning" title="Dynasty value unavailable">
          The canonical board could not be joined to this league&rsquo;s current rosters
          {vb.reason ? ` — ${reasonText(vb.reason)}` : ""}. Production above is unaffected.
        </Banner>
      ) : (
      <ExpandTable
        caption="Dynasty value held at each position, with league rank"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.position}
        rowLabel={(r) => `Value detail for ${r.position}`}
        renderDetail={(r) => (
          <div className={styles.detailGrid}>
            <DetailBlock label="Pricing coverage">
              <span className={styles.detailValue}>
                {r.value.pricedCount ?? "—"} priced · {r.value.unpricedCount ?? "—"} unpriced
              </span>
              {(r.value.unpricedIds || []).length ? (
                <span className={styles.meta}>
                  Not counted as zero. Unpriced player ids: {r.value.unpricedIds.join(", ")}
                </span>
              ) : null}
            </DetailBlock>
            <DetailBlock label="Concentration">
              <span className={styles.detailValue}>
                Top holder share {fmtShare(r.value.top1Share) ?? "—"}
                {r.value.hhi != null ? ` · concentration index ${fmtRatio(r.value.hhi)}` : ""}
              </span>
            </DetailBlock>
            <DetailBlock label="League comparison">
              <span className={styles.detailValue}>
                League mean {fmtValue(r.value.leagueMean) ?? "—"} · median{" "}
                {fmtValue(r.value.leagueMedian) ?? "—"}
              </span>
              <span className={styles.meta}>
                As of {r.value.asOf || asOf || "unstated"}; current rosters.
              </span>
            </DetailBlock>
          </div>
        )}
        emptyState={
          <EmptyState
            title="No value rows"
            description="The canonical board did not join to this team's roster."
          />
        }
      />
      )}
    </Panel>
  );
}

// ── mismatch ───────────────────────────────────────────────────────────

function MismatchPanel({ payload }) {
  const rows = useMemo(
    () => mismatchRows(payload.positions, payload.diagnoses),
    [payload.positions, payload.diagnoses],
  );
  const columns = useMemo(
    () => [
      {
        key: "position",
        header: "Position",
        accessor: (r) => r.position,
        render: (r) => <PosBadge position={r.position} />,
      },
      {
        key: "prod",
        header: "Production rank",
        numeric: true,
        accessor: (r) => r.production?.rank ?? null,
        render: (r) => fmtRank(r.production?.rank, r.production?.of) ?? <Missing />,
      },
      {
        key: "value",
        header: "Value rank",
        numeric: true,
        accessor: (r) => r.value?.rank ?? null,
        render: (r) => fmtRank(r.value?.rank, r.value?.of) ?? <Missing />,
      },
      {
        key: "prodPct",
        header: "Production pct.",
        numeric: true,
        hideBelow: "sm",
        accessor: (r) => r.production?.percentile ?? null,
        render: (r) => fmtPercentile(r.production?.percentile) ?? <Missing />,
      },
      {
        key: "valuePct",
        header: "Value pct.",
        numeric: true,
        hideBelow: "sm",
        accessor: (r) => r.value?.percentile ?? null,
        render: (r) => fmtPercentile(r.value?.percentile) ?? <Missing />,
      },
      {
        key: "reading",
        header: "Rule reading",
        headerInfo: "What the value-and-production rule (RC-D1) concluded for this position.",
        hideBelow: "md",
        accessor: (r) => (r.diagnosis ? diagnosisState(r.diagnosis).label : ""),
        render: (r) => {
          if (!r.diagnosis) return <Missing>Not flagged</Missing>;
          const s = diagnosisState(r.diagnosis);
          return (
            <span>
              <Badge tone={s.tone}>{s.label}</Badge>{" "}
              <span className={styles.meta}>{r.diagnosis.explanation}</span>
            </span>
          );
        },
      },
    ],
    [],
  );
  return (
    <Panel
      flush
      title="Production versus value"
      subtitle="Each rank keeps its own denominator. A gap is something to read, not a trade signal."
    >
      <DataTable
        caption="Production rank and dynasty value rank side by side for each position"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.position}
        density="compact"
        presorted
        emptyState={<EmptyState title="Nothing to compare" description="No position groups were returned." />}
      />
    </Panel>
  );
}

// ── diagnoses ──────────────────────────────────────────────────────────

function DiagnosisItem({ d, names }) {
  const s = diagnosisState(d);
  const rows = evidenceRows(d.evidence, names);
  return (
    <li className={styles.diagnosis} data-testid="rc-diagnosis" data-rule={d.rule}>
      <div className={styles.diagnosisHead}>
        <Badge tone={s.tone}>{s.label}</Badge>
        <span className={styles.diagnosisTitle}>{ruleTitle(d.rule)}</span>
        {d.position ? <PosBadge position={d.position} /> : null}
        <span className={styles.meta}>{d.rule}</span>
      </div>
      {d.status === "not_evaluated" ? (
        <p className={styles.diagnosisText}>
          Not evaluated: {reasonText(d.notEvaluatedReason)}. This is not a pass.
        </p>
      ) : d.explanation ? (
        <p className={styles.diagnosisText}>{d.explanation}</p>
      ) : null}
      {rows.length ? (
        <dl className={styles.evidence}>
          {rows.map((r) => (
            <div key={r.key} style={{ display: "contents" }}>
              <dt>{r.label}</dt>
              <dd>{r.text}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </li>
  );
}

function DiagnosesPanel({ payload }) {
  const names = useMemo(() => playerNameIndex(payload.players), [payload.players]);
  const all = Array.isArray(payload.diagnoses) ? payload.diagnoses : [];
  const fired = all.filter((d) => d.status === "fired");
  const rest = all.filter((d) => d.status !== "fired");
  const overall = overallVerdictText(payload.overall);
  const evaluated = rulesEvaluated(payload.overall, all);
  const notEvaluated = rulesNotEvaluated(payload.overall);
  return (
    <Panel
      title="Construction diagnoses"
      subtitle="Each one is calculated evidence. None is a transaction recommendation, and no action is a valid result."
    >
      <div className={styles.stack} data-testid="rc-diagnoses">
        <p className={styles.diagnosisText} data-testid="rc-overall">
          <strong>Overall: {overall.label}.</strong> {overall.note}
          {evaluated.length ? ` Rules checked: ${evaluated.join(", ")}.` : ""}
          {notEvaluated.length
            ? ` Not evaluated: ${notEvaluated
                .map((n) => `${n.rule} (${reasonText(n.reason)})`)
                .join(", ")}.`
            : ""}
        </p>
        {fired.length ? (
          <ul className={styles.diagnosisList}>
            {fired.map((d) => (
              <DiagnosisItem key={`${d.rule}:${d.position || ""}`} d={d} names={names} />
            ))}
          </ul>
        ) : (
          <EmptyState
            title="No action"
            description="No rule fired for this team. Nothing here calls for a change."
          />
        )}
        {rest.length ? (
          <CollapsiblePanel
            title={`Rules that did not fire (${rest.length})`}
            headingLevel={3}
            defaultCollapsed
            dense
          >
            <ul className={styles.diagnosisList}>
              {rest.map((d) => (
                <DiagnosisItem key={`${d.rule}:${d.position || ""}`} d={d} names={names} />
              ))}
            </ul>
          </CollapsiblePanel>
        ) : null}
      </div>
    </Panel>
  );
}

// ── players ────────────────────────────────────────────────────────────

function PlayerDetail({ p, scenario }) {
  const hypo = p.hypotheticalStarts;
  const ls = p.leagueStartable;
  const marg = p.marginalPoints;
  const par = p.pointsAboveReplacement;
  return (
    <div className={styles.detailGrid} data-testid="rc-player-detail">
      <DetailBlock label="Actual optimized starts while owned">
        <span className={styles.detailValue}>
          <span className={styles.detailNum}>{fmtCountOf(p.starts) ?? "—"}</span> weeks in this
          team&rsquo;s optimal legal lineup
        </span>
        <span className={styles.detailValue}>
          Owned {fmtSpells(p.ownershipSpells) ?? "dates unstated"} · {p.ownedWeeks ?? "—"} weeks,{" "}
          {p.eligibleOwnedWeeks ?? "—"} with a scored game
        </span>
        <span className={styles.detailValue}>
          Started points {fmtPoints(p.startedPoints) ?? "—"}
        </span>
        <span className={styles.meta}>
          {p.zeroPointWeeks ?? "—"} zero-point week(s) — the host does not distinguish a bye,
          an inactive player or a scoreless game.{" "}
          {p.unobservedWeeks ? `${p.unobservedWeeks} week(s) had no recorded points and are excluded.` : ""}
        </span>
      </DetailBlock>
      <DetailBlock label="Hypothetical optimal starts">
        {hypo && hypo.value != null ? (
          <span className={styles.detailValue}>
            <span className={styles.detailNum}>{fmtCountOf(hypo)}</span> weeks he would have
            started
            {hypo.undeterminedWeeksExcluded
              ? ` (${hypo.undeterminedWeeksExcluded} week(s) excluded: the answer depended on a teammate score that was unknown)`
              : ""}
            {hypo.unobservedWeeksExcluded
              ? ` (${hypo.unobservedWeeksExcluded} week(s) excluded: he had no recorded points)`
              : ""}
          </span>
        ) : (
          <span className={styles.detailValue}>Not computed for this player</span>
        )}
        {Array.isArray(scenario?.assumptions) && scenario.assumptions.length ? (
          scenario.assumptions.map((a) => (
            <span key={a} className={styles.meta}>
              Assumption: {a}
            </span>
          ))
        ) : (
          <span className={styles.meta}>
            Assumption: {scenarioText(hypo?.scenario) || "scenario not stated"}
          </span>
        )}
        {Array.isArray(scenario?.weeksWithUnknownTeammates) &&
        scenario.weeksWithUnknownTeammates.length ? (
          <span className={styles.meta}>
            Teammate scores unknown in {fmtWeeks(scenario.weeksWithUnknownTeammates)}.
          </span>
        ) : null}
      </DetailBlock>
      <DetailBlock label="League-relative startability">
        {ls && ls.value != null ? (
          <span className={styles.detailValue}>
            <span className={styles.detailNum}>{fmtCountOf(ls)}</span> weeks at or above the
            league&rsquo;s empirical starter line for his position
          </span>
        ) : (
          <span className={styles.detailValue}>Not computed for this player</span>
        )}
        <span className={styles.meta}>
          The line is the score the last starter at the position needed that week, over{" "}
          {poolScopeText(ls?.poolScope) || "a pool not stated"}.
        </span>
      </DetailBlock>
      <DetailBlock label="Lineup marginal">
        {marg && marg.value != null ? (
          <span className={styles.detailValue}>
            <span className={styles.detailNum}>{fmtPoints(marg.value)}</span> pts the lineup lost
            without him ({marg.knownWeeks ?? "—"} known weeks)
          </span>
        ) : (
          <span className={styles.detailValue}>
            Unknown
            {marginalUnavailableText(marg) ? ` — ${marginalUnavailableText(marg)}` : ""}
          </span>
        )}
      </DetailBlock>
      {par ? (
      <DetailBlock label="Points above replacement">
        {par && par.value != null ? (
          <span className={styles.detailValue}>
            <span className={styles.detailNum}>{fmtPoints(par.value)}</span>
          </span>
        ) : (
          <span className={styles.detailValue}>Unknown</span>
        )}
        {par?.temporalScope ? (
          <span className={styles.meta}>
            {par.temporalScope === "season_to_date_uses_later_weeks"
              ? "Uses the whole season, including weeks after a trade — not a point-in-time figure."
              : humanizeCode(par.temporalScope)}
          </span>
        ) : null}
      </DetailBlock>
      ) : null}
      <DetailBlock label="Dynasty value and tags">
        <span className={styles.detailValue}>
          Board value {fmtValue(p.rankDerivedValue) ?? "unpriced"}
          {p.age != null ? ` · age ${Math.round(p.age)}` : ""}
          {p.injuryStatus ? ` · ${humanizeCode(p.injuryStatus)}` : ""}
        </span>
        <span className={styles.meta}>
          {p.onCurrentRoster === false
            ? "Not on this team's current roster."
            : p.onCurrentRoster === true
              ? "On this team's current roster."
              : ""}
        </span>
        <span className={styles.tagRow}>
          {(p.tags || []).length ? (
            p.tags.map((t) => (
              <Badge key={t} tone="outline">
                {tagLabel(t)}
              </Badge>
            ))
          ) : (
            <span className={styles.meta}>No tags</span>
          )}
        </span>
      </DetailBlock>
    </div>
  );
}

function PlayersPanel({ payload }) {
  const [pos, setPos] = useState("ALL");
  const positions = useMemo(
    () => sortPositions(payload.positions).map((r) => r.position),
    [payload.positions],
  );
  const rows = useMemo(
    () =>
      (Array.isArray(payload.players) ? payload.players : []).filter(
        (p) => pos === "ALL" || p.position === pos,
      ),
    [payload.players, pos],
  );
  const columns = useMemo(
    () => [
      {
        key: "name",
        header: "Player",
        accessor: (p) => p.name,
        render: (p) => (
          <span className={styles.playerCell}>
            <PosBadge position={p.position} />
            <PlayerNameButton name={p.name} playerId={p.playerId} className={styles.playerName} />
          </span>
        ),
      },
      {
        key: "owned",
        header: "Owned",
        headerInfo: "Weeks on this team's roster, with the dates of each spell.",
        hideBelow: "sm",
        accessor: (p) => p.ownedWeeks ?? null,
        render: (p) => (
          <span>
            {p.ownedWeeks ?? "—"} wk
            <span className={styles.meta}> {fmtSpells(p.ownershipSpells) || ""}</span>
          </span>
        ),
      },
      {
        key: "actual",
        header: "Actual starts",
        headerInfo:
          "Weeks he was in this team's optimal legal lineup while he was actually owned, out of the weeks he was owned and scored.",
        numeric: true,
        sortable: true,
        accessor: (p) => p.starts?.value ?? null,
        render: (p) => fmtCountOf(p.starts) ?? <Missing />,
      },
      {
        key: "hypo",
        header: "Hypothetical",
        headerInfo:
          "Weeks he would have started under a stated counterfactual roster. The assumption is in the row detail and the method notes.",
        numeric: true,
        sortable: true,
        hideBelow: "sm",
        accessor: (p) => p.hypotheticalStarts?.value ?? null,
        render: (p) => fmtCountOf(p.hypotheticalStarts) ?? <Missing />,
      },
      {
        key: "startable",
        header: "Startable",
        headerInfo:
          "Weeks he scored at or above the league's empirical starter line for his position.",
        numeric: true,
        sortable: true,
        hideBelow: "sm",
        accessor: (p) => p.leagueStartable?.value ?? null,
        render: (p) => fmtCountOf(p.leagueStartable) ?? <Missing />,
      },
      {
        key: "marginal",
        header: "Lineup marginal",
        headerInfo:
          "Points the optimal lineup lost without him, summed over his owned weeks.",
        numeric: true,
        hideBelow: "md",
        accessor: (p) => p.marginalPoints?.value ?? null,
        render: (p) => fmtPoints(p.marginalPoints?.value) ?? <Missing>Unknown</Missing>,
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        hideBelow: "md",
        accessor: (p) => p.rankDerivedValue ?? null,
        render: (p) => fmtValue(p.rankDerivedValue) ?? <Missing>Unpriced</Missing>,
      },
    ],
    [],
  );
  return (
    <Panel
      flush
      title="Player starts"
      subtitle="Three separate counts, each with its own denominator: actual starts while owned, hypothetical starts under a stated scenario, and league-relative startability."
    >
      <div className={styles.controls} style={{ padding: "var(--space-3)" }}>
        <Field label="Position" id="rc-player-pos">
          <Select id="rc-player-pos" value={pos} onChange={(e) => setPos(e.target.value)}>
            <option value="ALL">All positions</option>
            {positions.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </Select>
        </Field>
      </div>
      <ExpandTable
        caption="Per-player starts: actual while owned, hypothetical and league-relative"
        columns={columns}
        rows={rows}
        rowKey={(p) => p.playerId || p.name}
        rowLabel={(p) => `Start detail for ${p.name}`}
        renderDetail={(p) => <PlayerDetail p={p} scenario={payload.hypotheticalScenario} />}
        emptyState={
          <EmptyState
            title="No players"
            description="No players at this position have roster history for this team."
          />
        }
      />
    </Panel>
  );
}

// ── depth ──────────────────────────────────────────────────────────────

function DepthPanel({ payload }) {
  const rows = useMemo(
    () => sortPositions(payload.positions).filter((r) => r.depth),
    [payload.positions],
  );
  const columns = useMemo(
    () => [
      {
        key: "position",
        header: "Position",
        accessor: (r) => r.position,
        render: (r) => <PosBadge position={r.position} />,
      },
      {
        key: "holes",
        header: "Unfilled slots",
        headerInfo:
          "Weeks a dedicated slot at this position was empty or filled by a zero-point player; FLEX slots are counted separately.",
        numeric: true,
        accessor: (r) => r.depth.holes?.dedicated ?? null,
        render: (r) =>
          r.depth.holes ? (
            <span>
              {r.depth.holes.dedicated}
              {r.depth.holes.zeroPointFlexStarts ? (
                <span className={styles.meta}>
                  {" "}
                  + {r.depth.holes.zeroPointFlexStarts} zero-point flex
                </span>
              ) : null}
            </span>
          ) : (
            <Missing />
          ),
      },
      {
        key: "insurance",
        header: "Depth insurance",
        headerInfo:
          "How much of the top starter's points the backups absorb when he is removed. Near 1 means well covered; near 0 means a cliff. Compared with the league's 25th percentile.",
        numeric: true,
        sortable: true,
        accessor: (r) => r.depth.depthInsurance?.meanRatio ?? null,
        render: (r) => {
          const d = r.depth.depthInsurance;
          if (!d || d.meanRatio == null) return <Missing>Unknown</Missing>;
          return (
            <span>
              {fmtRatio(d.meanRatio)}
              <span className={styles.meta}> vs {fmtRatio(d.leagueP25) ?? "—"} P25</span>
            </span>
          );
        },
      },
      {
        key: "redundant",
        header: "Redundant pts",
        headerInfo: "Points scored by owned players at this position who did not start.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.depth.redundantPoints ?? null,
        render: (r) => fmtPoints(r.depth.redundantPoints) ?? <Missing />,
      },
      {
        key: "spike",
        header: "Spike weeks",
        headerInfo:
          "Player-weeks where a bench player scored at or above the league's starter line.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.depth.redundantStartableWeeks ?? null,
        render: (r) => r.depth.redundantStartableWeeks ?? <Missing />,
      },
      {
        key: "perSlot",
        header: "Rostered per slot",
        headerInfo: "Players rostered at this position per starting slot it can fill. A measured fact; no target is implied.",
        numeric: true,
        hideBelow: "md",
        accessor: (r) => r.depth.rosteredPerStartingSlot ?? null,
        render: (r) => fmtRatio(r.depth.rosteredPerStartingSlot) ?? <Missing />,
      },
      {
        key: "leaveout",
        header: "Group leave-out pts",
        headerInfo:
          "Points the optimal lineup loses if every player at this position is removed.",
        numeric: true,
        hideBelow: "lg",
        accessor: (r) => r.depth.positionLeaveOutPoints ?? null,
        render: (r) => fmtPoints(r.depth.positionLeaveOutPoints) ?? <Missing />,
      },
    ],
    [],
  );
  return (
    <Panel
      flush
      title="Depth and coverage"
      subtitle="How the position group holds up when a starter is missing. Select a row for the weeks and counts."
    >
      <ExpandTable
        caption="Depth and coverage by position"
        columns={columns}
        rows={rows}
        rowKey={(r) => r.position}
        rowLabel={(r) => `Depth detail for ${r.position}`}
        renderDetail={(r) => {
          const d = r.depth;
          return (
            <div className={styles.detailGrid}>
              <DetailBlock label="Unfilled slot weeks">
                <span className={styles.detailValue}>
                  {fmtWeeks(d.holes?.weeks) || "None"}
                </span>
                <span className={styles.meta}>
                  Dedicated {d.holes?.dedicated ?? "—"} · zero-point flex starts{" "}
                  {d.holes?.zeroPointFlexStarts ?? "—"}
                </span>
              </DetailBlock>
              <DetailBlock label="Depth insurance">
                <span className={styles.detailValue}>
                  Mean {fmtRatio(d.depthInsurance?.meanRatio) ?? "unknown"} over{" "}
                  {d.depthInsurance?.n ?? "—"} weeks; league 25th percentile{" "}
                  {fmtRatio(d.depthInsurance?.leagueP25) ?? "unknown"}
                </span>
              </DetailBlock>
              <DetailBlock label="Bench production">
                <span className={styles.detailValue}>
                  {fmtPoints(d.redundantPoints) ?? "—"} pts from non-starters ·{" "}
                  {d.redundantStartableWeeks ?? "—"} spike week(s) ·{" "}
                  {fmtRatio(d.rosteredPerStartingSlot) ?? "—"} rostered per slot
                </span>
              </DetailBlock>
            </div>
          );
        }}
        emptyState={<EmptyState title="No depth rows" description="No coverage data was returned." />}
      />
    </Panel>
  );
}

// ── method ─────────────────────────────────────────────────────────────

function MethodPanel({ payload }) {
  const cov = payload.coverage || {};
  const notComputed = Object.entries(payload.notComputed || {});
  const priors = payload.priors || {};
  const scalarPriors = Object.entries(priors).filter(
    ([k, v]) =>
      k !== "version" &&
      k !== "status" &&
      (typeof v === "number" || typeof v === "string" || typeof v === "boolean"),
  );
  const exclusions = [
    ...(cov.weeksExcluded || []).map((e) => `${exclusionText(e)} (every team)`),
    ...(cov.teamWeeksExcluded || []).map((e) => `${exclusionText(e)} (excluded from ranks)`),
    ...(cov.contradictedWeeks || []).map((e) => `${exclusionText(e)} (contradicted by the host)`),
    ...(payload.team?.excludedWeeks || []).map((e) => `This team: ${exclusionText(e)}`),
  ];
  const parity = Object.entries(payload.team?.lineupParity || {});
  return (
    <CollapsiblePanel title="Assumptions, coverage and method" defaultCollapsed>
      <div className={styles.stack}>
        <ul className={styles.notes}>
          {(payload.assumptions || []).map((a) => (
            <li key={a} className={styles.note}>
              {a}
            </li>
          ))}
          {(payload.hypotheticalScenario?.assumptions || []).map((a) => (
            <li key={`h:${a}`} className={styles.note}>
              Hypothetical starts: {a}
            </li>
          ))}
          <li className={styles.note}>
            Method {payload.methodVersion || "unstated"} · schema {payload.schemaVersion || "unstated"} ·
            generated {payload.generatedAt || "unstated"}.
          </li>
          {parity.length ? (
            <li className={styles.note} data-testid="rc-parity">
              Lineup parity with the host:{" "}
              {parity
                .map(([k, n]) => `${humanizeCode(k).toLowerCase()} ${n} week${n === 1 ? "" : "s"}`)
                .join(", ")}
              .
              {payload.team?.flexUnfilledSlotWeeks
                ? ` ${payload.team.flexUnfilledSlotWeeks} FLEX slot-week(s) went unfilled.`
                : ""}
            </li>
          ) : null}
        </ul>
        {exclusions.length ? (
          <ul className={styles.notes} data-testid="rc-exclusions">
            {exclusions.map((t) => (
              <li key={t} className={styles.note}>
                {t}.
              </li>
            ))}
          </ul>
        ) : null}
        {notComputed.length ? (
          <ul className={styles.notes}>
            {notComputed.map(([k, v]) => (
              <li key={k} className={styles.note}>
                Not computed in V1 — {humanizeCode(k).toLowerCase()}: {String(v)}
              </li>
            ))}
          </ul>
        ) : null}
        {Object.keys(priors).length ? (
          <ul className={styles.notes}>
            <li className={styles.note}>
              {priors.status || "Thresholds are labelled priors."} ({priors.version || "version unstated"}
              ){scalarPriors.length ? ": " : "."}
              {scalarPriors
                .map(([k, v]) => `${humanizeCode(k).toLowerCase()} ${String(v)}`)
                .join(", ")}
              {scalarPriors.length ? "." : ""}
            </li>
          </ul>
        ) : null}
      </div>
    </CollapsiblePanel>
  );
}

// ── root ───────────────────────────────────────────────────────────────

export default function RosterConstructionPanel({ leagueKey, rosterId, season, validWeeks }) {
  const { payload, failure, loading } = useRosterConstruction({
    leagueKey,
    rosterId,
    season,
    enabled: Boolean(leagueKey && rosterId),
  });

  if (!rosterId) {
    return (
      <EmptyState
        title="Pick a team"
        description="Every number here is specific to one team, so a team is never guessed."
      />
    );
  }
  return (
    <div className={styles.page} data-testid="roster-construction-panel" aria-busy={loading || undefined}>
      {failure ? <FailureState failure={failure} context="Roster Construction" /> : null}
      {loading && !payload && !failure ? <SkeletonTable rows={8} columns={5} /> : null}
      {payload && !failure ? (
        <>
          <Summary payload={payload} validWeeks={validWeeks} />
          <ProductionPanel payload={payload} />
          <ValuePanel payload={payload} />
          <MismatchPanel payload={payload} />
          <DiagnosesPanel payload={payload} />
          <PlayersPanel payload={payload} />
          <DepthPanel payload={payload} />
          <MethodPanel payload={payload} />
        </>
      ) : null}
    </div>
  );
}
