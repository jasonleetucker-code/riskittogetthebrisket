"use client";

import { useState } from "react";

export default function SavedRunsList({
  runs,
  currentRunId,
  promotedRunId,
  onOpen,
  onDelete,
  deleting,
}) {
  const [confirmRunId, setConfirmRunId] = useState(null);

  function handleDeleteClick(runId) {
    if (confirmRunId !== runId) {
      setConfirmRunId(runId);
      return;
    }
    setConfirmRunId(null);
    onDelete?.(runId);
  }

  if (!runs?.length) {
    return (
      <div className="card idp-lab-section">
        <h2>Saved runs</h2>
        <p className="muted">No runs saved yet. Analyze two leagues to save one.</p>
      </div>
    );
  }
  return (
    <div className="card idp-lab-section">
      <h2>Saved runs</h2>
      <div className="table-wrap">
        <table className="table idp-lab-runs-table">
          <thead>
            <tr>
              <th>Run</th>
              <th>Generated</th>
              <th>Test</th>
              <th>Mine</th>
              <th>Seasons</th>
              <th>Warnings</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((run) => {
              const isActive = run.run_id === currentRunId;
              const isPromoted = promotedRunId && run.run_id === promotedRunId;
              const isConfirming = confirmRunId === run.run_id;
              return (
                <tr
                  key={run.run_id}
                  className={isActive ? "idp-lab-row-active" : ""}
                >
                  <td>
                    <code className="text-sm">{run.run_id}</code>
                    {isPromoted && (
                      <span className="badge idp-lab-badge-promoted"> promoted</span>
                    )}
                  </td>
                  <td className="muted">{run.generated_at}</td>
                  <td>
                    <code className="text-sm">{run.test_league_id}</code>
                  </td>
                  <td>
                    <code className="text-sm">{run.my_league_id}</code>
                  </td>
                  <td>{(run.resolved_seasons || []).join(", ") || "—"}</td>
                  <td>{run.warning_count}</td>
                  <td className="idp-lab-runs-actions">
                    <button
                      className="button"
                      onClick={() => onOpen?.(run.run_id)}
                      disabled={Boolean(deleting)}
                    >
                      Open
                    </button>
                    <button
                      className={`button ${isConfirming ? "button-danger" : ""}`}
                      onClick={() => handleDeleteClick(run.run_id)}
                      disabled={Boolean(deleting)}
                      title={
                        isPromoted
                          ? "This run is the source of the current production config. Deleting it does NOT revert production."
                          : "Delete run"
                      }
                    >
                      {isConfirming ? "Confirm" : "Delete"}
                    </button>
                    {isConfirming && (
                      <button
                        className="button"
                        onClick={() => setConfirmRunId(null)}
                        disabled={Boolean(deleting)}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
