"use client";

/**
 * GameDayPanel — the canonical Game Day surface (W1-25/W1-26, #1335/#1334).
 *
 * The private counterpart to /league's public preview. That one is
 * head-to-head record and recent form, which are facts about the past.
 * This one is projections, win and beat-median probabilities, best-ball
 * lineup chances and game leverage — proprietary decision intelligence
 * under CLAUDE.md §5, which is why it lives on a private route and reads a
 * `no-store` endpoint.
 *
 * DISPLAY ONLY. Every number is read from `GET /api/matchup/intel`
 * verbatim; nothing is recomputed, re-ranked or re-derived (the same
 * materializer relationship `buildRows` has with the canonical contract).
 * Presentation helpers live in `lib/game-day-view.js` and do no math.
 *
 * Owner hierarchy (2026-09-24 escalation on #1335):
 *   1. MatchupHero      — score now / projected finish / win / median
 *   2. WhatMattersNow   — 3–5 evidence-backed items
 *   3. NflSlate         — every game, kickoff order, relevance emphasized
 *   4. BestBallDetails  — collapsed: counting / could enter / finished
 *   5. DataInfo         — collapsed: sources, coverage, timestamps, method
 *
 * REFRESH IN PLACE (carried from draft PR #1346, owner decision in its
 * comment 5825392001, plus the league guard it lacked):
 *   - polls never overlap; a manual refresh or context change aborts the
 *     request in flight (AbortController) and its late response cannot
 *     publish — checked by identity even when a transport ignores abort;
 *   - `requestKey` = [leagueKey, team, week, season]. A response is only
 *     published into the context that asked for it, so a late answer for a
 *     previously selected LEAGUE, team, week or season can never replace
 *     the current one;
 *   - a background refresh keeps the last good answer on screen (the tree
 *     stays mounted, so scroll, focus and every expanded section survive)
 *     and reports "Refresh unavailable" locally on a transient failure; an
 *     explicit refusal (auth, week state, team) replaces it;
 *   - a hidden tab does not poll; it refreshes when it becomes visible;
 *   - `validMatchupPayload` refuses a malformed 200 rather than rendering
 *     it as a useful answer — including one for a different league or a
 *     different TEAM than the one asked for.
 *
 * TEAM SWITCHER (owner directive 2026-09-25). Game Day answers for ANY
 * roster in the selected league. The perspective is `?team=<ownerId>` in
 * the URL (refresh keeps it, back/forward walks it, a link shares it); the
 * picker pushes it and the request key above does the rest, so a slow Team
 * A answer can never publish under Team C. The list is the backend's own
 * `leagueTeams` for the requested league, remembered per league so the
 * picker stays mounted (and focused) while the next team loads, and dropped
 * the moment the league changes. Every number still comes from the backend,
 * which composes the chosen side out of the same league-week render.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { EmptyState, FailureState, SkeletonText } from "@/components/ds";
import { useLeague } from "@/components/useLeague";
import { useUserState } from "@/components/useUserState";
import BestBallDetails from "@/components/game-day/BestBallDetails";
import DataInfo from "@/components/game-day/DataInfo";
import MatchupHero from "@/components/game-day/MatchupHero";
import NflSlate from "@/components/game-day/NflSlate";
import TeamPicker from "@/components/game-day/TeamPicker";
import WhatMattersNow from "@/components/game-day/WhatMattersNow";
import styles from "@/components/game-day/game-day.module.css";
import { validLeagueTeams } from "@/lib/game-day-view";

const POLL_MS = 60000;
// While the server is computing the forecast (probabilityState PENDING, Game
// Day G), check back sooner: the background run takes tens of seconds and the
// next poll after it serves the finished generation.
const PENDING_POLL_MS = 10000;

export function validMatchupPayload(body, expectedLeagueKey = "", expectedOwnerId = "") {
  return (
    body !== null &&
    typeof body === "object" &&
    !Array.isArray(body) &&
    typeof body.leagueKey === "string" &&
    body.leagueKey.length > 0 &&
    (!expectedLeagueKey || body.leagueKey === expectedLeagueKey) &&
    Number.isInteger(body.season) &&
    body.season > 0 &&
    Number.isInteger(body.week) &&
    body.week > 0 &&
    ["pregame", "live", "final"].includes(body.mode) &&
    body.team !== null &&
    typeof body.team === "object" &&
    !Array.isArray(body.team) &&
    typeof body.team.ownerId === "string" &&
    body.team.ownerId.length > 0 &&
    // The team asked for is the team answered: another team's numbers must
    // never render under the selected team's name.
    (!expectedOwnerId || body.team.ownerId === expectedOwnerId)
  );
}

export function GameDayLoading({ teamName = "" }) {
  return (
    <div className={styles.loading} role="status">
      <p className={styles.note}>
        {teamName ? `Loading ${teamName}'s matchup...` : "Loading this week's matchup..."}
      </p>
      <SkeletonText lines={4} />
    </div>
  );
}

export default function GameDayPanel() {
  const [state, setState] = useState({ status: "loading", payload: null, error: null });
  const requestRef = useRef(null);

  // SELECTED-TEAM CONTEXT (W1-25). `useUserState().selectedTeam` is the
  // switcher's own answer, the same one /rosters and /phases read. An
  // explicit `?team=<ownerId>` WINS (linkable per team, and the only way a
  // session with no selected team can see a real team) — the same
  // explicit-over-implicit precedence the backend resolver uses.
  const { state: userState } = useUserState();
  const searchParams = useSearchParams();
  const router = useRouter();
  const pathname = usePathname() || "/game-day";
  const urlOwnerId = String(searchParams?.get("team") || "").trim();
  const myOwnerId = userState?.selectedTeam?.ownerId ? String(userState.selectedTeam.ownerId) : "";
  const selectedOwnerId = urlOwnerId || myOwnerId;

  // SELECTED-LEAGUE CONTEXT. Sent explicitly so the answer is for the
  // league the switcher shows, and part of the request key so a response
  // for a previously selected league can never publish. `?leagueKey=`
  // wins, like `?team=`. While the league list is still resolving we wait
  // rather than ask about whichever league the server would default to.
  const { selectedLeagueKey, loading: leagueLoading } = useLeague();
  const urlLeagueKey = String(searchParams?.get("leagueKey") || "").trim();
  const leagueKey = urlLeagueKey || selectedLeagueKey || "";
  const leagueReady = Boolean(urlLeagueKey) || !leagueLoading;
  // The registry key is canonical, so its echo must match exactly; a URL
  // key may be an alias the backend canonicalises, so it is not compared.
  const expectedLeagueKey = urlLeagueKey ? "" : selectedLeagueKey || "";

  // `week` / `season` forwarded verbatim: the endpoint's `_int_param`
  // treats an unparseable value as absent and falls back to the HOST's
  // clock. Deciding that here too is how page and endpoint would start to
  // disagree about which week is shown. They keep a completed week's FINAL
  // Game Day reachable after the host rolls over.
  const urlWeek = String(searchParams?.get("week") || "").trim();
  const urlSeason = String(searchParams?.get("season") || "").trim();
  const requestKey = JSON.stringify([leagueKey, selectedOwnerId, urlWeek, urlSeason]);

  // The league's rosters, as the backend listed them for THIS requested
  // league. Kept across a team switch (the picker must not vanish while the
  // next team loads) and ignored the moment the league differs.
  const [roster, setRoster] = useState({ leagueKey: null, teams: [] });
  const leagueTeams = roster.leagueKey === leagueKey ? roster.teams : [];

  const load = useCallback(
    async ({ background = false } = {}) => {
      // Polls never overlap. A manual retry or a context change supersedes
      // an old request; its response cannot publish into the new context.
      if (background && requestRef.current) return;
      requestRef.current?.abort();
      const controller = new AbortController();
      requestRef.current = controller;
      const keepPrevious = (previous) =>
        background && previous.status === "ok" && previous.requestKey === requestKey;
      setState((previous) =>
        keepPrevious(previous)
          ? { ...previous, refreshing: true, refreshError: false }
          : { status: "loading", payload: null, error: null, requestKey },
      );
      try {
        const params = new URLSearchParams();
        if (leagueKey) params.set("leagueKey", leagueKey);
        if (selectedOwnerId) params.set("team", selectedOwnerId);
        if (urlWeek) params.set("week", urlWeek);
        if (urlSeason) params.set("season", urlSeason);
        const qs = params.toString() ? `?${params.toString()}` : "";
        const res = await fetch(`/api/matchup/intel${qs}`, {
          cache: "no-store",
          signal: controller.signal,
        });
        const body = await res.json().catch(() => ({}));
        if (controller.signal.aborted || requestRef.current !== controller) return;
        if (res.ok) {
          if (!validMatchupPayload(body, expectedLeagueKey, selectedOwnerId)) {
            setState((previous) =>
              keepPrevious(previous)
                ? { ...previous, refreshing: false, refreshError: true }
                : {
                    status: "error",
                    payload: null,
                    error: {
                      error: "invalid_matchup",
                      message: "The matchup response is incomplete. Please retry.",
                    },
                    requestKey,
                  },
            );
            return;
          }
          if (validLeagueTeams(body.leagueTeams)) {
            setRoster({ leagueKey, teams: body.leagueTeams });
          }
          setState({ status: "ok", payload: body, error: null, requestKey });
          return;
        }
        // A team this league does not hold (or no team at all — a guest or
        // unlinked session) still names the teams it DOES hold, so the
        // picker can recover in-league — never elsewhere.
        if (
          (body.error === "team_not_found" || body.error === "team_required") &&
          validLeagueTeams(body.leagueTeams) &&
          (!expectedLeagueKey || body.leagueKey === expectedLeagueKey)
        ) {
          setRoster({ leagueKey, teams: body.leagueTeams });
        }
        // The error CODE is the state. Explicit domain/auth refusals
        // replace the old answer; a transient server failure may retain it
        // only with a visible "Refresh unavailable" warning.
        const transient = res.status >= 500 && body.error !== "clock_unavailable";
        setState((previous) =>
          keepPrevious(previous) && transient
            ? { ...previous, refreshing: false, refreshError: true }
            : {
                status: "error",
                payload: null,
                error: { httpStatus: res.status, ...body },
                requestKey,
              },
        );
      } catch (err) {
        if (controller.signal.aborted || requestRef.current !== controller) return;
        setState((previous) =>
          keepPrevious(previous)
            ? { ...previous, refreshing: false, refreshError: true }
            : {
                status: "error",
                payload: null,
                error: { error: "network", detail: String(err) },
                requestKey,
              },
        );
      } finally {
        if (requestRef.current === controller) requestRef.current = null;
      }
    },
    [leagueKey, selectedOwnerId, urlWeek, urlSeason, requestKey, expectedLeagueKey],
  );

  useEffect(() => {
    if (!leagueReady) return undefined;
    if (!document.hidden) load();
    const refreshVisible = () => {
      if (!document.hidden) load({ background: true });
    };
    const timer = setInterval(refreshVisible, POLL_MS);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refreshVisible);
      requestRef.current?.abort();
      requestRef.current = null;
    };
  }, [load, leagueReady]);

  const pendingPayload = state.payload?.probabilityState === "PENDING" ? state.payload : null;
  useEffect(() => {
    if (!pendingPayload) return undefined;
    const timer = setTimeout(() => {
      if (!document.hidden) load({ background: true });
    }, PENDING_POLL_MS);
    return () => clearTimeout(timer);
  }, [pendingPayload, load]);

  const manualRefresh = useCallback(() => load({ background: true }), [load]);

  // Switching perspective is a URL change: `team` is replaced, every other
  // parameter (league, week, season) is carried as-is. `push`, so back
  // returns to the previous team; no scroll jump.
  const selectTeam = useCallback(
    (ownerId) => {
      if (!ownerId) return;
      const params = new URLSearchParams(Array.from(searchParams || []));
      params.set("team", ownerId);
      router.push(`${pathname}?${params.toString()}`, { scroll: false });
    },
    [router, pathname, searchParams],
  );

  const current = state.status === "ok" && state.requestKey === requestKey ? state.payload : null;
  const shownOwnerId = selectedOwnerId || current?.team?.ownerId || "";
  const shownTeam = leagueTeams.find((t) => t.ownerId && t.ownerId === shownOwnerId) || null;

  return (
    // One stable tree: the picker stays mounted (and keeps focus) while the
    // body below moves through loading / error / ready for the new team.
    <div className={styles.stack}>
      {leagueTeams.length > 0 ? (
        <TeamPicker
          teams={leagueTeams}
          value={shownOwnerId}
          myOwnerId={myOwnerId}
          opponentOwnerId={current?.opponent?.ownerId || ""}
          onSelect={selectTeam}
        />
      ) : null}
      <GameDayBody
        state={state}
        requestKey={requestKey}
        teamName={shownTeam?.teamName || ""}
        leagueTeamsKnown={leagueTeams.length > 0}
        onRetry={load}
        onRefresh={manualRefresh}
      />
    </div>
  );
}

function GameDayBody({ state, requestKey, teamName, leagueTeamsKnown, onRetry, onRefresh }) {
  if (state.status === "loading" || state.requestKey !== requestKey) {
    return <GameDayLoading teamName={teamName} />;
  }

  if (state.status === "error") {
    const code = state.error?.error;
    // These are STATES, not faults, and `EmptyState` is the quiet voice for
    // them: "the games started", "the host has not said", "pick a team".
    if (code === "week_in_progress") {
      return (
        <EmptyState
          title="This week has already started"
          description="Pregame intelligence is only meaningful before kickoff, and live evidence for this week could not be assembled, so nothing is shown rather than a pregame number presented as a live one."
        />
      );
    }
    if (code === "clock_unavailable") {
      return (
        <EmptyState
          title="The host has not stated the current week"
          description="Sleeper did not report a season and week, and guessing one would describe a different week than your league is playing."
        />
      );
    }
    if (code === "team_required") {
      return (
        <EmptyState
          title="No team selected"
          description={
            leagueTeamsKnown
              ? "Choose any team in this league above to see its Game Day."
              : "Pick your team from the switcher above, or pass ?team= on this URL."
          }
        />
      );
    }
    if (code === "team_not_found") {
      return (
        <EmptyState
          title="That team is not in this league"
          description={
            leagueTeamsKnown
              ? "Choose a team from this league above. Game Day never switches to another league to find it."
              : "Pick a team from the switcher above. Game Day never switches to another league to find it."
          }
        />
      );
    }
    return (
      <FailureState
        failure={{
          kind:
            state.error?.httpStatus === 401
              ? "auth"
              : state.error?.httpStatus === 503
                ? "degraded"
                : state.error?.error === "network"
                  ? "offline"
                  : "error",
          code: state.error?.error,
          message: state.error?.message || state.error?.detail || "",
        }}
        onRetry={() => onRetry()}
        variant="block"
        context="this week's matchup"
      />
    );
  }

  const p = state.payload || {};
  return (
    <div
      // Keyed by team: detail sections opened for one team never stay open,
      // looking current, under another.
      key={p.team?.ownerId || "team"}
      className={styles.stack}
      aria-busy={state.refreshing || undefined}
      data-game-day-ready="true"
      data-game-day-team={p.team?.ownerId || undefined}
    >
      <p
        role="status"
        className={`${styles.refreshStatus} ${state.refreshError ? styles.refreshStatusWarn : ""}`.trim()}
      >
        {state.refreshError
          ? "Refresh unavailable. Showing the last successful matchup update."
          : state.refreshing
            ? "Updating this matchup…"
            : ""}
      </p>
      <MatchupHero payload={p} refreshing={Boolean(state.refreshing)} onRefresh={onRefresh} />
      <WhatMattersNow payload={p} />
      <NflSlate payload={p} />
      <BestBallDetails payload={p} />
      <DataInfo payload={p} />
    </div>
  );
}
