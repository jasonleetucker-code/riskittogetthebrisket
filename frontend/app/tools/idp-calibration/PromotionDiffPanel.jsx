"use client";

/**
 * PromotionDiffPanel — per-bucket diff between the currently loaded
 * run and the promoted production config.
 *
 * Mounts inside ProductionConfigPanel just above the Promote button so
 * the reviewer cannot promote without seeing which multipliers will
 * move. If no production is promoted yet, shows the candidate values
 * alone (with "—" in the production column).
 */

const POSITIONS = ["DL", "LB", "DB"];
const KINDS = ["intrinsic", "market", "final"];
const KIND_BY_MODE = {
  blended: "final",
  intrinsic_only: "intrinsic",
  market_only: "market",
};

function fmt(value) {
  if (value == null || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(4);
}

function deltaCell(candidate, current) {
  if (candidate == null) return { text: "—", cls: "" };
  if (current == null) return { text: `+${fmt(candidate)}`, cls: "idp-lab-diff-new" };
  const d = Number(candidate) - Number(current);
  if (Math.abs(d) < 1e-4) return { text: "—", cls: "idp-lab-diff-flat" };
  const sign = d > 0 ? "+" : "";
  return {
    text: `${sign}${d.toFixed(4)}`,
    cls: d > 0 ? "idp-lab-diff-up" : "idp-lab-diff-down",
  };
}

function bucketByLabel(positionBlock) {
  if (!positionBlock?.buckets) return {};
  const out = {};
  for (const b of positionBlock.buckets) out[b.label] = b;
  return out;
}

export default function PromotionDiffPanel({
  candidateRun,
  production,
  activeMode,
}) {
  if (!candidateRun?.multipliers) return null;

  const kind = KIND_BY_MODE[activeMode] || "final";
  const promoted = production?.present ? production.config : null;
  const promotedAt = promoted?.promoted_at;

  return (
    <div className="idp-lab-diff">
      <div className="idp-lab-diff-header">
        <strong>What would change?</strong>
        <span className="muted text-sm">
          candidate run <code>{candidateRun.run_id}</code>{" "}
          {promoted ? (
            <>vs promoted <code>{promoted.source_run_id}</code> ({promotedAt})</>
          ) : (
            <>vs <em>(no production config yet)</em></>
          )}
          {" "}· kind: <strong>{kind}</strong>
        </span>
      </div>
      {POSITIONS.map((pos) => {
        const candidateBuckets = bucketByLabel(candidateRun.multipliers[pos]);
        const promotedBuckets = bucketByLabel(promoted?.multipliers?.[pos]);
        const labels = Array.from(
          new Set([
            ...Object.keys(candidateBuckets),
            ...Object.keys(promotedBuckets),
          ]),
        ).sort((a, b) => {
          const ax = Number(a.split("-")[0]) || 0;
          const bx = Number(b.split("-")[0]) || 0;
          return ax - bx;
        });
        if (!labels.length) return null;
        return (
          <div key={pos} className="idp-lab-diff-block">
            <div className="idp-lab-subheading">
              <strong>{pos}</strong>
              <span className="muted text-sm">per-bucket {kind}</span>
            </div>
            <div className="table-wrap">
              <table className="table idp-lab-diff-table">
                <thead>
                  <tr>
                    <th>Bucket</th>
                    <th>Current production</th>
                    <th>Candidate run</th>
                    <th>Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {labels.map((label) => {
                    const cand = candidateBuckets[label]?.[kind];
                    const cur = promotedBuckets[label]?.[kind];
                    const cell = deltaCell(cand, cur);
                    return (
                      <tr key={label}>
                        <td>{label}</td>
                        <td>{fmt(cur)}</td>
                        <td>{fmt(cand)}</td>
                        <td className={cell.cls}>{cell.text}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
      <details className="idp-lab-diff-details">
        <summary className="muted text-sm">
          Show all three kinds (intrinsic / market / final)
        </summary>
        {POSITIONS.map((pos) => {
          const cand = bucketByLabel(candidateRun.multipliers[pos]);
          const prom = bucketByLabel(promoted?.multipliers?.[pos]);
          const labels = Object.keys(cand).sort((a, b) => {
            const ax = Number(a.split("-")[0]) || 0;
            const bx = Number(b.split("-")[0]) || 0;
            return ax - bx;
          });
          if (!labels.length) return null;
          return (
            <div key={pos} className="idp-lab-diff-block">
              <strong>{pos}</strong>
              <div className="table-wrap">
                <table className="table idp-lab-diff-all-table">
                  <thead>
                    <tr>
                      <th>Bucket</th>
                      {KINDS.map((k) => (
                        <th key={k} colSpan={3}>{k}</th>
                      ))}
                    </tr>
                    <tr>
                      <th></th>
                      {KINDS.map((k) => (
                        <>
                          <th key={`${k}-cur`}>prod</th>
                          <th key={`${k}-cand`}>cand</th>
                          <th key={`${k}-d`}>Δ</th>
                        </>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {labels.map((label) => (
                      <tr key={label}>
                        <td>{label}</td>
                        {KINDS.map((k) => {
                          const c = cand[label]?.[k];
                          const p = prom[label]?.[k];
                          const cell = deltaCell(c, p);
                          return (
                            <>
                              <td key={`${k}-p`}>{fmt(p)}</td>
                              <td key={`${k}-c`}>{fmt(c)}</td>
                              <td key={`${k}-d`} className={cell.cls}>
                                {cell.text}
                              </td>
                            </>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })}
      </details>
    </div>
  );
}
