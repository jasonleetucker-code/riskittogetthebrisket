"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

// ── Angle ───────────────────────────────────────────────────────────
// Multi-player trade-target arbitrage.
// Pick your team → check off any players you'd offer → get counter-
// packages from other teams, sized within ±1 of your offer, where
// your league's calibrated rankings say win but the market the
// counterparty consults says fair-or-better. "Market" is per-position:
// IDP Trade Calculator for DL/LB/DB, KTC for everyone else.

const DEFAULT_MIN_MY = 5;
const DEFAULT_MAX_MARKET = 5;
const DEFAULT_LIMIT = 50;
const DEFAULT_PER_TEAM = 4;
const DEFAULT_MIN_PLAYER_VALUE = 3000;
const POSITION_FILTERS = ["QB", "RB", "WR", "TE", "DL", "LB", "DB"];
const IDP_POS_RE = /^(?:DL|DE|DT|EDGE|NT|LB|ILB|OLB|MLB|DB|CB|S|SS|FS)$/i;

function marketSourceForPos(position) {
  return IDP_POS_RE.test(String(position || "").trim()) ? "idpTradeCalc" : "ktc";
}

function marketLabelForSource(source) {
  return source === "idpTradeCalc" ? "IDPTC" : "KTC";
}

export default function AnglePage() {
  const { loading: dataLoading, error: dataError, rawData, rows } = useDynastyData();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) =>
      String(a?.name || "").localeCompare(String(b?.name || "")),
    );
  }, [rawData]);

  // Quick lookup: canonical name → { my_value, market_value, market_source, position }.
  // "Market" source is IDPTC for IDP positions, KTC for everyone else
  // — matches the per-position market anchor the backend uses.
  const valueByName = useMemo(() => {
    const m = new Map();
    for (const r of rows || []) {
      const name = r?.name || r?.canonicalName;
      if (!name) continue;
      const pos = r?.pos || r?.position || "";
      const source = marketSourceForPos(pos);
      const my_v = Number(r?.rankDerivedValue) || 0;
      const market_v = Number(r?.canonicalSites?.[source]) || 0;
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
  const [rosterFilter, setRosterFilter] = useState("");
  const [offer, setOffer] = useState(() => new Set());
  const [minMyGainPct, setMinMyGainPct] = useState(DEFAULT_MIN_MY);
  const [maxMarketGainPct, setMaxMarketGainPct] = useState(DEFAULT_MAX_MARKET);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [perTeamLimit, setPerTeamLimit] = useState(DEFAULT_PER_TEAM);
  const [positionFilters, setPositionFilters] = useState(() => new Set());
  const [minPlayerValue, setMinPlayerValue] = useState(DEFAULT_MIN_PLAYER_VALUE);
  // Up to 2 opposing teams the user explicitly wants to trade with.
  const [targetOwners, setTargetOwners] = useState(["", ""]);
  // Seed players keyed by ownerId — players that MUST appear in
  // every counter-package when a target team is selected.
  const [seedsByOwner, setSeedsByOwner] = useState({});
  // "offer" (default): user picks players from their roster and we
  // search opposing rosters for counter-packages.
  // "acquire": user picks players on opposing rosters to acquire and
  // we search their own roster for offer-side packages. Lets the
  // user skip selecting their own players first.
  const [mode, setMode] = useState("offer");
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!ownerId && teams.length > 0) {
      setOwnerId(String(teams[0].ownerId || ""));
    }
  }, [teams, ownerId]);

  const selectedTeam = useMemo(
    () => teams.find((t) => String(t.ownerId || "") === ownerId),
    [teams, ownerId],
  );

  const roster = useMemo(() => {
    if (!selectedTeam) return [];
    return [...(selectedTeam.players || [])]
      .filter(
        (name) =>
          !rosterFilter.trim() ||
          name.toLowerCase().includes(rosterFilter.trim().toLowerCase()),
      )
      .sort((a, b) => {
        const av = valueByName.get(a)?.my_value || 0;
        const bv = valueByName.get(b)?.my_value || 0;
        if (bv !== av) return bv - av;  // high value first
        return a.localeCompare(b);        // ties → alphabetical
      });
  }, [selectedTeam, rosterFilter, valueByName]);

  // Reset offer whenever the team changes — an offer on the old team
  // isn't coherent with the new roster.
  useEffect(() => {
    setOffer(new Set());
    setResult(null);
    setErr(null);
  }, [ownerId]);

  // Clear stale results and errors when flipping modes so the page
  // doesn't render offer-mode candidates after switching to acquire.
  useEffect(() => {
    setResult(null);
    setErr(null);
  }, [mode]);

  const offerList = useMemo(() => Array.from(offer), [offer]);

  const offerTotals = useMemo(() => {
    let my = 0;
    let market = 0;
    for (const name of offerList) {
      const info = valueByName.get(name);
      if (info) {
        my += info.my_value || 0;
        market += info.market_value || 0;
      }
    }
    return { my, market };
  }, [offerList, valueByName]);

  function toggleOffer(name) {
    setOffer((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  function togglePosition(pos) {
    setPositionFilters((prev) => {
      const next = new Set(prev);
      if (next.has(pos)) next.delete(pos);
      else next.add(pos);
      return next;
    });
  }

  function setTargetOwnerAt(slot, value) {
    setTargetOwners((prev) => {
      const next = [...prev];
      next[slot] = value;
      return next;
    });
  }

  function toggleSeed(ownerIdKey, playerName) {
    setSeedsByOwner((prev) => {
      const current = new Set(prev[ownerIdKey] || []);
      if (current.has(playerName)) current.delete(playerName);
      else current.add(playerName);
      return { ...prev, [ownerIdKey]: current };
    });
  }

  const activeTargetOwnerIds = useMemo(
    () =>
      targetOwners
        .filter((id) => id && id !== ownerId)
        // Deduplicate so selecting the same team twice doesn't double-count.
        .reduce((acc, id) => (acc.includes(id) ? acc : [...acc, id]), []),
    [targetOwners, ownerId],
  );

  const activeSeedNames = useMemo(() => {
    const out = [];
    for (const id of activeTargetOwnerIds) {
      for (const name of seedsByOwner[id] || []) out.push(name);
    }
    return out;
  }, [activeTargetOwnerIds, seedsByOwner]);

  async function findAngles() {
    if (!ownerId) {
      setErr("Pick your team.");
      return;
    }
    if (mode === "offer" && offerList.length === 0) {
      setErr("Check at least one player from your roster to offer.");
      return;
    }
    if (mode === "acquire" && activeSeedNames.length === 0) {
      setErr(
        "Pick a target team and check at least one player you want to acquire.",
      );
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const body =
        mode === "acquire"
          ? {
              mode: "acquire",
              ownerId,
              acquirePlayerNames: activeSeedNames,
              minMyGainPct: Number(minMyGainPct),
              maxMarketGainPct: Number(maxMarketGainPct),
              limit: Number(limit),
              minPlayerMyValue: Number(minPlayerValue),
              positions: Array.from(positionFilters),
            }
          : {
              mode: "offer",
              ownerId,
              playerNames: offerList,
              minMyGainPct: Number(minMyGainPct),
              maxMarketGainPct: Number(maxMarketGainPct),
              limit: Number(limit),
              perTeamLimit: Number(perTeamLimit),
              minPlayerMyValue: Number(minPlayerValue),
              positions: Array.from(positionFilters),
              targetTeamOwnerIds: activeTargetOwnerIds,
              seedPlayerNames: activeSeedNames,
            };
      const res = await fetch("/api/angle/packages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data?.error) {
        setErr(data?.error || `HTTP ${res.status}`);
        setResult(null);
      } else {
        setResult(data);
      }
    } catch (e) {
      setErr(e?.message || "Network error");
      setResult(null);
    } finally {
      setBusy(false);
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

  return (
    <div className="page-shell angle-page">
      <div className="page-header-row">
        <div>
          <h1 className="page-title">Angle</h1>
          <p className="page-subtitle muted" style={{ marginTop: 4 }}>
            {mode === "acquire"
              ? "Pick players on another team you want to acquire; get back offer packages from your roster (±1 in size) that win on your rankings but look fair-or-better on the market the counterparty consults (IDPTC for IDP, KTC otherwise)."
              : "Build an offer from your roster; get counter-packages (±1 in size) that win on your rankings but look fair-or-better on the market the counterparty consults (IDPTC for IDP, KTC otherwise)."}
          </p>
          <div className="angle-pill-row" style={{ marginTop: 10 }}>
            <button
              type="button"
              className={`angle-pill ${mode === "offer" ? "angle-pill-active" : ""}`}
              onClick={() => setMode("offer")}
              disabled={busy}
              title="Build an offer from your roster and get counter-packages from other teams."
            >
              Build an offer
            </button>
            <button
              type="button"
              className={`angle-pill ${mode === "acquire" ? "angle-pill-active" : ""}`}
              onClick={() => setMode("acquire")}
              disabled={busy}
              title="Pick players you want to acquire from another team; get offer packages from your roster."
            >
              Acquire players
            </button>
          </div>
        </div>
      </div>

      <section className="card angle-controls">
        <div className="angle-controls-row">
          <label className="angle-field">
            <span className="muted">Your team</span>
            <select
              value={ownerId}
              onChange={(e) => setOwnerId(e.target.value)}
              disabled={busy || teams.length === 0}
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
          <label className="angle-field">
            <span className="muted">
              Min my-value gain %{" "}
              <span className="angle-field-hint">(counter beats offer by ≥)</span>
            </span>
            <input
              type="number"
              value={minMyGainPct}
              step="1"
              min="0"
              onChange={(e) => setMinMyGainPct(e.target.value)}
              disabled={busy}
            />
          </label>
          <label className="angle-field">
            <span className="muted">
              Max market gap %{" "}
              <span className="angle-field-hint">(IDPTC for IDP / KTC for offense)</span>
            </span>
            <input
              type="number"
              value={maxMarketGainPct}
              step="1"
              onChange={(e) => setMaxMarketGainPct(e.target.value)}
              disabled={busy}
            />
          </label>
          {mode === "offer" && (
            <label className="angle-field">
              <span className="muted">
                Max per team{" "}
                <span className="angle-field-hint">(top N from each opposing roster)</span>
              </span>
              <input
                type="number"
                value={perTeamLimit}
                min="1"
                max="50"
                onChange={(e) => setPerTeamLimit(e.target.value)}
                disabled={busy}
              />
            </label>
          )}
          <label className="angle-field">
            <span className="muted">Total results</span>
            <input
              type="number"
              value={limit}
              min="1"
              max="200"
              onChange={(e) => setLimit(e.target.value)}
              disabled={busy}
            />
          </label>
          <button
            type="button"
            className="button button-primary angle-go"
            onClick={findAngles}
            disabled={
              busy ||
              !ownerId ||
              (mode === "offer"
                ? offerList.length === 0
                : activeSeedNames.length === 0)
            }
          >
            {busy
              ? "Searching…"
              : mode === "acquire"
                ? `Find offer packages (${activeSeedNames.length})`
                : `Find counter-packages (${offerList.length})`}
          </button>
        </div>
        {err && (
          <p className="err-text" style={{ marginTop: 8 }}>
            {err}
          </p>
        )}
      </section>

      <section className="card angle-filter-card">
        <div className="angle-filter-head">
          <strong>
            {mode === "acquire"
              ? "Offer package filters"
              : "Counter-package filters"}
          </strong>
          <span className="muted">
            {mode === "acquire"
              ? "Narrow the offer-side candidates the search considers from your roster."
              : "Narrow the candidates the search considers from other teams."}
          </span>
        </div>
        <div className="angle-filter-row">
          <div className="angle-filter-group">
            <span className="muted">Positions wanted</span>
            <div className="angle-pill-row">
              {POSITION_FILTERS.map((pos) => {
                const active = positionFilters.has(pos);
                return (
                  <button
                    key={pos}
                    type="button"
                    className={`angle-pill ${active ? "angle-pill-active" : ""}`}
                    onClick={() => togglePosition(pos)}
                    disabled={busy}
                    title={
                      active
                        ? `Only include ${pos}s in counter-packages`
                        : `Click to require ${pos}`
                    }
                  >
                    {pos}
                  </button>
                );
              })}
              {positionFilters.size > 0 && (
                <button
                  type="button"
                  className="angle-pill angle-pill-clear"
                  onClick={() => setPositionFilters(new Set())}
                  disabled={busy}
                  title="Clear — accept all positions"
                >
                  × clear
                </button>
              )}
            </div>
            <span className="angle-field-hint">
              Leave empty to allow any position.
            </span>
          </div>
          <div className="angle-filter-group">
            <span className="muted">
              Minimum value per target player:{" "}
              <strong>{Number(minPlayerValue).toLocaleString()}</strong>
            </span>
            <input
              type="range"
              min="0"
              max="9999"
              step="100"
              value={minPlayerValue}
              onChange={(e) => setMinPlayerValue(Number(e.target.value))}
              disabled={busy}
              className="angle-slider"
            />
            <span className="angle-field-hint">
              Each individual player in a counter-package must have a
              my-value at or above this. Default 3,000 filters out
              deep-bench filler.
            </span>
          </div>
        </div>
      </section>

      <section className="card angle-targets-card">
        <div className="angle-filter-head">
          <strong>
            {mode === "acquire"
              ? "Players to acquire"
              : "Trade with specific teams (optional)"}
          </strong>
          <span className="muted">
            {mode === "acquire"
              ? "Pick up to 2 opposing teams and check off the players you want to acquire. The search will build offer packages from your roster that land these players."
              : "Pick up to 2 opposing teams. Check off any \"must-have\" players from their rosters and the search will build counter-packages that include those seeds and fill the rest from the selected teams' top players."}
          </span>
        </div>
        <div className="angle-targets-row">
          {[0, 1].map((slot) => {
            const selectedId = targetOwners[slot];
            const otherId = targetOwners[1 - slot];
            const team = teams.find(
              (t) => String(t.ownerId || "") === selectedId,
            );
            const roster = team?.players || [];
            const seedsForTeam = new Set(seedsByOwner[selectedId] || []);
            return (
              <div key={slot} className="angle-target-slot">
                <label className="angle-field">
                  <span className="muted">Team {slot + 1}</span>
                  <select
                    value={selectedId}
                    onChange={(e) => setTargetOwnerAt(slot, e.target.value)}
                    disabled={busy}
                  >
                    <option value="">(any team)</option>
                    {teams
                      .filter(
                        (t) =>
                          String(t.ownerId || "") !== ownerId &&
                          String(t.ownerId || "") !== otherId,
                      )
                      .map((t) => (
                        <option
                          key={t.ownerId}
                          value={String(t.ownerId || "")}
                        >
                          {t.name}
                        </option>
                      ))}
                  </select>
                </label>
                {selectedId && (
                  <div className="angle-target-seeds">
                    <div className="muted">
                      Seed players from <strong>{team?.name}</strong>{" "}
                      <span className="angle-field-hint">
                        (required in every counter-package)
                      </span>
                    </div>
                    <div className="angle-target-seed-grid">
                      {[...roster]
                        .sort((a, b) => {
                          const av = valueByName.get(a)?.my_value || 0;
                          const bv = valueByName.get(b)?.my_value || 0;
                          return bv - av || a.localeCompare(b);
                        })
                        .map((name) => {
                          const info = valueByName.get(name);
                          const checked = seedsForTeam.has(name);
                          return (
                            <label
                              key={name}
                              className={`angle-roster-row ${
                                checked ? "angle-roster-checked" : ""
                              }`}
                            >
                              <input
                                type="checkbox"
                                checked={checked}
                                onChange={() => toggleSeed(selectedId, name)}
                                disabled={busy}
                              />
                              <span className="angle-roster-name">{name}</span>
                              {info && (
                                <span className="muted angle-roster-meta">
                                  {info.position || "—"} · my{" "}
                                  {info.my_value.toLocaleString()} ·{" "}
                                  {marketLabelForSource(info.market_source)}{" "}
                                  {info.market_value.toLocaleString()}
                                </span>
                              )}
                            </label>
                          );
                        })}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {mode === "offer" && (
      <section className="card angle-offer-bar">
        <div className="angle-offer-head">
          <strong>Your offer ({offerList.length} player{offerList.length === 1 ? "" : "s"})</strong>
          <div className="angle-offer-totals">
            <span>
              My total <strong>{offerTotals.my.toLocaleString()}</strong>
            </span>
            <span>
              Market total{" "}
              <strong>{offerTotals.market.toLocaleString()}</strong>
              <span className="angle-field-hint"> (IDPTC for IDP, KTC otherwise)</span>
            </span>
            {offerList.length > 0 && (
              <button
                className="button"
                onClick={() => setOffer(new Set())}
                disabled={busy}
              >
                Clear
              </button>
            )}
          </div>
        </div>
        {offerList.length > 0 && (
          <div className="angle-offer-chips">
            {offerList.map((name) => {
              const info = valueByName.get(name);
              return (
                <button
                  key={name}
                  className="angle-offer-chip"
                  onClick={() => toggleOffer(name)}
                  title="Remove from offer"
                >
                  <strong>{name}</strong>
                  {info && (
                    <span className="muted">
                      {info.position} · my {info.my_value.toLocaleString()} ·{" "}
                      {marketLabelForSource(info.market_source)}{" "}
                      {info.market_value.toLocaleString()}
                    </span>
                  )}
                  <span className="angle-chip-x">×</span>
                </button>
              );
            })}
          </div>
        )}
        <div className="angle-search">
          <input
            type="text"
            placeholder="Filter your roster…"
            value={rosterFilter}
            onChange={(e) => setRosterFilter(e.target.value)}
            disabled={busy || !selectedTeam}
          />
        </div>
        <div className="angle-roster-grid">
          {roster.length === 0 ? (
            <p className="muted">No players match.</p>
          ) : (
            roster.map((name) => {
              const info = valueByName.get(name);
              const checked = offer.has(name);
              return (
                <label
                  key={name}
                  className={`angle-roster-row ${checked ? "angle-roster-checked" : ""}`}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggleOffer(name)}
                    disabled={busy}
                  />
                  <span className="angle-roster-name">{name}</span>
                  {info && (
                    <span className="muted angle-roster-meta">
                      {info.position || "—"} · my{" "}
                      {info.my_value.toLocaleString()} ·{" "}
                      {marketLabelForSource(info.market_source)}{" "}
                      {info.market_value.toLocaleString()}
                    </span>
                  )}
                </label>
              );
            })
          )}
        </div>
      </section>
      )}

      {result?.warnings?.length ? (
        <section className="card angle-warnings">
          <div className="muted">Notes:</div>
          <ul>
            {result.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </section>
      ) : null}

      {result?.candidates?.length ? (
        <section className="card angle-results">
          <div className="angle-section-head">
            <h2>
              {result?.mode === "acquire"
                ? `Offer packages (${result.candidates.length})`
                : `Counter-packages (${result.candidates.length})`}
            </h2>
            <span className="muted">
              {result?.mode === "acquire"
                ? `Sorted by arbitrage score (my gain % − market gap %). Each package is from your roster and lands the ${result.acquire?.size || "?"} player(s) above. Market is IDPTC for IDP, KTC otherwise. Sizes allowed: ${(result.thresholds?.target_sizes || []).join(", ")}.`
                : `Sorted by arbitrage score (my gain % − market gap %). Market is IDPTC for IDP, KTC otherwise. Sizes allowed: ${(result.thresholds?.target_sizes || []).join(", ")}.`}
            </span>
          </div>
          {result?.mode === "acquire" && result.acquire?.players?.length ? (
            <div className="angle-acquire-summary muted" style={{ marginBottom: 12 }}>
              <strong>Acquiring:</strong>{" "}
              {result.acquire.players
                .map(
                  (p) =>
                    `${p.name} (${p.position}, my ${Number(p.my_value).toLocaleString()} · ${marketLabelForSource(p.market_source)} ${Number(p.market_value).toLocaleString()})`,
                )
                .join(" + ")}{" "}
              · my total <strong>{Number(result.acquire.my_total).toLocaleString()}</strong> · market total{" "}
              <strong>{Number(result.acquire.market_total).toLocaleString()}</strong>
            </div>
          ) : null}
          <div className="angle-package-grid">
            {result.candidates.map((c, i) => (
              <div key={i} className="angle-package">
                <div className="angle-package-head">
                  <div>
                    <strong>#{i + 1}</strong>{" "}
                    <span className="muted">
                      {result?.mode === "acquire"
                        ? `${result.acquire?.team || "You"} offer · ${c.size}-for-${result.acquire?.size || "?"}`
                        : `${c.team} · ${c.size}-for-${result.offer?.size || "?"}`}
                    </span>
                  </div>
                  <div className="angle-package-scores">
                    <span className="angle-delta-pos" title="my-value gain %">
                      +{c.my_gain_pct.toFixed(1)}%
                    </span>
                    <span
                      className={
                        c.market_gain_pct <= 0
                          ? "angle-delta-pos"
                          : "angle-delta-neutral"
                      }
                      title="Market gap % (IDPTC for IDP / KTC for offense)"
                    >
                      {c.market_gain_pct > 0 ? "+" : ""}
                      {c.market_gain_pct.toFixed(1)}% mkt
                    </span>
                    <span title="Arbitrage score">
                      <strong>+{c.arb_score.toFixed(1)}</strong>
                    </span>
                  </div>
                </div>
                <ul className="angle-package-players">
                  {c.players.map((p, j) => (
                    <li key={j}>
                      <strong>{p.name}</strong>{" "}
                      <span className="muted">{p.position}</span>{" "}
                      <span className="muted">
                        my {p.my_value.toLocaleString()} ·{" "}
                        {marketLabelForSource(p.market_source)}{" "}
                        {p.market_value.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="angle-package-totals muted">
                  my total <strong>{c.my_total.toLocaleString()}</strong>{" "}
                  · market total{" "}
                  <strong>{c.market_total.toLocaleString()}</strong>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : result && !busy ? (
        <section className="card">
          <p className="muted">
            {result?.mode === "acquire"
              ? "No offer packages match. Loosen the thresholds (lower \"Min my-value gain %\" or raise \"Max market gap %\"), pick different acquisition targets, or raise the candidate pool cap."
              : "No counter-packages match. Loosen the thresholds (lower \"Min my-value gain %\" or raise \"Max market gap %\"), pick different offer players, or widen the candidate pool on the backend."}
          </p>
        </section>
      ) : null}
    </div>
  );
}
