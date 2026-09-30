/**
 * Rookie auction room — client transport.
 *
 * The server decides everything; this module only carries requests and
 * keeps the rendered snapshot honest:
 *
 *  - `sendCommand` gives every mutation an Idempotency-Key.  If the network
 *    drops after submission the outcome is UNKNOWN, not failed: we ask the
 *    server for the receipt of that key and only re-send (with the SAME key)
 *    if no receipt exists.  A re-send can never place a second bid.
 *  - `useAuctionRoom` long-polls `/view?after=<rev>`.  Every response is a
 *    full authorised snapshot; a response older than the one we hold is
 *    dropped, so duplicate / out-of-order delivery cannot roll the UI back.
 *  - Browser clocks are used only to animate countdowns between snapshots.
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const BASE = "/api/auction";

export class AuctionRequestError extends Error {
  constructor(status, body) {
    super((body && body.message) || `Request failed (${status})`);
    this.status = status;
    this.code = body && body.error;
    this.body = body;
  }
}

export async function auctionFetch(path, { method = "GET", body, headers = {}, signal } = {}) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    signal,
    headers: body !== undefined ? { "Content-Type": "application/json", ...headers } : headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 204) return null;
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) throw new AuctionRequestError(res.status, data);
  return data;
}

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

/** Transport-level failure where the server may or may not have committed. */
function isUnknownOutcome(err) {
  return !(err instanceof AuctionRequestError) || err.status >= 502;
}

/**
 * Send one room command.  Resolves with the committed result; rejects with
 * an AuctionRequestError for a definitive rejection; rejects with
 * `{unknown: true, key}` when the outcome could not be established.
 */
export async function sendCommand(roomId, body, { attempts = 3 } = {}) {
  const key = newKey();
  const path = `/rooms/${encodeURIComponent(roomId)}/commands`;
  let lastErr = null;
  for (let i = 0; i < attempts; i += 1) {
    try {
      return await auctionFetch(path, { method: "POST", body, headers: { "Idempotency-Key": key } });
    } catch (err) {
      if (!isUnknownOutcome(err)) throw err;
      lastErr = err;
      // Did it commit?  Ask before re-sending.
      try {
        const receipt = await auctionFetch(`/rooms/${encodeURIComponent(roomId)}/receipts/${encodeURIComponent(key)}`);
        if (receipt) {
          if (receipt.status >= 200 && receipt.status < 300) return { ...receipt.result, revision: receipt.revision, replayed: true };
          throw new AuctionRequestError(receipt.status, receipt.result);
        }
      } catch (rErr) {
        if (rErr instanceof AuctionRequestError && rErr.status !== 404 && !isUnknownOutcome(rErr)) throw rErr;
      }
      await new Promise((r) => setTimeout(r, 400 * (i + 1)));
    }
  }
  const unknown = new Error("The server did not confirm this action. It may or may not have been accepted — check the room before retrying.");
  unknown.unknown = true;
  unknown.key = key;
  unknown.cause = lastErr;
  throw unknown;
}

/**
 * Live room state.  Returns {view, sync, error, refresh}.
 * sync: "connecting" | "live" | "reconnecting" | "offline"
 */
export function useAuctionRoom(roomId) {
  const [view, setView] = useState(null);
  const [sync, setSync] = useState("connecting");
  const [error, setError] = useState(null);
  const revRef = useRef(-1);
  const kickRef = useRef(0);
  const [kick, setKick] = useState(0);

  const accept = useCallback((data) => {
    if (!data || typeof data.revision !== "number") return;
    if (data.revision < revRef.current) return; // stale / out of order
    revRef.current = data.revision;
    setView(data);
  }, []);

  const refresh = useCallback(() => {
    kickRef.current += 1;
    setKick(kickRef.current);
  }, []);

  useEffect(() => {
    if (!roomId) return undefined;
    let stopped = false;
    const ctl = new AbortController();
    let failures = 0;
    (async () => {
      // First snapshot immediately.
      while (!stopped) {
        try {
          const first = await auctionFetch(`/rooms/${encodeURIComponent(roomId)}/view`, { signal: ctl.signal });
          accept(first);
          setSync("live");
          setError(null);
          break;
        } catch (err) {
          if (stopped) return;
          if (err instanceof AuctionRequestError && err.status < 500) {
            setError(err);
            setSync("offline");
            return;
          }
          setSync("reconnecting");
          await new Promise((r) => setTimeout(r, 2000));
        }
      }
      while (!stopped) {
        try {
          const data = await auctionFetch(
            `/rooms/${encodeURIComponent(roomId)}/view?after=${revRef.current}&wait=25`,
            { signal: ctl.signal },
          );
          if (data) accept(data);
          failures = 0;
          setSync("live");
          setError(null);
        } catch (err) {
          if (stopped) return;
          if (err instanceof AuctionRequestError && err.status < 500) {
            setError(err);
            setSync("offline");
            return;
          }
          failures += 1;
          setSync("reconnecting");
          await new Promise((r) => setTimeout(r, Math.min(10000, 1000 * 2 ** Math.min(failures, 4))));
        }
      }
    })();
    return () => {
      stopped = true;
      ctl.abort();
    };
  }, [roomId, kick, accept]);

  return { view, sync, error, refresh, accept };
}

/** Local ticking clock for countdown display only. */
export function useNowTicker(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now() / 1000), intervalMs);
    return () => clearInterval(t);
  }, [intervalMs]);
  return now;
}

export function formatActiveSeconds(sec) {
  if (sec == null || !Number.isFinite(sec)) return "—";
  const s = Math.max(0, Math.floor(sec));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h >= 1) return `${h}h ${String(m).padStart(2, "0")}m`;
  if (m >= 1) return `${m}m ${String(r).padStart(2, "0")}s`;
  return `${r}s`;
}

export function formatRoomTime(epoch) {
  if (epoch == null) return "—";
  return new Date(epoch * 1000).toLocaleString("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

export function dollars(n) {
  if (n == null) return "—";
  return `$${n}`;
}

/**
 * Parse a user-entered bid.  Whole dollars only; "$12" and "12" accepted.
 * Returns an integer or null.  Never rounds a fraction up or down.
 */
export function parseDollars(input) {
  const s = String(input ?? "").trim().replace(/^\$/, "");
  if (!/^\d{1,7}$/.test(s)) return null;
  const n = Number(s);
  return Number.isSafeInteger(n) ? n : null;
}
