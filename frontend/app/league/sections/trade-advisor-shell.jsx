"use client";

// Brisket Trade Advisor — the team step (design §8.1-§8.3).
//
// Loaded by ../LeagueClient.jsx as its own chunk that is still
// SERVER-RENDERED (next/dynamic `ssr: true`): while the advisor is the
// hub's default tab the first paint shows the real team picker, not a
// loading flash, and with the advisor switched off /league loads none of
// this code.  Everything past the team step — partner selection, the
// asset picker, the summary and the result — is the lazy
// ./trade-advisor.jsx chunk, loaded once a team is chosen.
//
// What this shell holds: the server-fetched team list (identities and
// names only), the builder's reducer state (asset identities, labels,
// roster ids, the fairness result enums + fixed text) and the URL / session
// wiring.
// It never holds a value, a rank or a score (design §8.6).  Isolation: no
// import from the private trade, rankings or dynasty-data modules.
//
// State restore happens in an effect after mount — never during render —
// so server and first client render agree (no hydration mismatch).

import { Suspense, lazy, useCallback, useEffect, useReducer, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Combobox } from "@/components/ds/Combobox";
import { SegmentedControl } from "@/components/ds/SegmentedControl";
import {
  MAX_TEAMS,
  MIN_TEAMS,
  SESSION_KEY,
  advisorReducer,
  initialAdvisorState,
  restoreAdvisorState,
  serializeAdvisorState,
  teamLabel,
  toAnalyzeRequest,
  tradeKey,
} from "@/lib/trade-advisor";
import { fetchAdvisorTeams } from "@/lib/trade-advisor-client";
import { TRADE_ADVISOR_TAB, leagueTabHref } from "../tabs.js";
import styles from "./trade-advisor.module.css";

const TradeAdvisorBuilder = lazy(() => import("./trade-advisor.jsx"));

// Focus targets after leaving a result (see `pendingFocusRef`).
export const TEAM_STEP_HEADING_ID = "advisor-step-team";
export const BUILD_STEP_HEADING_ID = "advisor-step-build";

// Lists older than this are refetched when the tab becomes visible again.
const LIST_MAX_AGE_MS = 5 * 60 * 1000;

function readSession() {
  try {
    return window.sessionStorage.getItem(SESSION_KEY);
  } catch {
    return null;
  }
}

function writeSession(state) {
  try {
    window.sessionStorage.setItem(SESSION_KEY, serializeAdvisorState(state));
  } catch {
    /* private mode / blocked storage: the builder still works, unsaved */
  }
}

export function TeamCountControl({ value, onChange, max = MAX_TEAMS, className = "" }) {
  const options = [];
  for (let n = MIN_TEAMS; n <= max; n += 1) options.push({ value: n, label: String(n) });
  return (
    <div className={`${styles.teamCount} ${className}`.trim()}>
      <span className={styles.label} id="advisor-team-count-label">
        Teams involved
      </span>
      <SegmentedControl label="Teams involved" value={value} onChange={onChange} options={options} />
    </div>
  );
}

export function teamOptions(teams, slots, index) {
  return (teams || []).map((t) => {
    const taken = slots.some((rid, i) => i !== index && rid === t.rosterId);
    return {
      value: t.rosterId,
      label: t.teamName || t.displayName,
      description: t.teamName && t.teamName !== t.displayName ? t.displayName : undefined,
      disabled: taken,
      disabledReason: taken ? "in trade" : undefined,
    };
  });
}

