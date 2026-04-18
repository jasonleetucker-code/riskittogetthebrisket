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
  onRefreshBoard,
  refreshing,
  refreshError,
}) {
  const [mode, setMode] = useState("blended");
  const [confirming, setConfirming] = useState(false);
  const [lastRefreshAt, setLastRefreshAt] = useState(null);
  const promoted = production?.present ? production.config : null;

  const canPromote = Boolean(currentRun?.run_id) && !loading;
  // Must also gate on `loading` (the promote flag). If the user clicks
  // Refresh while a promote is in flight, the rebuild would read the
  // OLD config from disk (promote hasn't written yet) but still report
  // success — leaving a misleading "Last refresh" timestamp. Block the
  // button until promote resolves.
  const canRefresh = Boolean(promoted) && !refreshing && !loading;

  async function handleRefreshClick() {
    if (!canRefresh || !onRefreshBoard) return;
    const result = await onRefreshBoard();
    if (result?.ok) {
      setLastRefreshAt(result.rebuilt_at || new Date().toISOString());
    }
  }

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
          <div className="idp-lab-refresh-block">
            <button
              type="button"
              className="button"
              onClick={handleRefreshClick}
              disabled={!canRefresh}
              title={
                loading
                  ? "Promotion in flight — wait until it finishes"
                  : !promoted
                  ? "Nothing to refresh until a calibration is promoted"
                  : refreshing
                  ? "Refresh already running"
                  : "Force the live /rankings + /trade contracts to rebuild with the current promoted calibration"
              }
            >
              {refreshing ? "Refreshing…" : "Refresh live board now"}
            </button>
            {lastRefreshAt && !refreshing && (
              <span className="muted text-sm">
                Last refresh: <code>{lastRefreshAt}</code>
              </span>
            )}
            {refreshError && (
              <span className="idp-lab-error-text">{refreshError}</span>
            )}
          </div>
          <p className="muted text-sm idp-lab-refresh-hint">
            Without clicking, the live board picks up the promoted calibration on
            the next scheduled scrape. This button forces it to happen now.
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
