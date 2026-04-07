"use client";

import { useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { buildEdgeProjection } from "@/lib/edge-detection";
import { useApp } from "@/components/AppShell";

const SIGNAL_FILTERS = [
  { key: "all", label: "All" },
  { key: "BUY", label: "BUY" },
  { key: "SELL", label: "SELL" },
  { key: "HOLD", label: "HOLD" },
];

const CLASS_FILTERS = [
  { key: "all", label: "All" },
  { key: "offense", label: "OFF" },
  { key: "idp", label: "IDP" },
  { key: "pick", label: "Picks" },
];

const SORT_COLS = [
  { key: "edgePct", label: "Edge %" },
  { key: "valueEdge", label: "Value Edge" },
  { key: "modelValue", label: "Our Value" },
  { key: "actualExternal", label: "Market" },
  { key: "name", label: "Name" },
];

export default function EdgePage() {
  const { loading, error, rows } = useDynastyData();
  const { openPlayerPopup } = useApp();
  const [signalFilter, setSignalFilter] = useState("all");
  const [classFilter, setClassFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [sortCol, setSortCol] = useState("edgePct");
  const [sortDir, setSortDir] = useState("desc");

  const edgeRows = useMemo(() => {
    if (!rows.length) return [];
    return buildEdgeProjection(rows);
  }, [rows]);

  const filtered = useMemo(() => {
    let list = edgeRows;
    if (signalFilter !== "all") list = list.filter((r) => r.signal === signalFilter);
    if (classFilter !== "all") list = list.filter((r) => r.assetClass === classFilter);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      list = list.filter((r) => r.name.toLowerCase().includes(q));
    }
    // Sort
    const dir = sortDir === "asc" ? 1 : -1;
    list = [...list].sort((a, b) => {
      if (sortCol === "name") return dir * a.name.localeCompare(b.name);
      const va = Number(a[sortCol]) || 0;
      const vb = Number(b[sortCol]) || 0;
      return dir * (va - vb) || a.name.localeCompare(b.name);
    });
    return list;
  }, [edgeRows, signalFilter, classFilter, query, sortCol, sortDir]);

  // Summary counts
  const summary = useMemo(() => {
    const buys = edgeRows.filter((r) => r.signal === "BUY").length;
    const sells = edgeRows.filter((r) => r.signal === "SELL").length;
    const comparable = edgeRows.filter((r) => r.comparable).length;
    return { buys, sells, comparable, total: edgeRows.length };
  }, [edgeRows]);

  function handleSort(col) {
    if (sortCol === col) {
      setSortDir(sortDir === "desc" ? "asc" : "desc");
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  function signalBadge(signal) {
    if (signal === "BUY") return <span className="badge" style={{ background: "rgba(39,174,96,0.2)", color: "var(--green)", fontWeight: 700 }}>BUY</span>;
    if (signal === "SELL") return <span className="badge" style={{ background: "rgba(231,76,60,0.2)", color: "var(--red)", fontWeight: 700 }}>SELL</span>;
    return <span className="badge" style={{ opacity: 0.4 }}>HOLD</span>;
  }

  function confBadge(label) {
    const color = label === "HIGH" ? "var(--green)" : label === "MED" ? "var(--amber, orange)" : "var(--subtext, gray)";
    return <span style={{ color, fontWeight: 600, fontSize: "0.76rem" }}>{label}</span>;
  }

  return (
    <section className="card">
      <h1 style={{ margin: 0 }}>Edge Detection</h1>
      <p className="muted" style={{ marginTop: 4 }}>
        Identifies buy-low and sell-high opportunities by comparing our composite model rank against external market curves.
      </p>

      {loading && <p style={{ marginTop: 16 }}>Loading...</p>}
      {!!error && <p style={{ color: "var(--red)", marginTop: 16 }}>{error}</p>}

      {!loading && !error && (
        <>
          {/* Summary bar */}
          <div className="row" style={{ marginTop: 12, gap: 16 }}>
            <span className="muted" style={{ fontSize: "0.82rem" }}>
              {summary.comparable.toLocaleString()} comparable ·{" "}
              <span style={{ color: "var(--green)", fontWeight: 700 }}>{summary.buys} BUY</span> ·{" "}
              <span style={{ color: "var(--red)", fontWeight: 700 }}>{summary.sells} SELL</span> ·{" "}
              {summary.total.toLocaleString()} total
            </span>
          </div>

          {/* Filters */}
          <div className="row" style={{ marginTop: 10, gap: 8, flexWrap: "wrap" }}>
            <input
              className="input"
              placeholder="Search player"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ minWidth: 200 }}
            />
            <select className="select" value={signalFilter} onChange={(e) => setSignalFilter(e.target.value)}>
              {SIGNAL_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
            <select className="select" value={classFilter} onChange={(e) => setClassFilter(e.target.value)}>
              {CLASS_FILTERS.map((f) => (
                <option key={f.key} value={f.key}>{f.label}</option>
              ))}
            </select>
          </div>

          {/* Table */}
          <div className="table-wrap" style={{ marginTop: 12 }}>
            <table>
              <thead>
                <tr>
                  <th>Player</th>
                  <th>Pos</th>
                  <th>Source</th>
                  <th style={{ cursor: "pointer" }} onClick={() => handleSort("actualExternal")}>
                    Market Val {sortCol === "actualExternal" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </th>
                  <th style={{ cursor: "pointer" }} onClick={() => handleSort("projected")}>
                    Projected {sortCol === "projected" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </th>
                  <th style={{ cursor: "pointer" }} onClick={() => handleSort("modelValue")}>
                    Our Value {sortCol === "modelValue" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </th>
                  <th style={{ cursor: "pointer" }} onClick={() => handleSort("valueEdge")}>
                    Value Edge {sortCol === "valueEdge" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </th>
                  <th style={{ cursor: "pointer" }} onClick={() => handleSort("edgePct")}>
                    Edge % {sortCol === "edgePct" ? (sortDir === "asc" ? "▲" : "▼") : ""}
                  </th>
                  <th>Conf</th>
                  <th>Signal</th>
                </tr>
              </thead>
              <tbody>
                {filtered.slice(0, 250).map((r) => {
                  const valueEdge = Number(r.valueEdge || 0);
                  const edgePct = Number(r.edgePct || 0);
                  const edgeColor = valueEdge > 0 ? "var(--green)" : valueEdge < 0 ? "var(--red)" : "inherit";
                  const pctColor = edgePct > 0 ? "var(--green)" : edgePct < 0 ? "var(--red)" : "inherit";
                  return (
                    <tr key={r.name}>
                      <td style={{ fontWeight: 600, cursor: "pointer" }} onClick={() => openPlayerPopup?.(r.row)}>
                        {r.name}
                      </td>
                      <td><span className="badge">{r.pos}</span></td>
                      <td className="muted" style={{ fontSize: "0.76rem" }}>{r.marketLabel}</td>
                      <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.82rem" }}>
                        {r.actualExternal != null ? r.actualExternal.toLocaleString() : "---"}
                      </td>
                      <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.82rem" }}>
                        {r.projected != null ? r.projected.toLocaleString() : "---"}
                      </td>
                      <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.82rem" }}>
                        {r.modelValue.toLocaleString()}
                      </td>
                      <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.82rem", color: edgeColor, fontWeight: 600 }}>
                        {r.comparable ? `${valueEdge > 0 ? "+" : ""}${Math.round(valueEdge).toLocaleString()}` : "---"}
                      </td>
                      <td style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.82rem", color: pctColor, fontWeight: 600 }}>
                        {r.comparable ? `${edgePct > 0 ? "+" : ""}${edgePct.toFixed(1)}%` : "---"}
                      </td>
                      <td>{r.comparable ? confBadge(r.confidenceLabel) : <span className="muted">---</span>}</td>
                      <td>{signalBadge(r.signal)}</td>
                    </tr>
                  );
                })}
                {filtered.length === 0 && (
                  <tr>
                    <td colSpan={10} className="muted" style={{ textAlign: "center", padding: 20 }}>
                      No players match current filters.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          {filtered.length > 250 && (
            <p className="muted" style={{ marginTop: 8, fontSize: "0.76rem" }}>
              Showing 250 of {filtered.length.toLocaleString()} results. Use filters to narrow.
            </p>
          )}
        </>
      )}
    </section>
  );
}
