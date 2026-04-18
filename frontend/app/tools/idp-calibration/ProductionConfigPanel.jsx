"use client";

import { useState } from "react";
import PromotionDiffPanel from "./PromotionDiffPanel";

const VALID_MODES = ["blended", "intrinsic_only", "market_only"];

export default function ProductionConfigPanel({
  production,
  currentRun,
  onPromote,
  loading,
  error,
}) {
  const [mode, setMode] = useState("blended");
  const [confirming, setConfirming] = useState(false);
  const promoted = production?.present ? production.config : null;

  const canPromote = Boolean(currentRun?.run_id) && !loading;

  function handlePromoteClick() {
    if (!canPromote) return;
    if (!confirming) {
      setConfirming(true);
      return;
    }
    onPromote?.({ runId: currentRun.run_id, activeMode: mode });
    setConfirming(false);
  }

  return (
    <div className="card idp-lab-section">
      <h2>Production config</h2>
      {promoted ? (
        <div>
          <p className="muted text-sm">
            Promoted at <strong>{promoted.promoted_at}</strong> by{" "}
            <strong>{promoted.promoted_by}</strong> from run{" "}
            <code>{promoted.source_run_id}</code>. Active mode:{" "}
            <strong>{promoted.active_mode}</strong>.
          </p>
          <p className="muted text-sm">
            Year coverage: {(promoted.year_coverage || []).join(", ") || "—"} |{" "}
            League IDs: test <code>{promoted.league_ids?.test}</code>, mine{" "}
            <code>{promoted.league_ids?.mine}</code>.
          </p>
        </div>
      ) : (
        <p className="muted text-sm">
          No production config promoted yet. The live trade calculator is
          operating in identity mode (all IDP multipliers = 1.0).
        </p>
      )}

      {currentRun && (
        <PromotionDiffPanel
          candidateRun={currentRun}
          production={production}
          activeMode={mode}
        />
      )}

      <div className="idp-lab-promote-block">
        <label className="idp-lab-field">
          <span className="idp-lab-label">Promotion mode</span>
          <select
            className="input"
            value={mode}
            onChange={(e) => setMode(e.target.value)}
          >
            {VALID_MODES.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          className={`button ${confirming ? "button-danger" : "button-primary"}`}
          onClick={handlePromoteClick}
          disabled={!canPromote}
          title={!canPromote ? "Analyze a run first" : "Promote this run"}
        >
          {loading
            ? "Promoting…"
            : confirming
            ? "Click again to confirm"
            : "Promote to production"}
        </button>
        {confirming && (
          <button
            type="button"
            className="button"
            onClick={() => setConfirming(false)}
          >
            Cancel
          </button>
        )}
      </div>
      {error && (
        <p className="idp-lab-error-text">{error}</p>
      )}
    </div>
  );
}
