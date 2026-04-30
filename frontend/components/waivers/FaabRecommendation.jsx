"use client";

/**
 * FaabRecommendation — bid panel for the manual add/drop calculator.
 *
 * Calls ``POST /api/waiver/faab-recommend`` when both add + drop are
 * selected (or when only an add is selected, with drop value 0) and
 * renders the four bid pills + confidence badge + factor breakdown
 * + warnings + plain-English explanation.
 *
 * The recommender's output shape is documented in
 * ``src/trade/faab_recommender.py::recommend_faab``.  This component
 * is purely presentational + a single fetch — all the math lives on
 * the backend so the bid pills always match what the contract
 * computes.
 */

import { useEffect, useState } from "react";

function _fmtBid(n) {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return `$${Math.round(Number(n)).toLocaleString()}`;
}

function ConfidenceBadge({ level }) {
  const map = {
    high:   { label: "High confidence",   color: "var(--green, #34d399)" },
    medium: { label: "Medium confidence", color: "var(--cyan, #FFC704)" },
    low:    { label: "Low confidence",    color: "var(--muted, #c7b8dc)" },
  };
  const meta = map[level] || map.low;
  return (
    <span
      className="badge"
      style={{
        background: "rgba(0,0,0,0.25)",
        color: meta.color,
        border: `1px solid ${meta.color}`,
        fontWeight: 600,
        fontSize: "0.66rem",
        padding: "2px 8px",
        letterSpacing: "0.04em",
      }}
    >
      {meta.label}
    </span>
  );
}

function BidPill({ label, amount, accent, emphasized }) {
  return (
    <div
      style={{
        flex: 1,
        minWidth: 0,
        padding: emphasized ? "10px 14px" : "8px 12px",
        background: emphasized
          ? `linear-gradient(180deg, rgba(255,255,255,0.04), rgba(255,255,255,0.02))`
          : "rgba(255,255,255,0.02)",
        border: `1px solid ${emphasized ? accent : "var(--border, rgba(255,255,255,0.1))"}`,
        borderRadius: 8,
        textAlign: "center",
      }}
    >
      <div
        className="muted"
        style={{
          fontSize: "0.62rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: emphasized ? accent : undefined,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: emphasized ? "1.4rem" : "1.1rem",
          fontWeight: 700,
          color: emphasized ? accent : "var(--fg, #f1ecff)",
        }}
      >
        {_fmtBid(amount)}
      </div>
    </div>
  );
}

function FactorRow({ factor }) {
  return (
    <li
      style={{
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        padding: "4px 0",
        borderBottom: "1px solid var(--border, rgba(255,255,255,0.06))",
        fontSize: "0.78rem",
      }}
    >
      <span
        style={{
          color: factor.missing ? "var(--muted, #c7b8dc)" : "var(--fg, #f1ecff)",
        }}
      >
        {factor.label}
      </span>
      <span
        className="muted"
        style={{
          fontStyle: factor.missing ? "italic" : "normal",
        }}
      >
        {factor.contribution}
      </span>
    </li>
  );
}

