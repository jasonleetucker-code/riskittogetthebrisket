"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

// ── Angle ───────────────────────────────────────────────────────────
// Multi-player trade-target arbitrage.
// Pick your team → check off any players you'd offer → get counter-
// packages from other teams, sized within ±1 of your offer, where
// your league's calibrated rankings say win but KTC sees fair-or-
// better for the counterparty.

const DEFAULT_MIN_MY = 5;
const DEFAULT_MAX_KTC = 5;
const DEFAULT_LIMIT = 50;
const DEFAULT_PER_TEAM = 4;

export default function AnglePage() {
  const { loading: dataLoading, error: dataError, rawData, rows } = useDynastyData();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) =>
      String(a?.name || "").localeCompare(String(b?.name || "")),
    );
  }, [rawData]);

  // Quick lookup: canonical name → { my_value, ktc_value, position }.
  // Used to show per-player totals in the checklist and offer bar.
  const valueByName = useMemo(() => {
    const m = new Map();
    for (const r of rows || []) {
      const name = r?.name || r?.canonicalName;
      if (!name) continue;
      const my_v = Number(r?.rankDerivedValue) || 0;
      const ktc_v = Number(r?.canonicalSites?.ktc) || 0;
      m.set(name, {
        my_value: my_v,
        ktc_value: ktc_v,
        position: r?.pos || r?.position || "",
      });
    }
    return m;
  }, [rows]);

  const [ownerId, setOwnerId] = useState("");
  const [rosterFilter, setRosterFilter] = useState("");
  const [offer, setOffer] = useState(() => new Set());
  const [minMyGainPct, setMinMyGainPct] = useState(DEFAULT_MIN_MY);
  const [maxKtcGainPct, setMaxKtcGainPct] = useState(DEFAULT_MAX_KTC);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [perTeamLimit, setPerTeamLimit] = useState(DEFAULT_PER_TEAM);
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

  const offerList = useMemo(() => Array.from(offer), [offer]);

  const offerTotals = useMemo(() => {
    let my = 0;
    let ktc = 0;
    for (const name of offerList) {
      const info = valueByName.get(name);
      if (info) {
        my += info.my_value || 0;
        ktc += info.ktc_value || 0;
      }
    }
    return { my, ktc };
  }, [offerList, valueByName]);

  function toggleOffer(name) {
    setOffer((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function findAngles() {
    if (!ownerId || offerList.length === 0) {
      setErr("Pick a team and check at least one player.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/angle/packages", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          ownerId,
          playerNames: offerList,
          minMyGainPct: Number(minMyGainPct),
          maxKtcGainPct: Number(maxKtcGainPct),
          limit: Number(limit),
          perTeamLimit: Number(perTeamLimit),
        }),
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
            Build an offer from your roster; get counter-packages
            (±1 in size) that win on your rankings but look fair-or-better on KTC.
          </p>
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
              Max KTC gap %{" "}
              <span className="angle-field-hint">(counter KTC ≤ this above)</span>
            </span>
            <input
              type="number"
              value={maxKtcGainPct}
              step="1"
              onChange={(e) => setMaxKtcGainPct(e.target.value)}
              disabled={busy}
            />
          </label>
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
            disabled={busy || !ownerId || offerList.length === 0}
          >
            {busy ? "Searching…" : `Find counter-packages (${offerList.length})`}
          </button>
        </div>
        {err && (
          <p className="err-text" style={{ marginTop: 8 }}>
            {err}
          </p>
        )}
      </section>

      <section className="card angle-offer-bar">
        <div className="angle-offer-head">
          <strong>Your offer ({offerList.length} player{offerList.length === 1 ? "" : "s"})</strong>
          <div className="angle-offer-totals">
            <span>
              My total <strong>{offerTotals.my.toLocaleString()}</strong>
            </span>
            <span>
              KTC total <strong>{offerTotals.ktc.toLocaleString()}</strong>
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
                      {info.position} · my {info.my_value.toLocaleString()} / ktc{" "}
                      {info.ktc_value.toLocaleString()}
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
                      {info.my_value.toLocaleString()} / ktc{" "}
                      {info.ktc_value.toLocaleString()}
                    </span>
                  )}
                </label>
              );
            })
          )}
        </div>
      </section>

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
            <h2>Counter-packages ({result.candidates.length})</h2>
            <span className="muted">
              Sorted by arbitrage score (my gain % − KTC gap %). Sizes allowed:{" "}
              {(result.thresholds?.target_sizes || []).join(", ")}.
            </span>
          </div>
          <div className="angle-package-grid">
            {result.candidates.map((c, i) => (
              <div key={i} className="angle-package">
                <div className="angle-package-head">
                  <div>
                    <strong>#{i + 1}</strong>{" "}
                    <span className="muted">
                      {c.team} · {c.size}-for-{result.offer?.size || "?"}
                    </span>
                  </div>
                  <div className="angle-package-scores">
                    <span className="angle-delta-pos" title="my-value gain %">
                      +{c.my_gain_pct.toFixed(1)}%
                    </span>
                    <span
                      className={
                        c.ktc_gain_pct <= 0
                          ? "angle-delta-pos"
                          : "angle-delta-neutral"
                      }
                      title="KTC gap %"
                    >
                      {c.ktc_gain_pct > 0 ? "+" : ""}
                      {c.ktc_gain_pct.toFixed(1)}% ktc
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
                        my {p.my_value.toLocaleString()} / ktc{" "}
                        {p.ktc_value.toLocaleString()}
                      </span>
                    </li>
                  ))}
                </ul>
                <div className="angle-package-totals muted">
                  my total <strong>{c.my_total.toLocaleString()}</strong>{" "}
                  · ktc total <strong>{c.ktc_total.toLocaleString()}</strong>
                </div>
              </div>
            ))}
          </div>
        </section>
      ) : result && !busy ? (
        <section className="card">
          <p className="muted">
            No counter-packages match. Loosen the thresholds (lower
            "Min my-value gain %" or raise "Max KTC gap %"), pick
            different offer players, or widen the candidate pool on
            the backend.
          </p>
        </section>
      ) : null}
    </div>
  );
}
