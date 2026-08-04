"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { PageHeader, LoadingState, EmptyState } from "@/components/ui";
import { apiErrorMessage } from "@/lib/api-error";

// PURE DISPLAY. Every number here — score, classification, confidence, component
// values, the explanation sentences — is computed by src/edge/ and rendered
// verbatim. Nothing on this page recomputes a buy/sell, and nothing should: this
// repository has a hard rule against a second ranking engine on the client, and a
// label computed in two places becomes two different products.

const CLASSIFICATION_TONE = {
  "Strong Buy": { color: "var(--positive, #16a34a)", weight: 700 },
  Buy: { color: "var(--positive, #16a34a)", weight: 600 },
  Neutral: { color: "var(--text-secondary, #888)", weight: 500 },
  Sell: { color: "var(--negative, #dc2626)", weight: 600 },
  "Strong Sell": { color: "var(--negative, #dc2626)", weight: 700 },
  Conflicted: { color: "var(--warning, #d97706)", weight: 600 },
  "Insufficient Evidence": { color: "var(--text-secondary, #888)", weight: 400 },
  Withheld: { color: "var(--text-secondary, #888)", weight: 400 },
};

function Classification({ value }) {
  const tone = CLASSIFICATION_TONE[value] || CLASSIFICATION_TONE.Neutral;
  return (
    <span style={{ color: tone.color, fontWeight: tone.weight, fontSize: "0.78rem" }}>{value}</span>
  );
}

function ConfidenceBar({ value }) {
  const pct = Math.max(0, Math.min(100, Number(value) || 0));
  return (
    <div title={`Confidence ${pct.toFixed(0)} / 100`} style={{ minWidth: 76 }}>
      <div
        style={{
          height: 5,
          borderRadius: 3,
          background: "var(--border-default, #333)",
          overflow: "hidden",
        }}
      >
        <div style={{ width: `${pct}%`, height: "100%", background: "var(--accent, #4f8cff)" }} />
      </div>
      <div className="muted" style={{ fontSize: "0.62rem", marginTop: 2 }}>
        conf {pct.toFixed(0)}
      </div>
    </div>
  );
}

// Components are shown SEPARATELY and always — the composite exists for ranking,
// not to replace them. A reader must be able to see whether a call is a
// mispricing bet or a crowd-behaviour bet, because those fail differently.
function ComponentBar({ component }) {
  if (!component) return null;
  const value = component.value;
  const unavailable = value === null || value === undefined;
  const magnitude = unavailable ? 0 : Math.abs(value) * 50;
  const positive = !unavailable && value > 0;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.66rem" }}>
      <span className="muted" style={{ minWidth: 78 }}>
        {component.key}
        {component.directional === false ? " (context)" : ""}
      </span>
      <div
        style={{
          position: "relative",
          width: 100,
          height: 6,
          background: "var(--border-default, #333)",
          borderRadius: 3,
        }}
      >
        {!unavailable ? (
          <div
            style={{
              position: "absolute",
              left: positive ? "50%" : `${50 - magnitude}%`,
              width: `${magnitude}%`,
              height: "100%",
              borderRadius: 3,
              background: positive ? "var(--positive, #16a34a)" : "var(--negative, #dc2626)",
            }}
          />
        ) : null}
      </div>
      <span className="muted">{unavailable ? "no data" : value.toFixed(2)}</span>
    </div>
  );
}

