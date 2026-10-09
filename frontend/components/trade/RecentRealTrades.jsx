"use client";

/**
 * RecentRealTrades — recorded real dynasty trades that moved an asset on
 * the calculator, with their league-format tags (C3-CALC-01 / TC-07 +
 * TC-10).
 *
 * Reference evidence, NOT a valuation: nothing here grades a trade, prices
 * an asset or touches the calculator's totals / verdict.  Every fact comes
 * from GET /api/market/trades/reference (a projection of the canonical
 * underlying-trade ledger); identity matching happens on the backend
 * through src/identity — this component only sends ids / board row names.
 *
 * States, never collapsed into one another:
 *   no assets      — nothing on the calculator yet
 *   loading
 *   unavailable    — no ledger on the server / server failure
 *                    ("we have no evidence", which is not "no trades")
 *   request_error  — a 4xx the request itself caused
 *   auth           — signed out
 *   ok             — trades, or an explicit "none recorded" empty state
 *
 * Only verified-dynasty trades arrive (the backend withholds unverified game
 * types and says how many); the panel is mounted only while open, so it
 * never refetches while collapsed.
 *
 * Loaded on demand from /trade (React.lazy inside a collapsed panel), so
 * none of this is in the page's first-load chunk.
 */

import { useEffect, useMemo, useState } from "react";
import { Banner, EmptyState, SkeletonTable } from "@/components/ds";
import {
  assetText,
  caveatTexts,
  formatMatchText,
  formatTagList,
  formatTimingText,
  referenceQueryFromSides,
  referenceQueryIsEmpty,
  referenceFailureKind,
  referenceQueryString,
  sideHeading,
  sourceText,
  withheldText,
} from "@/lib/recent-real-trades";
import styles from "./recent-real-trades.module.css";

function AssetItem({ asset }) {
  const text = assetText(asset);
  if (!asset.match) return <span className={styles.asset}>{text}</span>;
  return (
    <strong className={styles.assetMatched}>
      {text}
      <span className={styles.matchNote}>
        {asset.match === "exact" ? " (on your calculator)" : " (same round)"}
      </span>
    </strong>
  );
}

function TradeRow({ trade }) {
  const tags = formatTagList(trade.formatTags);
  return (
    <li className={styles.trade}>
      <div className={styles.tradeHead}>
        <span className={styles.date}>{trade.occurredDate || "Date unknown"}</span>
        <span className={styles.source}>{sourceText(trade)}</span>
      </div>
      <div className={styles.sides}>
        {trade.sides.map((side, idx) => (
          <div className={styles.side} key={idx}>
            <span className={styles.sideHeading}>{sideHeading(trade, idx)}</span>
            <span className={styles.assets}>
              {side.length ? (
                side.map((asset, i) => (
                  <span key={i}>
                    {i > 0 ? <span aria-hidden="true"> · </span> : null}
                    <AssetItem asset={asset} />
                  </span>
                ))
              ) : (
                <span className={styles.unknown}>No assets recorded</span>
              )}
            </span>
          </div>
        ))}
      </div>
      <p className={styles.tags} aria-label="League format">
        {tags.map((tag, i) => (
          <span key={tag.key} className={tag.known ? styles.tag : styles.unknown}>
            {i > 0 ? <span aria-hidden="true"> · </span> : null}
            {tag.text}
          </span>
        ))}
      </p>
      <p className={styles.meta}>
        {[formatTimingText(trade), formatMatchText(trade), ...caveatTexts(trade)].join(" · ")}
      </p>
    </li>
  );
}

export default function RecentRealTrades({ sides, leagueKey }) {
  const query = useMemo(() => referenceQueryFromSides(sides), [sides]);
  const qs = useMemo(() => referenceQueryString(query, leagueKey), [query, leagueKey]);
  const empty = referenceQueryIsEmpty(query);
  const [state, setState] = useState({ status: "idle", body: null, qs: null });

  useEffect(() => {
    if (empty) return undefined;
    const ctl = new AbortController();
    const timer = setTimeout(async () => {
      setState((s) => ({ ...s, status: "loading" }));
      try {
        const res = await fetch(`/api/market/trades/reference?${qs}`, {
          credentials: "same-origin",
          signal: ctl.signal,
        });
        const body = await res.json().catch(() => null);
        if (!res.ok || !body || body.state !== "ok") {
          setState({
            status: res.ok ? "unavailable" : referenceFailureKind(res.status),
            body,
            qs,
          });
          return;
        }
        setState({ status: "ok", body, qs });
      } catch (err) {
        if (err?.name === "AbortError") return;
        setState({ status: "unavailable", body: null, qs });
      }
    }, 400);
    return () => {
      clearTimeout(timer);
      ctl.abort();
    };
  }, [qs, empty]);

  if (empty) {
    return (
      <EmptyState
        title="No assets yet"
        description="Add players or picks to see recorded real trades that moved them."
      />
    );
  }
  if (state.status === "idle" || state.status === "loading") {
    return (
      <div aria-busy="true" aria-label="Loading recent real trades">
        <SkeletonTable rows={3} columns={3} />
      </div>
    );
  }
  if (state.status === "request_error") {
    return (
      <Banner tone="warning" title="Request not understood">
        The server rejected this lookup ({state.body?.error || "bad request"}). The trades on
        the calculator were not searched.
      </Banner>
    );
  }
  if (state.status === "auth") {
    return (
      <Banner tone="warning" title="Sign in to see real trades">
        Recorded trades are only shown to signed-in members.
      </Banner>
    );
  }
  if (state.status === "unavailable") {
    return (
      <Banner tone="info" title="Real-trade evidence unavailable">
        The recorded-trade ledger could not be read on the server, so no trades are shown. This is
        missing evidence, not a sign that these assets have not been traded.
      </Banner>
    );
  }

  const body = state.body;
  const trades = body.trades || [];
  const ledger = body.ledger || {};
  return (
    <div className={styles.root}>
      <p className={styles.lede}>
        Reference evidence, not a valuation — these trades do not change the totals or verdict
        above. Verified-dynasty trades since {body.since}
        {ledger.builtAt ? `; ledger rebuilt ${String(ledger.builtAt).slice(0, 10)}` : ""}.
      </p>
      {trades.length === 0 ? (
        <EmptyState
          title="No recorded trades"
          description="No trade in the recorded sample moved these assets in this window."
        />
      ) : (
        <ol className={styles.list}>
          {trades.map((t) => (
            <TradeRow key={t.id} trade={t} />
          ))}
        </ol>
      )}
      {withheldText(body.withheld) ? (
        <p className={styles.meta}>{withheldText(body.withheld)}</p>
      ) : null}
      {body.truncated ? (
        <p className={styles.meta}>
          Showing the {trades.length} most recent matching trades; older ones are not listed.
        </p>
      ) : null}
      {(body.query?.unresolved || []).length ? (
        <p className={styles.meta}>
          {body.query.unresolved.length} calculator asset
          {body.query.unresolved.length === 1 ? "" : "s"} could not be identified and{" "}
          {body.query.unresolved.length === 1 ? "was" : "were"} not searched.
        </p>
      ) : null}
      <details className={styles.about}>
        <summary>About this sample</summary>
        <ul>
          {(body.samplingBiases || []).map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}
