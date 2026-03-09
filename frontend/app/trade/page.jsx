"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

const VALUE_MODES = [
  { key: "full", label: "Fully Adjusted" },
  { key: "raw", label: "Raw" },
  { key: "scoring", label: "Scoring" },
  { key: "scarcity", label: "Scarcity" },
];

const STORAGE_KEY = "next_trade_workspace_v1";
const RECENT_KEY = "next_trade_recent_assets_v1";

function verdictFromGap(gap) {
  const abs = Math.abs(gap);
  if (abs < 200) return "Near even";
  if (abs < 600) return "Lean";
  if (abs < 1200) return "Strong lean";
  return "Major gap";
}

function colorFromGap(gap) {
  if (Math.abs(gap) < 200) return "";
  return gap > 0 ? "green" : "red";
}

export default function TradePage() {
  const { loading, error, rows } = useDynastyData();
  const [valueMode, setValueMode] = useState("full");
  const [sideA, setSideA] = useState([]);
  const [sideB, setSideB] = useState([]);
  const [activeSide, setActiveSide] = useState("A");
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerQuery, setPickerQuery] = useState("");
  const [pickerFilter, setPickerFilter] = useState("all");
  const [recentNames, setRecentNames] = useState([]);
  const [hydrated, setHydrated] = useState(false);
  const pickerInputRef = useRef(null);

  const rowByName = useMemo(() => {
    const m = new Map();
    rows.forEach((r) => m.set(r.name, r));
    return m;
  }, [rows]);

  useEffect(() => {
    try {
      const rawRecent = localStorage.getItem(RECENT_KEY);
      if (rawRecent) {
        const parsed = JSON.parse(rawRecent);
        if (Array.isArray(parsed)) setRecentNames(parsed.filter((x) => typeof x === "string").slice(0, 20));
      }
    } catch {
      // ignore localStorage parse errors
    }
  }, []);

  useEffect(() => {
    if (!rows.length || hydrated) return;
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw);
        if (parsed && typeof parsed === "object") {
          const nextMode = String(parsed.valueMode || "full");
          if (VALUE_MODES.some((m) => m.key === nextMode)) setValueMode(nextMode);
          setActiveSide(parsed.activeSide === "B" ? "B" : "A");

          const a = Array.isArray(parsed.sideA) ? parsed.sideA.map((n) => rowByName.get(n)).filter(Boolean) : [];
          const b = Array.isArray(parsed.sideB) ? parsed.sideB.map((n) => rowByName.get(n)).filter(Boolean) : [];
          setSideA(a);
          setSideB(b);
        }
      }
    } catch {
      // ignore localStorage parse errors
    } finally {
      setHydrated(true);
    }
  }, [rows, hydrated, rowByName]);

  useEffect(() => {
    if (!hydrated) return;
    const payload = {
      valueMode,
      activeSide,
      sideA: sideA.map((r) => r.name),
      sideB: sideB.map((r) => r.name),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
  }, [hydrated, valueMode, activeSide, sideA, sideB]);

  useEffect(() => {
    if (pickerOpen && pickerInputRef.current) {
      pickerInputRef.current.focus();
    }
  }, [pickerOpen]);

  const totalA = useMemo(() => sideA.reduce((sum, r) => sum + Number(r.values?.[valueMode] || 0), 0), [sideA, valueMode]);
  const totalB = useMemo(() => sideB.reduce((sum, r) => sum + Number(r.values?.[valueMode] || 0), 0), [sideB, valueMode]);
  const gap = totalA - totalB;

  const pickerRows = useMemo(() => {
    const q = pickerQuery.trim().toLowerCase();
    const isInTrade = new Set([...sideA, ...sideB].map((r) => r.name));

    let list = rows.filter((r) => !isInTrade.has(r.name));
    if (pickerFilter !== "all") list = list.filter((r) => r.assetClass === pickerFilter);
    if (q) list = list.filter((r) => r.name.toLowerCase().includes(q));

    return list.slice(0, 80);
  }, [rows, sideA, sideB, pickerQuery, pickerFilter]);

  const recentRows = useMemo(() => {
    return recentNames.map((n) => rowByName.get(n)).filter(Boolean);
  }, [recentNames, rowByName]);

  function addRecent(name) {
    setRecentNames((prev) => {
      const next = [name, ...prev.filter((x) => x !== name)].slice(0, 20);
      localStorage.setItem(RECENT_KEY, JSON.stringify(next));
      return next;
    });
  }

  function addToSide(row, side) {
    if (!row) return;
    const inA = sideA.some((r) => r.name === row.name);
    const inB = sideB.some((r) => r.name === row.name);
    if (inA || inB) return;
    if (side === "A") {
      setSideA((prev) => (prev.some((r) => r.name === row.name) ? prev : [...prev, row]));
    } else {
      setSideB((prev) => (prev.some((r) => r.name === row.name) ? prev : [...prev, row]));
    }
    addRecent(row.name);
  }

  function addToActiveSide(row) {
    addToSide(row, activeSide);
  }

  function removeFromSide(name, side) {
    if (side === "A") setSideA((prev) => prev.filter((r) => r.name !== name));
    else setSideB((prev) => prev.filter((r) => r.name !== name));
  }

  function clearTrade() {
    setSideA([]);
    setSideB([]);
  }

  function swapSides() {
    setSideA(sideB);
    setSideB(sideA);
    setActiveSide((s) => (s === "A" ? "B" : "A"));
  }

  function openPickerFor(side) {
    setActiveSide(side);
    setPickerOpen(true);
  }

  return (
    <section className="card">
      <h1 style={{ marginTop: 0 }}>Trade Builder</h1>
      <p className="muted" style={{ marginTop: 4 }}>Persistent mobile workspace with live verdict and fast add/remove flow.</p>

      {loading && <p>Loading player pool...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

      {!loading && !error && (
        <>
          <div className="row" style={{ marginBottom: 10 }}>
            <select className="select" value={valueMode} onChange={(e) => setValueMode(e.target.value)}>
              {VALUE_MODES.map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
            <button className="button" onClick={swapSides}>Swap Sides</button>
            <button className="button" onClick={clearTrade}>Clear Trade</button>
          </div>

          <div className="row" style={{ alignItems: "stretch", paddingBottom: 78 }}>
            <div className="card" style={{ flex: 1, minWidth: 280 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Side A</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div className="value">{Math.round(totalA).toLocaleString()}</div>
                  <button className="button" onClick={() => openPickerFor("A")}>+ Add</button>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {sideA.map((r) => (
                  <div className="asset-row" key={`A-${r.name}`}>
                    <div>
                      <div className="asset-name">{r.name}</div>
                      <div className="asset-meta">{r.pos} · {r.values[valueMode].toLocaleString()}</div>
                    </div>
                    <button className="button" onClick={() => removeFromSide(r.name, "A")}>Remove</button>
                  </div>
                ))}
                {sideA.length === 0 && <div className="muted">No assets yet.</div>}
              </div>
            </div>

            <div className="card" style={{ flex: 1, minWidth: 280 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0 }}>Side B</h3>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div className="value">{Math.round(totalB).toLocaleString()}</div>
                  <button className="button" onClick={() => openPickerFor("B")}>+ Add</button>
                </div>
              </div>
              <div className="list" style={{ marginTop: 10 }}>
                {sideB.map((r) => (
                  <div className="asset-row" key={`B-${r.name}`}>
                    <div>
                      <div className="asset-name">{r.name}</div>
                      <div className="asset-meta">{r.pos} · {r.values[valueMode].toLocaleString()}</div>
                    </div>
                    <button className="button" onClick={() => removeFromSide(r.name, "B")}>Remove</button>
                  </div>
                ))}
                {sideB.length === 0 && <div className="muted">No assets yet.</div>}
              </div>
            </div>
          </div>

          <div className="trade-sticky-tray">
            <div className="trade-tray-main">
              <div>
                <div className="label">Side A</div>
                <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(totalA).toLocaleString()}</div>
              </div>
              <div>
                <div className="label">Side B</div>
                <div className="value" style={{ fontSize: "1.0rem" }}>{Math.round(totalB).toLocaleString()}</div>
              </div>
              <div style={{ minWidth: 130 }}>
                <div className="label">Verdict</div>
                <div className={`verdict ${colorFromGap(gap)}`}>{verdictFromGap(gap)}</div>
                <div className="muted" style={{ fontSize: "0.72rem" }}>Gap {Math.round(gap).toLocaleString()}</div>
              </div>
            </div>
          </div>

          {pickerOpen && (
            <div className="picker-overlay" onClick={() => setPickerOpen(false)}>
              <div className="picker-sheet" onClick={(e) => e.stopPropagation()}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 10 }}>
                  <div>
                    <h3 style={{ margin: 0 }}>Add Asset to Side {activeSide}</h3>
                    <p className="muted" style={{ margin: "4px 0 0 0", fontSize: "0.76rem" }}>Tap a player/pick to add instantly.</p>
                  </div>
                  <button className="button" onClick={() => setPickerOpen(false)}>Close</button>
                </div>

                <div className="row" style={{ marginTop: 10 }}>
                  <input
                    ref={pickerInputRef}
                    className="input"
                    placeholder="Search player or pick"
                    value={pickerQuery}
                    onChange={(e) => setPickerQuery(e.target.value)}
                    style={{ minWidth: 220, flex: 1 }}
                  />
                  <select className="select" value={pickerFilter} onChange={(e) => setPickerFilter(e.target.value)}>
                    <option value="all">All</option>
                    <option value="offense">OFF</option>
                    <option value="idp">IDP</option>
                    <option value="pick">Picks</option>
                  </select>
                </div>

                {!pickerQuery && recentRows.length > 0 && (
                  <div style={{ marginTop: 10 }}>
                    <div className="label" style={{ marginBottom: 6 }}>Recent</div>
                    <div className="list">
                      {recentRows.slice(0, 8).map((r) => (
                        <button key={`recent-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                          <div>
                            <div className="asset-name">{r.name}</div>
                            <div className="asset-meta">{r.pos} · {r.values[valueMode].toLocaleString()}</div>
                          </div>
                          <span className="badge">Add</span>
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <div className="list" style={{ marginTop: 10, maxHeight: "52vh", overflow: "auto", paddingRight: 4 }}>
                  {pickerRows.map((r) => (
                    <button key={`pick-${r.name}`} className="asset-row button-reset" onClick={() => addToActiveSide(r)}>
                      <div>
                        <div className="asset-name">{r.name}</div>
                        <div className="asset-meta">{r.pos} · {r.values[valueMode].toLocaleString()}</div>
                      </div>
                      <span className="badge">Add</span>
                    </button>
                  ))}
                  {pickerRows.length === 0 && <div className="muted">No assets match.</div>}
                </div>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
