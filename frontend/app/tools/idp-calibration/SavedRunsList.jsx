"use client";

export default function SavedRunsList({ runs, currentRunId, onOpen }) {
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
            {runs.map((run) => (
              <tr
                key={run.run_id}
                className={run.run_id === currentRunId ? "idp-lab-row-active" : ""}
              >
                <td>
                  <code className="text-sm">{run.run_id}</code>
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
                <td>
                  <button className="button" onClick={() => onOpen?.(run.run_id)}>
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
