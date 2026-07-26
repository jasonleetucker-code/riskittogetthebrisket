"use client";

import { Panel } from "@/components/ds";

/**
 * FlexComparison — side-by-side detail for the Top-96 offensive flex
 * pool (RB ∪ WR ∪ TE, QB excluded).  This tells you whether the broad
 * flex value pool is balanced, which matters for lineup-construction
 * value beyond the per-position tables.
 */
export default function FlexComparison({ data }) {
  const flex = data?.flex;
  if (!flex || !flex.my) {
    return (
      <Panel>
        <p className="muted">Flex comparison unavailable.</p>
      </Panel>
    );
  }
  return (
    <Panel>
      <h2 className="section-title">Top-96 Offensive Flex</h2>
      <p className="muted text-sm" style={{ marginTop: 6, lineHeight: 1.5 }}>
        Top-96 of the RB / WR / TE pool (QBs excluded), under each
        league's actual scoring settings.  This is the broad "starter
        pool" for lineup decisions — if your custom league inflates or
        deflates this pool relative to a standard league, lineup value
        construction shifts in ways that aren't visible from per-position
        cards alone.
      </p>

      <div style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr", marginTop: "var(--space-md)" }}>
        <FlexBlock title="My League" flex={flex.my} accent="cyan" />
        <FlexBlock title="Standard Baseline" flex={flex.baseline} accent="gold" />
      </div>

      <div className="card" style={{ marginTop: "var(--space-md)", background: "rgba(255,255,255,0.04)" }}>
        <div className="text-sm" style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
          <Stat label="Diff (Improved)" value={fmtSigned(flex.diffImproved)} />
          <Stat label="Rel Diff" value={`${fmtSigned(flex.relDiffPct)}%`} />
          <Stat label="Diff (Legacy)" value={fmtSigned(flex.diffLegacy)} />
        </div>
        <p className="text-sm" style={{ marginTop: 10 }}>{flex.interpretation}</p>
      </div>
    </Panel>
  );
}

function FlexBlock({ title, flex, accent }) {
  const color = accent === "gold" ? "var(--gold, #FFC704)" : "var(--cyan)";
  const m = flex.metrics || {};
  return (
    <div style={{ border: "1px solid var(--border)", borderRadius: "var(--radius-sm, 6px)", padding: "var(--space-sm)" }}>
      <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>{title}</div>
      <div style={{ fontSize: "1.4rem", fontWeight: 700, color, marginTop: 4 }}>
        {fmt(flex.improvedScore)}
        <span className="muted text-xs" style={{ marginLeft: 8, fontWeight: 400 }}>improved</span>
      </div>
      <div className="text-sm muted">
        Legacy: <strong>{fmt(flex.legacyScore)}</strong>
      </div>
      <div className="text-xs" style={{ marginTop: 8, lineHeight: 1.7 }}>
        <Stat inline label="Avg" value={fmt(m.average)} />
        <Stat inline label="Med" value={fmt(m.median)} />
        <Stat inline label="P25" value={fmt(m.p25)} />
        <Stat inline label="P75" value={fmt(m.p75)} />
        <Stat inline label="Repl" value={fmt(m.replacementLevel)} />
        <Stat inline label="Elite" value={fmt(m.elite)} />
      </div>
    </div>
  );
}

function Stat({ label, value, inline }) {
  if (inline) {
    return (
      <span style={{ marginRight: 12 }}>
        <span className="muted">{label}:</span> <strong style={{ fontFamily: "var(--mono)" }}>{value}</strong>
      </span>
    );
  }
  return (
    <span>
      <span className="muted">{label}:</span> <strong>{value}</strong>
    </span>
  );
}

function fmt(v) { return v == null ? "—" : Number(v).toFixed(1); }
function fmtSigned(v) {
  if (v == null) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;
}
