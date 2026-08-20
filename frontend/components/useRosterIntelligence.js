"use client";

/**
 * useRosterIntelligence — the canonical Team Strength binding of the
 * generic private-endpoint fetch.
 *
 * `GET /api/roster/intelligence` is league-scoped and team-scoped: it
 * needs an `ownerId`, and defaults to the session's own team when none
 * is passed. Passing `team: ""` therefore means "my team", not "no
 * team", which is why an empty value is simply omitted by the generic
 * hook rather than sent.
 *
 * @returns {{ loading, data, failure, refetch }}
 *   failure: null | { kind: "not_ready"|"team_required"|"team_not_found"|
 *                           "league"|"auth"|"unavailable"|"error", message }
 */

import { useMemo } from "react";
import { useJsonEndpoint } from "@/components/useJsonEndpoint";
import { classifyRosterIntelligenceFailure } from "@/lib/roster-intelligence";

export function useRosterIntelligence({ ownerId = "", enabled = true } = {}) {
  const params = useMemo(() => ({ team: ownerId || "" }), [ownerId]);
  return useJsonEndpoint("/api/roster/intelligence", {
    params,
    enabled,
    classify: classifyRosterIntelligenceFailure,
  });
}
