"use client";

// ── /waiver-advisor — Waiver Advisor (Workstream E) ───────────────────
//
// One team's add/drop + FAAB read.  DISPLAY ONLY: every number comes from
// POST /api/waiver/advisor (src/waivers/advisor.py), which composes the
// existing owners — Perfect Waivers, the FAAB engine (via find_waiver_targets),
// the exact lineup solver, roster capacity, droppability and competitive
// posture.  This file formats that payload; it computes no value, bid, lineup
// or legality (the no-frontend-engine rule).
//
// GATED: the page renders nothing but "not available" unless the backend
// serves the advisor (flag `waiver_advisor`, default OFF).  It is linked from
// nowhere (not in lib/nav-model.js) and is a private page (lib/public-routes.js
// default-deny), so it is also behind the site login.
//
// Advice only.  Nothing here submits, schedules or drafts a waiver claim.

import { lazy, Suspense, useEffect, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  CollapsiblePanel,
  DataTable,
  EmptyState,
  FailureState,
  Field,
  PageHeader,
  Panel,
  PlayerNameButton,
  Select,
  SkeletonTable,
  StatTile,
} from "@/components/ds";
import TeamSwitcher from "@/components/TeamSwitcher";
import { useLeague } from "@/components/useLeague";
import { useTeam } from "@/components/useTeam";
import { useWaiverAdvisor } from "@/components/waivers/useWaiverAdvisor";
import {
  ADVISOR_POSITION_OPTIONS,
  confidenceTone,
  expectedWinText,
  fmtDollars,
  fmtSigned,
  fmtValue,
  forcedDropText,
  lineupText,
  maxRationalText,
  planStatusLabel,
  postureText,
  reasonText,
  recommendedBidText,
  releaseText,
} from "@/lib/waiver-advisor";
import styles from "@/app/waivers/waivers.module.css";

// The per-pair bid desk is the existing FAAB v2 desk (/api/waiver/faab-recommend),
// loaded only when a user asks for it so it costs this page's chunk nothing.
const FaabRecommendation = lazy(
  () => import("@/components/waivers/FaabRecommendation"),
);

function Missing({ children }) {
  return <span className={styles.playerMeta}>{children}</span>;
}

function TeamContext({ payload }) {
  const faab = payload.faab || {};
  const posture = postureText(payload.posture);
  const plan = payload.plan?.summary || null;
  const capacity = payload.plan?.capacity || null;
  return (
    <div className={styles.summaryGrid} data-testid="advisor-team-context">
      <StatTile
        label="FAAB remaining"
        value={faab.state === "known" ? fmtDollars(faab.remaining) : "Unknown"}
        meta={
          faab.originalBudget
            ? `of ${fmtDollars(faab.originalBudget)} original`
            : undefined
        }
      />
      <StatTile
        label="Competitive posture"
        value={posture.label}
        meta={posture.note}
      />
      <StatTile
        label="Optimal plan"
        value={
          plan
            ? `${plan.addCount} add${plan.addCount === 1 ? "" : "s"}`
            : "Unavailable"
        }
        meta={
          plan
            ? `net ${fmtSigned(plan.netValueGain) ?? "—"} board value`
            : undefined
        }
      />
      <StatTile
        label="Roster"
        value={
          capacity && capacity.rosterLimit != null
            ? `${capacity.rosterCount ?? "?"} / ${capacity.rosterLimit}`
            : "Cap unknown"
        }
        meta={capacity ? `capacity ${capacity.state}` : undefined}
      />
    </div>
  );
}

