"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";
import { useRosterIntelligence } from "@/components/useRosterIntelligence";
import { useTeam } from "@/components/useTeam";
import { teamCutLadder } from "@/lib/roster-intelligence";
import { withValuationMode } from "@/lib/valuation-mode";
import { buildWaiverBidIndex } from "@/lib/waiver-faab";
import { computeWaiverAnalysis } from "@/lib/waiver-logic";

/**
 * useWaiverAnalysis — wraps the pure ``computeWaiverAnalysis`` helper
 * with the app's data plumbing (rows + sleeper teams + selected
 * league/team).  Returns a stable, memoized analysis object so the
 * page re-renders only when the underlying inputs (or filters) shift.
 *
 * Design notes:
 *
 *   • We pull ``rows`` from ``useApp`` (the AppShell context) rather
 *     than calling ``useDynastyData`` again — AppShell hydrates that
 *     hook once for every page and exposes the result through
 *     context, so reusing it avoids a redundant fetch.
 *
 *   • ``leagueMismatch`` short-circuits with ``analysis: null`` so the
 *     page can render the "data not ready" banner without crashing
 *     on a missing ``selectedTeam``.
 *
 *   • Memoization keys: ``rows`` reference (changes only on
 *     useDynastyData refetch), ``rawData?.sleeper?.teams`` reference,
 *     ``selectedTeam?.players`` reference, plus the four scalar
 *     toggles.  Avoids the O(N²) recompute on every keystroke.
 *
 *   • ``faabIndex`` is the ONE piece of this hook that is fetched
 *     rather than computed.  ``computeWaiverAnalysis`` runs over
 *     contract rows, and contract rows carry values, not bids — every
 *     dollar figure on this page is stamped by
 *     ``src/trade/faab_engine.py`` and reaches the client only on
 *     ``POST /api/waiver/suggestions``.  The page joins it onto its
 *     own rows at render time (``lib/waiver-faab.js``), exactly like
 *     the BDVM "Fund gap" column on /rankings, rather than letting a
 *     bid become a contract field.  ``bidFeed`` states the request's
 *     status (``"loading"`` / ``"failed"`` / ``null``) and ``retryBids``
 *     re-issues it, so the page can tell a pending bid from a failed one
 *     and offer a retry instead of one cause-less blank.
 *
 *   • WHO MAY BE DROPPED is fetched too, never computed (C2-DROP-01):
 *     the team's canonical cut ladder from
 *     ``GET /api/roster/intelligence?droppability=1``.  Unlike the bids
 *     it is NOT optional enrichment — every drop on the page comes from
 *     it — so it gates ``loading`` and, when it fails, the analysis
 *     carries ``dropState.state === "unavailable"`` and the page says so.
 */
