"use client";

import { useMemo, useState, useCallback, useEffect } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useApp } from "@/components/AppShell";
import { useTeam } from "@/components/useTeam";
import { isEligibleForAnalysis } from "@/lib/display-helpers";
import { rowChips } from "@/lib/rankings-helpers";
import { FINDER_ROW_LIMIT, CONFIDENCE_SPREAD_HIGH } from "@/lib/thresholds";
import {
  Banner,
  Button,
  DataTable,
  EmptyState,
  Input,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
  Tabs,
  tabPanelId,
} from "@/components/ds";
import {
  colConfidence,
  colGapDirection,
  colPos,
  colRank,
  colSignal,
} from "../edge/edge-columns";
import styles from "./finder.module.css";

// ── FINDER (Redesign R3) ─────────────────────────────────────────────
// The signal blotter: pick a workflow, get the players whose source
// signals match that opportunity shape. Sibling to /edge — same signal
// vocabulary, same column specs (imported, not re-declared), different
// question. /edge asks "where is the market wrong?"; /finder asks
// "show me every player of THIS shape."
//
// NOT an arbitrage calculator, despite the route name. Every workflow
// below filters and sorts the board that the backend already stamped
// (sourceRankSpread, confidenceBucket, isSingleSource, rookie); nothing
// here compares our value against a market value. This comment used to
// say "arbitrage blotter", and that one word is why backlog #6 recorded
// a client-side arbitrage implementation competing with
// ``src/trade/finder.py`` — there is no such implementation, and per
// CLAUDE.md's "no frontend ranking engine, period" rule there must not
// be one.
//
// The real arbitrage engine is ``src/trade/finder.py``, served at
// POST /api/trade/finder. It currently has no UI caller at all; see
// tests/trade/test_finder_engine_has_no_ui_caller.py.
//
// Everything is preserved verbatim: the five workflow presets and
// their filter/sort predicates, IDP league gating (workflows + pos
// filters + the stale-selection snap-back), the filter reset on
// workflow change, the row limit + expand, row chips, and the
// quarantined row treatment. The table gains sortable headers with
// aria-sort; the workflow strip becomes a real tablist.

const WORKFLOWS = [
  {
    key: "wr-gaps",
    label: "WR Gaps",
    description:
      "Wide receivers where ranking sources disagree most — potential buy-low or sell-high targets depending on which market you trust.",
    filter: (r) =>
      r.pos === "WR" &&
      (r.sourceRankSpread ?? 0) > 15 &&
      (r.rank ?? Infinity) <= 250 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
    defaultSort: { key: "spread", direction: "desc" },
    showSpread: true,
    showGap: true,
  },
  {
    key: "stable-idp",
    label: "Stable IDP",
    description:
      "IDP players with high confidence and tight multi-source agreement. Safest IDP targets for trades — both markets agree on value.",
    filter: (r) =>
      r.assetClass === "idp" &&
      r.confidenceBucket === "high" &&
      (r.sourceCount ?? 0) >= 2 &&
      !r.quarantined,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    defaultSort: { key: "rank", direction: "asc" },
    showSpread: true,
    showGap: false,
  },
  {
    key: "single-risk",
    label: "1-Source Risk",
    description:
      "Players valued from only one ranking source. Higher uncertainty — value could shift significantly if another source disagrees.",
    filter: (r) => r.isSingleSource && (r.rank ?? Infinity) <= 300,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    defaultSort: { key: "rank", direction: "asc" },
    showSpread: false,
    showGap: false,
  },
  {
    key: "rookie-spread",
    label: "Rookie Spread",
    description:
      "Rookies where ranking sources disagree — upside signal if one market sees value the other doesn't. Worth monitoring through camp.",
    filter: (r) =>
      r.rookie &&
      (r.sourceRankSpread ?? 0) > 10 &&
      (r.rank ?? Infinity) <= 400 &&
      !r.quarantined,
    sort: (a, b) => (b.sourceRankSpread ?? 0) - (a.sourceRankSpread ?? 0),
    defaultSort: { key: "spread", direction: "desc" },
    showSpread: true,
    showGap: true,
  },
  {
    key: "all",
    label: "All Players",
    description:
      "Browse the full ranked board with your own filters. Use position and confidence filters to narrow results.",
    filter: () => true,
    sort: (a, b) => (a.rank ?? Infinity) - (b.rank ?? Infinity),
    defaultSort: { key: "rank", direction: "asc" },
    showSpread: true,
    showGap: true,
  },
];

