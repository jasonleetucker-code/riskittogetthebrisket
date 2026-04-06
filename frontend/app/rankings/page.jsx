"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

// ── FULL-BOARD RANKINGS PAGE ──────────────────────────────────────────
// Data source: normalized contract rows from useDynastyData/buildRows
// Value:       rankDerivedValue when KTC-ranked, else canonical full value
// Columns:     Our Rank | Player | Pos | Our Value
// Sort:        precomputed row rank (ranked KTC first, then remaining board)

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

  // Show the full board (including unranked-by-KTC IDP pools).
  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rows.filter((r) => r.pos && r.pos !== "?" && r.pos !== "PICK");

    if (assetFilter !== "all") {
      list = list.filter((r) => r.assetClass === assetFilter);
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    // rows are already pre-ranked in buildRows(), but keep deterministic sort.
    return [...list].sort((a, b) => (a.rank || Number.MAX_SAFE_INTEGER) - (b.rank || Number.MAX_SAFE_INTEGER));
  }, [rows, assetFilter, query]);

  async function copyValues() {
    const lines = ["Our Rank\tPlayer\tPos\tOur Value"];
    ranked.forEach((row) => {
      lines.push(`${row.rank}\t${row.name}\t${row.pos}\t${Math.round(row.rankDerivedValue || row.values.full)}`);
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
            Full board · {ranked.length.toLocaleString()} shown · Source: {source || "unknown"}
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
                  <th style={{ width: 64, textAlign: "center" }} title="Overall board rank — 1 is best">Our Rank</th>
                  <th>Player</th>
                  <th>Pos</th>
                  <th title="Our board value (KTC-derived where available)">Our Value</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map((row) => (
                  <tr key={row.name}>
                    <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)" }}>
                      {row.rank}
                    </td>
                    <td style={{ fontWeight: 600 }}>{row.name}</td>
                    <td><span className="badge">{row.pos}</span></td>
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
