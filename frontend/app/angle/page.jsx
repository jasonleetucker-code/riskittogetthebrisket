"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useTeam } from "@/components/useTeam";

// ── Trade Finder ─────────────────────────────────────────────────────
// Pick one or more players on your roster, optionally pick a target
// team, get back ranked counter-packages where the trade wins on your
// league's calibrated rankings (default ≥5%) but still looks fair-or-
// better on the market the counterparty consults (default ≤5%). Market
// is per-position: IDP Trade Calculator for DL/LB/DB, KTC for everyone
// else — backend handles routing automatically.

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

  // canonicalName → my-value, market-value, position. Mirrors the
  // source the backend reads via _value_pair so labels and order match.
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
  const [playerNames, setPlayerNames] = useState(() => new Set());
  const [playerSearch, setPlayerSearch] = useState("");
  const [targetOwnerId, setTargetOwnerId] = useState(""); // "" → any team
  const [minMyGainPct, setMinMyGainPct] = useState(5);
  const [maxMarketGainPct, setMaxMarketGainPct] = useState(5);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (ownerId) return;
    if (
      activeOwnerId &&
      teams.some((t) => String(t.ownerId) === String(activeOwnerId))
    ) {
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

  // Filter + sort the user's roster by the search input — high my-value
  // first, alpha tie-break.
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

  // Wipe selected players + stale results when the user switches teams
  // — an offer from the old team is incoherent with the new roster.
  useEffect(() => {
    setPlayerNames(new Set());
    setResult(null);
    setErr(null);
  }, [ownerId]);

  function togglePlayer(name) {
    setPlayerNames((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  const playerNameList = useMemo(() => Array.from(playerNames), [playerNames]);

  const offerTotals = useMemo(() => {
    let my = 0;
    let market = 0;
    for (const name of playerNameList) {
      const info = valueByName.get(name);
      if (info) {
        my += info.my_value || 0;
        market += info.market_value || 0;
      }
    }
    return { my, market };
  }, [playerNameList, valueByName]);

  const targetTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === String(targetOwnerId)),
    [teams, targetOwnerId],
  );

  async function findTrades() {
    if (!ownerId) {
      setErr("Pick your team.");
      return;
    }
    if (playerNameList.length === 0) {
      setErr("Pick at least one player on your roster to send.");
      return;
    }
    setLoading(true);
    setErr(null);
    try {
      const body = {
        mode: "offer",
        ownerId,
        playerNames: playerNameList,
        minMyGainPct: Number(minMyGainPct),
        maxMarketGainPct: Number(maxMarketGainPct),
      };
      if (targetOwnerId) body.targetTeamOwnerIds = [targetOwnerId];
      if (selectedLeagueKey) body.leagueKey = selectedLeagueKey;
      const res = await fetch("/api/angle/packages", {
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

  const canSubmit = !!ownerId && playerNameList.length > 0 && !loading;
  const offer = result?.offer || null;
  const candidates = result?.candidates || [];
  const warnings = result?.warnings || [];

  return (
    <div className="page-shell angle-page">
      <div className="page-header-row">
        <div>
          <h1 className="page-title">Trade Finder</h1>
          <p className="page-subtitle muted" style={{ marginTop: 4 }}>
            Pick one or more players from your roster — optionally pick a
            team to focus on — and get back ranked return packages where
            your league&apos;s board says you win and the market still
            looks fair to the other side.
          </p>
        </div>
      </div>

      <section className="card">
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(180px, 1fr) minmax(280px, 2fr) minmax(220px, 1fr)",
            gap: 16,
            alignItems: "flex-start",
          }}
        >
          <label className="angle-field">
            <span className="muted">Your team</span>
            <select
              value={ownerId}
              onChange={(e) => setOwnerId(e.target.value)}
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

          <div className="angle-field">
            <span className="muted">
              Your players to send{" "}
              <span style={{ fontWeight: 400 }}>
                ({playerNameList.length} selected)
              </span>
            </span>
            <input
              type="search"
              placeholder="Search your roster…"
              value={playerSearch}
              onChange={(e) => setPlayerSearch(e.target.value)}
              disabled={loading || !myTeam}
              style={{ marginBottom: 6 }}
            />
            <div
              style={{
                maxHeight: 220,
                overflowY: "auto",
                border: "1px solid var(--border, #2a2a3a)",
                borderRadius: 6,
                padding: "4px 6px",
                background: "var(--surface-2, transparent)",
              }}
            >
              {roster.length === 0 ? (
                <div className="muted" style={{ padding: 8, fontSize: "0.85rem" }}>
                  {myTeam ? "No matches" : "No players on this roster"}
                </div>
              ) : (
                roster.map((name) => {
                  const info = valueByName.get(name);
                  const checked = playerNames.has(name);
                  return (
                    <label
                      key={name}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 8,
                        padding: "4px 4px",
                        cursor: "pointer",
                        fontSize: "0.85rem",
                        borderRadius: 4,
                        background: checked
                          ? "rgba(95, 199, 255, 0.08)"
                          : "transparent",
                      }}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => togglePlayer(name)}
                        disabled={loading}
                      />
                      <span style={{ flex: 1 }}>
                        {name}
                        <span
                          className="muted"
                          style={{ marginLeft: 6, fontSize: "0.78rem" }}
                        >
                          {info?.position || "—"}
                        </span>
                      </span>
                      {info?.my_value ? (
                        <span style={{ fontVariantNumeric: "tabular-nums" }}>
                          {fmtValue(info.my_value)}
                        </span>
                      ) : null}
                    </label>
                  );
                })
              )}
            </div>
            {playerNameList.length > 1 && offerTotals.my > 0 && (
              <div
                className="muted"
                style={{ marginTop: 4, fontSize: "0.78rem" }}
              >
                Offer total: {fmtValue(offerTotals.my)} my ·{" "}
                {fmtValue(offerTotals.market)} market
              </div>
            )}
          </div>

          <label className="angle-field">
            <span className="muted">Trade with</span>
            <select
              value={targetOwnerId}
              onChange={(e) => setTargetOwnerId(e.target.value)}
              disabled={loading || opposingTeams.length === 0}
            >
              <option value="">Any team</option>
              {opposingTeams.map((t) => (
                <option key={t.ownerId} value={String(t.ownerId || "")}>
                  {t.name}
                </option>
              ))}
            </select>
            <details style={{ marginTop: 12 }}>
              <summary
                className="muted"
                style={{ cursor: "pointer", fontSize: "0.82rem" }}
              >
                Advanced options
              </summary>
              <div
                style={{
                  display: "grid",
                  gap: 8,
                  marginTop: 8,
                  fontSize: "0.85rem",
                }}
              >
                <label
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                  }}
                >
                  <span className="muted" style={{ fontSize: "0.78rem" }}>
                    Min my-value gain %{" "}
                    <span style={{ fontStyle: "italic" }}>
                      (counter beats offer by ≥)
                    </span>
                  </span>
                  <input
                    type="number"
                    step="1"
                    min="0"
                    value={minMyGainPct}
                    onChange={(e) => setMinMyGainPct(e.target.value)}
                    disabled={loading}
                  />
                </label>
                <label
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    gap: 4,
                  }}
                >
                  <span className="muted" style={{ fontSize: "0.78rem" }}>
                    Max market gap %{" "}
                    <span style={{ fontStyle: "italic" }}>
                      (KTC for offense, IDPTC for IDP)
                    </span>
                  </span>
                  <input
                    type="number"
                    step="1"
                    value={maxMarketGainPct}
                    onChange={(e) => setMaxMarketGainPct(e.target.value)}
                    disabled={loading}
                  />
                </label>
              </div>
            </details>
          </label>
        </div>

        <div style={{ marginTop: 14, display: "flex", gap: 12, alignItems: "center" }}>
          <button
            type="button"
            className="button button-primary"
            onClick={findTrades}
            disabled={!canSubmit}
            style={{ minHeight: 42 }}
          >
            {loading
              ? "Searching…"
              : `Find return options${playerNameList.length ? ` (${playerNameList.length})` : ""}`}
          </button>
          {playerNameList.length > 0 && !loading && (
            <button
              type="button"
              className="button"
              onClick={() => setPlayerNames(new Set())}
              style={{ minHeight: 42 }}
            >
              Clear selection
            </button>
          )}
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

      {offer && (
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
            <div style={{ flex: 1, minWidth: 220 }}>
              <div className="muted" style={{ fontSize: "0.75rem" }}>
                You send
              </div>
              <ul
                style={{
                  margin: "4px 0 0",
                  paddingLeft: 18,
                  fontSize: "0.95rem",
                }}
              >
                {(offer.players || []).map((p) => (
                  <li key={p.name}>
                    <strong>{p.name}</strong>{" "}
                    <span className="muted" style={{ fontSize: "0.78rem" }}>
                      {p.position}
                    </span>{" "}
                    <span style={{ fontSize: "0.82rem" }}>
                      — {fmtValue(p.my_value)} my ·{" "}
                      {fmtValue(p.market_value)}{" "}
                      {marketLabelForSource(p.market_source)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
            {(offer.my_total || offer.market_total) && (
              <div style={{ display: "flex", gap: 18, fontSize: "0.9rem" }}>
                <div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>
                    My total
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {fmtValue(offer.my_total)}
                  </div>
                </div>
                <div>
                  <div className="muted" style={{ fontSize: "0.7rem" }}>
                    Market total
                  </div>
                  <div style={{ fontWeight: 600 }}>
                    {fmtValue(offer.market_total)}
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
              {targetTeam
                ? `Return options from ${targetTeam.name}`
                : "Return options from any team"}
            </strong>
            <div className="muted" style={{ fontSize: "0.78rem", marginTop: 2 }}>
              Sorted by best edge. Each package clears +
              {Number(minMyGainPct)}% on your board and stays within ±
              {Number(maxMarketGainPct)}% on the market the other side
              consults.
            </div>
          </div>

          {candidates.length === 0 ? (
            <p className="muted" style={{ margin: 0 }}>
              No return packages clear the +{Number(minMyGainPct)}% / ±
              {Number(maxMarketGainPct)}% bar with this offer
              {targetTeam ? ` against ${targetTeam.name}` : ""}. Try a
              different selection, loosen the percentages under
              Advanced, or remove the team filter.
            </p>
          ) : (
            <div style={{ display: "grid", gap: 10 }}>
              {candidates.map((c, idx) => (
                <div
                  key={`${c.owner_id}-${idx}-${(c.players || []).map((p) => p.name).join("|")}`}
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr auto",
                    gap: 16,
                    alignItems: "center",
                    padding: "10px 12px",
                    border: "1px solid var(--border, #2a2a3a)",
                    borderRadius: 6,
                    background: "var(--surface, transparent)",
                  }}
                >
                  <div>
                    <div
                      className="muted"
                      style={{ fontSize: "0.7rem", marginBottom: 2 }}
                    >
                      From {c.team || "(unknown)"} · {c.size}{" "}
                      {c.size === 1 ? "player" : "players"}
                    </div>
                    <ul style={{ margin: 0, paddingLeft: 18 }}>
                      {(c.players || []).map((p) => (
                        <li key={p.name} style={{ fontSize: "0.92rem" }}>
                          <strong>{p.name}</strong>{" "}
                          <span
                            className="muted"
                            style={{ fontSize: "0.78rem" }}
                          >
                            {p.position}
                          </span>{" "}
                          <span style={{ fontSize: "0.8rem" }}>
                            — {fmtValue(p.my_value)} my ·{" "}
                            {fmtValue(p.market_value)}{" "}
                            {marketLabelForSource(p.market_source)}
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      alignItems: "flex-end",
                      gap: 2,
                      fontSize: "0.82rem",
                      minWidth: 130,
                    }}
                  >
                    <div className="muted" style={{ fontSize: "0.7rem" }}>
                      {fmtValue(c.my_total)} my · {fmtValue(c.market_total)}{" "}
                      market
                    </div>
                    <div style={{ color: "var(--cyan, #5fc7ff)" }}>
                      {fmtSignedPct(c.my_gain_pct)} mine
                    </div>
                    <div className="muted" style={{ fontSize: "0.78rem" }}>
                      {fmtSignedPct(c.market_gain_pct)} market
                    </div>
                    <div
                      style={{ color: "var(--green, #6ee07b)", fontWeight: 600 }}
                    >
                      arb {fmtSignedPct(c.arb_score)}
                    </div>
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
