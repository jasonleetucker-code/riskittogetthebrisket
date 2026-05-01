"use client";

/**
 * SummaryCards — high-density at-a-glance scorecard.
 *
 * Renders:
 *   • Similarity Score (big number 0..100 + label + distortion tag)
 *   • Per-position match cards (QB / RB / WR / TE / Flex)
 *   • Biggest Difference + Closest Match callouts
 *
 * Method toggle (improved vs legacy) lives at the top so the user
 * can see how the two formulas compare without leaving the page.
 */
export default function SummaryCards({ data, method, setMethod }) {
  const sim = data?.similarity || {};
  const summary = data?.summary || {};
  const positions = data?.positions || {};
  const flex = data?.flex || {};

  const score = sim.score ?? 0;
  const scoreColor =
    score >= 95 ? "var(--green, #22c55e)" :
    score >= 85 ? "var(--green, #22c55e)" :
    score >= 75 ? "var(--amber, #facc15)" :
    score >= 60 ? "var(--orange, #f97316)" :
                  "var(--red, #ef4444)";

  return (
    <>
      <div className="card" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 12 }}>
        <div>
          <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>Method</div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            <button
              type="button"
              className={`btn btn-secondary ${method === "improved" ? "active" : ""}`}
              onClick={() => setMethod("improved")}
              style={method === "improved" ? { borderColor: "var(--cyan)", color: "var(--cyan)" } : {}}
            >
              Improved
            </button>
            <button
              type="button"
              className={`btn btn-secondary ${method === "legacy" ? "active" : ""}`}
              onClick={() => setMethod("legacy")}
              style={method === "legacy" ? { borderColor: "var(--cyan)", color: "var(--cyan)" } : {}}
            >
              Legacy (avg+median)/2
            </button>
          </div>
        </div>
        <div className="muted text-xs" style={{ maxWidth: 360, lineHeight: 1.5 }}>
          {method === "improved"
            ? "Multi-signal blend of median, average, percentiles, and replacement-adjusted value."
            : "Original simple formula — average and median averaged together. Useful as a sanity-check reference."}
        </div>
      </div>

      <div className="card" style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "minmax(180px, 1fr) 2fr" }}>
        <div style={{ textAlign: "center", padding: "var(--space-md) 0" }}>
          <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
            Similarity Score
          </div>
          <div style={{ fontSize: "3.5rem", fontWeight: 800, color: scoreColor, lineHeight: 1, marginTop: 6 }}>
            {score}
          </div>
          <div style={{ fontSize: "0.95rem", marginTop: 4 }}>{sim.label || "—"}</div>
          <div className="muted text-xs" style={{ marginTop: 4 }}>
            Distortion: <strong>{sim.distortionLabel || "—"}</strong>
          </div>
        </div>

        <div style={{ display: "grid", gap: 8, gridTemplateColumns: "repeat(auto-fit, minmax(120px, 1fr))" }}>
          <PositionMatchCard pos="QB" comp={positions.QB} method={method} />
          <PositionMatchCard pos="RB" comp={positions.RB} method={method} />
          <PositionMatchCard pos="WR" comp={positions.WR} method={method} />
          <PositionMatchCard pos="TE" comp={positions.TE} method={method} />
          <FlexMatchCard flex={flex} />
        </div>
      </div>

      <div className="card" style={{ display: "grid", gap: "var(--space-md)", gridTemplateColumns: "1fr 1fr" }}>
        <Callout
          label="Biggest Difference"
          value={summary.biggestDiffPosition || "—"}
          tone="amber"
          detail={
            summary.biggestDiffPosition
              ? `Status: ${positions[summary.biggestDiffPosition]?.status}`
              : "All positions are aligned"
          }
        />
        <Callout
          label="Closest Match"
          value={summary.closestMatchPosition || "—"}
          tone="green"
          detail={
            summary.closestMatchPosition
              ? `Status: ${positions[summary.closestMatchPosition]?.status}`
              : ""
          }
        />
      </div>
    </>
  );
}

function PositionMatchCard({ pos, comp, method }) {
  if (!comp) {
    return (
      <div style={cardBoxStyle()}>
        <div className="muted text-xs">{pos}</div>
        <div className="muted">—</div>
      </div>
    );
  }
  const diff = method === "legacy" ? comp.diffPpLegacy : comp.diffPpImproved;
  const myShare = method === "legacy" ? comp.my?.shareLegacy : comp.my?.shareImproved;
  const baseShare = method === "legacy" ? comp.baseline?.shareLegacy : comp.baseline?.shareImproved;
  const tone = absDiffTone(diff);
  return (
    <div style={cardBoxStyle()}>
      <div className="muted text-xs" style={{ textTransform: "uppercase" }}>{pos}</div>
      <div style={{ fontSize: "0.95rem", color: tone, marginTop: 4 }}>
        {comp.status}
      </div>
      <div className="text-xs muted" style={{ marginTop: 6 }}>
        Mine: {fmtPct(myShare)} &nbsp;·&nbsp; Base: {fmtPct(baseShare)}
      </div>
      <div className="text-xs" style={{ color: tone, marginTop: 2 }}>
        Δ {fmtSigned(diff)} pp
      </div>
    </div>
  );
}

function FlexMatchCard({ flex }) {
  if (!flex || !flex.my) {
    return (
      <div style={cardBoxStyle()}>
        <div className="muted text-xs">FLEX</div>
        <div className="muted">—</div>
      </div>
    );
  }
  const tone = absDiffTone(flex.relDiffPct, { lo: 1, mid: 5 });
  return (
    <div style={cardBoxStyle()}>
      <div className="muted text-xs" style={{ textTransform: "uppercase" }}>Top-96 Flex</div>
      <div className="text-xs" style={{ marginTop: 6 }}>
        Mine: {fmtNum(flex.my.improvedScore)}
      </div>
      <div className="text-xs" style={{ marginTop: 2 }}>
        Base: {fmtNum(flex.baseline.improvedScore)}
      </div>
      <div className="text-xs" style={{ color: tone, marginTop: 2 }}>
        Δ {fmtSigned(flex.relDiffPct)}%
      </div>
    </div>
  );
}

function Callout({ label, value, tone, detail }) {
  const color = tone === "amber" ? "var(--amber)" : tone === "green" ? "var(--green, #22c55e)" : "var(--text)";
  return (
    <div style={cardBoxStyle()}>
      <div className="muted text-xs" style={{ textTransform: "uppercase", letterSpacing: 0.5 }}>
        {label}
      </div>
      <div style={{ fontSize: "1.6rem", fontWeight: 700, color, marginTop: 4 }}>
        {value}
      </div>
      {detail && <div className="muted text-xs" style={{ marginTop: 4 }}>{detail}</div>}
    </div>
  );
}

function cardBoxStyle() {
  return {
    background: "rgba(255,255,255,0.03)",
    border: "1px solid var(--border)",
    borderRadius: "var(--radius-sm, 6px)",
    padding: "var(--space-sm)",
  };
}

function absDiffTone(diff, bands) {
  const b = bands || { lo: 0.5, mid: 1.5, hi: 3 };
  const d = Math.abs(Number(diff) || 0);
  if (d <= b.lo) return "var(--green, #22c55e)";
  if (d <= b.mid) return "var(--cyan)";
  if (d <= (b.hi || 3)) return "var(--amber)";
  return "var(--red, #ef4444)";
}

function fmtPct(v) {
  if (v == null) return "—";
  return `${Number(v).toFixed(1)}%`;
}
function fmtNum(v) {
  if (v == null) return "—";
  return Number(v).toFixed(1);
}
function fmtSigned(v) {
  if (v == null) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;
}
