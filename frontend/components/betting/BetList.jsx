"use client";

/**
 * BetList — the user's bets with live status, plus per-bet cancel and a
 * global kill switch that cancels every open resting order.
 */
const OPEN = new Set(["proposed", "approved", "resting"]);

function statusClass(status) {
  if (status === "filled" || status === "settled") return "text-green";
  if (status === "canceled" || status === "rejected") return "muted";
  return "text-cyan";
}

export default function BetList({ bets, onCancel, onKill }) {
  const hasOpen = Array.isArray(bets) && bets.some((b) => OPEN.has(b.status));
  return (
    <section className="card" style={{ marginBottom: "var(--space-md)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="page-title" style={{ fontSize: "1rem" }}>Your bets</h2>
        {hasOpen ? (
          <button className="button button-danger" onClick={onKill}>
            Kill all resting orders
          </button>
        ) : null}
      </div>

      {(!bets || bets.length === 0) ? (
        <p className="muted text-sm" style={{ marginTop: "var(--space-sm)" }}>
          No bets yet.
        </p>
      ) : (
        <div className="table-wrap" style={{ marginTop: "var(--space-sm)" }}>
          <table>
            <thead>
              <tr>
                <th style={{ textAlign: "left" }}>Bet</th>
                <th>Price</th>
                <th>Stake</th>
                <th>Status</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {bets.map((b) => (
                <tr key={b.id}>
                  <td style={{ textAlign: "left" }}>
                    <div style={{ fontWeight: 600 }}>{b.side_label || b.kalshi_ticker}</div>
                    <div className="muted text-xs">{b.game || ""}</div>
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {b.filled_price ? `${b.filled_price}¢ fill` : `${b.target_price}¢`}
                  </td>
                  <td style={{ textAlign: "center" }}>${Number(b.stake_usd || 0).toFixed(2)}</td>
                  <td style={{ textAlign: "center" }}>
                    <span className={`badge ${statusClass(b.status)}`}>{b.status}</span>
                    {b.env === "prod" ? null : <span className="muted text-xs"> demo</span>}
                  </td>
                  <td style={{ textAlign: "center" }}>
                    {OPEN.has(b.status) ? (
                      <button className="button button-reset text-xs" onClick={() => onCancel(b.id)}>
                        Cancel
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
