"use client";

import { useEffect, useMemo, useState } from "react";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";
import { useTeam } from "@/components/useTeam";
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
 *     bid become a contract field.
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
  ]);

  // ── Backend FAAB bids (optional enrichment) ─────────────────────
  //
  // Silent-vanish, per the BDVM gap-column posture: any non-OK
  // response, malformed body, abort or network failure leaves
  // ``bidPayload`` null, the index null, and the FAAB cells "—".  It
  // is deliberately NOT folded into ``error`` — the add/drop tables
  // are fully usable without a bid, and a red banner over a working
  // page because an optional column couldn't load is a worse outcome
  // than a blank column.
  const leagueKey = selectedLeague?.key || "";
  const faabRemaining = Number.isFinite(Number(selectedTeam?.faabRemaining))
    ? Number(selectedTeam.faabRemaining)
    : null;
  const bidsEnabled = Boolean(selectedTeam) && !leagueMismatch;
  const [bidPayload, setBidPayload] = useState(null);

  useEffect(() => {
    if (!bidsEnabled) {
      setBidPayload(null);
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
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
          return;
        }
        const json = await res.json();
        if (cancelled) return;
        setBidPayload(json && typeof json === "object" ? json : null);
      } catch {
        // Includes AbortError on unmount/league switch.  Nothing to
        // report: the column simply doesn't appear.
        if (!cancelled) setBidPayload(null);
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
  }, [bidsEnabled, leagueKey, faabRemaining, selectedTeam?.ownerId]);

  const faabIndex = useMemo(() => buildWaiverBidIndex(bidPayload), [bidPayload]);

  return {
    analysis,
    faabIndex,
    loading,
    error,
    leagueMismatch,
    hasTeam: Boolean(selectedTeam),
    teamCount: availableTeams?.length || 0,
    selectedLeagueName: selectedLeague?.displayName || "",
  };
}
