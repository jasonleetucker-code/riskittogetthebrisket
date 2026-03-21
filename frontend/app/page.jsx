import Link from "next/link";
import { getDynastyFrontendData } from "../lib/dynasty-data-server";

function RawFallbackDiagnostics({ diagnostics }) {
  const skippedRawFiles = Array.isArray(diagnostics?.skippedRawFiles)
    ? diagnostics.skippedRawFiles.filter((entry) => entry && typeof entry === "object")
    : [];

  if (!skippedRawFiles.length) return null;

  return (
    <section className="card ops-alert-card">
      <div className="row" style={{ justifyContent: "space-between", alignItems: "baseline" }}>
        <div>
          <div className="label">Runtime Diagnostics</div>
          <h2 style={{ marginTop: 6, marginBottom: 0 }}>Skipped Raw Fallback Files</h2>
        </div>
        <span className="quality-pill stale">{skippedRawFiles.length.toLocaleString()} flagged</span>
      </div>
      <p className="muted" style={{ marginTop: 8, marginBottom: 0 }}>
        The Next runtime ignored these local raw files while resolving fallback data. Clean them up so emergency fallback stays trustworthy.
      </p>
      <div className="ops-alert-list" style={{ marginTop: 12 }}>
        {skippedRawFiles.map((entry) => (
          <div
            key={`${entry.file || "unknown"}:${entry.reason || "unknown"}`}
            className="ops-alert-item"
          >
            <div className="ops-alert-file mono">{entry.file || "unknown file"}</div>
            <div className="ops-alert-reason">{entry.reason || "Unknown parse failure."}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export default async function HomePage() {
  const data = await getDynastyFrontendData();
  const summary = data?.summary || { total: 0, offense: 0, idp: 0, picks: 0 };

  return (
    <div className="league-stack">
      <section className="card">
        <h1 style={{ marginTop: 0, marginBottom: 0 }}>Frontend Modernization Console</h1>
        <p className="muted mono" style={{ marginTop: 8 }}>
          Migration surface only. Production route authority stays backend + static runtime unless <code>FRONTEND_RUNTIME</code> is intentionally switched.
        </p>

        {!data.ok ? (
          <p style={{ color: "var(--red)" }}>
            {data.error || "Failed to load dynasty data."}
          </p>
        ) : (
          <>
            <div className="row" style={{ marginTop: 14 }}>
              <div className="card kpi">
                <div className="label">Data Source</div>
                <div className="value mono" style={{ fontSize: "0.92rem" }}>{data.source || "unknown"}</div>
              </div>
              <div className="card kpi">
                <div className="label">Players</div>
                <div className="value">{summary.total.toLocaleString()}</div>
              </div>
              <div className="card kpi">
                <div className="label">Offense</div>
                <div className="value">{summary.offense.toLocaleString()}</div>
              </div>
              <div className="card kpi">
                <div className="label">IDP</div>
                <div className="value">{summary.idp.toLocaleString()}</div>
              </div>
              <div className="card kpi">
                <div className="label">Picks</div>
                <div className="value">{summary.picks.toLocaleString()}</div>
              </div>
            </div>

            <div className="row" style={{ marginTop: 16 }}>
              <Link href="/rankings" className="button">Open Rankings</Link>
              <Link href="/trade" className="button">Open Trade</Link>
              <Link href="/league" className="button">Open Public League</Link>
            </div>

            <p className="muted" style={{ marginTop: 14, marginBottom: 0, fontSize: "0.8rem" }}>
              Scrape timestamp: {String(data.scrapeTimestamp || data.dataDate || "n/a")}
            </p>
            <p className="muted" style={{ marginTop: 4, marginBottom: 0, fontSize: "0.74rem" }}>
              Data revalidate window: {data.revalidateSeconds || 0}s
            </p>
          </>
        )}
      </section>

      <RawFallbackDiagnostics diagnostics={data?.diagnostics} />
    </div>
  );
}