function Detail({ c, payload, leagueKey, ownerId, selectedTeam }) {
  const [deskOpen, setDeskOpen] = useState(false);
  const exp = expectedWinText(c.faab);
  const lineup = lineupText(c.lineup);
  const forced = forcedDropText(c.capacity);
  const release = c.plan?.release;
  const dropForDesk =
    release?.kind === "drop" && release.name ? { name: release.name } : null;
  const market = c.marketReference || {};
  const rep = c.replacement || {};
  const option = payload.faab?.seasonOption;
  return (
    <div className={styles.contextGrid} data-testid="advisor-detail">
      <div className={styles.contextBlock}>
        <span className={styles.contextLabel}>Value</span>
        <span className={styles.contextValue}>
          {fmtValue(c.value?.rankDerivedValue)} canonical dynasty value
          {c.rank ? ` · rank ${c.rank}` : ""} · confidence{" "}
          {c.value?.confidenceLabel || c.value?.confidenceBucket || "unstated"}
        </span>
        <span className={styles.contextValue}>
          Market reference (KTC, non-voting):{" "}
          {market.state === "available"
            ? fmtValue(market.value)
            : `unavailable — ${reasonText(market.reason)}`}
        </span>
        <span className={styles.contextValue}>
          Waiver level at {c.position}:{" "}
          {rep.state === "available"
            ? `${fmtValue(rep.waiverLevel)} (${fmtSigned(rep.valueOverWaiverLevel)} over)`
            : "unavailable"}
          {rep.scarcityMultiplier != null
            ? ` · scarcity ×${rep.scarcityMultiplier}`
            : " · scarcity unavailable"}
        </span>
      </div>
      <div className={styles.contextBlock}>
        <span className={styles.contextLabel}>Roster fit</span>
        <span className={styles.contextValue}>
          Lineup: {lineup.text}
          {c.lineup?.state === "evaluated" && c.lineup.leavesLineup?.length
            ? ` — replaces ${c.lineup.leavesLineup.map((p) => p.name).join(", ")}`
            : ""}
          {c.lineup?.state === "evaluated"
            ? ` (starting value ${fmtSigned(c.lineup.startingValueDelta)})`
            : ""}
        </span>
        <span className={styles.contextValue}>
          Plan: {planStatusLabel(c.plan).label}
          {releaseText(release) ? ` — ${releaseText(release)}` : ""}
          {c.plan?.gain != null ? ` (gain ${fmtSigned(c.plan.gain)})` : ""}
        </span>
        <span className={styles.contextValue}>
          If added alone: {forced.text}
          {c.capacity?.forcedDropCost != null
            ? ` · opportunity cost ${fmtValue(c.capacity.forcedDropCost)}`
            : ""}{" "}
          <Badge tone="outline">reported, not applied</Badge>
        </span>
      </div>
      <div className={styles.contextBlock}>
        <span className={styles.contextLabel}>FAAB (engine, standalone)</span>
        <span className={styles.contextValue}>
          Recommended bid: {recommendedBidText(c.faab)}
        </span>
        <span className={styles.contextValue}>
          Expected winning bid (market estimate): {exp.text}
          {exp.median ? ` · median ${exp.median}` : ""}
        </span>
        <span className={styles.contextValue}>
          Max rational bid (your ceiling): {maxRationalText(c.faab)}
        </span>
        {option ? (
          <span className={styles.contextValue}>
            Season option value: ×{option.listBids?.factor} on these list bids (
            {option.listBids?.reason}); the bid desk applies ×
            {option.bidDesk?.factor} ({option.bidDesk?.reason})
          </span>
        ) : null}
        {deskOpen ? (
          // The desk is the existing FAAB v2 desk; it states its own fetch
          // failures.  Not wrapped in ResilientSection: importing it here
          // re-split webpack's shared chunk and pushed /trade over budget.
          <Suspense fallback={<SkeletonTable rows={3} columns={3} />}>
            <FaabRecommendation
              addPlayer={{ name: c.name }}
              dropPlayer={dropForDesk}
              leagueKey={leagueKey}
              ownerId={ownerId}
              selectedTeam={selectedTeam}
            />
          </Suspense>
        ) : (
          <Button size="sm" onClick={() => setDeskOpen(true)}>
            Price this {dropForDesk ? "add/drop pair" : "add"} in the bid desk
          </Button>
        )}
      </div>
    </div>
  );
}

