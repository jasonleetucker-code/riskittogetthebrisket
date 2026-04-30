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
}) {
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [showFactors, setShowFactors] = useState(false);
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
    </section>
  );
}
