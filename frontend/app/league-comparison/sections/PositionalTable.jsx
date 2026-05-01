"use client";

/**
 * PositionalTable — main comparison grid.
 *
 * Columns: Position, Standard score, My score, Standard share, My share,
 * Diff (pp), Rel diff (%), Status, Recommendation.  Method toggle
 * controls whether legacy or improved values populate each row.
 */
const POSITIONS = ["QB", "RB", "WR", "TE"];

export default function PositionalTable({ data, method, setMethod }) {
  const positions = data?.positions || {};

  return (
    <div className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 8 }}>
        <h2 className="section-title" style={{ margin: 0 }}>Positional Comparison</h2>
        <div style={{ display: "flex", gap: 6 }}>
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
            Legacy
          </button>
        </div>
      </div>

      <div className="table-wrap" style={{ marginTop: "var(--space-sm)" }}>
        <table>
          <thead>
            <tr>
              <th>Pos</th>
              <th style={{ textAlign: "right" }}>Standard Score</th>
              <th style={{ textAlign: "right" }}>My Score</th>
              <th style={{ textAlign: "right" }}>Standard Share</th>
              <th style={{ textAlign: "right" }}>My Share</th>
              <th style={{ textAlign: "right" }}>Diff (pp)</th>
              <th style={{ textAlign: "right" }}>Rel %</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {POSITIONS.map((pos) => {
              const c = positions[pos];
              if (!c) {
                return (
                  <tr key={pos}>
                    <td>{pos}</td>
                    <td colSpan={7} className="muted">—</td>
                  </tr>
                );
              }
              const myScore = method === "legacy" ? c.my?.legacyScore : c.my?.improvedScore;
              const baseScore = method === "legacy" ? c.baseline?.legacyScore : c.baseline?.improvedScore;
              const myShare = method === "legacy" ? c.my?.shareLegacy : c.my?.shareImproved;
              const baseShare = method === "legacy" ? c.baseline?.shareLegacy : c.baseline?.shareImproved;
              const diff = method === "legacy" ? c.diffPpLegacy : c.diffPpImproved;
              const tone = diffTone(diff);
              return (
                <tr key={pos}>
                  <td style={{ fontWeight: 700 }}>{pos}</td>
                  <td style={mono()}>{fmt(baseScore)}</td>
                  <td style={mono()}>{fmt(myScore)}</td>
                  <td style={mono()}>{fmtPct(baseShare)}</td>
                  <td style={mono()}>{fmtPct(myShare)}</td>
                  <td style={{ ...mono(), color: tone }}>{fmtSigned(diff)}</td>
                  <td style={{ ...mono(), color: tone }}>{fmtSigned(c.relDiffPct)}%</td>
                  <td style={{ color: tone }}>{c.status}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div style={{ marginTop: "var(--space-md)" }}>
        <h3 className="section-title" style={{ fontSize: "1rem" }}>Recommendations</h3>
        <ul style={{ marginTop: 6, paddingLeft: 18 }}>
          {POSITIONS.map((pos) => {
            const c = positions[pos];
            if (!c) return null;
            return (
              <li key={pos} className="text-sm" style={{ marginBottom: 6 }}>
                {c.recommendation}
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

function diffTone(diff) {
  const d = Math.abs(Number(diff) || 0);
  if (d <= 0.5) return "var(--green, #22c55e)";
  if (d <= 1.5) return "var(--cyan)";
  if (d <= 3) return "var(--amber)";
  return "var(--red, #ef4444)";
}

function fmt(v) { return v == null ? "—" : Number(v).toFixed(1); }
function fmtPct(v) { return v == null ? "—" : `${Number(v).toFixed(1)}%`; }
function fmtSigned(v) {
  if (v == null) return "—";
  const n = Number(v);
  return `${n >= 0 ? "+" : ""}${n.toFixed(1)}`;
}
function mono() { return { textAlign: "right", fontFamily: "var(--mono)" }; }