const POS_FILTERS = [
  { key: "all", label: "All positions" },
  { key: "offense", label: "Offense" },
  { key: "idp", label: "IDP" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

const CONF_FILTERS = [
  { key: "all", label: "Any confidence" },
  { key: "high", label: "High" },
  { key: "medium", label: "Medium" },
  { key: "low", label: "Low" },
];

function posMatches(row, filter) {
  if (filter === "all") return true;
  if (filter === "offense") return row.assetClass === "offense";
  if (filter === "idp") return row.assetClass === "idp";
  return row.pos === filter;
}

const ROW_LIMIT = FINDER_ROW_LIMIT;
const EM_DASH = "—";

/** Player cell — identity plus the meta the blotter reads at a glance
 *  (team · age) and the shared row chips. */
function colFinderPlayer(onPlayerClick) {
  return {
    key: "name",
    header: "Player",
    sortable: true,
    accessor: (r) => r.name || "",
    render: (r) => {
      const chips = rowChips(r);
      const meta = [r.team, r.age].filter(Boolean).join(" · ");
      return (
        <button
          type="button"
          className={styles.playerCell}
          onClick={() => onPlayerClick?.(r)}
          title={`Open ${r.name}`}
        >
          <span>{r.name}</span>
          {meta ? <span className={styles.playerMeta}>{meta}</span> : null}
          {chips.length > 0 && (
            <span className="rankings-chips">
              {chips.map((c) => (
                <span
                  key={c.label}
                  className={`badge ${c.css} rankings-chip`}
                  title={c.title}
                >
                  {c.label}
                </span>
              ))}
            </span>
          )}
        </button>
      );
    },
  };
}

function colFinderValue() {
  return {
    key: "value",
    header: "Value",
    numeric: true,
    sortable: true,
    accessor: (r) => Math.round(r.rankDerivedValue || r.values?.full || 0) || null,
    render: (r) => {
      const val = Math.round(r.rankDerivedValue || r.values?.full || 0);
      return val > 0 ? val.toLocaleString() : EM_DASH;
    },
  };
}

/** Spread with the wide-disagreement emphasis the pre-R3 table had. */
function colFinderSpread() {
  return {
    key: "spread",
    header: "Spread",
    numeric: true,
    sortable: true,
    headerTitle: "How far apart the sources ranked this player (ordinal spread)",
    accessor: (r) => r.sourceRankSpread ?? null,
    render: (r) => {
      if (r.sourceRankSpread == null) return EM_DASH;
      const wide = (r.sourceRankSpread ?? 0) > CONFIDENCE_SPREAD_HIGH;
      return (
        <span className={wide ? styles.spreadWide : undefined}>
          ±{r.sourceRankSpread}
        </span>
      );
    },
  };
}

export default function FinderPage() {
  const { loading, error, rows } = useDynastyData();
  const { openPlayerPopup } = useApp();
  // League gating: hide IDP workflows + filter tabs on non-IDP
  // leagues.  ``idpEnabled`` comes from the registry via useTeam.
  const { idpEnabled } = useTeam();

  const visibleWorkflows = useMemo(
    () => (idpEnabled ? WORKFLOWS : WORKFLOWS.filter((w) => w.key !== "stable-idp")),
    [idpEnabled],
  );
  const visiblePosFilters = useMemo(() => {
    if (idpEnabled) return POS_FILTERS;
    const IDP_KEYS = new Set(["idp", "DL", "LB", "DB"]);
    return POS_FILTERS.filter((f) => !IDP_KEYS.has(f.key));
  }, [idpEnabled]);

  const [activeWorkflow, setActiveWorkflow] = useState("wr-gaps");
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [confFilter, setConfFilter] = useState("all");
  const [expanded, setExpanded] = useState(false);

  // Snap away from stale IDP selections when the user switches to a
  // non-IDP league mid-session.
  useEffect(() => {
    if (idpEnabled) return;
    if (activeWorkflow === "stable-idp") setActiveWorkflow("wr-gaps");
    if (posFilter === "idp" || posFilter === "DL" || posFilter === "LB" || posFilter === "DB") {
      setPosFilter("all");
    }
  }, [idpEnabled, activeWorkflow, posFilter]);

  const handleWorkflowChange = useCallback((key) => {
    setActiveWorkflow(key);
    setQuery("");
    setPosFilter("all");
    setConfFilter("all");
    setExpanded(false);
  }, []);

  // Eligible: non-pick, ranked players.
  const eligible = useMemo(() => rows.filter(isEligibleForAnalysis), [rows]);

  const workflow = WORKFLOWS.find((w) => w.key === activeWorkflow) || WORKFLOWS[0];

  const results = useMemo(() => {
    let list = eligible.filter(workflow.filter);
    if (posFilter !== "all") list = list.filter((r) => posMatches(r, posFilter));
    if (confFilter !== "all") {
      list = list.filter((r) => {
        if (confFilter === "low") {
          return r.confidenceBucket === "low" || r.confidenceBucket === "none";
        }
        return r.confidenceBucket === confFilter;
      });
    }
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }
    return [...list].sort(workflow.sort);
  }, [eligible, workflow, posFilter, confFilter, query]);

  const displayRows = expanded ? results : results.slice(0, ROW_LIMIT);
  const hasMore = results.length > ROW_LIMIT && !expanded;

  // Columns follow the workflow's own disclosure flags — the preset
  // decides which signals are meaningful for its opportunity shape.
  const columns = useMemo(() => {
    const cols = [
      colRank(),
      colFinderPlayer(openPlayerPopup),
      colPos(),
      colFinderValue(),
    ];
    if (workflow.showSpread) cols.push(colFinderSpread());
    if (workflow.showGap) cols.push(colGapDirection());
    cols.push(colConfidence());
    cols.push({ ...colSignal(), hideBelow: "md" });
    return cols;
  }, [workflow, openPlayerPopup]);

  const workflowTabs = useMemo(
    () => visibleWorkflows.map((w) => ({ id: w.key, label: w.label })),
    [visibleWorkflows],
  );

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Market"
        title="Player Screener"
        description="Surface players by the shape of their source signals. Each workflow is a standing query over the board; layer position and confidence on top to narrow it."
      />

      {!!error && (
        <Banner tone="negative" title="Couldn't load player data">
          {String(error)}
        </Banner>
      )}

      {loading && (
        <Panel title="Loading board">
          <SkeletonTable rows={10} />
        </Panel>
      )}

      {!loading && !error && rows.length === 0 && (
        <Panel>
          <EmptyState
            title="No player data available"
            description="The backend may still be initializing — this page fills in as soon as the contract lands."
          />
        </Panel>
      )}

      {!loading && !error && eligible.length > 0 && (
        <Panel flush>
          <div className={styles.workflowStrip}>
            <Tabs
              tabs={workflowTabs}
              active={activeWorkflow}
              onChange={handleWorkflowChange}
              label="Discovery workflow"
              idPrefix="finder-workflow"
            />
          </div>
          <p className={styles.workflowNote}>{workflow.description}</p>

          <div className={`finder-filters ${styles.filters}`}>
            <Input
              type="search"
              className={styles.filtersSearch}
              placeholder="Search player…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search players by name"
            />
            <Select
              className={styles.filtersSelect}
              value={posFilter}
              onChange={(e) => setPosFilter(e.target.value)}
              aria-label="Filter by position"
            >
              {visiblePosFilters.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
            <Select
              className={styles.filtersSelect}
              value={confFilter}
              onChange={(e) => setConfFilter(e.target.value)}
              aria-label="Filter by confidence"
            >
              {CONF_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>
                  {f.label}
                </option>
              ))}
            </Select>
            <p className={styles.resultCount}>
              {results.length.toLocaleString()} player
              {results.length !== 1 ? "s" : ""} match
              {posFilter !== "all" ? ` · ${posFilter}` : ""}
              {confFilter !== "all" ? ` · ${confFilter} conf` : ""}
            </p>
          </div>

          <div
            id={tabPanelId("finder-workflow", activeWorkflow)}
            role="tabpanel"
            aria-label={`${workflow.label} results`}
            tabIndex={-1}
          >
            {/* Keyed by workflow so switching presets resets the sort
                along with every other filter (handleWorkflowChange
                clears the rest). defaultSort mirrors the workflow's own
                comparator, so the initial order is identical to the
                pre-R3 table while headers stay genuinely sortable. */}
            <DataTable
              key={activeWorkflow}
              columns={columns}
              rows={displayRows}
              rowKey={(r) => r.name}
              caption={`${workflow.label} — ${results.length} matching players`}
              density="compact"
              defaultSort={workflow.defaultSort}
              rowClassName={(r) => (r.quarantined ? "rankings-row-quarantined" : "")}
              emptyState={
                <EmptyState
                  title="No players match"
                  description="Try adjusting your filters or switching to a different workflow."
                />
              }
            />
          </div>

          {hasMore && (
            <div className={styles.filters}>
              <div className={styles.tableFooter}>
                <p className={styles.resultCount}>
                  Showing the top {ROW_LIMIT.toLocaleString()} by this workflow&apos;s
                  ranking.
                </p>
                <Button variant="secondary" onClick={() => setExpanded(true)}>
                  Show all {results.length.toLocaleString()} results
                </Button>
              </div>
            </div>
          )}
        </Panel>
      )}
    </div>
  );
}