function Row({ item }) {
  const [open, setOpen] = useState(false);
  const components = item.components || {};
  return (
    <>
      <tr
        onClick={() => setOpen((v) => !v)}
        style={{ cursor: "pointer", borderTop: "1px solid var(--border-default, #333)" }}
      >
        <td style={{ padding: "6px 8px", fontWeight: 600 }}>{item.playerKey}</td>
        <td style={{ padding: "6px 8px", fontFamily: "var(--mono)", textAlign: "right" }}>
          {item.score > 0 ? "+" : ""}
          {item.score.toFixed(1)}
        </td>
        <td style={{ padding: "6px 8px" }}>
          <Classification value={item.classification} />
        </td>
        <td style={{ padding: "6px 8px" }}>
          <ConfidenceBar value={item.confidence} />
        </td>
        <td className="muted" style={{ padding: "6px 8px", fontSize: "0.66rem" }}>
          {open ? "hide" : "why?"}
        </td>
      </tr>
      {open ? (
        <tr>
          <td colSpan={5} style={{ padding: "8px 12px 14px", background: "var(--bg-subtle, #111)" }}>
            <div style={{ display: "grid", gap: 4, marginBottom: 8 }}>
              {["mispricing", "sharp_flow", "momentum", "data_quality"].map((key) => (
                <ComponentBar key={key} component={components[key]} />
              ))}
            </div>
            {(item.reasons || []).map((reason) => (
              <div key={reason} style={{ fontSize: "0.7rem", marginBottom: 4 }}>
                {reason}
              </div>
            ))}
            {item.warnings?.length ? (
              <div className="muted" style={{ fontSize: "0.63rem", marginTop: 6 }}>
                flags: {item.warnings.join(" · ")}
              </div>
            ) : null}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function Board({ title, rows, emptyNote }) {
  return (
    <div className="card" style={{ flex: "1 1 380px", minWidth: 340 }}>
      <h3 style={{ fontSize: "0.82rem", marginBottom: 6 }}>{title}</h3>
      {rows?.length ? (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.74rem" }}>
          <thead>
            <tr className="muted" style={{ fontSize: "0.64rem", textAlign: "left" }}>
              <th style={{ padding: "0 8px 4px" }}>Player</th>
              <th style={{ padding: "0 8px 4px", textAlign: "right" }}>Edge</th>
              <th style={{ padding: "0 8px 4px" }}>Call</th>
              <th style={{ padding: "0 8px 4px" }}>Confidence</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((item) => (
              <Row key={item.playerKey} item={item} />
            ))}
          </tbody>
        </table>
      ) : (
        // Never padded to a target length. An empty list means nobody cleared
        // the bar, which is a real answer.
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          {emptyNote}
        </div>
      )}
    </div>
  );
}

export default function ConsensusEdgePage() {
  const [payload, setPayload] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const response = await fetch("/api/consensus-edge/top", {
        cache: "no-store",
        credentials: "same-origin",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(apiErrorMessage(body, response.status));
      setPayload(body);
      setError(null);
    } catch (err) {
      setError(apiErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const counts = payload?.counts || {};
  const positionLeaders = payload?.positionLeaders?.buy || {};
  const leaderRows = useMemo(
    () =>
      ["QB", "RB", "WR", "TE", "DL", "LB", "DB"].map((position) => ({
        position,
        result: positionLeaders[position] || null,
      })),
    [positionLeaders],
  );

  if (loading && !payload) return <LoadingState label="Scoring the board…" />;

  return (
    <section>
      <PageHeader
        title="Consensus Edge"
        description="Independent fair value against the acquisition market, with every component shown separately."
      />

      {/* Shadow status is the first thing on the page, not a footnote. A reader
          must not be able to mistake this for a promoted, validated model. */}
      <div
        className="card"
        style={{ marginBottom: 12, borderLeft: "3px solid var(--warning, #d97706)" }}
      >
        <strong style={{ fontSize: "0.78rem" }}>Shadow mode — not validated for decisions</strong>
        <div className="muted" style={{ fontSize: "0.7rem", marginTop: 4 }}>
          Weights are provisional and were <strong>not</strong> fitted out-of-sample. Only the
          mispricing component has out-of-sample evidence (Spearman ≈ +0.09 to +0.12 at 14 days,
          positive in every fold). Sharp Flow has no historical data to validate against, IDP cannot
          be backtested (the IDP market anchor has 14 days of history), and the target is future{" "}
          <em>market movement</em> — not league-scored production. Compare it against the existing
          signals; do not yet trade on it.
        </div>
        {payload?.modelVersion ? (
          <div className="muted" style={{ fontSize: "0.63rem", marginTop: 6 }}>
            {payload.modelVersion} · weightsValidated={String(payload.weightsValidated)} · scored{" "}
            {counts.scored ?? 0} · with sharp activity {counts.withSharpActivity ?? 0}
          </div>
        ) : null}
      </div>

      {error ? <EmptyState title="Consensus Edge unavailable" description={error} /> : null}

      {payload?.status === "no_contract" ? (
        <EmptyState
          title="No board loaded"
          description="The canonical contract is not loaded, so there is nothing to price. This is a real state, not an error."
        />
      ) : null}

      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <Board
          title={`Top buys (${counts.qualifyingBuys ?? 0} qualified)`}
          rows={payload?.topBuys}
          emptyNote="No player cleared the score and confidence thresholds. The list is not padded."
        />
        <Board
          title={`Top sells (${counts.qualifyingSells ?? 0} qualified)`}
          rows={payload?.topSells}
          emptyNote="No player cleared the score and confidence thresholds. The list is not padded."
        />
      </div>

      <div className="card" style={{ marginTop: 12 }}>
        <h3 style={{ fontSize: "0.82rem", marginBottom: 6 }}>Position leaders (buy)</h3>
        <div className="muted" style={{ fontSize: "0.66rem", marginBottom: 8 }}>
          Best <em>qualifying</em> player per position. A position with nobody above the bar shows
          “No qualifying buy” rather than promoting the least-bad candidate.
        </div>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {leaderRows.map(({ position, result }) => (
            <div
              key={position}
              style={{
                border: "1px solid var(--border-default, #333)",
                borderRadius: 4,
                padding: "6px 10px",
                minWidth: 150,
              }}
            >
              <div className="muted" style={{ fontSize: "0.62rem" }}>
                {position}
              </div>
              {result ? (
                <>
                  <div style={{ fontSize: "0.74rem", fontWeight: 600 }}>{result.playerKey}</div>
                  <div style={{ fontSize: "0.68rem" }}>
                    {result.score > 0 ? "+" : ""}
                    {result.score.toFixed(1)} · <Classification value={result.classification} />
                  </div>
                </>
              ) : (
                <div className="muted" style={{ fontSize: "0.7rem" }}>
                  No qualifying buy
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
