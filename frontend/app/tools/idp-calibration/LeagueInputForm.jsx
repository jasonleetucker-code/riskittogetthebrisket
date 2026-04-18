"use client";

import { useState } from "react";

export default function LeagueInputForm({
  initialTestLeagueId = "",
  initialMyLeagueId = "",
  onAnalyze,
  onOpenSettings,
  loading,
}) {
  const [testId, setTestId] = useState(initialTestLeagueId);
  const [myId, setMyId] = useState(initialMyLeagueId);

  function handleSubmit(e) {
    e.preventDefault();
    if (!testId.trim() || !myId.trim()) return;
    onAnalyze?.({ testLeagueId: testId.trim(), myLeagueId: myId.trim() });
  }

  const disabled = Boolean(loading) || !testId.trim() || !myId.trim();

  return (
    <form className="card idp-lab-input" onSubmit={handleSubmit}>
      <div className="idp-lab-input-grid">
        <label className="idp-lab-field">
          <span className="idp-lab-label">Test (market) league ID</span>
          <input
            className="input"
            value={testId}
            onChange={(e) => setTestId(e.target.value)}
            placeholder="e.g. 984651234567890123"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
        <label className="idp-lab-field">
          <span className="idp-lab-label">My league ID</span>
          <input
            className="input"
            value={myId}
            onChange={(e) => setMyId(e.target.value)}
            placeholder="e.g. 984659876543210987"
            autoComplete="off"
            spellCheck={false}
          />
        </label>
      </div>
      <div className="idp-lab-actions">
        <button
          type="submit"
          className="button button-primary"
          disabled={disabled}
        >
          {loading ? "Analyzing…" : "Analyze"}
        </button>
        <button
          type="button"
          className="button"
          onClick={onOpenSettings}
          disabled={Boolean(loading)}
        >
          Advanced settings
        </button>
      </div>
      <p className="muted text-sm idp-lab-hint">
        Both league IDs stay private to this session. Analysis will walk
        <code> previous_league_id </code> back through 2022–2025 and rescore
        the same IDP universe under each scoring system.
      </p>
    </form>
  );
}