function buildColumns() {
  return [
    {
      key: "name",
      header: "Player",
      accessor: (c) => c.name,
      render: (c) => (
        <span className={styles.playerCell}>
          <Badge tone="outline">{c.position || "?"}</Badge>
          <PlayerNameButton
            name={c.name}
            playerId={c.playerId}
            className={styles.playerName}
          />
          {c.age != null ? (
            <span className={styles.playerMeta}>{Math.round(c.age)}</span>
          ) : null}
        </span>
      ),
    },
    {
      key: "value",
      header: "Value",
      numeric: true,
      accessor: (c) => c.value?.rankDerivedValue ?? null,
      render: (c) =>
        fmtValue(c.value?.rankDerivedValue) ?? <Missing>Unpriced</Missing>,
    },
    {
      key: "confidence",
      header: "Conf.",
      headerInfo:
        "The canonical board's confidence in this value (five-axis bottleneck).",
      hideBelow: "sm",
      accessor: (c) => c.value?.confidenceBucket || "",
      render: (c) =>
        c.value?.confidenceBucket ? (
          <Badge tone={confidenceTone(c.value.confidenceBucket)}>
            {c.value.confidenceBucket}
          </Badge>
        ) : (
          <Missing>Unstated</Missing>
        ),
    },
    {
      key: "lineup",
      header: "Lineup",
      hideBelow: "md",
      accessor: (c) => lineupText(c.lineup).text,
    },
    {
      key: "plan",
      header: "Plan",
      hideBelow: "md",
      accessor: (c) => planStatusLabel(c.plan).label,
      render: (c) => {
        const s = planStatusLabel(c.plan);
        const rel = releaseText(c.plan?.release);
        return (
          <span>
            <Badge tone={s.tone}>{s.label}</Badge>
            {rel ? <span className={styles.playerMeta}> {rel}</span> : null}
          </span>
        );
      },
    },
    {
      key: "forced",
      header: "Forced drop",
      headerInfo:
        "If added alone, who the roster must release (cut ladder). Reported, never applied.",
      hideBelow: "lg",
      accessor: (c) => forcedDropText(c.capacity).text,
    },
    {
      key: "bid",
      header: "Bid",
      numeric: true,
      accessor: (c) => c.faab?.recommendedBid ?? null,
      render: (c) => recommendedBidText(c.faab),
    },
    {
      key: "expected",
      header: "Expected win",
      headerInfo:
        "The market's expected winning bid — an estimate, not your maximum offer.",
      hideBelow: "md",
      accessor: (c) => c.faab?.expectedWinningBid?.median ?? null,
      render: (c) => expectedWinText(c.faab).text,
    },
    {
      key: "max",
      header: "Max rational",
      headerInfo:
        "The most this team could rationally pay (bounded by its balance).",
      numeric: true,
      hideBelow: "sm",
      accessor: (c) => c.faab?.maxRationalBid?.value ?? null,
      render: (c) => maxRationalText(c.faab),
    },
  ];
}

const COLUMNS = buildColumns();

function NotAvailable() {
  return (
    <div
      className={`main-shell ${styles.page}`}
      data-testid="waiver-advisor-unavailable"
    >
      <EmptyState title="This page is not available." />
    </div>
  );
}

