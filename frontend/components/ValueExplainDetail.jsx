"use client";

/**
 * ValueExplainDetail — renders the backend's value-explain/v2 contract for
 * ONE player: which estimator produced the value, whether vote-share
 * attribution is exact, every source with its three clocks, freshness
 * treatment and exclusion reason, and a leave-one-out labelled
 * non-additive.
 *
 * Display only. Every number is a field of
 * GET /api/players/{player}/value-explain (owner:
 * src/api/source_weighting_explain.py::player_explain); labels come from
 * lib/value-explainers.js. Nothing here computes a value, weight, share,
 * rank or confidence — there is no frontend ranking engine and no
 * frontend confidence math.
 *
 * PRIVATE surface: the endpoint is session-gated. This component belongs
 * on the private Player File only, never on a public /league page.
 *
 * Code-split: the Player File loads it with React.lazy + Suspense (the
 * repo's pattern — not next/dynamic, see CLAUDE.md "Perfect Draft"), and
 * only once the collapsed panel is opened, so the fetch and the chunk
 * cost nothing until asked for.
 */
import React, { useEffect, useState } from "react";
import { Banner, Button, DataTable, SkeletonText } from "@/components/ds";
import { SOURCE_FRESHNESS_STATE_LABELS, formatAgo } from "@/lib/value-explainers";
import { FRESHNESS_TREATMENT_LABELS, valueExplainView } from "@/lib/value-explain-contract";
import styles from "./value-explain.module.css";

export function valueExplainUrl(playerKey) {
  return `/api/players/${encodeURIComponent(String(playerKey))}/value-explain`;
}

function classifyFailure(status) {
  if (status === 401) return "auth";
  if (status === 404) return "not_found";
  if (status === 503) return "not_ready";
  return "error";
}

const FAILURE_COPY = {
  auth: "Sign in to see how this value was computed.",
  not_found: "This asset is not on the loaded board, so there is nothing to itemise.",
  not_ready: "The board is not loaded on the server yet — try again shortly.",
  error: "The explanation could not be loaded.",
  network: "The explanation could not be loaded.",
};

