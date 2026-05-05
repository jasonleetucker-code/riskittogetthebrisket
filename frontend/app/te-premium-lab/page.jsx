"use client";

// ── TE Premium Lab — research / sandbox page ──────────────────────────
//
// Helps decide how to adjust tight end values BEFORE any change is
// applied to live values.  Specifically: "if we drop the TE reception
// premium + TE first-down premium but require teams to start two
// tight ends, how should TE values shift?".
//
// Read-only sandbox.  Every fetch on this page goes through the
// ``/api/te-premium/*`` proxy → FastAPI handlers in ``server.py``,
// which call ``src/research/te_premium.py``.  None of those code
// paths mutate ``latest_contract_data`` or any persisted live value.
// The page surfaces a "Research only" banner so the operator never
// confuses these projections with applied changes.

import { useCallback, useEffect, useMemo, useState } from "react";
import PageHeader from "@/components/ui/PageHeader";
import SubNav from "@/components/ui/SubNav";
import EmptyState from "@/components/ui/EmptyState";
import LoadingState from "@/components/ui/LoadingState";
import ErrorState from "@/components/ui/ErrorState";

const TABS = [
  { key: "summary", label: "Summary" },
  { key: "sources", label: "External Sources" },
  { key: "scenarios", label: "League Scenarios" },
  { key: "recommendations", label: "Recommendations" },
];

const DEFAULT_SCENARIO = {
  remove_te_reception_bonus: true,
  remove_te_first_down_bonus: true,
  use_two_te_starters: true,
  include_rookies: true,
};

// ── Small format helpers ─────────────────────────────────────────────

function fmtPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function fmtSignedPct(value, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${(value * 100).toFixed(digits)}%`;
}

function fmtNum(value, digits = 0) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return Number(value).toFixed(digits);
}

function fmtSigned(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${Number(value).toFixed(digits)}`;
}

// ── CSV export ───────────────────────────────────────────────────────

