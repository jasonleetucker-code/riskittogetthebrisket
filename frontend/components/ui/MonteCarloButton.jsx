/**
 * MonteCarloButton — embeds a "Simulate" button into the trade
 * calculator that calls POST /api/trade/simulate-mc with the
 * current sides and renders the result.
 *
 * Degradation:
 *   - 401 → silent (user isn't signed in; shouldn't reach this UI anyway)
 *   - 503 feature_disabled → render a tiny "coming soon" pill instead
 *     of a functional button, so users know the capability exists.
 *
 * Consumer contract: pass `sides` — an array like
 * `[{assets:[rowObj, ...]}, {assets:[...]}]` matching the trade
 * calc's existing state.  We send only the minimum payload (name,
 * team, position, rankDerivedValue, valueBand).
 */
"use client";

import React, { useState } from "react";


function _payloadFromSides(sides) {
  const pick = (i) => {
    const assets = sides?.[i]?.assets || [];
    return assets.map((r) => ({
      name: r?.name,
      team: r?.team,
      pos: r?.pos || r?.position,
      rankDerivedValue: r?.rankDerivedValue,
      valueBand: r?.valueBand,
    }));
  };
  return { sideA: pick(0), sideB: pick(1) };
}


export default function MonteCarloButton({ sides }) {
  const [state, setState] = useState("idle");  // idle|running|ok|error|disabled
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const totalAssets = (sides?.[0]?.assets?.length || 0) + (sides?.[1]?.assets?.length || 0);
  if (totalAssets === 0) return null;  // no point in a button with no players

  async function run() {
    try {
      setState("running");
      setErr("");
      const body = { ..._payloadFromSides(sides), nSims: 20000 };
      const res = await fetch("/api/trade/simulate-mc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.status === 503) {
        setState("disabled");
        return;
      }
      if (!res.ok) {
        setErr(`HTTP ${res.status}`);
        setState("error");
        return;
      }
      const json = await res.json();
      setResult(json);
      setState("ok");
    } catch (e) {
      setErr(e?.message || "Simulation failed");
      setState("error");
    }
  }

  if (state === "disabled") {
    return (
      <span
        className="badge badge-muted"
        title="Monte Carlo simulator is behind a feature flag — currently disabled"
        style={{ fontSize: "0.7rem", padding: "3px 8px" }}
      >
        MC sim: flag off
      </span>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 8 }}>
      <button
        type="button"
        className="btn btn-sm"
        disabled={state === "running"}
        onClick={run}
        style={{ alignSelf: "flex-start" }}
      >
        {state === "running" ? "Simulating..." : "Simulate (Monte Carlo)"}
      </button>
      {err && (
        <div className="text-xs" style={{ color: "var(--amber)" }}>
          {err}
        </div>
      )}
      {state === "ok" && result && (
        <div
          className="card"
          style={{
            padding: "var(--space-sm, 8px)",
            fontSize: "0.85rem",
            background: "rgba(255,255,255,0.02)",
          }}
        >
          <div style={{ display: "flex", gap: 16, flexWrap: "wrap" }}>
            <span>
              <strong>Win %:</strong>{" "}
              {(result.winProbA != null
                ? (result.winProbA * 100).toFixed(1)
                : (result.winPct || 0).toFixed(1))}%
            </span>
            <span>
              <strong>Δ:</strong>{" "}
              {result.meanDelta?.toFixed(0) ?? result.valueDelta?.toFixed(0) ?? "—"}
            </span>
            <span>
              <strong>Range:</strong>{" "}
              {result.deltaRange?.p10?.toFixed(0) ?? "—"} to{" "}
              {result.deltaRange?.p90?.toFixed(0) ?? "—"}
            </span>
            {result.riskLevel && (
              <span>
                <strong>Risk:</strong>{" "}
                <span
                  style={{
                    color:
                      result.riskLevel === "high" ? "var(--amber)" :
                      result.riskLevel === "medium" ? "var(--cyan)" :
                      "var(--green)",
                  }}
                >
                  {result.riskLevel}
                </span>
              </span>
            )}
            {result.tierImpact && (
              <span>
                <strong>Impact:</strong> {result.tierImpact}
              </span>
            )}
          </div>
          {result.decisionSummary && (
            <div style={{ marginTop: 6, color: "var(--subtext)" }}>
              {result.decisionSummary}
            </div>
          )}
          <div
            style={{
              marginTop: 8,
              fontSize: "0.65rem",
              color: "var(--muted)",
              fontStyle: "italic",
              borderTop: "1px solid rgba(255,255,255,0.05)",
              paddingTop: 6,
            }}
          >
            {result.disclaimer ||
              "Consensus-based win rate. NOT a real-world probability."}
          </div>
        </div>
      )}
    </div>
  );
}
