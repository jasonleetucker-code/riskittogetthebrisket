"use client";

import Link from "next/link";
import { useDynastyData } from "@/components/useDynastyData";

export default function HomePage() {
  const { loading, error, source, rows, rawData } = useDynastyData();

  const offense = rows.filter((r) => r.assetClass === "offense").length;
  const idp = rows.filter((r) => r.assetClass === "idp").length;
  const picks = rows.filter((r) => r.assetClass === "pick").length;

  return (
    <section className="card">
      <h1 style={{ marginTop: 0 }}>React + Next.js Frontend</h1>
      <p className="muted" style={{ marginTop: 6 }}>
        This is the Next.js shell for development and incremental migration. It reads the latest dynasty dataset directly, while the Static app remains the default production runtime unless FRONTEND_RUNTIME is overridden.
      </p>

      {loading && <p>Loading latest dynasty data...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
          <div className="row" style={{ marginTop: 14 }}>
            <div className="card kpi">
              <div className="label">Data Source</div>
              <div className="value" style={{ fontSize: "0.98rem" }}>{source || "unknown"}</div>
            </div>
            <div className="card kpi">
              <div className="label">Players</div>
              <div className="value">{rows.length.toLocaleString()}</div>
            </div>
            <div className="card kpi">
              <div className="label">Offense</div>
              <div className="value">{offense.toLocaleString()}</div>
            </div>
            <div className="card kpi">
              <div className="label">IDP</div>
              <div className="value">{idp.toLocaleString()}</div>
            </div>
            <div className="card kpi">
              <div className="label">Picks</div>
              <div className="value">{picks.toLocaleString()}</div>
            </div>
          </div>

          <div className="row" style={{ marginTop: 16 }}>
            <Link href="/rankings" className="button">Open Rankings</Link>
            <Link href="/trade" className="button">Open Trade Builder</Link>
          </div>

          <p className="muted" style={{ marginTop: 14, marginBottom: 0, fontSize: "0.8rem" }}>
            Scrape timestamp: {String(rawData?.scrapeTimestamp || rawData?.date || "n/a")}
          </p>
        </>
      )}
    </section>
  );
}
