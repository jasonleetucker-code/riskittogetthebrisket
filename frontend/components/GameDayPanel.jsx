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
 *     it as a useful answer.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { EmptyState, FailureState, SkeletonText } from "@/components/ds";
import { useLeague } from "@/components/useLeague";
import { useUserState } from "@/components/useUserState";
import BestBallDetails from "@/components/game-day/BestBallDetails";
import DataInfo from "@/components/game-day/DataInfo";
import MatchupHero from "@/components/game-day/MatchupHero";
import NflSlate from "@/components/game-day/NflSlate";
import WhatMattersNow from "@/components/game-day/WhatMattersNow";
import styles from "@/components/game-day/game-day.module.css";

const POLL_MS = 60000;

export function validMatchupPayload(body, expectedLeagueKey = "") {
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
    body.team.ownerId.length > 0
  );
}

export function GameDayLoading() {
  return (
    <div className={styles.loading} role="status">
      <p className={styles.note}>Loading this week&apos;s matchup...</p>
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
  const urlOwnerId = String(searchParams?.get("team") || "").trim();
  const selectedOwnerId =
    urlOwnerId || (userState?.selectedTeam?.ownerId ? String(userState.selectedTeam.ownerId) : "");

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
          if (!validMatchupPayload(body, expectedLeagueKey)) {
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
          setState({ status: "ok", payload: body, error: null, requestKey });
          return;
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

  const manualRefresh = useCallback(() => load({ background: true }), [load]);

  if (state.status === "loading" || state.requestKey !== requestKey) {
    return <GameDayLoading />;
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
    if (code === "team_required" || code === "team_not_found") {
      return (
        <EmptyState
          title="No team selected"
          description="Pick your team from the switcher above, or pass ?team= on this URL."
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
        onRetry={() => load()}
        variant="block"
        context="this week's matchup"
      />
    );
  }

  const p = state.payload || {};
  return (
    <div className={styles.stack} aria-busy={state.refreshing || undefined} data-game-day-ready="true">
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
      <MatchupHero payload={p} refreshing={Boolean(state.refreshing)} onRefresh={manualRefresh} />
      <WhatMattersNow payload={p} />
      <NflSlate payload={p} />
      <BestBallDetails payload={p} />
      <DataInfo payload={p} />
    </div>
  );
}
