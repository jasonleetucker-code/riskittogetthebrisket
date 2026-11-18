"use client";

/**
 * The auction room's frozen rookie pool — loading state and player labels.
 *
 * The pool (`/rooms/<id>/pool`) is what turns a lot's player id into a name
 * and what the Nominate list is built from.  It used to be fetched once with
 * any failure swallowed into `null`, which left an empty nominate list and
 * raw player ids printed as names, with nothing saying why and no way to try
 * again.  This hook keeps the three states apart (loading / ready / failed),
 * offers a retry, and `rookieLabel` never prints an id as a name.
 */
import { useCallback, useEffect, useState } from "react";

import { auctionFetch } from "@/lib/auction-client";

export const POOL_LOADING_LABEL = "Loading name…";
export const POOL_UNAVAILABLE_LABEL = "Name unavailable";

/**
 * A player's display name, or an explicit placeholder — never the raw id.
 *
 * @param {object|null|undefined} players  pool.players (id → {name, pos})
 * @param {string} pid                     player id
 * @param {"loading"|"ready"|"failed"} status  pool load state
 * @param {string} [hint]                  a name the server already sent with
 *                                         the event (e.g. `player_name`)
 */
export function rookieLabel(players, pid, status, hint) {
  const name = players?.[pid]?.name;
  if (name) return name;
  if (hint) return hint;
  return status === "loading" ? POOL_LOADING_LABEL : POOL_UNAVAILABLE_LABEL;
}

export function useRoomPool(roomId) {
  const [state, setState] = useState({ status: "loading", players: null, error: null });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!roomId) return undefined;
    let alive = true;
    setState((s) => ({ ...s, status: "loading", error: null }));
    auctionFetch(`/rooms/${encodeURIComponent(roomId)}/pool`)
      .then((pool) => {
        if (!alive) return;
        const players = pool && typeof pool === "object" ? pool.players : null;
        if (players && typeof players === "object") {
          setState({ status: "ready", players, error: null });
        } else {
          setState({ status: "failed", players: null, error: "The server returned no rookie pool." });
        }
      })
      .catch((err) => {
        if (!alive) return;
        setState({ status: "failed", players: null, error: err?.message || "The rookie pool could not be loaded." });
      });
    return () => {
      alive = false;
    };
  }, [roomId, attempt]);

  const retry = useCallback(() => setAttempt((n) => n + 1), []);
  return { ...state, retry };
}