export default function FaabRecommendation({
  addPlayer,
  dropPlayer,
  leagueKey,
  ownerId,
  selectedTeam,
  leagueFaab,
}) {
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [showFactors, setShowFactors] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!addPlayer?.name) {
      setState("idle");
      setData(null);
      return;
    }
    let cancelled = false;
    setState("loading");
    setErr("");
    (async () => {
      try {
        const res = await fetch("/api/waiver/faab-recommend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            leagueKey,
            addPlayerName: addPlayer.name,
            dropPlayerName: dropPlayer?.name || undefined,
            teamOwnerId: ownerId || undefined,
          }),
        });
        if (cancelled) return;
        if (!res.ok) {
          const txt = await res.text().catch(() => "");
          setErr(`API ${res.status}: ${txt.slice(0, 120)}`);
          setState("error");
          return;
        }
        const json = await res.json();
        if (cancelled) return;
        setData(json);
        setState("done");
      } catch (exc) {
        if (cancelled) return;
        setErr(String(exc?.message || exc));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [addPlayer?.name, dropPlayer?.name, leagueKey, ownerId]);

  if (state === "idle") return null;

  if (state === "loading") {
    return (
      <div
        className="card"
        style={{ padding: 12, marginTop: 10 }}
        aria-live="polite"
      >
        <div className="muted" style={{ fontSize: "0.8rem" }}>
          Computing FAAB recommendation…
        </div>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div
        className="card"
        style={{ padding: 12, marginTop: 10, borderColor: "var(--red, #ef4444)" }}
      >
        <div style={{ fontSize: "0.85rem" }}>
          FAAB recommender unavailable
        </div>
        <div className="muted" style={{ fontSize: "0.72rem", marginTop: 4 }}>
          {err}
        </div>
      </div>
    );
  }

  const factors = Array.isArray(data?.factors) ? data.factors : [];
  const warnings = Array.isArray(data?.warnings) ? data.warnings : [];

  return (
    <section
      className="card"
      style={{ padding: 14, marginTop: 12 }}
      aria-label="FAAB bid recommendation"
    >
      <header
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: "0.95rem",
            fontWeight: 700,
          }}
        >
          Recommended FAAB bid
        </h3>
        <ConfidenceBadge level={data?.confidence || "low"} />
      </header>

      <div
        style={{
          display: "flex",
          gap: 8,
          marginBottom: 8,
          flexWrap: "wrap",
        }}
      >
        <BidPill
          label="Conservative"
          amount={data?.conservative}
          accent="var(--cyan, #FFC704)"
        />
        <BidPill
          label="Standard"
          amount={data?.standard}
          accent="var(--green, #34d399)"
          emphasized
        />
        <BidPill
          label="Aggressive"
          amount={data?.aggressive}
          accent="var(--orange, #fb923c)"
        />
        <BidPill
          label="Max"
          amount={data?.max}
          accent="var(--muted, #c7b8dc)"
        />
      </div>

      {data?.explanation && (
        <p
          className="muted"
          style={{
            margin: "8px 0 6px",
            fontSize: "0.82rem",
            lineHeight: 1.4,
          }}
        >
          {data.explanation}
        </p>
      )}

      {warnings.length > 0 && (
        <ul
          style={{
            listStyle: "none",
            padding: 0,
            margin: "6px 0 0",
            display: "flex",
            flexDirection: "column",
            gap: 4,
          }}
        >
          {warnings.map((w, i) => (
            <li
              key={`warn-${i}`}
              style={{
                fontSize: "0.78rem",
                padding: "4px 8px",
                background: "rgba(239,68,68,0.1)",
                color: "var(--red, #ef4444)",
                borderRadius: 6,
              }}
            >
              ⚠ {w}
            </li>
          ))}
        </ul>
      )}

      {factors.length > 0 && (
        <div style={{ marginTop: 10 }}>
          <button
            type="button"
            className="button-reset"
            onClick={() => setShowFactors((s) => !s)}
            style={{
              fontSize: "0.72rem",
              color: "var(--muted, #c7b8dc)",
              cursor: "pointer",
              border: "none",
              background: "transparent",
              padding: 0,
            }}
          >
            {showFactors ? "▾" : "▸"} Why this bid ({factors.length} factors)
          </button>
          {showFactors && (
            <ul
              style={{
                listStyle: "none",
                padding: 0,
                margin: "6px 0 0",
              }}
            >
              {factors.map((f, i) => (
                <FactorRow key={`f-${i}`} factor={f} />
              ))}
            </ul>
          )}
        </div>
      )}

      {leagueFaab && (
        <LeagueFaabContext
          analytics={leagueFaab}
          addPlayer={addPlayer}
          selectedTeam={selectedTeam}
          recommendation={data}
          show={showContext}
          onToggle={() => setShowContext((s) => !s)}
        />
      )}
    </section>
  );
}

// ── League FAAB context panel ─────────────────────────────────