export function useWaiverAnalysis({
  includeRookies = false,
  filters = {},
} = {}) {
  const { rows, rawData, loading, error } = useApp();
  const { selectedLeague } = useLeague();
  const { selectedTeam, leagueMismatch, availableTeams } = useTeam();

  const sleeperTeams = rawData?.sleeper?.teams;
  const myRosterNames = selectedTeam?.players;
  const idpEnabled = Boolean(selectedLeague?.idpEnabled);

  // Stabilize the filters object so a new object literal every render
  // doesn't cascade into an unnecessary recompute.  The page passes
  // primitive scalars; we destructure them here.
  const position = filters?.position || "ALL";
  const minGain = Number(filters?.minGain) || 0;
  const upgradeStrength = filters?.upgradeStrength || "all";

  const stableFilters = useMemo(
    () => ({ position, minGain, upgradeStrength }),
    [position, minGain, upgradeStrength],
  );

  const ownerId = selectedTeam?.ownerId ? String(selectedTeam.ownerId) : "";
  const ladderEnabled = Boolean(ownerId) && !leagueMismatch;
  const {
    loading: ladderLoading,
    data: ladderPayload,
    failure: ladderFailure,
  } = useRosterIntelligence({ ownerId, enabled: ladderEnabled, droppability: true });
  const cutLadder = useMemo(() => {
    if (!ladderEnabled) {
      return { state: "unavailable", reason: "team_required", reasonText: "no team is selected" };
    }
    if (ladderFailure) {
      return {
        state: "unavailable",
        reason: ladderFailure.kind || "error",
        reasonText: ladderFailure.message || "roster intelligence could not be loaded",
      };
    }
    // ownerId-checked: the previous team's payload is kept while the next
    // one loads, and its ladder must never be read as this team's.
    return teamCutLadder(ladderPayload, { ownerId });
  }, [ladderEnabled, ladderFailure, ladderPayload, ownerId]);

  const analysis = useMemo(() => {
    if (leagueMismatch) return null;
    if (!selectedTeam) return null;
    if (!Array.isArray(rows) || rows.length === 0) return null;
    return computeWaiverAnalysis({
      rows,
      myRosterNames,
      sleeperTeams,
      includeRookies,
      idpEnabled,
      filters: stableFilters,
      cutLadder,
    });
  }, [
    rows,
    myRosterNames,
    sleeperTeams,
    includeRookies,
    idpEnabled,
    stableFilters,
    leagueMismatch,
    selectedTeam,
    cutLadder,
  ]);
  // Still fetching THIS team's ladder: the page keeps its skeleton rather
  // than flashing an "unavailable" state that is about to resolve.  ONLY
  // while a request is in flight — a fetch that SETTLED without data and
  // without a failure is not "pending", it is an answer with nothing in
  // it, and ``teamCutLadder`` already states it as unavailable
  // (``not_loaded`` / ``team_mismatch``).  Waiting on ``!ladderPayload``
  // here held the skeleton forever in exactly that case.
  const ladderPending = ladderEnabled && !ladderFailure && Boolean(ladderLoading);

  // ── Backend FAAB bids (optional enrichment) ─────────────────────
  //
  // Optional, but STATED, never silent.  A failed bid request is
  // deliberately NOT folded into ``error`` — the add/drop tables are fully
  // usable without a bid, and a red page banner over a working page
  // because an optional column couldn't load is the wrong answer.  But it
  // is not hidden either: ``bidFeed`` says why there is no index, so a bid
  // that is still loading and one whose request failed do not render as
  // the same blank, and ``retryBids`` lets the page offer a retry.
  //
  //   "loading"  a request for the CURRENT bid identity (team, league,
  //              balance) and the current retry attempt has not settled.
  //   "failed"   it settled with a non-OK status, a malformed body (not a
  //              JSON object, a body carrying an ``error``, or a payload
  //              labelled for a different league) or a network error.
  //   null       it settled with a usable payload — or no request applies
  //              (no team selected, league mismatch).
  //
  // An ABORT is never "failed": the request is aborted only because the
  // identity changed, a retry superseded it, or the component unmounted —
  // in the first two cases the new request is what is in flight, so the
  // feed reads "loading" for it.
  const leagueKey = selectedLeague?.key || "";
  const rawBalance = selectedTeam?.faabRemaining;
  const numericBalance = typeof rawBalance === "number" ||
    (typeof rawBalance === "string" && rawBalance.trim() !== "");
  const faabRemaining = numericBalance && Number.isFinite(Number(rawBalance))
    ? Number(rawBalance)
    : null;
  const bidsEnabled = Boolean(selectedTeam) && !leagueMismatch;
  const bidIdentity = JSON.stringify([bidsEnabled, leagueKey, selectedTeam?.ownerId || null, faabRemaining]);
  const [bidPayload, setBidPayload] = useState(null);
  // Bumped by ``retryBids``; it rides in ``bidRequestKey``, which is in
  // the fetch effect's deps, so a bump re-issues the request for the
  // same identity.
  const [bidAttempt, setBidAttempt] = useState(0);
  const bidRequestKey = `${bidIdentity}#${bidAttempt}`;
  // The settled outcome of the LAST request, tagged with the request key
  // it answers.  A tag that is not the current key means the current
  // request has not settled yet — "loading" — whatever the previous one
  // said, so a stale "failed" can never outlive a retry or an identity
  // change.
  const [bidSettled, setBidSettled] = useState(null);
  const retryBids = useCallback(() => setBidAttempt((n) => n + 1), []);

  useEffect(() => {
    if (!bidsEnabled) {
      setBidPayload(null);
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    const settle = (state) => setBidSettled({ key: bidRequestKey, state });
    (async () => {
      try {
        const res = await fetch("/api/waiver/suggestions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctl.signal,
          // A bid is derived from a value, so the request has to name
          // the board the user is looking at — same reasoning as the
          // manual bid desk's /api/waiver/faab-recommend call.
          body: JSON.stringify(
            withValuationMode({
              leagueKey: leagueKey || undefined,
              // The engine scales bids off the league's ORIGINAL
              // budget and uses this only as a cap, so omitting it
              // (unknown balance) is safe — it must never be sent as
              // the budget.
              faabRemaining: faabRemaining ?? undefined,
              // Required for the backend to run the market-aware
              // engine (rival contention, season option value,
              // positional need) instead of its ceiling-only fallback
              // — same field the manual bid desk
              // (FaabRecommendation.jsx) already sends. Omitting this
              // was the whole bug: bidsEnabled already requires
              // selectedTeam, so ownerId is always available here.
              teamOwnerId: selectedTeam?.ownerId || undefined,
            }),
          ),
        });
        if (cancelled) return;
        if (!res.ok) {
          setBidPayload(null);
          settle("failed");
          return;
        }
        const json = await res.json();
        if (cancelled) return;
        // The endpoint states every error with a non-2xx status and never
        // puts ``error`` on a success body (server.py
        // ``post_waiver_suggestions``), so a 2xx body carrying one is not
        // a bid board.
        const valid = json && typeof json === "object" && !Array.isArray(json) &&
          !Object.hasOwn(json, "error") &&
          (!leagueKey || !Object.hasOwn(json, "leagueKey") || json.leagueKey === leagueKey);
        setBidPayload(valid ? { identity: bidIdentity, payload: json } : null);
        settle(valid ? "loaded" : "failed");
      } catch (err) {
        // An abort is this effect's own cleanup (identity change, retry,
        // unmount) — never a failure; the request that replaced it, if
        // any, is the one in flight.
        if (cancelled || err?.name === "AbortError") return;
        setBidPayload(null);
        settle("failed");
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
    // selectedTeam?.ownerId is a dependency in its own right, not just
    // via bidsEnabled: switching between two already-selected teams
    // keeps bidsEnabled === true, so without this the bids for the
    // PREVIOUS team would silently stay on screen under the new one.
  }, [bidsEnabled, leagueKey, faabRemaining, selectedTeam?.ownerId, bidIdentity, bidRequestKey]);

  let bidFeed = null;
  if (bidsEnabled) {
    if (bidSettled?.key !== bidRequestKey) bidFeed = "loading";
    else if (bidSettled.state === "failed") bidFeed = "failed";
  }

  const faabIndex = useMemo(() => buildWaiverBidIndex(
    bidsEnabled && bidPayload?.identity === bidIdentity ? bidPayload.payload : null,
  ), [bidPayload, bidsEnabled, bidIdentity]);

  // How fresh the rosters behind this answer are (DYN10 B3), as the server
  // stamped it (``rosterFreshness``, ``src/api/roster_freshness.py``).  The
  // cut ladder's payload first — it is this page's required feed and is
  // built on the same live teams overlay /api/data serves — then the bid
  // payload's.  Only THIS team's payloads count; ``null`` when neither has
  // answered.
  const ladderForTeam =
    ladderEnabled && String(ladderPayload?.team?.ownerId ?? "") === ownerId ? ladderPayload : null;
  const bidForTeam = bidsEnabled && bidPayload?.identity === bidIdentity ? bidPayload.payload : null;
  const rosterFreshness = ladderForTeam?.rosterFreshness || bidForTeam?.rosterFreshness || null;

  return {
    analysis,
    faabIndex,
    rosterFreshness,
    bidFeed,
    retryBids,
    loading: Boolean(loading) || ladderPending,
    error,
    leagueMismatch,
    hasTeam: Boolean(selectedTeam),
    teamCount: availableTeams?.length || 0,
    selectedLeagueName: selectedLeague?.displayName || "",
  };
}
