import { getDynastyFrontendData } from "../../lib/dynasty-data-server";

const RENDER_LIMIT = 250;

function fmt(v) {
  const n = Number(v || 0);
  return Number.isFinite(n) ? n.toLocaleString() : "-";
}

export default async function RankingsPage() {
  const data = await getDynastyFrontendData();

  if (!data.ok) {
    return (
      <section className="card">
        <h1 style={{ marginTop: 0 }}>Rankings</h1>
        <p style={{ color: "var(--red)", marginBottom: 0 }}>
          {data.error || "Failed to load rankings data."}
        </p>
      </section>
    );
  }

  const rows = Array.isArray(data.rows) ? data.rows.slice(0, RENDER_LIMIT) : [];

  return (
    <section className="card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <h1 style={{ margin: 0 }}>Rankings Surface</h1>
        <span className="muted mono" style={{ fontSize: "0.72rem" }}>
          Source: {data.source || "unknown"} · showing {rows.length.toLocaleString()} of {data.summary.total.toLocaleString()}
        </span>
      </div>
      <p className="muted" style={{ marginTop: 8 }}>
        Updated: {data.scrapeTimestamp}
      </p>

      <div className="table-wrap rankings-table-wrap" style={{ marginTop: 10 }}>
        <table>
          <thead>
            <tr>
              <th>#</th>
              <th>Player</th>
              <th>Pos</th>
              <th>Team</th>
              <th>Full</th>
              <th>Scoring</th>
              <th>Raw</th>
              <th>Sites</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={`${row.name}-${row.rank}`}>
                <td>{row.rank}</td>
                <td>{row.name}</td>
                <td>{row.pos}</td>
                <td>{row.team || "-"}</td>
                <td>{fmt(row.values?.full)}</td>
                <td>{fmt(row.values?.scoring)}</td>
                <td>{fmt(row.values?.raw)}</td>
                <td>{Number(row.siteCount || 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
