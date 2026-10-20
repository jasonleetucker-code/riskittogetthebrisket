"use client";

// Brisket Trade Advisor — trade builder, review, analyze and result
// (design §8.2-§8.4).  Lazy chunk: loaded by ./trade-advisor-shell.jsx once
// "your team" is chosen.
//
// The flow follows the directive's mobile order: 1 your team (shell) →
// 2 trade partner(s) → 3 build (each team's panel) → 4 review → 5 analyze →
// 6 recommendation.  Desktop lays the same steps out denser.
//
// It renders identities and the server's words only.  Asset lists arrive
// already ordered by the server for the requested sort; this component
// filters them and never reorders, ranks or values anything.  The
// recommendation is the backend's enum + fixed copy, rendered verbatim
// (design §3, §8.6).

import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Banner } from "@/components/ds/Banner";
import { Button } from "@/components/ds/Button";
import { Combobox } from "@/components/ds/Combobox";
import { canAnalyze, slotName, teamsById, toAnalyzeRequest, tradeIssues, tradeKey, DEFAULT_SORT } from "@/lib/trade-advisor";
import { fetchAdvisorAssets, postAdvisorAnalyze } from "@/lib/trade-advisor-client";
import { TeamCountControl, teamOptions } from "./trade-advisor-shell.jsx";
import { AdvisorTeamPanel } from "./_advisor-team-panel.jsx";
import { AdvisorSummary } from "./_advisor-summary.jsx";
import { AdvisorResult } from "./_advisor-result.jsx";
import styles from "./trade-advisor.module.css";

const AdvisorAssetSheet = lazy(() => import("./_advisor-asset-sheet.jsx"));

// One cache entry per (team, sort, epoch): {status, data?, error?}.  The
// epoch bumps on a 409, a generation change or a stale-tab refresh, which
// drops every list at once.
function useAssetLists(epoch) {
  const [lists, setLists] = useState({});
  const controllers = useRef({});
  useEffect(() => {
    setLists({});
    for (const c of Object.values(controllers.current)) c.abort();
    controllers.current = {};
  }, [epoch]);
  useEffect(() => () => {
    for (const c of Object.values(controllers.current)) c.abort();
  }, []);
  const load = useCallback(
    (rosterId, sort, { reload = false } = {}) => {
      const key = `${rosterId}|${sort}`;
      controllers.current[key]?.abort();
      const controller = new AbortController();
      controllers.current[key] = controller;
      setLists((prev) => ({ ...prev, [key]: { status: "loading", data: prev[key]?.data || null } }));
      fetchAdvisorAssets(rosterId, sort, { signal: controller.signal, reload: reload || epoch > 0 })
        .then((r) => {
          if (controller.signal.aborted) return;
          setLists((prev) => ({
            ...prev,
            [key]: r.ok ? { status: "ready", data: r.data } : { status: "error", error: r.error, data: null },
          }));
        })
        .catch(() => {});
    },
    [epoch],
  );
  return { lists, load };
}

