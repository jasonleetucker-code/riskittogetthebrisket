"use client";

/**
 * /managers/compare — Manager comparisons (Manager Intelligence Batch E,
 * C6-MGR-02).
 *
 * `?a=<username>&b=<username>` puts two managers side by side: career
 * totals, season tendencies, portfolio summary, draft capital and suggested
 * archetypes — the SAME blocks the single-manager views show, computed once
 * by GET /api/manager-intel/compare (`src/intel/manager_compare.py`).
 * `?a=<username>&league=<leagueId>` shows where that manager's team sits in
 * one league (percentiles over the Batch C scouting rows).  Both may be
 * given.
 *
 * PRIVATE: it sits under /managers, on no public prefix
 * (lib/public-routes.js), so the middleware's session gate covers it.
 * Display only: `lib/manager-intel.js` lays the backend's blocks out; a
 * missing value reads "—" and a missing percentile says why.  Wide screens
 * get a three-column table; narrow screens the same rows stacked.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Banner,
  Button,
  Field,
  Input,
  PageHeader,
  Panel,
  SkeletonTable,
} from "@/components/ds";
import {
  USERNAME_RE,
  LEAGUE_ID_RE,
  compareHref,
  compareQuery,
  compareRows,
  errorMessage,
  formatValue,
  percentileText,
  readCompareParams,
} from "@/lib/manager-intel";
import { ArchetypeChips } from "../ManagerCareer";
import styles from "../managers.module.css";

function SideBySide({ payload }) {
  const rows = compareRows(payload);
  const nameA = payload.a?.manager?.displayName || payload.query?.a;
  const nameB = payload.b?.manager?.displayName || payload.query?.b;
  return (
    <>
      {payload.sameManager ? (
        <Banner tone="info" title="Same manager">
          Both usernames resolve to the same Sleeper account.
        </Banner>
      ) : null}
      <table className={`${styles.miniTable} ${styles.tableOnly}`}>
        <caption className={styles.srOnly}>
          {nameA} and {nameB} side by side.
        </caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">{nameA}</th>
            <th scope="col">{nameB}</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key}>
              <th scope="row">{r.label}</th>
              <td>{r.a}</td>
              <td>{r.b}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className={styles.scoutStack} aria-label="Comparison">
        {rows.map((r) => (
          <li key={r.key}>
            <strong>{r.label}</strong>
            <dl className={styles.scoutStackFacts}>
              <div>
                <dt>{nameA}</dt>
                <dd>{r.a}</dd>
              </div>
              <div>
                <dt>{nameB}</dt>
                <dd>{r.b}</dd>
              </div>
            </dl>
          </li>
        ))}
      </ul>
      {payload.sharedLeagueIds?.length ? (
        <p className={styles.note}>
          They share {payload.sharedLeagueIds.length} league
          {payload.sharedLeagueIds.length === 1 ? "" : "s"} this season.
        </p>
      ) : null}
      <div className={styles.compareArchetypes}>
        {["a", "b"].map((k) => (
          <section key={k} aria-label={`Archetypes for ${k === "a" ? nameA : nameB}`}>
            <h4>{k === "a" ? nameA : nameB}</h4>
            <ArchetypeChips archetypes={payload[k]?.archetypes} idPrefix={`cmp-${k}`} />
          </section>
        ))}
      </div>
      <p className={styles.note}>{payload.basis}</p>
    </>
  );
}

function LeagueStanding({ payload }) {
  const name = payload.league?.name || "this league";
  if (!payload.managerInLeague) {
    return (
      <p className={styles.note}>
        {payload.manager?.displayName || payload.query?.a} does not own a team in {name}
        {" "}(a co-owner is matched only by the team&apos;s owner).
      </p>
    );
  }
  return (
    <>
      <p className={styles.note}>
        {payload.team?.displayName} in {name} · {formatValue(payload.teamCount)} teams ·
        window {payload.windowApplied}
      </p>
      <div className={styles.tableScroll}>
      <table className={styles.miniTable}>
        <caption className={styles.srOnly}>Where this team sits in the league.</caption>
        <thead>
          <tr>
            <th scope="col">Measure</th>
            <th scope="col">Team</th>
            <th scope="col">League median</th>
            <th scope="col">Standing</th>
          </tr>
        </thead>
        <tbody>
          {(payload.metrics || []).map((m) => (
            <tr key={m.key}>
              <th scope="row">{m.label}</th>
              <td>{formatValue(m.value)}</td>
              <td>{formatValue(m.leagueMedian)}</td>
              <td>{percentileText(m)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      </div>
      <p className={styles.note}>Percentile: {payload.percentileDefinition}.</p>
    </>
  );
}

export default function ComparePage() {
  const [inputs, setInputs] = useState({ a: "", b: "", league: "" });
  const [state, setState] = useState({ phase: "idle", data: null, error: null });

  const run = useCallback(async ({ a, b, league }) => {
    if (!USERNAME_RE.test(a) || (!b && !league)) {
      setState({
        phase: "error",
        data: null,
        error: "Enter a manager and a second manager or a league id.",
      });
      return;
    }
    if ((b && !USERNAME_RE.test(b)) || (league && !LEAGUE_ID_RE.test(league))) {
      setState({ phase: "error", data: null, error: "Check the username and league id." });
      return;
    }
    setState({ phase: "loading", data: null, error: null });
    try {
      const response = await fetch(compareQuery({ a, b, leagueId: league }), {
        cache: "no-store",
        credentials: "same-origin",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setState({ phase: "error", data: null, error: errorMessage(response.status, body) });
        return;
      }
      setState({ phase: "ready", data: body, error: null });
      const href = compareHref({ a, b, leagueId: league });
      if (href) {
        try {
          window.history.replaceState(null, "", href);
        } catch {
          /* address bar is a convenience */
        }
      }
    } catch {
      setState({ phase: "error", data: null, error: errorMessage(0, null) });
    }
  }, []);

  useEffect(() => {
    const initial = readCompareParams(window.location.search);
    setInputs(initial);
    if (initial.a && (initial.b || initial.league)) run(initial);
  }, [run]);

  const submit = (event) => {
    event.preventDefault();
    run({ a: inputs.a.trim(), b: inputs.b.trim(), league: inputs.league.trim() });
  };
  const set = (key) => (event) => setInputs((prev) => ({ ...prev, [key]: event.target.value }));
  const data = state.data;

  return (
    <div className={`${styles.page} psi-editorial`}>
      <PageHeader
        title="Compare managers"
        description="Two managers side by side, or one manager against the rest of a league."
      />
      <form className={styles.search} onSubmit={submit} role="search">
        <Field label="Manager">
          <Input value={inputs.a} onChange={set("a")} maxLength={40} autoComplete="off" />
        </Field>
        <Field label="Compare with manager">
          <Input value={inputs.b} onChange={set("b")} maxLength={40} autoComplete="off" />
        </Field>
        <Field label="Or a league id">
          <Input value={inputs.league} onChange={set("league")} maxLength={24} inputMode="numeric" />
        </Field>
        <Button type="submit" variant="primary" loading={state.phase === "loading"}>
          Compare
        </Button>
      </form>
      <p className={styles.note}>
        <a href="/managers" className={styles.link}>
          Back to Manager Intelligence
        </a>
      </p>

      {state.phase === "error" ? (
        <Banner tone="negative" title="Comparison failed">
          {state.error}
        </Banner>
      ) : null}
      {state.phase === "loading" ? (
        <Panel title="Reading both managers">
          <p className={styles.note}>
            Each side reads every league, this season&apos;s activity and the league history —
            this can take a while.
          </p>
          <SkeletonTable rows={8} columns={3} />
        </Panel>
      ) : null}
      {state.phase === "ready" && data ? (
        <>
          {data.status === "partial" ? (
            <Banner tone="warning" title="Partly read">
              Some of the data behind this comparison could not be fully read from Sleeper, so
              counts may be low. Each manager&apos;s own page names what is missing.
            </Banner>
          ) : null}
          {data.managers ? (
            <Panel title="Side by side">
              <SideBySide payload={data.managers} />
            </Panel>
          ) : null}
          {data.league ? (
            <Panel title="Against the league">
              <LeagueStanding payload={data.league} />
            </Panel>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
