"use client";

import { useState } from "react";

/**
 * BettingSettings — per-user guardrails: default unit, per-bet max,
 * daily exposure cap, and the real-money confirmation toggle (only
 * meaningful when the server is in prod/live mode).
 */
export default function BettingSettings({ settings, env, onSave }) {
  const [unit, setUnit] = useState(settings?.unit_usd ?? 5);
  const [perBet, setPerBet] = useState(settings?.per_bet_max_usd ?? 25);
  const [daily, setDaily] = useState(settings?.daily_cap_usd ?? 50);
  const [liveConfirmed, setLiveConfirmed] = useState(Boolean(settings?.live_confirmed));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  async function save() {
    setBusy(true);
    setMsg("");
    try {
      await onSave({
        unit_usd: Number(unit),
        per_bet_max_usd: Number(perBet),
        daily_cap_usd: Number(daily),
        live_confirmed: liveConfirmed,
      });
      setMsg("Saved.");
    } catch (e) {
      setMsg(e?.message || "Save failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card" style={{ marginBottom: "var(--space-md)" }}>
      <h2 className="page-title" style={{ fontSize: "1rem" }}>Guardrails</h2>
      <p className="muted text-xs" style={{ marginTop: 2 }}>
        Server-enforced limits. Every bet still requires your explicit approval.
      </p>
      <div style={{ display: "grid", gap: "var(--space-sm)", marginTop: "var(--space-sm)" }}>
        <label className="label">
          Default unit ($)
          <input type="number" min={1} step="0.5" value={unit} onChange={(e) => setUnit(e.target.value)} />
        </label>
        <label className="label">
          Per-bet max ($)
          <input type="number" min={1} step="0.5" value={perBet} onChange={(e) => setPerBet(e.target.value)} />
        </label>
        <label className="label">
          Daily exposure cap ($)
          <input type="number" min={1} step="1" value={daily} onChange={(e) => setDaily(e.target.value)} />
        </label>
        <label className="label" style={{ display: "flex", alignItems: "center", gap: "var(--space-sm)" }}>
          <input
            type="checkbox"
            checked={liveConfirmed}
            onChange={(e) => setLiveConfirmed(e.target.checked)}
          />
          I understand bets are placed with {env === "prod" ? "REAL money" : "demo funds"} and want to enable real-money placement
        </label>
        {env !== "prod" ? (
          <p className="muted text-xs">
            Server is in DEMO mode — no real money moves regardless of this toggle.
          </p>
        ) : null}
        <button className="button button-primary" disabled={busy} onClick={save}>
          {busy ? "Saving…" : "Save guardrails"}
        </button>
        {msg ? <div className="muted text-xs">{msg}</div> : null}
      </div>
    </section>
  );
}
