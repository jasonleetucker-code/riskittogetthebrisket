import { getTradeCalculatorData } from "../../lib/dynasty-data-server";

const ASSET_LIMIT = 140;

function fmt(v) {
  const n = Number(v || 0);
  return Number.isFinite(n) ? n.toLocaleString() : "-";
}

export default async function TradePage() {
  const data = await getTradeCalculatorData();

  if (!data.ok) {
    return (
      <section className="card">
        <h1 style={{ marginTop: 0 }}>Trade Calculator</h1>
        <p style={{ color: "var(--red)", marginBottom: 0 }}>
          {data.error || "Failed to load trade data."}
        </p>
      </section>
    );
  }

  const topAssets = Array.isArray(data.rows) ? data.rows.slice(0, ASSET_LIMIT) : [];
  const leagueName = data.leagueContext?.leagueName || "League";

  return (
    <section className="trade-page-stack">
      <section className="card">
        <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
          <h1 style={{ margin: 0 }}>Trade Surface</h1>
          <span className="muted mono" style={{ fontSize: "0.72rem" }}>
            Source: {data.source || "unknown"} · updated {data.scrapeTimestamp}
          </span>
        </div>
        <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>
          League: {leagueName} · teams: {Number(data.teams?.length || 0)} · recent trades: {Number(data.trades?.length || 0)}
        </p>
      </section>

      <section className="card">
        <h2 style={{ marginTop: 0 }}>Top Trade Assets</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Player</th>
                <th>Pos</th>
                <th>Team</th>
                <th>Value</th>
                <th>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {topAssets.map((row) => (
                <tr key={`${row.name}-${row.rank}`}>
                  <td>{row.rank}</td>
                  <td>{row.name}</td>
                  <td>{row.pos}</td>
                  <td>{row.team || "-"}</td>
                  <td>{fmt(row.values?.full)}</td>
                  <td>{Math.round(Number(row.confidence || 0) * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </section>
  );
}
