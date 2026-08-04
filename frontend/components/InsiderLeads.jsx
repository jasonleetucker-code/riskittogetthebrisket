"use client";

import { useCallback, useEffect, useState } from "react";

// ── Insider Trading: sell mode / buy mode lead list ──────────────────
//
// SELL MODE  "I want to move X"  → ranks league-mates by how much they
//                                  look like they want X.
// BUY MODE   "I want X"          → surfaces the CURRENT OWNER in this
//                                  league and what they look likely to
//                                  want back.
//
// Both modes read the SAME cross-league observations from opposite
// sides, which is why one backend call serves either.
//
// Backed by POST /api/intel/leads.  Every number is computed
// server-side by src/intel/leads.py; this is a pure renderer and does
// not derive, combine or re-rank anything.
//
// EPISTEMICS: the lead score is a RANKING of who to approach, never a
// probability that anyone accepts — Sleeper does not record declined
// offers, so an acceptance rate is unobservable. The payload's
// `limitations` block is rendered, not hidden behind a tooltip.

const MODES = [
  {
    key: "sell",
    label: "I'm selling",
    blurb: "Who in this league looks most likely to want this asset.",
  },
  {
    key: "buy",
    label: "I'm buying",
    blurb: "Who holds it here, and what they look likely to want back.",
  },
];

// Component keys in display order, with the plain-English label used in
// the breakdown. Penalties render last and are always shown even at
// zero, so "no penalty applied" and "penalty not computed" cannot read
// the same.
const COMPONENT_LABELS = [
  ["demonstratedInterest", "Traded for/away elsewhere"],
  ["partnerFit", "Trade-partner fit"],
  ["positionalNeed", "Positional need"],
  ["valueMatch", "Value-matched assets"],
  ["activity", "Trade activity"],
  ["contradictionPenalty", "Contradiction penalty"],
  ["lowSamplePenalty", "Thin-evidence penalty"],
];

function scoreColor(score) {
  if (score >= 55) return "var(--green)";
  if (score >= 30) return "var(--amber)";
  return "var(--subtext)";
}

function ScoreBar({ score }) {
  const pct = Math.max(0, Math.min(100, score));
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, justifyContent: "flex-end" }}>
      <div
        style={{
          width: 46,
          height: 5,
          borderRadius: 3,
          background: "rgba(255,255,255,0.09)",
          overflow: "hidden",
        }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: scoreColor(score) }} />
      </div>
      <span
        style={{
          fontFamily: "var(--mono)",
          fontWeight: 700,
          color: scoreColor(score),
          minWidth: 34,
          textAlign: "right",
        }}
      >
        {score.toFixed(1)}
      </span>
    </div>
  );
}

