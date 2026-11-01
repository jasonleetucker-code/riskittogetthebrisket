"use client";

/**
 * useIdpStreamingGate — the team-less gate probe for the /waiver-advisor
 * "Weekly IDP streaming" mode switch.
 *
 * The probe carries no team, so the backend answers `503 feature_disabled`
 * (flag `waiver_advisor` or `idp_streaming` off) BEFORE `team_required`: the
 * page learns whether the mode exists without running the solver.  A backend
 * without the route answers a plain 404, which also closes the gate.
 *
 * Self-contained on purpose: it imports nothing from lib/idp-streaming, so
 * that module (and the panel) stay in the lazy chunk rather than the page's.
 * The endpoint literal is pinned equal to `IDP_STREAMING_ENDPOINT` by test.
 */
import { useEffect, useState } from "react";

export const IDP_STREAMING_GATE_ENDPOINT = "/api/waiver/streaming";

/** "unknown" until answered; then "open" or "closed". */
export function useIdpStreamingGate({ leagueKey, enabled = true } = {}) {
  const key = `${leagueKey || ""}|${enabled}`;
  const [state, setState] = useState({ key: null, gate: "unknown" });
  useEffect(() => {
    if (!enabled) {
      setState({ key, gate: "closed" });
      return undefined;
    }
    let cancelled = false;
    const ctl = new AbortController();
    (async () => {
      try {
        const res = await fetch(IDP_STREAMING_GATE_ENDPOINT, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: ctl.signal,
          body: JSON.stringify(leagueKey ? { leagueKey } : {}),
        });
        const json = await res.json().catch(() => null);
        if (cancelled) return;
        const code =
          json && typeof json === "object" ? String(json.error || "") : "";
        const closed =
          code === "feature_disabled" || (res.status === 404 && !code);
        setState({ key, gate: closed ? "closed" : "open" });
      } catch (err) {
        if (cancelled || err?.name === "AbortError") return;
        setState({ key, gate: "closed" });
      }
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [enabled, leagueKey, key]);
  return state.key === key ? state.gate : "unknown";
}
