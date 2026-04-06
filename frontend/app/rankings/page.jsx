"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

// ── KTC-ONLY RANKINGS PAGE ────────────────────────────────────────────
// Data source: KTC trade value → ordinal KTC rank (integer, 1 = best)
// Value:       Our rank-to-value formula applied to that exact KTC rank
// Columns:     Our Rank | Player | Pos | Our Value  — nothing else
// Sort:        KTC rank ascending only (no multi-source consensus, no blending)

const FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
];

export default function RankingsPage() {
  const { loading, error, source, rows } = useDynastyData();
  const [query, setQuery] = useState("");
  const [assetFilter, setAssetFilter] = useState("all");
  const [copyStatus, setCopyStatus] = useState("");

  // Only show KTC-ranked players (ktcRank > 0, position resolved, no picks)
  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rows.filter((r) => r.ktcRank > 0);

    if (assetFilter !== "all") {
      list = list.filter((r) => r.assetClass === assetFilter);
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    // Sort strictly by KTC rank ascending — no other sort basis
    return [...list].sort((a, b) => a.ktcRank - b.ktcRank);
  }, [rows, assetFilter, query]);

  async function copyValues() {
    const lines = ["Our Rank\tPlayer\tPos\tOur Value"];
    ranked.forEach((row) => {
      lines.push(`${row.ktcRank}\t${row.name}\t${row.pos}\t${Math.round(row.rankDerivedValue || row.values.full)}`);
    });
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyStatus(`Copied ${ranked.length.toLocaleString()} rows`);
      setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy failed");
      setTimeout(() => setCopyStatus(""), 1800);
    }
  }

  return (
    <section className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>Rankings</h1>
          <p className="muted" style={{ marginTop: 4, marginBottom: 0 }}>
            KTC-only · {ranked.length.toLocaleString()} shown · Source: {source || "unknown"}
          </p>
        </div>
      </div>

      {loading && <p style={{ marginTop: 16 }}>Loading rankings...</p>}
      {!!error && <p style={{ color: "var(--red)", marginTop: 16 }}>{error}</p>}

      {!loading && !error && (
        <>
          <div className="row" style={{ marginTop: 14 }}>
            <input
              className="input"
              placeholder="Search player"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 220 }}
            />

            <select className="select" value={assetFilter} onChange={(e) => setAssetFilter(e.target.value)}>
              {FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>

            <button className="button" onClick={copyValues}>
              Copy Values
            </button>
            {copyStatus ? <span className="muted" style={{ fontSize: "0.78rem", alignSelf: "center" }}>{copyStatus}</span> : null}
          </div>

          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th style={{ width: 64, textAlign: "center" }} title="KTC rank — 1 is best">Our Rank</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th title="Raw KTC trade value">KTC</th>
                  <th title="Raw IDPTradeCalc trade value">IDPTradeCalc</th>
                  <th title="Our formula value derived from KTC rank">Our Value</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((row) => (
                  <tr key={row.name}>
                    <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)" }}>
                      {row.ktcRank}
                    </td>
                    <td style={{ fontWeight: 600 }}>{row.name}</td>
                    <td><span className="badge">{row.pos}</span></td>
                    <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.78rem", color: "var(--subtext)" }}>
                      {row.raw?.ktc || '—'}
                    </td>
                    <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.78rem", color: "var(--subtext)" }}>
                      {row.raw?.idpTradeCalc || '—'}
                    </td>
                    <td style={{ fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)" }}>
                      {Math.round(row.rankDerivedValue || row.values.full).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}
