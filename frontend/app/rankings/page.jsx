"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { VALUE_MODES } from "@/lib/trade-logic";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
  { key: "pick", label: "Picks" },
];

export default function RankingsPage() {
  const { loading, error, source, rows, siteKeys } = useDynastyData();
  const [query, setQuery] = useState("");
  const [assetFilter, setAssetFilter] = useState("all");
  const [valueMode, setValueMode] = useState("full");
  const [sort, setSort] = useState({ key: "selected", dir: "desc" });
  const [copyStatus, setCopyStatus] = useState("");

  function getNumeric(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }

  function getValueForSort(row, key) {
    if (key === "name") return row.name;
    if (key === "pos") return row.pos;
    if (key === "ourRank") return getNumeric(modelRankMap.get(row.name));
    if (key === "sites") return getNumeric(row.siteCount);
    if (key === "selected") return getNumeric(row.values?.[valueMode]);
    if (key === "raw") return getNumeric(row.values?.raw);
    if (key === "scoring") return getNumeric(row.values?.scoring);
    if (key === "scarcity") return getNumeric(row.values?.scarcity);
    if (key.startsWith("site:")) {
      const siteKey = key.slice(5);
      return getNumeric(row.canonicalSites?.[siteKey]);
    }
    return null;
  }

  function isNumericSortKey(key) {
    return key !== "name" && key !== "pos";
  }

  function compareWithEmptyLast(aVal, bVal, dir, numeric) {
    const aEmpty = aVal == null || aVal === "";
    const bEmpty = bVal == null || bVal === "";
    if (aEmpty && !bEmpty) return 1;
    if (!aEmpty && bEmpty) return -1;
    if (aEmpty && bEmpty) return 0;

    if (numeric) {
      const cmp = Number(aVal) - Number(bVal);
      if (cmp === 0) return 0;
      return dir === "asc" ? cmp : -cmp;
    }

    const cmp = String(aVal).localeCompare(String(bVal), undefined, { sensitivity: "base" });
    if (cmp === 0) return 0;
    return dir === "asc" ? cmp : -cmp;
  }

  function nextSort(key) {
    setSort((prev) => {
      if (prev.key === key) {
        return { key, dir: prev.dir === "desc" ? "asc" : "desc" };
      }
      const nextDir = key === "name" || key === "pos" || key === "ourRank" ? "asc" : "desc";
      return { key, dir: nextDir };
    });
  }

  // Stable overall model rank before any filters/sorts.
  // Priority: canonical consensus rank (from pipeline) > computed consensus
  // rank (decimal, from per-site rank blending in buildRows) > integer fallback.
  const modelRankMap = useMemo(() => {
    const map = new Map();

    rows.forEach((r) => {
      const rank = r.canonicalConsensusRank ?? r.computedConsensusRank;
      if (rank != null && Number.isFinite(rank) && rank > 0) {
        map.set(r.name, rank);
      }
    });

    // Integer fallback for rows without a consensus rank
    const sorted = [...rows].sort((a, b) => b.values.full - a.values.full);
    sorted.forEach((r, i) => {
      if (!map.has(r.name)) map.set(r.name, i + 1);
    });
    return map;
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    let list = rows;

    if (assetFilter !== "all") {
      list = list.filter((r) => r.assetClass === assetFilter);
    }
    if (q) {
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }

    return [...list].sort((a, b) => {
      const av = getValueForSort(a, sort.key);
      const bv = getValueForSort(b, sort.key);
      const cmp = compareWithEmptyLast(av, bv, sort.dir, isNumericSortKey(sort.key));
      if (cmp !== 0) return cmp;
      return a.name.localeCompare(b.name);
    });
  }, [rows, assetFilter, query, sort.key, sort.dir, valueMode, modelRankMap]);

  const tierStarts = useMemo(() => {
    const starts = new Set([0]);
    if (!filtered.length) return starts;
    const key = sort.key;
    const numeric = isNumericSortKey(key);

    if (!numeric) {
      const chunk = 24;
      for (let i = chunk; i < filtered.length; i += chunk) starts.add(i);
      return starts;
    }

    const values = filtered
      .map((r) => getValueForSort(r, key))
      .filter((v) => v != null)
      .map((v) => Number(v));

    if (values.length < 3) return starts;

    const gaps = [];
    for (let i = 1; i < values.length; i++) {
      gaps.push(Math.abs(values[i - 1] - values[i]));
    }
    const sortedGaps = [...gaps].sort((a, b) => a - b);
    const medianGap = sortedGaps[Math.floor(sortedGaps.length / 2)] || 0;
    const gapTrigger = Math.max(40, medianGap * 2.2);
    const hardTierSize = 28;

    for (let i = 1; i < filtered.length; i++) {
      const prevVal = getValueForSort(filtered[i - 1], key);
      const curVal = getValueForSort(filtered[i], key);
      if (prevVal == null || curVal == null) continue;
      const gap = Math.abs(Number(prevVal) - Number(curVal));
      if (gap >= gapTrigger || i % hardTierSize === 0) starts.add(i);
    }

    return starts;
  }, [filtered, sort.key, sort.dir, valueMode]);

  async function copyValues() {
    const headers = [
      "#",
      "Our Rank",
      "Player",
      "Pos",
      VALUE_MODES.find((m) => m.key === valueMode)?.label || "Value",
      "Raw",
      "Scoring",
      "Scarcity",
      "Sites",
      ...siteKeys,
    ];
    const lines = [headers.join(",")];

    filtered.forEach((row, idx) => {
      const ourRank = modelRankMap.get(row.name);
      const cols = [
        String(idx + 1),
        ourRank != null ? (ourRank % 1 !== 0 ? ourRank.toFixed(1) : String(Math.round(ourRank))) : "",
        `"${row.name.replace(/"/g, '""')}"`,
        row.pos,
        String(Math.round(Number(row.values?.[valueMode] || 0))),
        String(Math.round(Number(row.values?.raw || 0))),
        String(Math.round(Number(row.values?.scoring || 0))),
        String(Math.round(Number(row.values?.scarcity || 0))),
        String(Math.round(Number(row.siteCount || 0))),
      ];
      siteKeys.forEach((s) => {
        const v = Number(row.canonicalSites?.[s]);
        cols.push(Number.isFinite(v) && v > 0 ? String(Math.round(v)) : "");
      });
      lines.push(cols.join(","));
    });

    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyStatus(`Copied ${filtered.length.toLocaleString()} rows`);
      setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy failed");
      setTimeout(() => setCopyStatus(""), 1800);
    }
  }

  function formatRank(rank) {
    if (rank == null || !Number.isFinite(rank)) return "—";
    if (rank % 1 !== 0) return rank.toFixed(1);
    return String(Math.round(rank));
  }

  function thLabel(label, key) {
    const active = sort.key === key;
    const arrow = active ? (sort.dir === "desc" ? " \u2193" : " \u2191") : "";
    return `${label}${arrow}`;
  }

  return (
    <section className="card">
      <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
        <div>
          <h1 style={{ margin: 0 }}>Rankings</h1>
          <p className="muted" style={{ marginTop: 4, marginBottom: 0 }}>
            Source: {source || "unknown"} · {filtered.length.toLocaleString()} shown / {rows.length.toLocaleString()} total
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
              placeholder="Search player or pick"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 220 }}
            />

            <select className="select" value={assetFilter} onChange={(e) => setAssetFilter(e.target.value)}>
              {FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>

            <select className="select" value={valueMode} onChange={(e) => setValueMode(e.target.value)}>
              {VALUE_MODES.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
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
                  <th onClick={() => nextSort("selected")}>{thLabel("#", "selected")}</th>
                  <th onClick={() => nextSort("ourRank")} title="Consensus rank across sources (weighted median/mean blend)">{thLabel("Our Rank", "ourRank")}</th>
                  <th className="sticky-name" onClick={() => nextSort("name")}>{thLabel("Player", "name")}</th>
                  <th onClick={() => nextSort("pos")}>{thLabel("Pos", "pos")}</th>
                  <th onClick={() => nextSort("selected")}>{thLabel(VALUE_MODES.find((m) => m.key === valueMode)?.label || "Value", "selected")}</th>
                  <th onClick={() => nextSort("raw")}>{thLabel("Raw", "raw")}</th>
                  <th onClick={() => nextSort("scoring")}>{thLabel("Score", "scoring")}</th>
                  <th onClick={() => nextSort("scarcity")}>{thLabel("Scarcity", "scarcity")}</th>
                  <th onClick={() => nextSort("sites")}>{thLabel("Sites", "sites")}</th>
                  {siteKeys.map((s) => (
                    <th key={s} onClick={() => nextSort(`site:${s}`)}>{thLabel(s, `site:${s}`)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filtered.map((row, i) => (
                  <tr key={row.name}>
                    <td>{i + 1}</td>
                    <td style={{ fontWeight: 700, color: "var(--cyan)", fontFamily: "var(--mono, monospace)", textAlign: "center" }}>{formatRank(modelRankMap.get(row.name))}</td>
                    <td className="sticky-name">
                      {tierStarts.has(i) ? (
                        <div className="tier-label">Tier {Array.from(tierStarts).filter((x) => x <= i).length}</div>
                      ) : null}
                      <div style={{ fontWeight: 600 }}>{row.name}</div>
                      <div className="muted" style={{ fontSize: "0.72rem" }}>{row.marketLabel || ""}</div>
                    </td>
                    <td><span className="badge">{row.pos}</span></td>
                    <td style={{ fontWeight: 700, color: "var(--cyan)" }}>{row.values[valueMode]?.toLocaleString?.() ?? row.values[valueMode]}</td>
                    <td>{row.values.raw.toLocaleString()}</td>
                    <td>{row.values.scoring.toLocaleString()}</td>
                    <td>{row.values.scarcity.toLocaleString()}</td>
                    <td>{row.siteCount}</td>
                    {siteKeys.map((s) => {
                      const v = Number(row.canonicalSites?.[s]);
                      return <td key={`${row.name}-${s}`}>{Number.isFinite(v) && v > 0 ? Math.round(v).toLocaleString() : "-"}</td>;
                    })}
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
