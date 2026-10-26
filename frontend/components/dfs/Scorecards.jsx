"use client";

/**
 * Scorecards — how the forecasts and models have actually done, always with
 * their sample size.  Reads stored evaluations (src/dfs/pit.py) and can replay
 * the owner's settled contests through the point-in-time backtest.  A small
 * sample is labelled as such: one slate proves nothing.  Lazily loaded.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Banner, Button, DataTable, EmptyState } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

const KIND_LABELS = { ownership: "Ownership", duplication: "Duplication", backtest: "Backtest" };

function num(v, digits = 2) {
  return v == null || !Number.isFinite(v) ? "—" : v.toFixed(digits);
}

export default function Scorecards({ resultIds = [] }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [backtest, setBacktest] = useState(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/dfs/evaluations", { credentials: "same-origin", cache: "no-store" });
      const body = await errorBody(res);
      if (!res.ok) setError(errorMessage(body, "Scorecards could not be loaded."));
      else setRows(body.evaluations || []);
    } catch {
      setError("Scorecards could not be loaded.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const replay = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/dfs/backtest", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: resultIds.map((resultId) => ({ resultId })) }),
      });
      const body = await errorBody(res);
      if (!res.ok) setError(errorMessage(body, "The backtest could not run."));
      else {
        setBacktest(body);
        await load();
      }
    } catch {
      setError("The backtest could not run.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className={styles.objective}>
      <legend>Scorecards</legend>
      <p className={styles.note}>
        How each forecast source and model has done against settled results, with how many players or lineups it was
        judged on. Small samples are flagged; nothing is promoted from a handful of slates.
      </p>
      {resultIds.length ? (
        <div className={styles.actions}>
          <Button variant="secondary" onClick={replay} loading={busy}>
            Replay imported results (backtest)
          </Button>
        </div>
      ) : null}
      {backtest ? (
        <p className={styles.note} role="status">
          Replayed {backtest.contests} contest(s) using only what was known before lock
          {backtest.skipped?.length ? `; ${backtest.skipped.length} skipped (lock time unknown)` : ""}. {backtest.note}
        </p>
      ) : null}
      {rows === null ? null : rows.length ? (
        <DataTable
          caption="Stored evaluations"
          columns={[
            { key: "kind", header: "Kind", render: (r) => KIND_LABELS[r.kind] || r.kind },
            { key: "subject", header: "Source / model" },
            {
              key: "n",
              header: "Sample",
              numeric: true,
              render: (r) => (r.metrics?.smallSample ? `${r.n} (small)` : r.n),
            },
            { key: "mae", header: "MAE", numeric: true, render: (r) => num(r.metrics?.mae) },
            { key: "bias", header: "Bias", numeric: true, hideBelow: "md", render: (r) => num(r.metrics?.bias) },
            { key: "spearman", header: "Rank corr.", numeric: true, hideBelow: "md", render: (r) => num(r.metrics?.spearman) },
          ]}
          rows={rows}
          rowKey={(r) => r.evaluationId}
          density="compact"
        />
      ) : (
        <EmptyState title="No evaluations yet" description="Import a finished contest's standings to score your forecasts." />
      )}
      {error ? (
        <Banner tone="negative" title="Scorecards">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
