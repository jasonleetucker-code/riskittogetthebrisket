"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useTeam } from "@/components/useTeam";

// ── Trade Finder ─────────────────────────────────────────────────────
// Simplified single-player flow: pick a player on your roster, pick a
// target opposing team, get back ranked return-side recommendations
// from that team's roster where the trade wins on your league's
// calibrated rankings (≥5%) but still looks fair-or-better on the
// market the counterparty consults (≤5%). Market is per-position:
// IDP Trade Calculator for DL/LB/DB, KTC for everyone else — the
// backend handles routing automatically.

const IDP_POS_RE = /^(?:DL|DE|DT|EDGE|NT|LB|ILB|OLB|MLB|DB|CB|S|SS|FS)$/i;

function marketSourceForPos(position) {
  return IDP_POS_RE.test(String(position || "").trim()) ? "idpTradeCalc" : "ktcSfTep";
}

function marketLabelForSource(source) {
  return source === "idpTradeCalc" ? "IDPTC" : "KTC";
}

function fmtValue(v) {
  return Number(v || 0).toLocaleString();
}

function fmtSignedPct(v) {
  const n = Number(v || 0);
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(1)}%`;
}

export default function AnglePage() {
  const { loading: dataLoading, error: dataError, rawData, rows } = useDynastyData();
  const { selectedLeagueKey, selectedOwnerId: activeOwnerId } = useTeam();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) =>
      String(a?.name || "").localeCompare(String(b?.name || "")),
    );
  }, [rawData]);

  // Quick lookup by canonical name → my-value, market-value, position.
  // Mirrors the source the backend reads via _value_pair, so sort keys
  // and labels match what the server returns.
  const valueByName = useMemo(() => {
    const m = new Map();
    for (const r of rows || []) {
      const name = r?.name || r?.canonicalName;
      if (!name) continue;
      const pos = r?.pos || r?.position || "";
      const source = marketSourceForPos(pos);
      const my_v = Number(r?.rankDerivedValue) || 0;
      const market_v =
        Number(r?.canonicalSites?.[source]) ||
        Number(r?.canonicalSites?.ktc) ||
        0;
      m.set(name, {
        my_value: my_v,
        market_value: market_v,
        market_source: source,
        position: pos,
      });
    }
    return m;
  }, [rows]);

  const [ownerId, setOwnerId] = useState("");
  const [playerName, setPlayerName] = useState("");
  const [playerSearch, setPlayerSearch] = useState("");
  const [targetOwnerId, setTargetOwnerId] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  // Default to the user's active team. Falls back to first team if
  // useTeam hasn't resolved yet (e.g. multi-league context still
  // booting).
  useEffect(() => {
    if (ownerId) return;
    if (activeOwnerId && teams.some((t) => String(t.ownerId) === String(activeOwnerId))) {
      setOwnerId(String(activeOwnerId));
    } else if (teams.length > 0) {
      setOwnerId(String(teams[0].ownerId || ""));
    }
  }, [activeOwnerId, teams, ownerId]);

  const myTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === String(ownerId)),
    [teams, ownerId],
  );

  const opposingTeams = useMemo(
    () => teams.filter((t) => String(t.ownerId || "") !== String(ownerId)),
    [teams, ownerId],
  );

  // Filter + sort the user's roster by the search input. Sorted by
  // my-value desc with alphabetical tie-break — high-value players
  // surface first when the search is empty, matching how the user
  // typically thinks ("who do I trade away?").
  const roster = useMemo(() => {
    if (!myTeam) return [];
    const q = playerSearch.trim().toLowerCase();
    return [...(myTeam.players || [])]
      .filter((name) => !q || name.toLowerCase().includes(q))
      .sort((a, b) => {
        const av = valueByName.get(a)?.my_value || 0;
        const bv = valueByName.get(b)?.my_value || 0;
        if (bv !== av) return bv - av;
        return a.localeCompare(b);
      });
  }, [myTeam, playerSearch, valueByName]);

  // Reset selection + results when the user changes any input. Stale
  // results from a different player/team would mislead.
  useEffect(() => {
    setResult(null);
    setErr(null);
  }, [ownerId, playerName, targetOwnerId]);

  const targetTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === String(targetOwnerId)),
    [teams, targetOwnerId],
  );

  async function findTrades() {
    if (!ownerId) {
      setErr("Pick your team.");
      return;
    }
    if (!playerName) {
      setErr("Pick a player on your roster to send.");
      return;
    }
    if (!targetOwnerId) {
      setErr("Pick a target team to trade with.");
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const body = {
        ownerId,
        playerName,
        targetTeamOwnerId: targetOwnerId,
      };
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      const res = await fetch("/api/angle/find", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        if (res.status === 503) {
          setErr(
            "Roster data not loaded for this league yet — try again in a moment.",
          );
        } else {
          setErr(data?.error || `HTTP ${res.status}`);
        }
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (e) {
      setErr(e?.message || "Network error");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  if (dataLoading) {
    return (
      <div className="page-shell">
        <p className="muted">Loading data…</p>
      </div>
    );
  }
  if (dataError) {
    return (
      <div className="page-shell">
        <p className="err-text">Failed to load data: {String(dataError)}</p>
      </div>
    );
  }

  const canSubmit = !!ownerId && !!playerName && !!targetOwnerId && !loading;
  const selected = result?.selected || null;
  const candidates = result?.candidates || [];
  const warnings = result?.warnings || [];

  return (
    <div className="page-shell angle-page">
      <div className="page-header-row">
        <div>
          <h1 className="page-title">Trade Finder</h1>
          <p className="page-subtitle muted" style={{ marginTop: 4 }}>
            Pick a player on your roster and a team to trade with — get
            back ranked return options where your league&apos;s board says
            you win and the market still looks fair to the other side.
          </p>
        </div>
      </div>

      <section className="card">
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 16,
            alignItems: "flex-end",
          }}
        >
          <label className="angle-field" style={{ minWidth: 180 }}>
            <span className="muted">Your team</span>
            <select
              value={ownerId}
              onChange={(e) => {
                setOwnerId(e.target.value);
                setPlayerName("");
                setPlayerSearch("");
              }}
              disabled={loading || teams.length === 0}
            >
              {teams.length === 0 ? (
                <option value="">No teams loaded</option>
              ) : (
                teams.map((t) => (
                  <option key={t.ownerId} value={String(t.ownerId || "")}>
                    {t.name}
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="angle-field" style={{ flex: "1 1 280px", minWidth: 240 }}>
            <span className="muted">Your player to send</span>
            <input
              type="search"
              placeholder="Search your roster…"
              value={playerSearch}
              onChange={(e) => setPlayerSearch(e.target.value)}
              disabled={loading || !myTeam}
              style={{ marginBottom: 6 }}
            />
            <select
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              disabled={loading || !myTeam || roster.length === 0}
              size={Math.min(8, Math.max(4, roster.length))}
              style={{ height: "auto" }}
            >
              {roster.length === 0 ? (
                <option value="">No players on this roster</option>
              ) : (
                roster.map((name) => {
                  const info = valueByName.get(name);
                  const pos = info?.position || "—";
                  const my = info?.my_value
                    ? `  •  ${fmtValue(info.my_value)}`
                    : "";
                  return (
                    <option key={name} value={name}>
                      {`${name}  •  ${pos}${my}`}
                    </option>
                  );
                })
              )}
            </select>
          </label>

          <label className="angle-field" style={{ minWidth: 220 }}>
            <span className="muted">Trade with</span>
            <select
              value={targetOwnerId}
              onChange={(e) => setTargetOwnerId(e.target.value)}
              disabled={loading || opposingTeams.length === 0}
            >
              <option value="">— pick a team —</option>
              {opposingTeams.map((t) => (
                <option key={t.ownerId} value={String(t.ownerId || "")}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>

          <button
            type="button"
            className="button button-primary"
            onClick={findTrades}
            disabled={!canSubmit}
            style={{ minHeight: 42 }}
          >
            {loading ? "Searching…" : "Find return options"}
          </button>
        </div>
        {err && (
          <p className="err-text" style={{ marginTop: 12 }}>
            {err}
          </p>
        )}
      </section>

      {warnings.length > 0 && (
        <section className="card" style={{ borderColor: "var(--amber, #d4a64a)" }}>
          <strong style={{ display: "block", marginBottom: 6 }}>Note</strong>
          <ul style={{ margin: 0, paddingLeft: 18 }}>
            {warnings.map((w, i) => (
              <li key={i} className="muted" style={{ fontSize: "0.85rem" }}>
                {w}
              </li>
            ))}
          </ul>
        </section>
      )}

      {selected && (
        <section className="card">
          <div
            style={{
              display: "flex",
              flexWrap: "wrap",
              alignItems: "baseline",
              gap: 12,
              justifyContent: "space-between",
            }}
          >
            <div>
              <div className="muted" style={{ fontSize: "0.75rem" }}>
                You send
              </div>
              <div
                style={{
                  fontSize: "1.15rem",
                  fontWeight: 600,
                  marginTop: 2,
                }}
              >
                {selected.name}
                {selected.position && (
                  <span
                    className="muted"
                    style={{ marginLeft: 8, fontWeight: 400, fontSize: "0.85rem" }}
                  >
                    {selected.position}
                  </span>
                )}
                {selected.team && (
                  <span
                    className="muted"
                    style={{ marginLeft: 8, fontWeight: 400, fontSize: "0.85rem" }}
                  >
                    · {selected.team}
                  </span>
                )}
              </div>
            </div>
            {selected.market_value != null && (
              <div style={{ display: "flex", gap: 18, fontSize: "0.9rem" }}>
                <div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>
                    My value
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {fmtValue(selected.my_value)}
                  </div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>
                    {marketLabelForSource(selected.market_source)}
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {fmtValue(selected.market_value)}
                  </div>
                </div>
              </div>
            )}
          </div>
        </section>
      )}

      {result && (
        <section className="card">
          <div style={{ marginBottom: 10 }}>
            <strong style={{ fontSize: "1rem" }}>
              {targetTeam ? `Get back from ${targetTeam.name}` : "Recommended return"}
            </strong>
            <div
              className="muted"
              style={{ fontSize: "0.78rem", marginTop: 2 }}
            >
              Sorted by best edge for you. Each row clears +5% on your
              board and stays within ±5% on the market the counterparty
              consults.
            </div>
          </div>

          {candidates.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              {selected
                ? `No returns from ${targetTeam?.name || "that team"} where ${selected.name} clears the +5% / ±5% bar. Try a different player or target team.`
                : "No candidates returned."}
            </p>
          ) : (
            <div style={{ display: "grid", gap: 8 }}>
              {candidates.map((c) => (
                <div
                  key={`${c.name}-${c.owner_id}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns:
                      "minmax(180px, 2fr) auto auto auto auto",
                    gap: 16,
                    alignItems: "center",
                    padding: "8px 10px",
                    border: "1px solid var(--border, #2a2a3a)",
                    borderRadius: 6,
                    background: "var(--surface, transparent)",
                  }}
                >
                  <div>
                    <div style={{ fontWeight: 600 }}>{c.name}</div>
                    <div
                      className="muted"
                      style={{ fontSize: "0.72rem", marginTop: 2 }}
                    >
                      {c.position}
                      {c.team ? ` · ${c.team}` : ""}
                    </div>
                  </div>
                  <div style={{ textAlign: "right", fontSize: "0.85rem" }}>
                    <div className="muted" style={{ fontSize: "0.65rem" }}>
                      My
                    </div>
                    <div style={{ fontWeight: 600 }}>{fmtValue(c.my_value)}</div>
                  </div>
                  <div style={{ textAlign: "right", fontSize: "0.85rem" }}>
                    <div className="muted" style={{ fontSize: "0.65rem" }}>
                      {marketLabelForSource(c.market_source)}
                    </div>
                    <div style={{ fontWeight: 600 }}>
                      {fmtValue(c.market_value)}
                    </div>
                  </div>
                  <div
                    style={{
                      textAlign: "right",
                      fontSize: "0.8rem",
                      color: "var(--cyan, #5fc7ff)",
                    }}
                    title="My-value gain (your board)"
                  >
                    {fmtSignedPct(c.my_gain_pct)} mine
                  </div>
                  <div
                    style={{
                      textAlign: "right",
                      fontSize: "0.8rem",
                      color: "var(--green, #6ee07b)",
                    }}
                    title="Edge: my-value gain minus market gain"
                  >
                    arb {fmtSignedPct(c.arb_score)}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>
      )}
    </div>
  );
}