function formatNumber(n, digits = 0) {
  if (n == null) return null;
  return n.toLocaleString(undefined, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function formatShare(share) {
  if (share == null) return null;
  return `${(share * 100).toFixed(1)}%`;
}

function formatSigned(n) {
  if (n == null) return null;
  const abs = formatNumber(Math.abs(n), 1);
  if (n > 0) return `+${abs}`;
  if (n < 0) return `−${abs}`;
  return abs;
}

/** One clock: relative time with the exact instant in the title; unknown is said. */
function Clock({ at }) {
  const ago = formatAgo(at);
  if (!at || !ago) return <span className={styles.unknown}>unknown</span>;
  return (
    <time dateTime={at} title={at}>
      {ago}
    </time>
  );
}

function SourceDetail({ s }) {
  const treatment = FRESHNESS_TREATMENT_LABELS[s.treatment] || s.treatment;
  const state = s.treatmentState
    ? SOURCE_FRESHNESS_STATE_LABELS[s.treatmentState] || s.treatmentState
    : null;
  return (
    <div className={styles.detail}>
      <p className={styles.detailLine}>
        <span className={styles.detailKey}>Freshness:</span> {treatment}
        {s.treatment === "down_weighted" && s.treatmentFactor != null
          ? ` ×${s.treatmentFactor.toFixed(2)}`
          : ""}
        {state ? ` · source ${state.toLowerCase()}` : ""}
        {s.judgedOn ? ` · age judged on ${s.judgedOn}` : " · age clock unknown"}
        {s.familyLabel && s.familyLabel !== s.label ? ` · family ${s.familyLabel}` : ""}
      </p>
      <dl className={styles.clockList}>
        {s.clocks.map((c) => (
          <div key={c.key} className={styles.clockItem}>
            <dt>{c.label}</dt>
            <dd>
              <Clock at={c.at} />
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

const SOURCE_COLUMNS = [
  {
    key: "source",
    header: "Source",
    render: (s) => <span className={`${styles.sourceName} ${styles.wrap}`}>{s.label}</span>,
  },
  {
    key: "status",
    header: "Status",
    render: (s) =>
      s.voting ? (
        "Voting"
      ) : (
        <span className={`${styles.notVoting} ${styles.wrap}`}>
          {s.statusLabel} — {s.exclusionLabel || "reason not published"}
        </span>
      ),
  },
  {
    key: "share",
    header: "Share",
    headerInfoLabel: "vote share",
    numeric: true,
    headerInfo:
      "How much say the source had in the blend — its effective weight over the voters' total. A non-voter has no share, which is not a zero share.",
    render: (s) =>
      formatShare(s.voteShare) ?? (
        <>
          <span aria-hidden="true">—</span>
          <span className="ds-visually-hidden">no share — not voting</span>
        </>
      ),
  },
  {
    key: "contribution",
    header: "≈ Contrib.",
    numeric: true,
    headerInfo:
      "Vote share × the source's normalized value. An approximation of influence, not an exact split of the value.",
    headerInfoLabel: "approximate contribution",
    render: (s) =>
      s.contribution == null ? (
        <>
          <span aria-hidden="true">—</span>
          <span className="ds-visually-hidden">none</span>
        </>
      ) : (
        `${s.contributionIsApproximate ? "≈ " : ""}${formatNumber(s.contribution)}`
      ),
  },
];

const LOO_COLUMNS = [
  { key: "label", header: "Left out" },
  {
    key: "valueWithout",
    header: "Without",
    headerInfo: "The blend recomputed with this one source left out.",
    headerInfoLabel: "value without it",
    numeric: true,
    render: (r) => formatNumber(r.valueWithout, 1) ?? "unknown",
  },
  {
    key: "delta",
    header: "Change",
    numeric: true,
    render: (r) => formatSigned(r.delta) ?? "unknown",
  },
];

/** Pure view over one payload — rendered by the fetching wrapper and by tests. */
export function ValueExplainDetailView({ payload, customMix = false, secondOpinion = null }) {
  const v = valueExplainView(payload);
  const est = v.estimator;
  const loo = v.leaveOneOut;
  return (
    <div className={styles.explain}>
      {customMix ? (
        <Banner tone="info" title="Explains the default board">
          <p className={styles.muted}>
            Your custom source mix re-weights the value shown above; the weights and shares
            here are the default board&rsquo;s.
          </p>
        </Banner>
      ) : null}
      {!v.isV2 ? (
        <Banner tone="info" title="Older explanation format">
          <p className={styles.muted}>
            The server answered {v.version || "an unversioned explanation"}, which does not
            publish the estimator, source clocks or exclusion reasons — they show as unknown.
          </p>
        </Banner>
      ) : null}

      <section aria-labelledby="vx-estimator">
        <h3 id="vx-estimator" className={styles.sectionTitle}>
          Estimator
        </h3>
        {est ? (
          <dl className={styles.facts}>
            <div className={styles.fact}>
              <dt>Method</dt>
              <dd>{est.pathLabel}</dd>
            </div>
            <div className={styles.fact}>
              <dt>Aggregation</dt>
              <dd>
                {est.rungLabel || "not published"}
                {est.voters != null ? ` · ${est.voters} voting` : ""}
              </dd>
            </div>
            <div className={styles.fact}>
              <dt>Single-source haircut</dt>
              <dd>{est.haircut ? "applied" : "not applied"}</dd>
            </div>
            {est.overrides.length > 0 ? (
              <div className={styles.fact}>
                <dt>Overrides after the blend</dt>
                <dd>{est.overrides.join("; ")}</dd>
              </div>
            ) : null}
            {/* The backend stamps anchorValue on offense rows too, as a
                diagnostic; it describes the value only on the anchor path. */}
            {est.path === "anchor_plus_alpha_shrinkage" && est.anchorValue != null ? (
              <div className={styles.fact}>
                <dt>Anchor</dt>
                <dd>
                  {formatNumber(est.anchorValue)}
                  {est.alphaShrinkage != null ? ` · shrinkage α ${est.alphaShrinkage}` : ""}
                </dd>
              </div>
            ) : null}
            <div className={styles.fact}>
              <dt>Published value</dt>
              <dd>{v.modelValue != null ? formatNumber(v.modelValue) : "not priced"}</dd>
            </div>
          </dl>
        ) : (
          <p className={styles.muted}>The estimator is not published for this asset.</p>
        )}
      </section>

      <section aria-labelledby="vx-sources">
        <h3 id="vx-sources" className={styles.sectionTitle}>
          Sources, clocks and exclusions
        </h3>
        <p className={styles.attribution} data-exact={v.attributionExact ? "true" : "false"}>
          {v.attributionExact ? (
            <>
              <strong>Exact attribution for this row.</strong> The estimator is a plain
              weighted mean (or a single source) with no haircut or override, so share ×
              value reproduces the blend, up to rounding.
            </>
          ) : (
            <>
              <strong>Approximate attribution.</strong> Vote share × normalized value shows
              how much say each source had; it is not an exact split of the value, and with
              this estimator the contributions need not add up to it.
            </>
          )}
        </p>
        {v.breakdownAvailable ? (
          <DataTable
            caption="Every source observed for this asset: voting status and reason, vote share, approximate contribution, freshness treatment and its clocks"
            columns={SOURCE_COLUMNS}
            rows={v.sources}
            rowKey={(s) => s.key}
            density="compact"
            renderAfterRow={(s) => (
              <tr className={styles.detailRow}>
                <td colSpan={SOURCE_COLUMNS.length}>
                  <SourceDetail s={s} />
                </td>
              </tr>
            )}
          />
        ) : (
          <p className={styles.muted}>
            No per-source breakdown is published for this asset, so there is nothing to
            itemise.
          </p>
        )}
      </section>

      <section aria-labelledby="vx-loo">
        <h3 id="vx-loo" className={styles.sectionTitle}>
          Leave-one-out <span className={styles.qualifier}>(not additive)</span>
        </h3>
        {loo && loo.available ? (
          <>
            <p className={styles.muted}>
              Each row re-runs the blend with one source left out, keeping the others&rsquo;
              stamped weights; the outlier filter and freshness are not re-run. The changes
              are not additive — they do not sum to the value and cannot be combined.
            </p>
            <DataTable
              caption="Blend with each voting source left out, and the change from the published blend; not additive"
              columns={LOO_COLUMNS}
              rows={loo.rows}
              rowKey={(r) => r.key}
              density="compact"
            />
          </>
        ) : (
          <p className={styles.muted}>
            Leave-one-out unavailable: {loo ? loo.reason : "not published by this server"}.
          </p>
        )}
      </section>

      {/* INTEGRATION SEAM — Signals second opinion (#1555 Unit A, PR #1572).
          The rank-only, NON-VOTING Signals opinion is owned by
          components/trade/SignalsRankOpinion.jsx + lib/second-opinions.js
          ::rankOnlyOpinionFor on `claude/signals-adapter`. It is not on this
          branch's base, so nothing renders here until the caller passes it
          in; once #1572 lands, the Player File passes a single-asset
          rendering through `secondOpinion`. Never a value, never a vote. */}
      {secondOpinion ? (
        <section aria-labelledby="vx-second">
          <h3 id="vx-second" className={styles.sectionTitle}>
            Second opinions <span className={styles.qualifier}>(not counted)</span>
          </h3>
          {secondOpinion}
        </section>
      ) : null}
    </div>
  );
}

/** Fetching wrapper: loading, failure with retry, then the view. */
export default function ValueExplainDetail({ playerKey, customMix = false, secondOpinion = null }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({ key: null, status: "loading" });
  const requestKey = `${playerKey ?? ""}#${attempt}`;

  useEffect(() => {
    if (!playerKey) return undefined;
    const ctl = new AbortController();
    fetch(valueExplainUrl(playerKey), {
      credentials: "same-origin",
      cache: "no-store",
      signal: ctl.signal,
    })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok || !body) {
          setResult({ key: requestKey, status: "error", kind: classifyFailure(res.status) });
        } else {
          setResult({ key: requestKey, status: "ok", payload: body });
        }
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setResult({ key: requestKey, status: "error", kind: "network" });
      });
    return () => ctl.abort();
  }, [playerKey, requestKey]);

  if (!playerKey) {
    return <p className={styles.muted}>{FAILURE_COPY.not_found}</p>;
  }
  // A result for a previous request is stale: show loading, not old data
  // for a different player.
  if (result.key !== requestKey || result.status === "loading") {
    return (
      <div role="status" aria-label="Loading the value explanation">
        <SkeletonText lines={4} />
      </div>
    );
  }
  if (result.status === "error") {
    const retryable = result.kind !== "auth" && result.kind !== "not_found";
    return (
      <div className={styles.failure}>
        <p className={styles.muted}>{FAILURE_COPY[result.kind] || FAILURE_COPY.error}</p>
        {retryable ? (
          <Button size="sm" variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        ) : null}
      </div>
    );
  }
  return (
    <ValueExplainDetailView
      payload={result.payload}
      customMix={customMix}
      secondOpinion={secondOpinion}
    />
  );
}