export default function WaiverAdvisorPage() {
  const { selectedLeague } = useLeague();
  const { selectedTeam } = useTeam();
  const [position, setPosition] = useState("ALL");
  const [expanded, setExpanded] = useState("");
  const leagueKey = selectedLeague?.key;
  const ownerId = selectedTeam?.ownerId ? String(selectedTeam.ownerId) : null;
  const { payload, failure, loading } = useWaiverAdvisor({
    leagueKey,
    ownerId,
    position,
  });
  // The gate latches on the first answer: "closed" (flag off / no route) shows
  // nothing but "not available"; "open" keeps the controls mounted across
  // team / position changes instead of flashing back to a skeleton.
  const [gate, setGate] = useState("unknown");
  useEffect(() => {
    if (failure?.kind === "disabled") setGate("closed");
    else if (payload || failure) setGate("open");
  }, [payload, failure]);

  if (gate === "closed" || failure?.kind === "disabled")
    return <NotAvailable />;
  // Until the first answer the gate is unknown: show nothing identifying.
  if (gate === "unknown") {
    return (
      <div className={`main-shell ${styles.page}`} aria-busy="true">
        <SkeletonTable rows={8} columns={5} />
      </div>
    );
  }

  const candidates = payload?.candidates || [];
  return (
    <div
      className={`main-shell ${styles.page} psi-editorial`}
      data-testid="waiver-advisor"
    >
      <PageHeader
        eyebrow="My Team"
        title="Waiver Advisor"
        description="Best available players for your team — value, roster fit, the drop it costs and what to bid. Advice only; nothing here submits a claim."
      />

      <Panel dense>
        <div className={styles.controls}>
          <TeamSwitcher variant="desktop" />
          <Field label="Position" id="advisor-pos">
            <Select
              id="advisor-pos"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            >
              {ADVISOR_POSITION_OPTIONS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      </Panel>

      {failure ? (
        failure.code === "team_required" ? (
          <EmptyState
            title="Pick your team"
            description="Every number here is roster-specific, so a team is never guessed."
          />
        ) : (
          <FailureState failure={failure} context="Waiver Advisor" />
        )
      ) : null}

      {loading && !payload ? <SkeletonTable rows={8} columns={5} /> : null}

      {payload ? (
        <>
          <TeamContext payload={payload} />
          {payload.faab?.bidMethodology !== "market_aware" ? (
            <Banner tone="warning" title="Ceiling-only bids">
              No rival model ran for this team, so expected winning bids and max
              rational bids are unavailable rather than estimated.
            </Banner>
          ) : null}
          <Panel
            flush
            title="Best available"
            subtitle={`${payload.census?.shown ?? 0} of ${payload.census?.matchingFilter ?? 0} on the canonical board order`}
          >
            <DataTable
              caption="Best available waiver players for the selected team"
              columns={COLUMNS}
              rows={candidates}
              rowKey={(c) => c.playerId || c.name}
              density="compact"
              presorted
              onRowClick={(c) =>
                setExpanded((k) =>
                  k === (c.playerId || c.name) ? "" : c.playerId || c.name,
                )
              }
              isRowExpanded={(c) => (c.playerId || c.name) === expanded}
              rowExpandLabel={(c) => `Advice detail for ${c.name}`}
              renderAfterRow={(c) =>
                (c.playerId || c.name) === expanded ? (
                  <tr>
                    <td colSpan={COLUMNS.length}>
                      <Detail
                        c={c}
                        payload={payload}
                        leagueKey={leagueKey}
                        ownerId={ownerId}
                        selectedTeam={selectedTeam}
                      />
                    </td>
                  </tr>
                ) : null
              }
              emptyState={
                <EmptyState
                  title="No available players"
                  description="Nothing on the wire at this position joined to the canonical board."
                />
              }
            />
          </Panel>
          <CollapsiblePanel title="How this is computed" defaultCollapsed>
            <ul className={styles.notes}>
              {(payload.methodologyDependencies || []).map((d) => (
                <li key={d.id} className={styles.note}>
                  {reasonText(d.id)}: {reasonText(d.state)}
                </li>
              ))}
              {(payload.notes || []).map((n) => (
                <li key={n} className={styles.note}>
                  {n}
                </li>
              ))}
            </ul>
          </CollapsiblePanel>
        </>
      ) : null}
    </div>
  );
}
