"use client";

import { useState } from "react";

/**
 * CallSheet — tonight's blended recommendations.  Each row expands into
 * an approve form (target price + stake + optional manual Kalshi ticker).
 * Approving calls onApprove(payload) which places a resting limit order.
 */
function ApproveForm({ rec, unitUsd, onApprove }) {
  const [price, setPrice] = useState(rec.fair_price_cents);
  const [stake, setStake] = useState(unitUsd);
  const [ticker, setTicker] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");

  async function submit() {
    setBusy(true);
    setErr("");
    try {
      await onApprove({
        sport: rec.sport,
        game: rec.game,
        sideTeam: rec.side_team,
        sideLabel: rec.side_label,
        targetPrice: Number(price),
        stakeUsd: Number(stake),
        ticker: ticker.trim() || undefined,
      });
    } catch (e) {
      setErr(e?.message || "Failed to place bet");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginTop: "var(--space-sm)", display: "grid", gap: "var(--space-sm)" }}>
      <div style={{ display: "flex", gap: "var(--space-sm)", flexWrap: "wrap" }}>
        <label className="label" style={{ flex: 1 }}>
          Target price (¢)
          <input
            type="number"
            min={1}
            max={99}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            style={{ width: "100%" }}
          />
        </label>
        <label className="label" style={{ flex: 1 }}>
          Stake ($)
          <input
            type="number"
            min={1}
            step="0.5"
            value={stake}
            onChange={(e) => setStake(e.target.value)}
            style={{ width: "100%" }}
          />
        </label>
      </div>
      <label className="label">
        Kalshi ticker (optional — only if auto-match fails)
        <input
          type="text"
          placeholder="e.g. KXNBAGAME-..."
          value={ticker}
          onChange={(e) => setTicker(e.target.value)}
          style={{ width: "100%" }}
        />
      </label>
      {err ? (
        <div className="text-red text-xs">{err}</div>
      ) : null}
      <button className="button button-primary" disabled={busy} onClick={submit}>
        {busy ? "Placing…" : `Place resting order — $${Number(stake).toFixed(2)} @ ${price}¢`}
      </button>
    </div>
  );
}

export default function CallSheet({ recommendations, env, unitUsd, generatedAt, onApprove }) {
  const [openId, setOpenId] = useState(null);

  return (
    <section className="card" style={{ marginBottom: "var(--space-md)" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <h2 className="page-title" style={{ fontSize: "1rem" }}>Call sheet</h2>
        <span className={env === "prod" ? "badge text-red" : "badge text-green"}>
          {env === "prod" ? "LIVE — real money" : "DEMO"}
        </span>
      </div>
      <p className="muted text-xs" style={{ marginTop: 2 }}>
        Blended sportsbook consensus. {generatedAt ? `Odds as of ${generatedAt}.` : "No odds snapshot yet."}
      </p>

      {(!recommendations || recommendations.length === 0) ? (
        <p className="muted text-sm" style={{ marginTop: "var(--space-sm)" }}>
          No recommendations available. Run the odds fetcher
          (<code>scripts/fetch_betting_odds.py</code>) or wait for the next scheduled refresh.
        </p>
      ) : (
        <div className="list" style={{ marginTop: "var(--space-sm)" }}>
          {recommendations.map((rec) => {
            const id = rec.game_id;
            const isOpen = openId === id;
            return (
              <div key={id} className="card">
                <div
                  style={{ display: "flex", justifyContent: "space-between", alignItems: "center", cursor: "pointer" }}
                  onClick={() => setOpenId(isOpen ? null : id)}
                >
                  <div>
                    <div style={{ fontWeight: 700 }} className="text-cyan">{rec.side_label}</div>
                    <div className="muted text-xs">{rec.game}</div>
                  </div>
                  <div style={{ textAlign: "right" }}>
                    <div className="text-sm">{rec.consensus_pct}% • fair {rec.fair_price_cents}¢</div>
                    <div className="muted text-xs">
                      conf {Math.round((rec.confidence || 0) * 100)}% • {rec.book_count} books
                    </div>
                  </div>
                </div>
                {isOpen ? (
                  <ApproveForm rec={rec} unitUsd={unitUsd} onApprove={onApprove} />
                ) : null}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