export default function TradeAdvisorShell({ bootstrap, onUnavailable, onOpenOverview }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const urlTeam = searchParams.get("team");
  const urlStep = searchParams.get("step");

  const [boot, setBoot] = useState(() =>
    bootstrap && bootstrap.state === "ready"
      ? { status: "ready", data: bootstrap.data, at: Date.now() }
      : { status: "loading" },
  );
  const [epoch, setEpoch] = useState(0);
  const [state, dispatch] = useReducer(advisorReducer, undefined, initialAdvisorState);
  const restoredRef = useRef(false);
  // True from the render that carries the RESTORED state.  The URL effects
  // below wait for it: run in the restore commit they would see the
  // pre-restore state and strip `?team=` / `?step=result` from the URL.
  const [restored, setRestored] = useState(false);
  const lastResultRef = useRef(null);
  // Where keyboard focus goes after leaving a result (launch gate 8 /
  // WCAG 2.4.3): the button that was pressed unmounts with the result, so
  // without this focus falls to <body>.  "build" = the Build-your-trade
  // heading (Edit trade, New trade: the teams are kept); "team" = the
  // Which-team-is-yours heading (Start over: everything is cleared).
  const pendingFocusRef = useRef(null);
  const teams = boot.status === "ready" ? boot.data.teams : [];

  const loadTeams = useCallback(
    async ({ reload = false, signal } = {}) => {
      const r = await fetchAdvisorTeams({ signal, reload });
      if (signal?.aborted) return;
      if (r.ok) {
        setBoot({ status: "ready", data: r.data, at: Date.now() });
      } else if (r.state === "disabled") {
        onUnavailable?.();
      } else {
        setBoot((prev) => (prev.status === "ready" ? prev : { status: "error", error: r.error }));
      }
    },
    [onUnavailable],
  );

  // No server answer (timeout / network): ask from the browser once.
  useEffect(() => {
    if (boot.status !== "loading") return undefined;
    const controller = new AbortController();
    loadTeams({ signal: controller.signal }).catch(() => {});
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Restore after mount, once the team list is known.  The URL wins.
  useEffect(() => {
    if (restoredRef.current || boot.status !== "ready") return;
    restoredRef.current = true;
    const restored = restoreAdvisorState(readSession(), {
      urlTeam,
      teams: boot.data.teams,
      maxTeams: boot.data.limits.maxTeams || MAX_TEAMS,
    });
    lastResultRef.current = restored.result;
    // A saved result is shown again only for THIS trade on THIS board
    // generation (design §8.3: keyed by generation + trade hash).
    const showResult =
      Boolean(restored.result) &&
      urlStep === "result" &&
      restored.result.key === tradeKey(toAnalyzeRequest(restored)) &&
      restored.result.generation === boot.data.generation;
    if (!showResult) {
      restored.result = null;
      restored.phase = "build";
      if (urlStep === "result") navigate({ step: null });
    }
    dispatch({ type: "RESTORE", state: restored });
    setRestored(true);
  }, [boot, urlTeam, urlStep]);

  useEffect(() => {
    if (restoredRef.current) writeSession(state.result ? state : { ...state, result: lastResultRef.current });
  }, [state]);

  const navigate = useCallback(
    (params, mode = "replace") => {
      const href = leagueTabHref(TRADE_ADVISOR_TAB, searchParams.toString(), params);
      if (mode === "push") router.push(href, { scroll: false });
      else router.replace(href, { scroll: false });
    },
    [router, searchParams],
  );

  // `?team=` mirrors "your team" (replace: no history entry per choice).
  const perspective = state.slots[0];
  useEffect(() => {
    if (!restored) return;
    const want = perspective == null ? "" : String(perspective);
    if ((urlTeam || "") !== want) navigate({ team: want || null, step: state.phase === "result" ? "result" : null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [perspective, restored]);

  // Back from a result returns to the builder with the legs intact;
  // Forward re-shows the result only when it was computed for THIS trade.
  useEffect(() => {
    if (!restored) return;
    if (urlStep !== "result" && state.phase === "result") {
      dispatch({ type: "EDIT" });
    } else if (urlStep === "result" && state.phase === "build") {
      const cached = lastResultRef.current;
      if (
        cached &&
        cached.key === tradeKey(toAnalyzeRequest(state)) &&
        (boot.status !== "ready" || cached.generation === boot.data.generation)
      ) {
        dispatch({ type: "RESULT", result: cached });
      } else {
        navigate({ step: null });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [urlStep]);

  const onResult = useCallback(
    (result) => {
      lastResultRef.current = result;
      dispatch({ type: "RESULT", result });
      // Already on a result entry (Try again from a result): replace it.
      navigate({ step: "result" }, urlStep === "result" ? "replace" : "push");
      if (boot.status === "ready" && result.generation && result.generation !== boot.data.generation) {
        // The board or rosters moved since the lists loaded: refresh them
        // in the background.  The result itself is already current.
        setEpoch((e) => e + 1);
        loadTeams({ reload: true }).catch(() => {});
      }
    },
    [navigate, boot, loadTeams, urlStep],
  );

  const onLeaveResult = useCallback(
    (type) => {
      if (type === "START_OVER") lastResultRef.current = null;
      pendingFocusRef.current = type === "START_OVER" ? TEAM_STEP_HEADING_ID : BUILD_STEP_HEADING_ID;
      dispatch({ type });
      navigate({ step: null, ...(type === "START_OVER" ? { team: null } : {}) });
    },
    [navigate],
  );

  // Runs after the commit that replaced the result: both headings are in
  // the DOM by then (the builder chunk is already loaded — it rendered the
  // result).  A target that is not there yet stays pending.
  useEffect(() => {
    const target = pendingFocusRef.current;
    if (!target || state.phase === "result") return;
    const el = document.getElementById(target);
    if (!el) return;
    pendingFocusRef.current = null;
    el.focus();
  }, [state]);

  const refreshLists = useCallback(() => {
    setEpoch((e) => e + 1);
    loadTeams({ reload: true }).catch(() => {});
  }, [loadTeams]);

  // Long-lived tabs: refetch when visible again after LIST_MAX_AGE_MS.
  useEffect(() => {
    if (boot.status !== "ready") return undefined;
    const onVisible = () => {
      if (document.visibilityState === "visible" && Date.now() - boot.at > LIST_MAX_AGE_MS) refreshLists();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [boot, refreshLists]);

  // The team cap is the server's (`limits.maxTeams`: public config ceiling,
  // also capped at the league's team count), never a constant here.
  const maxTeams = boot.status === "ready" ? boot.data.limits.maxTeams || MAX_TEAMS : MAX_TEAMS;
  const rosters = boot.status === "ready" ? boot.data.rosters : null;

  return (
    <div className={`psi-editorial ${styles.root}`} data-testid="trade-advisor">
      {rosters && rosters.state !== "current" ? (
        <p className={styles.note} role="note" data-testid="advisor-roster-freshness">
          {rosters.asOf
            ? `Rosters as of ${rosters.asOf}. Recent trades or roster moves may not appear yet.`
            : "Roster freshness can't be confirmed right now. Recent trades or roster moves may not appear yet."}
        </p>
      ) : null}

      {boot.status === "ready" ? (
        <div className="desktop-only">
          <TeamCountControl
            value={state.teamCount}
            max={maxTeams}
            onChange={(count) => dispatch({ type: "SET_TEAM_COUNT", count, max: maxTeams })}
          />
        </div>
      ) : null}

      <section className={styles.step} aria-labelledby="advisor-step-team">
        <div className={styles.stepHead}>
          <h2 className={styles.stepTitle} id={TEAM_STEP_HEADING_ID} tabIndex={-1}>
            <span className={styles.stepEyebrow}>Step 1</span>
            Which team is yours?
          </h2>
        </div>
        {boot.status === "ready" ? (
          <div className={styles.teamPicker}>
            <Combobox
              id="advisor-your-team"
              label="Your team"
              placeholder="Search teams"
              value={perspective}
              onChange={(rid) => dispatch({ type: "SET_SLOT", index: 0, rosterId: rid })}
              options={teamOptions(teams, state.slots, 0)}
              hint="Its result is shown first, and you can view every other team's result too. Choosing a team doesn't sign you in, and the advisor never changes a roster or sends an offer."
            />
          </div>
        ) : boot.status === "error" ? (
          <div role="alert" className={styles.analyzeRow}>
            <p className={styles.note}>{boot.error?.message || "The trade advisor couldn't load."}</p>
            <div className={styles.resultActions}>
              <button
                type="button"
                className="ds-btn ds-btn--secondary"
                onClick={() => {
                  setBoot({ status: "loading" });
                  loadTeams({ reload: true }).catch(() => {});
                }}
              >
                Try again
              </button>
              {onOpenOverview ? (
                <button type="button" className="ds-btn ds-btn--ghost" onClick={onOpenOverview}>
                  Go to the league overview
                </button>
              ) : null}
            </div>
          </div>
        ) : (
          <p className={styles.note} role="status" aria-live="polite">
            Loading teams…
          </p>
        )}
      </section>

      {boot.status === "ready" && perspective != null ? (
        <Suspense
          fallback={
            <p className={styles.note} role="status">
              Loading the trade builder…
            </p>
          }
        >
          <TradeAdvisorBuilder
            state={state}
            dispatch={dispatch}
            teams={teams}
            limits={boot.data.limits}
            epoch={epoch}
            perspectiveName={teamLabel(teams.find((t) => t.rosterId === perspective))}
            onResult={onResult}
            onLeaveResult={onLeaveResult}
            onRefreshLists={refreshLists}
            onUnavailable={onUnavailable}
            onOpenOverview={onOpenOverview}
          />
        </Suspense>
      ) : null}
    </div>
  );
}