export default function TradeAdvisorBuilder({
  state,
  dispatch,
  teams,
  limits,
  multiTeam,
  epoch,
  onResult,
  onLeaveResult,
  onRefreshLists,
  onUnavailable,
  onOpenOverview,
}) {
  const byId = useMemo(() => teamsById(teams), [teams]);
  const { lists, load } = useAssetLists(epoch);
  const [sheet, setSheet] = useState(null); // rosterId whose picker is open
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [cooldown, setCooldown] = useState(0);
  const analyzeRef = useRef(null);
  const issues = tradeIssues(state, teams);
  const ready = canAnalyze(state, teams) && cooldown === 0;
  const inTrade = useMemo(() => new Set(state.legs.map((l) => l.id)), [state.legs]);
  const stale = useMemo(() => new Set(state.staleIds), [state.staleIds]);
  const maxTeams = Math.min(4, (limits && limits.maxTeams) || 4);

  // 429 countdown.
  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((s) => Math.max(0, s - 1)), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const openSheet = (rid) => {
    setSheet(rid);
    const key = `${rid}|${sort}`;
    if (!lists[key] || lists[key].status === "error") load(rid, sort);
  };

  const changeSort = (next) => {
    setSort(next);
    if (sheet != null && !lists[`${sheet}|${next}`]) load(sheet, next);
  };

  const analyze = async () => {
    if (!ready) return;
    const body = toAnalyzeRequest(state);
    const key = tradeKey(body);
    dispatch({ type: "SUBMIT" });
    const controller = new AbortController();
    analyzeRef.current?.abort();
    analyzeRef.current = controller;
    let r;
    try {
      r = await postAdvisorAnalyze(body, { signal: controller.signal });
    } catch {
      return; // superseded
    }
    if (analyzeRef.current !== controller) return; // latest request wins
    if (r.ok) {
      onResult({ ...r.data, key });
      return;
    }
    if (r.error.kind === "disabled") {
      onUnavailable?.();
      return;
    }
    if (r.error.kind === "rate_limited") setCooldown(r.error.retryAfterSeconds);
    if (r.error.kind === "stale") onRefreshLists?.();
    dispatch({ type: "FAIL", error: r.error });
  };

  const multiUnavailable = state.teamCount > 2 && multiTeam !== "available";
  const submitting = state.phase === "submitting";

  if (state.phase === "result" && state.result) {
    return (
      <AdvisorResult
        state={state}
        teams={teams}
        onEdit={() => onLeaveResult("EDIT")}
        onNewTrade={() => onLeaveResult("NEW_TRADE")}
        onStartOver={() => onLeaveResult("START_OVER")}
        onRetry={analyze}
        retryDisabled={!ready}
      />
    );
  }

  return (
    <>
      <section className={styles.step} aria-labelledby="advisor-step-partner">
        <div className={styles.stepHead}>
          <h2 className={styles.stepTitle} id="advisor-step-partner">
            <span className={styles.stepEyebrow}>Step 2</span>
            {state.teamCount > 2 ? "Select the other teams" : "Select trade partner"}
          </h2>
        </div>
        <div className="mobile-only">
          <TeamCountControl
            value={state.teamCount}
            max={maxTeams}
            onChange={(count) => dispatch({ type: "SET_TEAM_COUNT", count })}
          />
        </div>
        <div className={styles.partners}>
          {state.slots.slice(1).map((rid, j) => {
            const index = j + 1;
            return (
              <Combobox
                key={index}
                id={`advisor-slot-${index}`}
                label={slotName(index)}
                placeholder="Search teams"
                value={rid}
                onChange={(v) => dispatch({ type: "SET_SLOT", index, rosterId: v })}
                options={teamOptions(teams, state.slots, index)}
              />
            );
          })}
        </div>
        {multiUnavailable ? (
          <Banner tone="info" title="Recommendations cover two-team trades for now">
            You can build and review a {state.teamCount}-team trade, but the advisor can&apos;t give a
            recommendation for trades with more than two teams yet.
          </Banner>
        ) : null}
      </section>

      <section className={styles.step} aria-labelledby="advisor-step-build">
        <div className={styles.stepHead}>
          <h2 className={styles.stepTitle} id="advisor-step-build">
            <span className={styles.stepEyebrow}>Step 3</span>
            Build your trade
          </h2>
        </div>
        {state.notice?.kind === "removed" ? (
          <Banner tone="info" onDismiss={() => dispatch({ type: "DISMISS_NOTICE" })}>
            Removed from the trade: {state.notice.labels.join(", ")}.
          </Banner>
        ) : null}
        {state.error ? <AdvisorError error={state.error} cooldown={cooldown} onRetry={analyze} onOpenOverview={onOpenOverview} /> : null}
        <div className={styles.panels} data-count={state.teamCount}>
          {state.slots.map((rid, index) =>
            rid == null ? null : (
              <AdvisorTeamPanel
                key={rid}
                index={index}
                team={byId.get(rid)}
                rosterId={rid}
                legs={state.legs.filter((l) => l.from === rid)}
                slots={state.slots}
                teams={teams}
                teamCount={state.teamCount}
                staleIds={stale}
                onAdd={() => openSheet(rid)}
                onRemove={(id) => dispatch({ type: "REMOVE_ASSET", id })}
                onRoute={(id, to) => dispatch({ type: "SET_DESTINATION", id, to })}
              />
            ),
          )}
        </div>
      </section>

      <section className={styles.step} aria-labelledby="advisor-step-review">
        <div className={styles.stepHead}>
          <h2 className={styles.stepTitle} id="advisor-step-review">
            <span className={styles.stepEyebrow}>Step 4</span>
            Review trade
          </h2>
        </div>
        <AdvisorSummary state={state} teams={teams} />
      </section>

      <section className={styles.step} aria-labelledby="advisor-step-analyze">
        <h2 className="ds-visually-hidden" id="advisor-step-analyze">
          Step 5: Analyze
        </h2>
        <div className={styles.analyzeRow}>
          {issues.length ? (
            <ul className={styles.issues} aria-label="Before you can analyze">
              {issues.map((i) => (
                <li key={`${i.code}-${i.slot ?? i.id ?? ""}`}>{i.message}</li>
              ))}
            </ul>
          ) : null}
          <Button
            variant="primary"
            className={styles.analyzeBtn}
            onClick={analyze}
            disabled={!ready}
            loading={submitting}
          >
            {submitting ? "Analyzing…" : "Analyze trade"}
          </Button>
        </div>
      </section>

      {sheet != null ? (
        <Suspense fallback={null}>
          <AdvisorAssetSheet
            team={byId.get(sheet)}
            rosterId={sheet}
            isYou={sheet === state.slots[0]}
            entry={lists[`${sheet}|${sort}`]}
            sort={sort}
            onSort={changeSort}
            inTrade={inTrade}
            onAdd={(asset) => dispatch({ type: "ADD_ASSET", asset, from: sheet })}
            onRetry={() => load(sheet, sort, { reload: true })}
            onClose={() => setSheet(null)}
          />
        </Suspense>
      ) : null}
    </>
  );
}

function AdvisorError({ error, cooldown, onRetry, onOpenOverview }) {
  if (error.kind === "stale") {
    return (
      <Banner tone="warning" title="Rosters changed">
        {error.message} Remove the flagged players or picks and analyze again.
      </Banner>
    );
  }
  if (error.kind === "rate_limited") {
    return (
      <Banner tone="warning" title="Please wait">
        {error.message}{" "}
        {cooldown > 0 ? <span data-testid="advisor-cooldown">You can try again in {cooldown}s.</span> : "You can try again now."}
      </Banner>
    );
  }
  if (error.kind === "invalid") {
    return (
      <Banner tone="warning" title="This trade can't be analyzed">
        {error.message}
      </Banner>
    );
  }
  return (
    <Banner tone="negative" title="No answer from the trade advisor">
      {error.message}{" "}
      <Button variant="secondary" size="sm" onClick={onRetry}>
        Try again
      </Button>
      {onOpenOverview ? (
        <>
          {" "}
          <Button variant="ghost" size="sm" onClick={onOpenOverview}>
            Go to the league overview
          </Button>
        </>
      ) : null}
    </Banner>
  );
}