function exportRecommendationsCsv(rows, filename = "te-premium-sandbox.csv") {
  if (!Array.isArray(rows) || rows.length === 0) return;
  const headers = [
    "player_id",
    "display_name",
    "tier",
    "age",
    "current_value",
    "market_boost_pct",
    "scoring_swing_ppg",
    "scarcity_value_delta",
    "recommended_adjustment_pct",
    "recommended_value",
    "confidence",
    "notes",
  ];
  const escape = (v) => {
    if (v === null || v === undefined) return "";
    const s = Array.isArray(v) ? v.join(" | ") : String(v);
    if (/[",\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
    return s;
  };
  const lines = [headers.join(",")];
  for (const r of rows) {
    lines.push(headers.map((h) => escape(r[h])).join(","));
  }
  const blob = new Blob([lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Main component ──────────────────────────────────────────────────

export default function TEPremiumLabPage() {
  const [tab, setTab] = useState("summary");
  const [scenario, setScenario] = useState(DEFAULT_SCENARIO);
  const [overview, setOverview] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [tableSort, setTableSort] = useState({
    column: "te_pool_rank",
    direction: "asc",
  });
  const [tableFilter, setTableFilter] = useState("");

  // Fetch overview + initial analysis on mount.  Sequential (not
  // parallel) because the analysis is a superset of overview signal —
  // if overview 503s the analysis would too, and we'd rather show one
  // clear error than two competing ones.
  const loadInitial = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [ovRes, anRes] = await Promise.all([
        fetch("/api/te-premium/overview", { cache: "no-store" }),
        fetch("/api/te-premium/run-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(scenario),
          cache: "no-store",
        }),
      ]);
      if (!ovRes.ok) {
        const body = await ovRes.json().catch(() => ({}));
        throw new Error(body?.message || body?.error || `Overview ${ovRes.status}`);
      }
      if (!anRes.ok) {
        const body = await anRes.json().catch(() => ({}));
        throw new Error(body?.message || body?.error || `Analysis ${anRes.status}`);
      }
      setOverview(await ovRes.json());
      setAnalysis(await anRes.json());
    } catch (err) {
      setError(err?.message || "Failed to load TE Premium Lab.");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    loadInitial();
  }, [loadInitial]);

  const runAnalysis = useCallback(
    async (nextScenario) => {
      setRunning(true);
      setError("");
      try {
        const res = await fetch("/api/te-premium/run-analysis", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(nextScenario || scenario),
          cache: "no-store",
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body?.message || body?.error || `Analysis ${res.status}`);
        }
        setAnalysis(await res.json());
      } catch (err) {
        setError(err?.message || "Failed to run analysis.");
      } finally {
        setRunning(false);
      }
    },
    [scenario],
  );

  const toggleScenario = useCallback(
    (key) => {
      const next = { ...scenario, [key]: !scenario[key] };
      setScenario(next);
    },
    [scenario],
  );

  // ── Player table — joined view ─────────────────────────────────
  const playerTableRows = useMemo(() => {
    if (!analysis) return [];
    const players = analysis.players || [];
    const boostById = new Map();
    for (const b of analysis.external_boost || []) {
      boostById.set(b.player_id, b);
    }
    const scoringById = new Map();
    for (const s of analysis.scoring_effect || []) {
      scoringById.set(s.player_id, s);
    }
    const scarcityById = new Map();
    for (const s of analysis.scarcity_effect || []) {
      scarcityById.set(s.player_id, s);
    }
    const recById = new Map();
    for (const r of analysis.recommendations || []) {
      recById.set(r.player_id, r);
    }
    return players.map((p) => {
      const b = boostById.get(p.player_id) || {};
      const s = scoringById.get(p.player_id) || {};
      const sc = scarcityById.get(p.player_id) || {};
      const r = recById.get(p.player_id) || {};
      // Surface the per-row "TE first-down bonus is estimated"
      // flag (set by the backend when the contract lacks
      // rule_contributions_detail.bonus_fd_te) as an inline note so
      // the operator sees per-player precision, not just the global
      // warning banner.
      const notes = [...(r.notes || [])];
      if (s.te_fd_estimated) {
        notes.push("TE 1D bonus estimated from first_downs aggregate");
      }
      return {
        player_id: p.player_id,
        display_name: p.display_name,
        team: p.team,
        age: p.age,
        te_pool_rank: p.te_pool_rank,
        position_rank: p.position_rank,
        current_value: p.current_value,
        ktc_normal_value: p.ktc_normal_value,
        ktc_premium_value: p.ktc_premium_value,
        market_boost_pct: b.boost_pct ?? null,
        market_reliable: b.reliable ?? null,
        scoring_swing_ppg: s.scoring_swing_ppg ?? null,
        te_fd_estimated: s.te_fd_estimated ?? false,
        ppg_baseline: p.ppg_baseline,
        ppg_league: p.ppg_league,
        rep_one_te: sc.replacement_one_te_ppg ?? null,
        rep_two_te: sc.replacement_two_te_ppg ?? null,
        vor_one_te: sc.vor_one_te ?? null,
        vor_two_te: sc.vor_two_te ?? null,
        vor_delta: sc.vor_delta ?? null,
        recommended_adjustment_pct: r.recommended_adjustment_pct ?? null,
        recommended_value: r.recommended_value ?? null,
        confidence: r.confidence ?? null,
        tier: r.tier ?? p.tier?.tier_label ?? "—",
        notes,
      };
    });
  }, [analysis]);

  const sortedFilteredRows = useMemo(() => {
    let rows = playerTableRows;
    if (tableFilter.trim()) {
      const q = tableFilter.toLowerCase();
      rows = rows.filter((r) => (r.display_name || "").toLowerCase().includes(q));
    }
    const { column, direction } = tableSort;
    const dir = direction === "desc" ? -1 : 1;
    return [...rows].sort((a, b) => {
      const va = a[column];
      const vb = b[column];
      if (va === null || va === undefined) return 1;
      if (vb === null || vb === undefined) return -1;
      if (typeof va === "number" && typeof vb === "number") {
        return (va - vb) * dir;
      }
      return String(va).localeCompare(String(vb)) * dir;
    });
  }, [playerTableRows, tableSort, tableFilter]);

  const handleSort = useCallback(
    (column) => {
      setTableSort((prev) => ({
        column,
        direction: prev.column === column && prev.direction === "asc" ? "desc" : "asc",
      }));
    },
    [],
  );

  // ── Render ─────────────────────────────────────────────────────
  if (loading && !analysis) {
    return (
      <div className="page-container">
        <PageHeader
          title="Tight End Premium Lab"
          subtitle="Research-only sandbox — does not affect live player values."
        />
        <LoadingState message="Loading TE Premium sandbox…" />
      </div>
    );
  }

  if (error && !analysis) {
    return (
      <div className="page-container">
        <PageHeader
          title="Tight End Premium Lab"
          subtitle="Research-only sandbox — does not affect live player values."
        />
        <ErrorState message={error} retry={loadInitial} />
      </div>
    );
  }

  const summary = analysis?.summary || {};
  const tierSummary = analysis?.tier_summary || [];
  const scarcity = analysis?.scarcity_summary || {};
  const warnings = (analysis?.warnings || []).concat(overview?.warnings || []);
  const sources = overview?.sources || [];

  return (
    <div className="page-container te-premium-lab">
      <PageHeader
        title="Tight End Premium Lab"
        subtitle="Compare external TE Premium markets against your league's scoring + lineup pressure. Sandbox only — never applied to live values."
        actions={
          <button
            type="button"
            className="button"
            onClick={() => exportRecommendationsCsv(analysis?.recommendations, "te-premium-sandbox.csv")}
            disabled={!analysis?.recommendations?.length}
            title="Download per-player recommendations as CSV"
          >
            Export CSV
          </button>
        }
      />

      <div
        className="warning-banner"
        role="status"
        style={{
          background: "var(--warning-bg, #3a2a14)",
          color: "var(--warning-fg, #ffcb6b)",
          border: "1px solid var(--warning-border, #604322)",
          borderRadius: 8,
          padding: "10px 14px",
          margin: "12px 0",
          fontSize: 13,
          fontWeight: 500,
        }}
      >
        <strong>Research only.</strong> Outputs from this page are not
        applied to live player values. Use this view to plan adjustments;
        a separate manually-approved promotion path would be required to
        push any change live.
      </div>

      {warnings.length > 0 && (
        <ul className="warning-list muted" style={{ fontSize: 12, marginBottom: 8 }}>
          {warnings.map((w, idx) => (
            <li key={idx}>⚠ {w}</li>
          ))}
        </ul>
      )}

      <ScenarioControls
        scenario={scenario}
        onToggle={toggleScenario}
        onRun={runAnalysis}
        running={running}
      />

      <SubNav items={TABS} active={tab} onChange={setTab} />

      {tab === "summary" && (
        <SummaryTab
          summary={summary}
          scarcity={scarcity}
          sources={sources}
          tierSummary={tierSummary}
          lineup={summary.lineup}
        />
      )}

      {tab === "sources" && (
        <SourcesTab
          sources={sources}
          boostRows={analysis?.external_boost || []}
          marketAvailable={
            analysis?.external_boards?.ktc_premium_available &&
            analysis?.external_boards?.ktc_normal_available
          }
        />
      )}

      {tab === "scenarios" && (
        <ScenariosTab
          summary={summary}
          scarcity={scarcity}
          scoringRows={analysis?.scoring_effect || []}
          scarcityRows={analysis?.scarcity_effect || []}
          tierSummary={tierSummary}
        />
      )}

      {tab === "recommendations" && (
        <RecommendationsTab
          rows={sortedFilteredRows}
          onSort={handleSort}
          sort={tableSort}
          filter={tableFilter}
          onFilter={setTableFilter}
          tierSummary={tierSummary}
        />
      )}
    </div>
  );
}

// ── Scenario controls ───────────────────────────────────────────────

function ScenarioControls({ scenario, onToggle, onRun, running }) {
  return (
    <div
      className="controls-panel"
      style={{
        display: "flex",
        flexWrap: "wrap",
        gap: 10,
        alignItems: "center",
        background: "var(--card-bg, rgba(255,255,255,0.04))",
        border: "1px solid var(--border, rgba(255,255,255,0.1))",
        borderRadius: 8,
        padding: 12,
        margin: "12px 0",
      }}
    >
      <strong style={{ marginRight: 8 }}>Scenario:</strong>
      <ScenarioToggle
        label="Remove TE reception bonus"
        checked={!!scenario.remove_te_reception_bonus}
        onChange={() => onToggle("remove_te_reception_bonus")}
      />
      <ScenarioToggle
        label="Remove TE 1D bonus"
        checked={!!scenario.remove_te_first_down_bonus}
        onChange={() => onToggle("remove_te_first_down_bonus")}
      />
      <ScenarioToggle
        label="Start 2 TEs"
        checked={!!scenario.use_two_te_starters}
        onChange={() => onToggle("use_two_te_starters")}
      />
      <ScenarioToggle
        label="Include rookies"
        checked={!!scenario.include_rookies}
        onChange={() => onToggle("include_rookies")}
      />
      <button
        type="button"
        className="button"
        onClick={() => onRun()}
        disabled={running}
        style={{ marginLeft: "auto" }}
      >
        {running ? "Running…" : "Run Sandbox Analysis"}
      </button>
    </div>
  );
}

function ScenarioToggle({ label, checked, onChange }) {
  return (
    <label
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        cursor: "pointer",
        fontSize: 13,
        userSelect: "none",
      }}
    >
      <input type="checkbox" checked={checked} onChange={onChange} />
      <span>{label}</span>
    </label>
  );
}

