"use client";

/**
 * useBdvmEndpoint — the BDVM binding of the generic private-endpoint
 * fetch. The machinery lives in `useJsonEndpoint`; only the classifier
 * is BDVM's (its three 503 variants carry different `error` codes and
 * flag-off is an expected configuration, not a failure).
 *
 * @returns {{ loading, data, failure, refetch }}
 *   failure: null | { kind: "disabled"|"not_ready"|"unavailable"|"auth"|"error", message }
 */

import { useJsonEndpoint } from "@/components/useJsonEndpoint";
import { classifyBdvmFailure } from "@/lib/bdvm";

export function useBdvmEndpoint(path, { params, enabled = true } = {}) {
  return useJsonEndpoint(path, { params, enabled, classify: classifyBdvmFailure });
}
