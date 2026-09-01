"use client";

/**
 * BestAvailableIdps — the "Best available IDPs" waivers card.
 *
 * A narrow, two-source-only decision lens, deliberately separate from
 * the rest of the Waivers page's canonical-board-driven panels: it
 * combines EXACTLY IDP Trade Calculator + The IDP Show, 50/50, for
 * unrostered IDP players in the selected league.
 *
 * Display-only. All scoring happens server-side
 * (``src/trade/waiver_idp_best_available.py``) — this component reshapes
 * and filters the already-computed, already-sorted payload, the same
 * materializer posture as ``buildRows`` / ``lib/bdvm.js``.
 *
 * ``payload.candidates`` is the FULL cross-position-scored list, not a
 * pre-sliced top 20 — filtering by position here and THEN slicing is
 * what finds a legitimate top-position player who sits outside the
 * naive top-20-overall cut (see the backend test
 * ``test_position_filter_must_apply_to_full_list_not_pre_sliced_top_20``).
 */
import { useMemo, useState } from "react";
import {
  Badge,
  Banner,
  DataTable,
  EmptyState,
  FailureState,
  Field,
  InfoTip,
  Panel,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { useBestAvailableIdp } from "@/components/useBestAvailableIdp";
import styles from "@/app/waivers/waivers.module.css";

const TOP_N = 20;

const POSITION_FILTER_OPTIONS = [
  { value: "ALL", label: "All IDP" },
  { value: "DL", label: "DL" },
  { value: "LB", label: "LB" },
  { value: "DB", label: "DB" },
];

function formatFreshness(entry) {
  if (!entry || typeof entry !== "object") return "unknown";
  const hours = Number(entry.ageHours);
  const stale = entry.staleness;
  const age = Number.isFinite(hours) ? `${hours < 1 ? "<1" : Math.round(hours)}h ago` : "unknown age";
  if (stale === "stale") return `${age} (stale)`;
  if (stale === "missing") return "no data";
  return age;
}

function SourceFormulaInfo({ sourceFreshness }) {
  return (
    <InfoTip label="the combined IDP score">
      <p>
        <strong>Combined IDP Score</strong> = 50% IDP Trade Calculator normalized
        ranking + 50% The IDP Show normalized ranking. Each source is ranked
        against every IDP player it covers, then converted to a 0-100 scale —
        neither source&apos;s raw scale can dominate the other.
      </p>
      <p>
        IDP Trade Calculator updated: {formatFreshness(sourceFreshness?.idpTradeCalc)}
        <br />
        The IDP Show updated: {formatFreshness(sourceFreshness?.idpShowCombined)}
      </p>
    </InfoTip>
  );
}

const MISSING_SOURCE_LABEL = {
  idpTradeCalc: "IDP Trade Calculator",
  idpShowCombined: "The IDP Show",
};

export default function BestAvailableIdps({ leagueKey, idpEnabled }) {
  const [position, setPosition] = useState("ALL");
  const { payload, loading } = useBestAvailableIdp({
    leagueKey,
    enabled: Boolean(idpEnabled),
  });

  const visibleCandidates = useMemo(() => {
    const all = Array.isArray(payload?.candidates) ? payload.candidates : [];
    const filtered = position === "ALL" ? all : all.filter((c) => c.position === position);
    return filtered.slice(0, TOP_N);
  }, [payload, position]);

  if (!idpEnabled) return null;

  const columns = [
    {
      key: "rank",
      header: "#",
      numeric: true,
      accessor: (_row, i) => i + 1,
      render: (_row, i) => i + 1,
    },
    {
      key: "name",
      header: "Player",
      render: (row) => (
        <div className={styles.playerCell}>
          <span className={styles.playerName}>{row.name}</span>
          <span className={styles.playerMeta}>
            {row.position}
            {row.team ? ` · ${row.team}` : ""}
            {row.tier === "B" ? (
              <Badge tone="neutral" className={styles.tierBadge}>
                1 of 2 sources
              </Badge>
            ) : null}
          </span>
        </div>
      ),
    },
    {
      key: "combinedScore",
      header: "Combined",
      numeric: true,
      accessor: (row) => row.combinedScore,
      render: (row) => row.combinedScore.toFixed(1),
    },
    {
      key: "idptc",
      header: "IDPTC",
      numeric: true,
      hideBelow: "sm",
      headerInfo: "IDP Trade Calculator rank (raw value in parentheses)",
      accessor: (row) => row.idpTradeCalc?.rank ?? null,
      render: (row) =>
        row.idpTradeCalc?.rank != null ? (
          <span title={`Raw value: ${row.idpTradeCalc.rawValue}`}>
            #{row.idpTradeCalc.rank}
          </span>
        ) : (
          <span className={styles.faabAbsent}>—</span>
        ),
    },
    {
      key: "idpshow",
      header: "IDP Show",
      numeric: true,
      hideBelow: "sm",
      headerInfo: "The IDP Show rank",
      accessor: (row) => row.idpShowCombined?.rank ?? null,
      render: (row) =>
        row.idpShowCombined?.rank != null ? (
          `#${row.idpShowCombined.rank}`
        ) : (
          <span className={styles.faabAbsent}>—</span>
        ),
    },
    {
      key: "ownership",
      header: "Ownership",
      hideBelow: "md",
      render: () => <Badge tone="positive">Available</Badge>,
    },
  ];

  function renderBody() {
    if (payload?.ownershipResolved === false) {
      return (
        <FailureState
          variant="block"
          failure={{
            kind: "degraded",
            message:
              "Availability unavailable — your league's roster data hasn't loaded yet, so free-agent status can't be determined truthfully.",
          }}
        />
      );
    }
    if (!payload && !loading) {
      return (
        <FailureState
          variant="block"
          failure={{
            kind: "unavailable",
            message: "Couldn't reach the IDP Trade Calculator / The IDP Show comparison right now.",
          }}
        />
      );
    }
    if (loading && !payload) {
      return <SkeletonTable rows={8} columns={6} />;
    }

    const missing = payload?.degraded?.missingSources || [];
    const totalAvailable = Array.isArray(payload?.candidates) ? payload.candidates.length : 0;
    const filteredTotal =
      position === "ALL"
        ? totalAvailable
        : (payload?.candidates || []).filter((c) => c.position === position).length;

    return (
      <>
        {missing.length > 0 ? (
          <Banner tone="warning" title="A source is missing">
            {missing.map((key) => MISSING_SOURCE_LABEL[key] || key).join(" and ")} data is
            currently unavailable. Scores below reflect only the source(s) present — never a
            silent single-source "combined" number.
          </Banner>
        ) : null}
        {filteredTotal < TOP_N ? (
          <p className={styles.controlsGainLabel}>
            Showing all {filteredTotal} available IDP free agent{filteredTotal === 1 ? "" : "s"}
            {position !== "ALL" ? ` at ${position}` : ""}.
          </p>
        ) : null}
        <DataTable
          caption="Best available IDP free agents by combined IDP Trade Calculator and The IDP Show score"
          columns={columns}
          rows={visibleCandidates}
          rowKey={(row) => row.name}
          presorted
          density="compact"
          emptyState={
            <EmptyState
              title="No available IDP free agents"
              description="Nobody at this position qualifies right now."
            />
          }
        />
      </>
    );
  }

  return (
    <Panel
      flush
      title="Best available IDPs"
      subtitle="IDP Trade Calculator + The IDP Show"
      actions={
        <div className={styles.controlsInline}>
          <SourceFormulaInfo sourceFreshness={payload?.sourceFreshness} />
          <Field label="Position" id="idp-best-available-pos">
            <Select
              id="idp-best-available-pos"
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            >
              {POSITION_FILTER_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
      }
    >
      {renderBody()}
    </Panel>
  );
}
