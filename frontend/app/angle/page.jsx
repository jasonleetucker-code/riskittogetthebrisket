"use client";

import { useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";

// ── Angle ───────────────────────────────────────────────────────────
// Player-specific trade-target arbitrage.
// Pick a team → pick a player on that team → surface players on other
// teams where your league's calibrated rankings say win but KTC sees
// the trade as fair or better for the counterparty.

const DEFAULT_MIN_MY = 5;
const DEFAULT_MAX_KTC = 5;
const DEFAULT_LIMIT = 50;

export default function AnglePage() {
  const { loading: dataLoading, error: dataError, rawData } = useDynastyData();

  const teams = useMemo(() => {
    const list = rawData?.sleeper?.teams || [];
    return [...list].sort((a, b) =>
      String(a?.name || "").localeCompare(String(b?.name || "")),
    );
  }, [rawData]);

  const [ownerId, setOwnerId] = useState("");
  const [playerName, setPlayerName] = useState("");
  const [minMyGainPct, setMinMyGainPct] = useState(DEFAULT_MIN_MY);
  const [maxKtcGainPct, setMaxKtcGainPct] = useState(DEFAULT_MAX_KTC);
  const [limit, setLimit] = useState(DEFAULT_LIMIT);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  // Default to the first team the moment the data loads.
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
    return [...(selectedTeam.players || [])].sort((a, b) => a.localeCompare(b));
  }, [selectedTeam]);

  useEffect(() => {
    // Reset the player picker whenever the team changes so we never
    // POST a player who isn't on the currently-selected roster.
    if (roster.length > 0 && !roster.includes(playerName)) {
      setPlayerName(roster[0]);
    } else if (roster.length === 0) {
      setPlayerName("");
    }
  }, [roster, playerName]);

  async function findAngles() {
    if (!ownerId || !playerName) {
      setErr("Pick a team and a player.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const res = await fetch("/api/angle/find", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({
          ownerId,
          playerName,
          minMyGainPct: Number(minMyGainPct),
          maxKtcGainPct: Number(maxKtcGainPct),
          limit: Number(limit),
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
            Find trades that win on your rankings but look fair or losing on
            KTC — easy to pitch to your leaguemates.
          </p>
        </div>
      </div>

      <section className="card angle-controls">
        <div className="angle-controls-row">
          <label className="angle-field">
            <span className="muted">Team</span>
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
            <span className="muted">Player on that team</span>
            <select
              value={playerName}
              onChange={(e) => setPlayerName(e.target.value)}
              disabled={busy || roster.length === 0}
            >
              {roster.length === 0 ? (
                <option value="">No roster loaded</option>
              ) : (
                roster.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))
              )}
            </select>
          </label>
          <label className="angle-field">
            <span className="muted">
              Min my-value gain %{" "}
              <span className="angle-field-hint">(target beats selected by ≥)</span>
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
              <span className="angle-field-hint">(KTC sees target ≤ this above)</span>
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
            <span className="muted">Results limit</span>
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
            disabled={busy || !ownerId || !playerName}
          >
            {busy ? "Searching…" : "Find angles"}
          </button>
        </div>
        {err && <p className="err-text" style={{ marginTop: 8 }}>{err}</p>}
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

      {result?.selected ? (
        <section className="card angle-selected">
          <div className="angle-selected-grid">
            <div>
              <div className="muted">You're offering</div>
              <div className="angle-player-head">
                <strong>{result.selected.name}</strong>
                <span className="muted">
                  {result.selected.position} ·{" "}
                  {result.selected.team || "(your team)"}
                </span>
              </div>
            </div>
            <div>
              <div className="muted">Your value</div>
              <div>
                <strong>{result.selected.my_value?.toLocaleString()}</strong>
              </div>
            </div>
            <div>
              <div className="muted">KTC value</div>
              <div>
                <strong>{result.selected.ktc_value?.toLocaleString()}</strong>
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {result?.candidates?.length ? (
        <section className="card angle-results">
          <div className="angle-section-head">
            <h2>Candidates ({result.candidates.length})</h2>
            <span className="muted">
              Sorted by arbitrage score (my gain % − KTC gap %)
            </span>
          </div>
          <div className="table-wrap">
            <table className="table angle-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Target</th>
                  <th>Pos</th>
                  <th>Owned by</th>
                  <th title="Your rankings value">My</th>
                  <th title="KeepTradeCut value">KTC</th>
                  <th title="Target my-value minus selected my-value, as %">
                    My Δ
                  </th>
                  <th title="Target KTC value minus selected KTC value, as %. 0 or negative = fair-or-better for counterparty.">
                    KTC Δ
                  </th>
                  <th title="my_gain% − ktc_gap%; bigger = better pitch">
                    Arb
                  </th>
                </tr>
              </thead>
              <tbody>
                {result.candidates.map((c, i) => (
                  <tr key={`${c.name}-${i}`}>
                    <td>{i + 1}</td>
                    <td>
                      <strong>{c.name}</strong>
                    </td>
                    <td>{c.position}</td>
                    <td>{c.team}</td>
                    <td>{c.my_value.toLocaleString()}</td>
                    <td>{c.ktc_value.toLocaleString()}</td>
                    <td className="angle-delta-pos">
                      +{c.my_gain_pct.toFixed(1)}%
                    </td>
                    <td
                      className={
                        c.ktc_gain_pct <= 0
                          ? "angle-delta-pos"
                          : "angle-delta-neutral"
                      }
                    >
                      {c.ktc_gain_pct > 0 ? "+" : ""}
                      {c.ktc_gain_pct.toFixed(1)}%
                    </td>
                    <td>
                      <strong>+{c.arb_score.toFixed(1)}</strong>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : result && !busy ? (
        <section className="card">
          <p className="muted">
            No candidates match. Loosen the thresholds (lower "Min my-value
            gain %" or raise "Max KTC gap %") or pick a different player.
          </p>
        </section>
      ) : null}
    </div>
  );
}
