/**
 * MonteCarloButton — runs the probabilistic trade simulator and
 * renders the result in plain English.
 *
 * Critical: the per-player values sent to the simulator must match
 * what the trade builder displays.  The trade builder uses
 * ``effectiveValue(row, valueMode, settings)`` which:
 *   1. Reads ``row.values[valueMode]`` (default "full"), NOT
 *      ``rankDerivedValue`` directly.
 *   2. Applies the pick-year discount for future picks.
 *
 * Skipping these steps (early versions of this component did) made
 * MC report wildly different deltas than the trade meter (e.g.
 * MC: -4281, builder: -632).  We now compute ``effectiveValue`` per
 * row + center the synthesized ``valueBand`` on it so MC and the
 * meter agree on the same numbers.
 *
 * Output is rewritten in plain English — no "Δ" / "consensus-band
 * samples" / "direction-symmetrized" — just "Side B wins 70% of
 * 50,000 simulations".
 */
"use client";

import React, { useState } from "react";
import { effectiveValue } from "@/lib/trade-logic";
import { useSettings } from "@/components/useSettings";


function _payloadFromSides(sides, valueMode, settings) {
  const pick = (i) => {
    const assets = sides?.[i]?.assets || [];
    return assets.map((r) => {
      // Use the SAME per-player value the trade builder displays
      // (backend-authoritative values[valueMode]; the pick-year
      // discount is already baked in upstream).  This is the
      // canonical "what is this player worth" number.
      const v = effectiveValue(r, valueMode, settings) || 0;
      // Build the consensus band centered on v.  Width comes from the
      // row's existing valueBand when the backend stamped one — that is
      // real source disagreement, and it is rescaled to v's center so
      // the pick-year discount carries through.
      //
      // When there is NO stamped band, we send NO band (W09-F005).
      // This component used to synthesize p10 = v*0.85 / p90 = v*1.15
      // here — numerically identical to the backend's own fallback, but
      // arriving as if it were measured, which suppressed the backend's
      // provenance stamp and left the panel free to describe a flat
      // placeholder as "our 6+ ranking sources don't fully agree".
      // 0 of 1,092 live rows carry a band, so that was every asset.
      // One synthesizer, in one place, that labels its own output.
      const existing = r?.valueBand;
      const asset = {
        name: r?.name,
        team: r?.team || "",
        pos: r?.pos || r?.position,
        rankDerivedValue: v,
      };
      if (existing && typeof existing.p50 === "number" && existing.p50 > 0) {
        const ratio = v / existing.p50;
        asset.valueBand = {
          p10: Math.round((existing.p10 || 0) * ratio),
          p50: Math.round(v),
          p90: Math.round((existing.p90 || 0) * ratio),
        };
      }
      return asset;
    });
  };
  return { sideA: pick(0), sideB: pick(1) };
}


function _renderPlainSummary(result, sides) {
  const winA = (result.winProbA != null ? result.winProbA : (result.winPct || 0) / 100);
  const pct = Math.round(winA * 100);
  const sims = (result.nSims || 0).toLocaleString();

  let headline, subline;
  if (pct >= 80) {
    headline = "Side A is the clear winner.";
    subline = `Side A came out ahead in ${pct}% of ${sims} simulations.`;
  } else if (pct >= 60) {
    headline = "Side A is favored.";
    subline = `Side A won ${pct}% of ${sims} simulations.`;
  } else if (pct >= 40) {
    headline = "Coin flip.";
    subline = `Side A won ${pct}% of ${sims} simulations — no clear winner.`;
  } else if (pct >= 20) {
    headline = "Side B is favored.";
    subline = `Side B won ${100 - pct}% of ${sims} simulations.`;
  } else {
    headline = "Side B is the clear winner.";
    subline = `Side B came out ahead in ${100 - pct}% of ${sims} simulations.`;
  }

  const meanDelta = Math.round(result.meanDelta || result.valueDelta || 0);
  let deltaLine;
  if (Math.abs(meanDelta) < 100) {
    deltaLine = "On average, the two sides are within 100 points of each other.";
  } else if (meanDelta > 0) {
    deltaLine = `On average, Side A's total beat Side B's by ${meanDelta.toLocaleString()} points.`;
  } else {
    deltaLine = `On average, Side B's total beat Side A's by ${Math.abs(meanDelta).toLocaleString()} points.`;
  }

  const r = result.deltaRange || {};
  let rangeLine;
  if (typeof r.p10 === "number" && typeof r.p90 === "number") {
    const tightness = r.p90 - r.p10;
    if (tightness < 1500) {
      rangeLine = "Range of outcomes is narrow — the result is consistent across simulations.";
    } else if (tightness < 4000) {
      rangeLine = "Moderate range of outcomes — some scenarios swing the other way.";
    } else {
      rangeLine = "Wide range of outcomes — high uncertainty.";
    }
  }

  return { headline, subline, deltaLine, rangeLine };
}