function LeagueFaabContext({
  analytics,
  addPlayer,
  selectedTeam,
  recommendation,
  show,
  onToggle,
}) {
  const remaining = selectedTeam?.faabRemaining;
  const budget = analytics?.leagueBudget;
  const avg = analytics?.leagueAvgWinningBid;
  const median = analytics?.leagueMedianWinningBid;
  const totalBids = analytics?.totalBidsAnalyzed || 0;

  // Resolve this player's position-bucket stats from the
  // analytics block.  Falls back gracefully when the position
  // hasn't been ranked enough times to surface a bucket.
  const position = recommendation?.resolvedAddPosition || addPlayer?.pos;
  const posStats = position
    ? (analytics?.positionBids?.[String(position).toUpperCase()] ||
       (position === "DT" || position === "DE" || position === "EDGE"
         ? analytics?.positionBids?.DL
         : null) ||
       (position === "ILB" || position === "OLB" || position === "MLB"
         ? analytics?.positionBids?.LB
         : null) ||
       (position === "CB" || position === "S" || position === "FS" || position === "SS"
         ? analytics?.positionBids?.DB
         : null))
    : null;

  // Per-player history is keyed by Sleeper player_id.
  const playerHistory = (() => {
    const pid = addPlayer?.raw?.playerId || addPlayer?.playerId;
    if (!pid || !analytics?.playerHistory) return [];
    const entries = analytics.playerHistory[String(pid)] || [];
    return Array.isArray(entries) ? entries.slice(0, 5) : [];
  })();

  const fmtPct = (b) =>
    budget && budget > 0 && Number.isFinite(b)
      ? `${Math.round((b / budget) * 100)}%`
      : null;

  return (
    <div
      style={{
        marginTop: 10,
        paddingTop: 10,
        borderTop: "1px solid var(--border, rgba(255,255,255,0.06))",
      }}
    >
      <button
        type="button"
        className="button-reset"
        onClick={onToggle}
        style={{
          fontSize: "0.72rem",
          color: "var(--muted, #c7b8dc)",
          cursor: "pointer",
          border: "none",
          background: "transparent",
          padding: 0,
        }}
        aria-expanded={show}
      >
        {show ? "▾" : "▸"} League FAAB context
      </button>
      {show && (
        <div style={{ marginTop: 8, fontSize: "0.78rem" }}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: 8,
              marginBottom: 10,
            }}
          >
            <ContextStat
              label="Your remaining FAAB"
              value={
                remaining != null
                  ? _fmtBid(remaining)
                  : budget != null
                    ? `${_fmtBid(budget)} budget`
                    : "—"
              }
              hint={
                budget && remaining != null
                  ? `${Math.round((remaining / budget) * 100)}% of $${budget}`
                  : null
              }
            />
            <ContextStat
              label="League avg winning bid"
              value={avg ? _fmtBid(avg) : "—"}
              hint={fmtPct(avg)}
            />
            <ContextStat
              label="League median winning bid"
              value={median ? _fmtBid(median) : "—"}
              hint={
                totalBids > 0 ? `${totalBids} bids analyzed` : null
              }
            />
          </div>

          {posStats && posStats.count > 0 && (
            <div style={{ marginBottom: 10 }}>
              <div
                className="muted"
                style={{
                  fontSize: "0.7rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 4,
                }}
              >
                Comparable {String(position).toUpperCase()} bids ({posStats.count} historical)
              </div>
              <div
                style={{
                  fontSize: "0.85rem",
                }}
              >
                Range <strong>{_fmtBid(posStats.min)}</strong>–
                <strong> {_fmtBid(posStats.max)}</strong>
                {", avg "}
                <strong>{_fmtBid(posStats.avg)}</strong>
                {fmtPct(posStats.avg) ? ` (${fmtPct(posStats.avg)} of budget)` : ""}
              </div>
            </div>
          )}

          {playerHistory.length > 0 && (
            <div>
              <div
                className="muted"
                style={{
                  fontSize: "0.7rem",
                  textTransform: "uppercase",
                  letterSpacing: "0.05em",
                  marginBottom: 4,
                }}
              >
                {addPlayer?.name || "Player"} — past league waivers
              </div>
              <ul
                style={{
                  listStyle: "none",
                  padding: 0,
                  margin: 0,
                  fontSize: "0.78rem",
                }}
              >
                {playerHistory.map((h, i) => (
                  <li
                    key={`ph-${i}`}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      padding: "2px 0",
                    }}
                  >
                    <span className="muted">
                      {h?.season || "—"}
                      {h?.type === "free_agent" ? " · FA pickup" : ""}
                    </span>
                    <span style={{ fontWeight: 600 }}>
                      {_fmtBid(h?.bid || 0)}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {!posStats && playerHistory.length === 0 && (
            <div className="muted" style={{ fontSize: "0.78rem" }}>
              Not enough historical data for {String(position || "this player").toUpperCase()} or this player yet.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ContextStat({ label, value, hint }) {
  return (
    <div
      style={{
        padding: "8px 10px",
        background: "rgba(255,255,255,0.02)",
        border: "1px solid var(--border, rgba(255,255,255,0.06))",
        borderRadius: 6,
      }}
    >
      <div
        className="muted"
        style={{
          fontSize: "0.62rem",
          textTransform: "uppercase",
          letterSpacing: "0.04em",
        }}
      >
        {label}
      </div>
      <div style={{ fontSize: "1rem", fontWeight: 700, marginTop: 2 }}>
        {value}
      </div>
      {hint ? (
        <div
          className="muted"
          style={{ fontSize: "0.66rem", marginTop: 1 }}
        >
          {hint}
        </div>
      ) : null}
    </div>
  );
}
