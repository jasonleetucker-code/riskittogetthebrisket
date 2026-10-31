"use client";

/**
 * useRosterConstructionGate — the team-less gate probe for /roster-construction.
 *
 * The request carries no team, so the backend answers `503 feature_disabled`
 * (flag `roster_construction` off) BEFORE anything else: the page learns
 * whether it exists without running a solve.  A backend without the route
 * answers a plain 404, which also closes the gate.  When the flag is on, the
 * answer is the league overview, whose `teams` fill the team selector.
 *
 * Self-contained on purpose: it imports nothing from lib/roster-construction,
 * so that module (and the panel) stay in the lazy chunk rather than the
 * page's.  The endpoint literal is pinned equal to
 * `ROSTER_CONSTRUCTION_ENDPOINT` by test.
 */
import { useEffect, useState } from "react";

export const ROSTER_CONSTRUCTION_GATE_ENDPOINT = "/api/roster-construction";

/**
 * Returns {gate, overview, failure}.  gate is "unknown" until answered, then
 * "open" or "closed".  An open gate with a failure is a stated state (data
 * not ready, offline), never "not available".
 */
export function useRosterConstructionGate({ leagueKey, season, enabled = true } = {}) {
  const key = `${leagueKey || ""}|${season || ""}|${enabled}`;
  const [state, setState] = useState({
    key: null,
    gate: "unknown",
    overview: null,
    failure: null,
  });
  useEffect(() => {
    if (!enabled || !leagueKey) {
      setState({ key, gate: enabled ? "unknown" : "closed", overview: null, failure: null });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    (async () => {
      try {
        const qs =
          `leagueKey=${encodeURIComponent(leagueKey)}` +
          (season ? `&season=${encodeURIComponent(season)}` : "");
        const res = await fetch(`${ROSTER_CONSTRUCTION_GATE_ENDPOINT}?${qs}`, {
          signal: ctl.signal,
          headers: { Accept: "application/json" },
        });
        const json = await res.json().catch(() => null);
        if (cancelled) return;
        const code =
          json && typeof json === "object" ? String(json.error || "") : "";
        if (code === "feature_disabled" || (res.status === 404 && !code)) {
          setState({ key, gate: "closed", overview: null, failure: null });
          return;
        }
        if (res.ok && json && typeof json === "object") {
          const stale = json.leagueKey && json.leagueKey !== leagueKey;
          setState({
            key,
            gate: "open",
            overview: stale ? null : json,
            failure: null,
          });
          return;
        }
        // `team_required` means the route is live but wants a team: open, no
        // team list.  Any other answer is open with the failure named.
        setState({
          key,
          gate: "open",
          overview: null,
          failure:
            code === "team_required"
              ? null
              : { status: res.status, body: json && typeof json === "object" ? json : null },
        });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({
          key,
          gate: "open",
          overview: null,
          failure: { status: 0, body: null },
        });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, leagueKey, season, key]);
  return state.key === key
    ? { gate: state.gate, overview: state.overview, failure: state.failure }
    : { gate: "unknown", overview: null, failure: null };
}
