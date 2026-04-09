"use client";

import { useMemo, useState, useCallback } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { resolvedRank } from "@/lib/dynasty-data";
import { useSettings } from "@/components/useSettings";
import { lamMultiplier } from "@/lib/trade-logic";
import { useApp } from "@/components/AppShell";

// ── UNIFIED RANKINGS PAGE ────────────────────────────────────────────
// One blended board: offense + IDP sorted by unified rank.
// Source columns show which source(s) contributed each player's value.
// All columns are sortable (click header to toggle asc/desc).

const POS_FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
  { key: "QB", label: "QB" },
  { key: "RB", label: "RB" },
  { key: "WR", label: "WR" },
  { key: "TE", label: "TE" },
  { key: "DL", label: "DL" },
  { key: "LB", label: "LB" },
  { key: "DB", label: "DB" },
];

function posMatchesFilter(pos, assetClass, filter) {
  if (filter === "all") return true;
  if (filter === "offense") return assetClass === "offense";
  if (filter === "idp") return assetClass === "idp";
  return pos === filter;
}

export default function RankingsPage() {
  const { loading, error, source, rows } = useDynastyData();
  const { settings } = useSettings();
  const { openPlayerPopup } = useApp();
  const [query, setQuery] = useState("");
  const [posFilter, setPosFilter] = useState("all");
  const [sortCol, setSortCol] = useState("rank");
  const [sortAsc, setSortAsc] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");

  const handleSort = useCallback((col) => {
    if (sortCol === col) {
      setSortAsc((prev) => !prev);
    } else {
      setSortCol(col);
      // Default direction: ascending for rank/player/pos, descending for values
      setSortAsc(["rank", "name", "pos"].includes(col));
    }
  }, [sortCol]);

  const ranked = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rows.filter((r) => r.pos && r.pos !== "?" && r.pos !== "PICK");

    if (posFilter !== "all") {
      list = list.filter((r) => posMatchesFilter(r.pos, r.assetClass, posFilter));
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    // Sort by selected column
    const sorted = [...list];
    const dir = sortAsc ? 1 : -1;
    sorted.sort((a, b) => {
      let va, vb;
      switch (sortCol) {
        case "rank":
          va = resolvedRank(a);
          vb = resolvedRank(b);
          return (va - vb) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "pos":
          return a.pos.localeCompare(b.pos) * dir || resolvedRank(a) - resolvedRank(b);
        case "value":
          va = a.rankDerivedValue || a.values?.full || 0;
          vb = b.rankDerivedValue || b.values?.full || 0;
          return (va - vb) * dir;
        case "ktc":
          va = Number(a.canonicalSites?.ktc) || 0;
          vb = Number(b.canonicalSites?.ktc) || 0;
          return (va - vb) * dir;
        case "idpTradeCalc":
          va = Number(a.canonicalSites?.idpTradeCalc) || 0;
          vb = Number(b.canonicalSites?.idpTradeCalc) || 0;
          return (va - vb) * dir;
        case "ktcRank":
          va = a.ktcRank ?? Infinity;
          vb = b.ktcRank ?? Infinity;
          return (va - vb) * dir;
        case "idpRank":
          va = a.idpRank ?? Infinity;
          vb = b.idpRank ?? Infinity;
          return (va - vb) * dir;
        default:
          return resolvedRank(a) - resolvedRank(b);
      }
    });
    return sorted;
  }, [rows, posFilter, query, sortCol, sortAsc]);

  function SortHeader({ col, children, style }) {
    const active = sortCol === col;
    const arrow = active ? (sortAsc ? " \u25B2" : " \u25BC") : "";
    return (
      <th
        style={{ cursor: "pointer", userSelect: "none", whiteSpace: "nowrap", ...style }}
        onClick={() => handleSort(col)}
        title={`Sort by ${children}${active ? (sortAsc ? " (ascending)" : " (descending)") : ""}`}
      >
        {children}{arrow}
      </th>
    );
  }

  async function copyValues() {
    const lines = ["Rank\tPlayer\tPos\tOur Value\tKTC Value\tKTC Rank\tIDPTC Value\tIDPTC Rank"];
    ranked.forEach((row) => {
      const ktcVal = row.canonicalSites?.ktc != null ? Math.round(Number(row.canonicalSites.ktc)) : "";
      const idpVal = row.canonicalSites?.idpTradeCalc != null ? Math.round(Number(row.canonicalSites.idpTradeCalc)) : "";
      lines.push(`${row.rank}\t${row.name}\t${row.pos}\t${Math.round(row.rankDerivedValue || row.values.full)}\t${ktcVal}\t${row.ktcRank || ""}\t${idpVal}\t${row.idpRank || ""}`);
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
            Unified overall board · {ranked.length.toLocaleString()} shown · Offense ranked from KTC + IDP Trade Calculator, IDP from IDP Trade Calculator
          </p>
          <p className="muted" style={{ marginTop: 2, marginBottom: 0, fontSize: "0.7rem" }}>
            — means this source does not cover this player. Players with two sources use a blended average rank.
          </p>
        </div>
      </div>

      {loading && <p style={{ marginTop: 16 }}>Loading rankings...</p>}
      {!!error && <p style={{ color: "var(--red)", marginTop: 16 }}>{error}</p>}

      {!loading && !error && rows.length === 0 && (
        <p className="muted" style={{ marginTop: 16 }}>No player data available. The backend may still be initializing.</p>
      )}

      {!loading && !error && rows.length > 0 && (
        <>
          <div className="row" style={{ marginTop: 14, gap: 8, flexWrap: "wrap" }}>
            <input
              className="input"
              placeholder="Search player"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 180 }}
            />

            <select className="select" value={posFilter} onChange={(e) => setPosFilter(e.target.value)}>
              {POS_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>

            <button className="button" onClick={copyValues}>
              Copy
            </button>
            {copyStatus ? <span className="muted" style={{ fontSize: "0.78rem", alignSelf: "center" }}>{copyStatus}</span> : null}
          </div>

          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <SortHeader col="rank" style={{ width: 56, textAlign: "center" }}>Our Rank</SortHeader>
                  <SortHeader col="name">Player</SortHeader>
                  <SortHeader col="pos">Pos</SortHeader>
                  <SortHeader col="value" style={{ textAlign: "right" }}>Our Value</SortHeader>
                  <SortHeader col="ktc" style={{ textAlign: "right", fontSize: "0.72rem" }}>KTC</SortHeader>
                  <SortHeader col="ktcRank" style={{ textAlign: "center", fontSize: "0.72rem" }}>KTC Rank</SortHeader>
                  <SortHeader col="idpTradeCalc" style={{ textAlign: "right", fontSize: "0.72rem" }}>IDPTC</SortHeader>
                  <SortHeader col="idpRank" style={{ textAlign: "center", fontSize: "0.72rem" }}>IDPTC Rank</SortHeader>
                </tr>
              </thead>
              <tbody>
                {ranked.map((row) => (
                  <tr key={row.name}>
                    <td style={{ textAlign: "center", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)" }}>
                      {row.rank}
                    </td>
                    <td style={{ fontWeight: 600, cursor: "pointer" }} onClick={() => openPlayerPopup?.(row)}>{row.name}</td>
                    <td><span className="badge">{row.pos}</span></td>
                    <td style={{ textAlign: "right", fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)" }}>
                      {Math.round(row.rankDerivedValue || row.values.full).toLocaleString()}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontSize: "0.78rem" }}>
                      {row.canonicalSites?.ktc != null ? Math.round(Number(row.canonicalSites.ktc)).toLocaleString() : "—"}
                    </td>
                    <td style={{ textAlign: "center", fontFamily: "var(--mono, monospace)", fontSize: "0.78rem", color: "var(--subtext)" }}>
                      {row.ktcRank ?? "—"}
                    </td>
                    <td style={{ textAlign: "right", fontFamily: "var(--mono, monospace)", fontSize: "0.78rem" }}>
                      {row.canonicalSites?.idpTradeCalc != null ? Math.round(Number(row.canonicalSites.idpTradeCalc)).toLocaleString() : "—"}
                    </td>
                    <td style={{ textAlign: "center", fontFamily: "var(--mono, monospace)", fontSize: "0.78rem", color: "var(--subtext)" }}>
                      {row.idpRank ?? "—"}
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
