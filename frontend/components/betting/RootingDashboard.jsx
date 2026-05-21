"use client";

/**
 * RootingDashboard — "who you need to be rooting for" based on the
 * user's open/filled Kalshi positions.  Pure presentational; data comes
 * from GET /api/betting/rooting.
 */
export default function RootingDashboard({ rooting }) {
  if (!Array.isArray(rooting) || rooting.length === 0) {
    return (
      <section className="card" style={{ marginBottom: "var(--space-md)" }}>
        <h2 className="page-title" style={{ fontSize: "1rem" }}>Who to root for</h2>
        <p className="muted text-sm" style={{ marginTop: 4 }}>
          No active positions yet. Approve a bet from the call sheet and it&apos;ll show up here.
        </p>
      </section>
    );
  }
  return (
    <section className="card" style={{ marginBottom: "var(--space-md)" }}>
      <h2 className="page-title" style={{ fontSize: "1rem" }}>Who to root for</h2>
      <p className="muted text-xs" style={{ marginTop: 2, marginBottom: "var(--space-sm)" }}>
        Where your money is tonight.
      </p>
      <div className="list">
        {rooting.map((r, i) => (
          <div
            key={`${r.game}-${i}`}
            className="card"
            style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}
          >
            <div>
              <div style={{ fontWeight: 700 }} className="text-cyan">
                {r.rootFor}
              </div>
              <div className="muted text-xs">{r.game || "—"}</div>
            </div>
            <div style={{ textAlign: "right" }}>
              <span className="badge">{r.status}</span>
              <div className="muted text-xs" style={{ marginTop: 2 }}>
                ${Number(r.stakeUsd || 0).toFixed(2)} @ {r.targetPrice}¢
              </div>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
