"use client";

/**
 * useManagerScout — the Manager Scout (C6-MGR-01) binding of the generic
 * private-endpoint fetch. League-scoped; the backend owns every number.
 *
 * @returns {{ loading, data, failure, refetch }}
 */

import { useJsonEndpoint } from "@/components/useJsonEndpoint";
import { classifyManagerScoutFailure } from "@/lib/manager-scout";

export function useManagerScout({ enabled = true } = {}) {
  return useJsonEndpoint("/api/manager-scout", {
    enabled,
    classify: classifyManagerScoutFailure,
  });
}