export default function MonteCarloButton({ sides, valueMode = "full" }) {
  const { settings } = useSettings();
  const [state, setState] = useState("idle");
  const [result, setResult] = useState(null);
  const [err, setErr] = useState("");

  const totalAssets = (sides?.[0]?.assets?.length || 0) + (sides?.[1]?.assets?.length || 0);
  if (totalAssets === 0) return null;

  async function run() {
    try {
      setState("running");
      setErr("");
      const body = { ..._payloadFromSides(sides, valueMode, settings), nSims: 20000, applyConsolidationAdjustment: true };
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

  const summary = state === "ok" && result ? _renderPlainSummary(result, sides) : null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 12 }}>
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
      {state === "ok" && summary && (
        <div
          className="card"
          style={{
            padding: "var(--space-md, 14px)",
            background: "rgba(255,255,255,0.03)",
            border: "1px solid rgba(255,255,255,0.06)",
          }}
        >
          <div
            style={{
              fontSize: "1rem", fontWeight: 700, marginBottom: 6,
              color:
                summary.headline.startsWith("Side A is the clear") ||
                summary.headline.startsWith("Side B is the clear")
                  ? "var(--green)"
                  : summary.headline.startsWith("Side A is favored") ||
                    summary.headline.startsWith("Side B is favored")
                  ? "var(--cyan)"
                  : "var(--subtext)",
            }}
          >
            {summary.headline}
          </div>
          <div style={{ fontSize: "0.85rem", marginBottom: 6 }}>
            {summary.subline}
          </div>
          <div style={{ fontSize: "0.85rem", marginBottom: 4 }}>
            {summary.deltaLine}
          </div>
          {summary.rangeLine && (
            <div style={{ fontSize: "0.85rem", color: "var(--subtext)" }}>
              {summary.rangeLine}
            </div>
          )}
          <details
            style={{
              marginTop: 10, paddingTop: 8,
              borderTop: "1px solid rgba(255,255,255,0.05)",
              fontSize: "0.72rem", color: "var(--muted)",
            }}
          >
            <summary style={{ cursor: "pointer", marginBottom: 4 }}>
              How is this calculated?
            </summary>
            <div style={{ marginTop: 4, lineHeight: 1.5 }}>
              For each player we sample {result.nSims?.toLocaleString() || "20,000"} times
              from a range around their board value, sum each side, and
              check who came out ahead.  The "win %" is the fraction of
              those samples where Side A's total beat Side B's.
              {result.mcStandardError != null && (
                <>
                  {" "}Simulation noise on that percentage is about ±
                  {(result.mcStandardError * 100).toFixed(2)} points.
                </>
              )}
            </div>
            {/* The backend's ``disclaimer`` is declared PART OF THE
                CONTRACT (server.py, /api/trade/simulate-mc): "the
                frontend MUST render the disclaimer somewhere visible so
                users don't mis-read win probability as real-world odds."
                Nothing rendered it. */}
            {result.disclaimer && (
              <div style={{ marginTop: 6, lineHeight: 1.5 }}>
                {result.disclaimer}
              </div>
            )}
            {/* Where the sampled range came from.  Today every band is
                a flat ±15% placeholder because no contract row carries
                a measured one — this panel used to describe that as
                source disagreement (W09-F005). */}
            {result.bandProvenance?.note && (
              <div
                style={{ marginTop: 6, lineHeight: 1.5, color: "var(--amber)" }}
              >
                {result.bandProvenance.note}
              </div>
            )}
          </details>
        </div>
      )}
    </div>
  );
}