function ComponentBreakdown({ components }) {
  const rows = COMPONENT_LABELS.filter(([key]) => key in (components || {}));
  if (rows.length === 0) return null;
  return (
    <table style={{ fontSize: "0.7rem", width: "100%", maxWidth: 340 }}>
      <tbody>
        {rows.map(([key, label]) => {
          const raw = components[key] || 0;
          const shown = raw * 100;
          return (
            <tr key={key}>
              <td className="muted" style={{ padding: "1px 8px 1px 0" }}>
                {label}
              </td>
              <td
                style={{
                  textAlign: "right",
                  fontFamily: "var(--mono)",
                  color: shown < 0 ? "var(--red)" : shown > 0 ? "var(--text)" : "var(--subtext)",
                }}
              >
                {shown > 0 ? "+" : ""}
                {shown.toFixed(1)}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function InterestCell({ interest, mode }) {
  if (!interest) {
    return (
      <span className="muted" title="No trade involving this asset observed for this manager in another tracked league.">
        —
      </span>
    );
  }
  // Sell mode cares about their BUYING, buy mode about their SELLING —
  // but both counts are always shown, because a net figure alone hides
  // whether the evidence is one-sided or contradictory.
  const primary = mode === "sell" ? interest.buys : interest.sells;
  const other = mode === "sell" ? interest.sells : interest.buys;
  return (
    <span style={{ fontFamily: "var(--mono)", fontSize: "0.72rem" }}>
      <strong style={{ color: primary > 0 ? "var(--green)" : "var(--subtext)" }}>{primary}</strong>
      <span className="muted"> / {other} opp</span>
      {interest.uniqueLeagues > 1 && (
        <span className="muted" title="Distinct leagues these trades happened in">
          {" "}
          · {interest.uniqueLeagues} lgs
        </span>
      )}
    </span>
  );
}

function LeadRow({ lead, mode, expanded, onToggle }) {
  return [
    <tr key={lead.ownerId} onClick={onToggle} style={{ cursor: "pointer" }}>
      <td style={{ fontWeight: 600 }}>
        <span style={{ marginRight: 6 }}>{expanded ? "▼" : "▶"}</span>
        {lead.displayName || `Manager ${lead.ownerId}`}
        {lead.ownsAsset && (
          <span
            className="badge"
            style={{ marginLeft: 6, fontSize: "0.62rem", borderColor: "var(--amber)", color: "var(--amber)" }}
            title="This manager currently rosters the asset in this league."
          >
            OWNER
          </span>
        )}
      </td>
      <td style={{ textAlign: "right" }}>
        <ScoreBar score={lead.leadScore || 0} />
      </td>
      <td style={{ textAlign: "right" }}>
        <InterestCell interest={lead.interest} mode={mode} />
      </td>
      <td style={{ textAlign: "right", fontFamily: "var(--mono)", fontSize: "0.72rem" }}>
        {lead.partnerFitScore == null ? (
          <span className="muted" title="No roster snapshot for this manager — the fit term abstains rather than guessing.">
            —
          </span>
        ) : (
          lead.partnerFitScore.toFixed(1)
        )}
      </td>
      <td style={{ fontSize: "0.72rem" }}>
        {(lead.reasons || []).slice(0, 2).join(" · ") || <span className="muted">No signal observed</span>}
      </td>
    </tr>,
    expanded ? (
      <tr key={`${lead.ownerId}::detail`}>
        <td colSpan={5} style={{ background: "rgba(255,255,255,0.02)" }}>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap", padding: "6px 0 10px" }}>
            <div>
              <div
                className="muted"
                style={{ fontSize: "0.64rem", textTransform: "uppercase", marginBottom: 3 }}
              >
                Score breakdown
              </div>
              <ComponentBreakdown components={lead.components} />
            </div>
            <div style={{ flex: "1 1 240px", minWidth: 220 }}>
              {(lead.reasons || []).length > 0 && (
                <>
                  <div
                    className="muted"
                    style={{ fontSize: "0.64rem", textTransform: "uppercase", marginBottom: 3 }}
                  >
                    Why
                  </div>
                  <ul style={{ margin: "0 0 8px", paddingLeft: 16, fontSize: "0.72rem" }}>
                    {lead.reasons.map((r, i) => (
                      <li key={i}>{r}</li>
                    ))}
                  </ul>
                </>
              )}
              {(lead.cautions || []).length > 0 && (
                <>
                  <div
                    style={{
                      fontSize: "0.64rem",
                      textTransform: "uppercase",
                      marginBottom: 3,
                      color: "var(--amber)",
                    }}
                  >
                    Cautions
                  </div>
                  <ul
                    style={{
                      margin: 0,
                      paddingLeft: 16,
                      fontSize: "0.72rem",
                      color: "var(--amber)",
                    }}
                  >
                    {lead.cautions.map((c, i) => (
                      <li key={i}>{c}</li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          </div>
        </td>
      </tr>
    ) : null,
  ];
}

export default function InsiderLeads({ assetId, assetName, leagueKey }) {
  const [mode, setMode] = useState("sell");
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(null);

  const load = useCallback(
    (activeMode, signal) => {
      setLoading(true);
      setError(null);
      const body = { mode: activeMode };
      if (assetId) body.assetId = assetId;
      else if (assetName) body.name = assetName;
      if (leagueKey) body.leagueKey = leagueKey;
      return fetch("/api/intel/leads", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal,
      })
        .then(async (r) => {
          if (r.ok) return r.json();
          const detail = await r.json().catch(() => null);
          throw new Error(detail?.message || detail?.error || `HTTP ${r.status}`);
        })
        .then((data) => {
          setPayload(data);
          setLoading(false);
        })
        .catch((err) => {
          if (err?.name === "AbortError") return;
          setError(String(err?.message || err));
          setLoading(false);
        });
    },
    [assetId, assetName, leagueKey],
  );

  useEffect(() => {
    const ctl = new AbortController();
    setExpanded(null);
    load(mode, ctl.signal);
    return () => ctl.abort();
  }, [load, mode]);

  const leads = payload?.leads || [];
  const activeMode = MODES.find((m) => m.key === mode);

  return (
    <div style={{ padding: "4px 0 8px" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 6, flexWrap: "wrap", alignItems: "center" }}>
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => setMode(m.key)}
            className={m.key === mode ? "button" : "button-outline"}
            style={{ fontSize: "0.72rem", padding: "3px 10px", minHeight: 28 }}
            title={m.blurb}
          >
            {m.label}
          </button>
        ))}
        <span className="muted" style={{ fontSize: "0.7rem", marginLeft: 4 }}>
          {activeMode?.blurb}
        </span>
      </div>

      {loading && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
          Scoring league-mates…
        </div>
      )}

      {!loading && error && (
        <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
          Couldn&apos;t build leads: {error}
        </div>
      )}

      {!loading && !error && (
        <>
          <div className="muted" style={{ fontSize: "0.7rem", marginBottom: 4 }}>
            {payload?.poolSize || 0} league-mate{(payload?.poolSize || 0) === 1 ? "" : "s"} ranked ·{" "}
            {payload?.leadsWithObservedInterest || 0} with observed cross-league activity in the last{" "}
            {payload?.window || "90d"}
            {payload?.ownerOfAsset && mode === "buy" ? " · owner highlighted" : ""}
          </div>

          {leads.length === 0 ? (
            <div className="muted" style={{ fontSize: "0.72rem", padding: "6px 0" }}>
              No league-mates to rank — the crawl has no members for this league yet.
            </div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>League-mate</th>
                    <th
                      style={{ textAlign: "right" }}
                      title="Ranking of who to approach first. NOT a probability that they accept."
                    >
                      Lead score
                    </th>
                    <th
                      style={{ textAlign: "right" }}
                      title="Trades involving this asset in their OTHER leagues — the mode's side first, the opposite side after the slash."
                    >
                      {mode === "sell" ? "Bought elsewhere" : "Sold elsewhere"}
                    </th>
                    <th
                      style={{ textAlign: "right" }}
                      title="roster_intel partner-fit score: need alignment, competitive window, activity. Blank when no roster snapshot exists."
                    >
                      Fit
                    </th>
                    <th style={{ textAlign: "left" }}>Top reasons</th>
                  </tr>
                </thead>
                <tbody>
                  {leads.map((lead) => (
                    <LeadRow
                      key={lead.ownerId}
                      lead={lead}
                      mode={mode}
                      expanded={expanded === lead.ownerId}
                      onToggle={() => setExpanded(expanded === lead.ownerId ? null : lead.ownerId)}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {payload?.limitations && (
            <div
              className="muted"
              style={{ fontSize: "0.66rem", marginTop: 6, lineHeight: 1.5, maxWidth: 780 }}
            >
              <strong>What this is not:</strong> {payload.limitations.statement}{" "}
              {payload.limitations.coverageCaveat}
            </div>
          )}
        </>
      )}
    </div>
  );
}
