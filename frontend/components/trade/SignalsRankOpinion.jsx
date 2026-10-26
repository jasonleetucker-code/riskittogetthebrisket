"use client";

/**
 * Signals Fantasy — a rank-only, NON-VOTING second opinion (#1555).
 *
 * Rendered under the Second Opinions table. Shows each piece's Signals
 * POSITIONAL rank + tier (e.g. "QB3 · S tier"), and nothing else: no value,
 * no side total, no winner, no tally entry, no cross-position ordering.
 * Resolution and state names live in `lib/second-opinions.js`
 * (`rankOnlyOpinionFor`); the identity join is server-side.
 *
 * Explicit states, never a silent zero: "not collected" when the private
 * store is empty, "not ranked / unresolved" per piece, "doesn't rank picks"
 * for out-of-scope assets. Vanishes only when the endpoint itself is
 * unreachable (401 / network) — an add-on must not break the trade page.
 */

import { useEffect, useState } from "react";

import {
  ASSET_COVERAGE,
  RANK_ONLY_STATE,
  rankOnlyOpinionFor,
  rankOnlyProviderState,
} from "@/lib/second-opinions";

let _cache = null; // { at, payload } — one fetch per page session window
const CACHE_MS = 10 * 60 * 1000;

async function loadSignals() {
  if (_cache && Date.now() - _cache.at < CACHE_MS) return _cache.payload;
  const res = await fetch("/api/second-opinion/signals", { credentials: "same-origin" });
  if (!res.ok) return null;
  const payload = await res.json().catch(() => null);
  if (payload) _cache = { at: Date.now(), payload };
  return payload;
}

/** Test seam: forget the module cache. */
export function _resetSignalsCache() {
  _cache = null;
}

function cellText(op) {
  if (op.status === ASSET_COVERAGE.NATIVE) {
    const e = op.entry;
    const tier = e.tier ? ` · ${e.tier}` : "";
    return `${e.position}${e.positionalRank}${tier}`;
  }
  if (op.status === ASSET_COVERAGE.OUT_OF_SCOPE) return "not ranked by Signals";
  if (op.detail === "not_collected") return "not collected";
  return "not ranked / unresolved";
}

export default function SignalsRankOpinion({ sides }) {
  const [payload, setPayload] = useState(undefined);

  useEffect(() => {
    let live = true;
    loadSignals()
      .then((p) => live && setPayload(p))
      .catch(() => live && setPayload(null));
    return () => {
      live = false;
    };
  }, []);

  if (!payload) return null;
  const state = rankOnlyProviderState(payload);
  if (state === RANK_ONLY_STATE.UNAVAILABLE) return null;
  const pieces = (sides || []).flatMap((s, si) =>
    (s.assets || []).map((row) => ({ si, label: s.label, row })),
  );
  if (pieces.length === 0) return null;

  const published = payload.boards?.dynasty?.release?.publishedAt;
  return (
    <div
      data-testid="signals-rank-opinion"
      className="muted"
      style={{ margin: "8px 0 0", fontSize: "0.72rem", lineHeight: 1.5 }}
    >
      <strong style={{ color: "var(--text)" }}>Signals Fantasy</strong>{" "}
      <span>— positional rank only · not counted</span>
      {state === RANK_ONLY_STATE.NOT_COLLECTED ? (
        <span data-testid="signals-not-collected"> · not collected yet</span>
      ) : (
        <>
          {published && <span> · published {String(published).slice(0, 10)}</span>}
          <ul style={{ margin: "2px 0 0", paddingLeft: 16 }}>
            {pieces.map(({ si, label, row }, i) => {
              const op = rankOnlyOpinionFor(row, payload);
              return (
                <li key={`${si}-${i}`}>
                  Side {label}: {row?.name || "—"} —{" "}
                  <span
                    style={{
                      fontFamily: "var(--mono)",
                      color: op.status === ASSET_COVERAGE.NATIVE ? "var(--text)" : undefined,
                    }}
                  >
                    {cellText(op)}
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
