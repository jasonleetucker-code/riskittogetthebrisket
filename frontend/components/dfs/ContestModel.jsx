"use client";

/**
 * ContestModel — simulate a build against the contest it was built for, or ask
 * for a contest-aware portfolio.  The server simulates (src/dfs/contestsim.py,
 * portfolio_opt.py); this renders.  Every number here is a MODEL OUTPUT under
 * the assumptions listed with it — never a promise of profit — and nothing is
 * entered or submitted.  Lazily loaded from the build result.
 */

import React, { useState } from "react";
import { Banner, Button, DataTable, Field, Input, Select } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

const OBJECTIVES = [
  { value: "ev", label: "Expected profit" },
  { value: "log_growth", label: "Bankroll growth (needs bankroll)" },
  { value: "mean_downside", label: "Profit with downside penalty" },
];

function money(cents) {
  if (cents == null || !Number.isFinite(cents)) return "—";
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

function pct(p) {
  if (p == null || !Number.isFinite(p)) return "—";
  return `${(p * 100).toFixed(p < 0.01 ? 2 : 1)}%`;
}

async function post(path, body) {
  const res = await fetch(`/api/dfs${path}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: res.ok, body: await errorBody(res) };
}

function LineupMetrics({ rows, names }) {
  return (
    <DataTable
      caption="Simulated contest outcomes per lineup"
      columns={[
        { key: "lineup", header: "Lineup", sortable: false, render: (r) => r.lineup.map((p) => names.get(p) || p).join(", ") },
        { key: "expectedProfitCents", header: "Exp. profit", numeric: true, render: (r) => `${money(r.expectedProfitCents)} ± ${money(r.expectedPayoutSe)}` },
        { key: "pCash", header: "Cash", numeric: true, render: (r) => pct(r.pCash?.p) },
        { key: "pWin", header: "Win", numeric: true, render: (r) => pct(r.pWin) },
        { key: "copies", header: "Exp. copies", numeric: true, hideBelow: "md", render: (r) => (r.expectedCopies == null ? "—" : r.expectedCopies.toFixed(2)) },
      ]}
      rows={rows}
      rowKey={(r) => r.lineup.join("|")}
      density="compact"
    />
  );
}

function Assumptions({ out }) {
  return (
    <>
      <p className={styles.note}>
        Portfolio: expected profit {money(out.portfolio?.expectedProfitCents)} (± {money(out.portfolio?.expectedPayoutSe)} simulation
        error), cash in {pct(out.portfolio?.pCash?.p)} of {out.sims} simulations. {out.note}
      </p>
      {out.assumptions?.length ? (
        <ul className={styles.list} aria-label="Assumptions">
          {out.assumptions.map((a) => (
            <li key={a}>{a}</li>
          ))}
        </ul>
      ) : null}
    </>
  );
}

export default function ContestModel({ build, snapshotId, athletes }) {
  const [allowPriors, setAllowPriors] = useState(false);
  const [entries, setEntries] = useState("3");
  const [objective, setObjective] = useState("ev");
  const [bankroll, setBankroll] = useState("");
  const [busy, setBusy] = useState(null);
  const [error, setError] = useState(null);
  const [sim, setSim] = useState(null);
  const [portfolio, setPortfolio] = useState(null);
  const contestId = build.contest?.contestId;
  const names = new Map((athletes || []).map((a) => [a.player_id, a.name]));

  if (!contestId) {
    return (
      <p className={styles.note}>
        To simulate a contest, save or pick a contest in step 3 and build again for it. Simulation needs the exact payout
        ladder and field size.
      </p>
    );
  }

  const run = async (kind) => {
    setBusy(kind);
    setError(null);
    const common = { contestId, allowPriors, sims: 800, fieldSample: 1500 };
    const req =
      kind === "simulate"
        ? post("/simulate", { ...common, buildId: build.buildId })
        : post("/portfolio", {
            ...common,
            snapshotId,
            entries: Number(entries),
            objective,
            ...(bankroll ? { bankroll } : {}),
          });
    const { ok, body } = await req;
    setBusy(null);
    if (!ok) {
      setError(errorMessage(body, "The simulation could not run."));
      return;
    }
    if (kind === "simulate") setSim(body);
    else setPortfolio(body);
  };

  return (
    <fieldset className={styles.objective}>
      <legend>Contest model (simulation)</legend>
      <p className={styles.note}>
        Simulates {build.contest.name}: player outcomes drawn together, a modelled field, duplicates and the exact payout
        ladder. Model output only — not a forecast of profit — and nothing is entered.
      </p>
      <label className={styles.check}>
        <input type="checkbox" checked={allowPriors} onChange={(e) => setAllowPriors(e.target.checked)} />
        Use flagged default spreads for players without imported ranges (uncalibrated)
      </label>
      <div className={styles.actions}>
        <Button variant="secondary" onClick={() => run("simulate")} loading={busy === "simulate"} disabled={Boolean(busy)}>
          Simulate this build
        </Button>
      </div>
      {sim ? (
        <>
          <LineupMetrics rows={sim.perLineup} names={names} />
          <Assumptions out={sim} />
        </>
      ) : null}
      <div className={styles.controlGrid}>
        <Field label="Entries">
          <Input data-numeric inputMode="numeric" value={entries} onChange={(e) => setEntries(e.target.value)} />
        </Field>
        <Field label="Objective">
          <Select value={objective} onChange={(e) => setObjective(e.target.value)} options={OBJECTIVES} />
        </Field>
        {objective === "log_growth" ? (
          <Field label="Bankroll ($)">
            <Input data-numeric inputMode="decimal" value={bankroll} onChange={(e) => setBankroll(e.target.value)} />
          </Field>
        ) : null}
      </div>
      <div className={styles.actions}>
        <Button variant="secondary" onClick={() => run("portfolio")} loading={busy === "portfolio"} disabled={Boolean(busy)}>
          Optimize a portfolio for this contest
        </Button>
      </div>
      {portfolio ? (
        <>
          <p className={styles.note} role="status">
            Chose {portfolio.result.perLineup.length} of {portfolio.candidates} candidate lineups. The model suggests at
            most {portfolio.selection.recommendedEntries} entr{portfolio.selection.recommendedEntries === 1 ? "y" : "ies"}
            {" "}(it stops where the next entry's expected profit is not clearly positive).
            {portfolio.vsProjectionBaseline
              ? ` Versus the projected-points portfolio on the same simulations: ${money(portfolio.vsProjectionBaseline.profitDifferenceCents)} ± ${money(portfolio.vsProjectionBaseline.profitDifferenceSe)} — a within-model comparison.`
              : ""}{" "}
            Decision {portfolio.decisionId} recorded ({portfolio.timing.replace("_", " ")}).
          </p>
          <LineupMetrics rows={portfolio.result.perLineup} names={names} />
          <Assumptions out={portfolio.result} />
        </>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Simulation">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