// ── Summary tab ─────────────────────────────────────────────────────

function SummaryTab({ summary, scarcity, sources, tierSummary, lineup }) {
  const cards = [
    {
      label: "Avg external TE Premium boost",
      value: fmtSignedPct(summary.avg_market_boost_pct),
      hint: "KTC normal vs KTC TE+ board",
    },
    {
      label: "Avg internal scoring penalty",
      value: `${fmtSigned(summary.avg_internal_scoring_swing_ppg, 2)} PPG`,
      hint: "PPG lost when removing the TEP scoring rules",
    },
    {
      label: "Avg scarcity boost (2-TE start)",
      value: `${fmtSigned(summary.avg_scarcity_vor_delta_points, 1)} pts`,
      hint: `Replacement: ${fmtNum(scarcity.replacement_one_te_ppg, 2)} → ${fmtNum(scarcity.replacement_two_te_ppg, 2)} PPG`,
    },
    {
      label: "Net recommended adjustment",
      value: fmtSignedPct(summary.avg_recommended_adjustment_pct, 1),
      hint: "Average across evaluated TEs (clipped ±25%)",
    },
    {
      label: "Confidence",
      value: fmtPct(summary.avg_confidence, 0),
      hint: "Geometric mean of market + scoring + scarcity confidences",
    },
  ];

  return (
    <div className="summary-tab">
      <div
        className="summary-cards"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: 10,
          margin: "12px 0",
        }}
      >
        {cards.map((c) => (
          <div
            key={c.label}
            style={{
              background: "var(--card-bg, rgba(255,255,255,0.04))",
              border: "1px solid var(--border, rgba(255,255,255,0.1))",
              borderRadius: 8,
              padding: 12,
            }}
          >
            <div className="muted" style={{ fontSize: 11 }}>{c.label}</div>
            <div style={{ fontSize: 22, fontWeight: 700, marginTop: 4 }}>{c.value}</div>
            {c.hint && <div className="muted" style={{ fontSize: 11, marginTop: 4 }}>{c.hint}</div>}
          </div>
        ))}
      </div>

      <h3>League context</h3>
      <p className="muted" style={{ fontSize: 13 }}>
        {lineup ? (
          <>
            Team count: <strong>{lineup.team_count}</strong> · TE starters
            today: <strong>{lineup.te_starters_one}</strong> (incl. flex
            contribution) · TE starters under "start 2 TEs":{" "}
            <strong>{lineup.te_starters_two}</strong>
            {lineup.two_te_is_noop && (
              <>
                {" "}
                <em>(no-op — league already starts {lineup.direct_te_per_team_current} TEs/team)</em>
              </>
            )}
            .
          </>
        ) : (
          "League settings unavailable."
        )}
      </p>

      <h3 style={{ marginTop: 18 }}>Tier breakdown</h3>
      <TierTable tierSummary={tierSummary} />

      <h3 style={{ marginTop: 18 }}>Source availability</h3>
      <ul style={{ fontSize: 13, lineHeight: 1.6, paddingLeft: 18 }}>
        {sources.map((s) => (
          <li key={s.key}>
            <strong>{s.label}</strong>{" "}
            <span className="muted">
              [normal: {s.supports_normal ? "yes" : "no"} · TE+: {s.supports_te_premium ? "yes" : "no"} · TE++: {s.supports_te_plus_plus ? "yes" : "no"}]
            </span>
            {!s.available && <span className="muted"> — unavailable</span>}
            <div className="muted" style={{ fontSize: 11 }}>{s.note}</div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TierTable({ tierSummary }) {
  if (!tierSummary || tierSummary.length === 0) {
    return <EmptyState title="No tier data yet" message="Run the analysis to populate tier rollups." />;
  }
  return (
    <div className="table-wrap" style={{ overflowX: "auto" }}>
      <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
        <thead>
          <tr>
            <th>Tier</th>
            <th style={{ textAlign: "right" }}>n</th>
            <th style={{ textAlign: "right" }}>Avg current value</th>
            <th style={{ textAlign: "right" }}>Avg market boost</th>
            <th style={{ textAlign: "right" }}>Avg scoring swing</th>
            <th style={{ textAlign: "right" }}>Avg scarcity Δ</th>
            <th style={{ textAlign: "right" }}>Avg recommended</th>
            <th style={{ textAlign: "right" }}>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {tierSummary.map((t) => (
            <tr key={t.tier_key}>
              <td>{t.tier_label}</td>
              <td style={{ textAlign: "right" }}>{t.player_count}</td>
              <td style={{ textAlign: "right" }}>{fmtNum(t.avg_current_value)}</td>
              <td style={{ textAlign: "right" }}>{fmtSignedPct(t.avg_market_boost_pct)}</td>
              <td style={{ textAlign: "right" }}>{fmtSigned(t.avg_scoring_swing_ppg, 2)}</td>
              <td style={{ textAlign: "right" }}>{fmtSigned(t.avg_scarcity_vor_delta, 1)}</td>
              <td style={{ textAlign: "right" }}>{fmtSignedPct(t.avg_recommended_adjustment_pct)}</td>
              <td style={{ textAlign: "right" }}>{fmtPct(t.avg_confidence, 0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Sources tab ─────────────────────────────────────────────────────

function SourcesTab({ sources, boostRows, marketAvailable }) {
  const reliable = (boostRows || []).filter((b) => b.reliable);
  const unreliable = (boostRows || []).filter((b) => !b.reliable);
  return (
    <div className="sources-tab">
      <p className="muted" style={{ fontSize: 13 }}>
        For every external source that exposes both a normal and a TE-Premium
        board, we compute per-player percentage boost. Today only KTC ships
        both boards from the same scrape; other sources show as unavailable
        and would need a CSV upload or scraper update.
      </p>

      {!marketAvailable && (
        <div
          style={{
            background: "var(--warning-bg, #3a2a14)",
            border: "1px solid var(--warning-border, #604322)",
            color: "var(--warning-fg, #ffcb6b)",
            padding: 10,
            borderRadius: 6,
            margin: "8px 0",
            fontSize: 13,
          }}
        >
          KTC TE-Premium board not loaded. Boost rows shown below are empty;
          recommendations fall back to tier-default heuristics until a fresh
          scrape lands.
        </div>
      )}

      <h3>KTC normal vs KTC TE+ — reliable rows</h3>
      <div className="table-wrap" style={{ overflowX: "auto" }}>
        <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
          <thead>
            <tr>
              <th>Player</th>
              <th style={{ textAlign: "right" }}>Normal value</th>
              <th style={{ textAlign: "right" }}>Normal rank</th>
              <th style={{ textAlign: "right" }}>Premium value</th>
              <th style={{ textAlign: "right" }}>Premium rank</th>
              <th style={{ textAlign: "right" }}>Boost</th>
              <th style={{ textAlign: "right" }}>Δ rank</th>
              <th style={{ textAlign: "right" }}>log ratio</th>
            </tr>
          </thead>
          <tbody>
            {reliable.length === 0 ? (
              <tr>
                <td colSpan={8} className="muted" style={{ padding: 8 }}>
                  No reliable comparisons available.
                </td>
              </tr>
            ) : (
              reliable.map((b) => (
                <tr key={`${b.source}-${b.player_id}`}>
                  <td>{b.display_name}</td>
                  <td style={{ textAlign: "right" }}>{fmtNum(b.normal_value)}</td>
                  <td style={{ textAlign: "right" }}>{fmtNum(b.normal_rank)}</td>
                  <td style={{ textAlign: "right" }}>{fmtNum(b.premium_value)}</td>
                  <td style={{ textAlign: "right" }}>{fmtNum(b.premium_rank)}</td>
                  <td style={{ textAlign: "right" }}>{fmtSignedPct(b.boost_pct)}</td>
                  <td style={{ textAlign: "right" }}>{fmtSigned(b.rank_change, 0)}</td>
                  <td style={{ textAlign: "right" }}>{fmtNum(b.log_ratio, 3)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {unreliable.length > 0 && (
        <>
          <h3 style={{ marginTop: 18 }}>Flagged unreliable</h3>
          <ul className="muted" style={{ fontSize: 12 }}>
            {unreliable.map((b) => (
              <li key={`u-${b.player_id}`}>
                <strong>{b.display_name}</strong> — {b.note || "missing data"}
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

// ── Scenarios tab ───────────────────────────────────────────────────

function ScenariosTab({ summary, scarcity, scoringRows, scarcityRows, tierSummary }) {
  const topScoringHits = useMemo(
    () =>
      [...(scoringRows || [])]
        .filter((s) => Math.abs(s.scoring_swing_ppg) > 0)
        .sort((a, b) => a.scoring_swing_ppg - b.scoring_swing_ppg)
        .slice(0, 15),
    [scoringRows],
  );
  const topScarcityWinners = useMemo(
    () => [...(scarcityRows || [])].sort((a, b) => b.vor_delta - a.vor_delta).slice(0, 15),
    [scarcityRows],
  );

  return (
    <div className="scenarios-tab">
      <p className="muted" style={{ fontSize: 13 }}>
        Internal scoring + scarcity comparison.  Scoring effect uses the
        per-rule contributions already attached to each TE in the live
        contract — we strip the TE Premium category and the TE-specific
        first-down bonus.  Scarcity uses the same VOR engine that powers
        the awards / scoring-fit pipeline.
      </p>

      <h3>Largest scoring losses (PPG)</h3>
      <div className="table-wrap" style={{ overflowX: "auto" }}>
        <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
          <thead>
            <tr>
              <th>Player</th>
              <th style={{ textAlign: "right" }}>Current Δ vs baseline</th>
              <th style={{ textAlign: "right" }}>TE rec bonus</th>
              <th style={{ textAlign: "right" }}>TE 1D bonus</th>
              <th style={{ textAlign: "right" }}>Proposed Δ</th>
              <th style={{ textAlign: "right" }}>Swing</th>
              <th style={{ textAlign: "right" }}>Confidence</th>
            </tr>
          </thead>
          <tbody>
            {topScoringHits.map((s) => (
              <tr key={`sc-${s.player_id}`}>
                <td>{s.display_name}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.current_ppg_delta)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.te_premium_ppg)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.te_first_down_ppg)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.proposed_ppg_delta)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.scoring_swing_ppg)}</td>
                <td style={{ textAlign: "right" }}>{fmtPct(s.confidence, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ marginTop: 18 }}>Biggest scarcity winners (2-TE start)</h3>
      <p className="muted" style={{ fontSize: 12 }}>
        Replacement PPG: {fmtNum(scarcity.replacement_one_te_ppg, 2)} (1
        starter) → {fmtNum(scarcity.replacement_two_te_ppg, 2)} (2 starters)
      </p>
      <div className="table-wrap" style={{ overflowX: "auto" }}>
        <table className="data-table" style={{ width: "100%", fontSize: 13 }}>
          <thead>
            <tr>
              <th>Player</th>
              <th style={{ textAlign: "right" }}>Season pts</th>
              <th style={{ textAlign: "right" }}>VOR (1 TE)</th>
              <th style={{ textAlign: "right" }}>VOR (2 TE)</th>
              <th style={{ textAlign: "right" }}>VOR Δ</th>
            </tr>
          </thead>
          <tbody>
            {topScarcityWinners.map((s) => (
              <tr key={`vor-${s.player_id}`}>
                <td>{s.display_name}</td>
                <td style={{ textAlign: "right" }}>{fmtNum(s.points, 1)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.vor_one_te, 1)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.vor_two_te, 1)}</td>
                <td style={{ textAlign: "right" }}>{fmtSigned(s.vor_delta, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <h3 style={{ marginTop: 18 }}>By tier</h3>
      <TierTable tierSummary={tierSummary} />
    </div>
  );
}

// ── Recommendations tab ─────────────────────────────────────────────

const COLUMNS = [
  { key: "te_pool_rank", label: "TE#", numeric: true },
  { key: "display_name", label: "Player", numeric: false },
  { key: "team", label: "Team", numeric: false },
  { key: "age", label: "Age", numeric: true },
  { key: "tier", label: "Tier", numeric: false },
  { key: "current_value", label: "Cur value", numeric: true, fmt: (v) => fmtNum(v, 0) },
  { key: "ktc_normal_value", label: "KTC norm", numeric: true, fmt: (v) => fmtNum(v, 0) },
  { key: "ktc_premium_value", label: "KTC TEP", numeric: true, fmt: (v) => fmtNum(v, 0) },
  { key: "market_boost_pct", label: "Mkt boost", numeric: true, fmt: (v) => fmtSignedPct(v) },
  { key: "ppg_baseline", label: "PPG (base)", numeric: true, fmt: (v) => fmtNum(v, 2) },
  { key: "ppg_league", label: "PPG (league)", numeric: true, fmt: (v) => fmtNum(v, 2) },
  { key: "scoring_swing_ppg", label: "Scoring Δ PPG", numeric: true, fmt: (v) => fmtSigned(v, 2) },
  { key: "rep_one_te", label: "Rep 1TE", numeric: true, fmt: (v) => fmtNum(v, 2) },
  { key: "rep_two_te", label: "Rep 2TE", numeric: true, fmt: (v) => fmtNum(v, 2) },
  { key: "vor_delta", label: "VOR Δ", numeric: true, fmt: (v) => fmtSigned(v, 1) },
  { key: "recommended_adjustment_pct", label: "Rec %", numeric: true, fmt: (v) => fmtSignedPct(v) },
  { key: "recommended_value", label: "Sandbox value", numeric: true, fmt: (v) => fmtNum(v, 0) },
  { key: "confidence", label: "Conf", numeric: true, fmt: (v) => fmtPct(v, 0) },
];

function RecommendationsTab({ rows, onSort, sort, filter, onFilter, tierSummary }) {
  return (
    <div className="recommendations-tab">
      <div style={{ display: "flex", gap: 8, alignItems: "center", margin: "10px 0" }}>
        <input
          type="search"
          placeholder="Filter by player name…"
          value={filter}
          onChange={(e) => onFilter(e.target.value)}
          style={{
            padding: "6px 10px",
            border: "1px solid var(--border, rgba(255,255,255,0.15))",
            borderRadius: 6,
            background: "var(--input-bg, rgba(255,255,255,0.04))",
            color: "inherit",
            fontSize: 13,
            minWidth: 220,
          }}
        />
        <span className="muted" style={{ fontSize: 12 }}>
          {rows.length} TEs · sandbox values are NOT applied to live data
        </span>
      </div>
      <div className="table-wrap" style={{ overflowX: "auto" }}>
        <table className="data-table" style={{ width: "100%", fontSize: 12 }}>
          <thead>
            <tr>
              {COLUMNS.map((col) => {
                const active = sort.column === col.key;
                return (
                  <th
                    key={col.key}
                    onClick={() => onSort(col.key)}
                    style={{
                      cursor: "pointer",
                      textAlign: col.numeric ? "right" : "left",
                      whiteSpace: "nowrap",
                      userSelect: "none",
                      borderBottom: active
                        ? "2px solid var(--accent, #6da3ff)"
                        : "1px solid var(--border, rgba(255,255,255,0.1))",
                    }}
                    title="Click to sort"
                  >
                    {col.label}
                    {active && (sort.direction === "asc" ? " ▲" : " ▼")}
                  </th>
                );
              })}
              <th style={{ textAlign: "left" }}>Notes</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="muted" style={{ padding: 8 }}>
                  No TEs match the current filter.
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.player_id}>
                  {COLUMNS.map((col) => {
                    const v = r[col.key];
                    const text = col.fmt ? col.fmt(v) : v ?? "—";
                    return (
                      <td
                        key={col.key}
                        style={{
                          textAlign: col.numeric ? "right" : "left",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {text}
                      </td>
                    );
                  })}
                  <td style={{ fontSize: 11, color: "var(--muted, rgba(255,255,255,0.6))" }}>
                    {(r.notes || []).join(" · ")}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <h3 style={{ marginTop: 18 }}>Tier rollups</h3>
      <TierTable tierSummary={tierSummary} />
    </div>
  );
}
