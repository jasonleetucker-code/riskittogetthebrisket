"use client";

/**
 * TitleOddsPanel — "This season's odds" in the Trade War Room (DYN10 #4).
 *
 * Asks `POST /api/trade/title-odds` AFTER the analysis has arrived, so the
 * recommendation never waits for the season simulation (~5.5 s).  Rendered
 * only when the server's `tradeTitleOdds` capability is true (the owner-held
 * `trade_title_odds_lens` flag); otherwise the War Room does not mount it and
 * no request is made.
 *
 * DISPLAY ONLY: every number is the route's (`src/trade/title_odds_lens.py`),
 * worded by `lib/trade-title-odds.js`.  Context, never a vote — it does not
 * change the recommendation above it.  Every unavailable state is said in
 * words, never as 0.  The uncalibrated-odds disclosure is always visible
 * (owner decision ODR-ODDS-WORDING, `lib/odds-disclosure.js`).
 *
 * Styling: the War Room's own module classes only (no new tokens or styles).
 */

import { useEffect, useId, useRef, useState } from "react";
import { Button } from "@/components/ds";
import { ODDS_EXPERIMENTAL_DISCLOSURE } from "@/lib/odds-disclosure";
import {
  titleOddsErrorText,
  titleOddsReasonText,
  titleOddsRetryable,
  titleOddsRows,
} from "@/lib/trade-title-odds";
import styles from "./war-room.module.css";

/** One request's ceiling: above the server's own 40 s bound, below nginx's 120 s. */
export const TITLE_ODDS_TIMEOUT_MS = 60_000;

function OddsCell({ cell, unavailable }) {
  if (unavailable) return <span className={styles.muted}>Not published: {unavailable}.</span>;
  if (!cell) return <span className={styles.muted}>—</span>;
  return (
    <>
      <span>{cell.levels}</span>
      {cell.change ? (
        <span className={styles.rowNote}>
          {" "}
          {cell.change}
          {cell.range ? ` (range ${cell.range})` : ""}
        </span>
      ) : null}
      {cell.noise ? (
        <span className={styles.rowNote} data-testid="title-odds-noise">
          {" "}
          Within simulation noise.
        </span>
      ) : null}
    </>
  );
}

export default function TitleOddsPanel({ body, requestKey }) {
  const headingId = useId();
  const [state, setState] = useState({ status: "loading", payload: null, error: null, key: "" });
  const [attempt, setAttempt] = useState(0);
  const controllerRef = useRef(null);

  useEffect(() => {
    // A new trade invalidates the request in flight at once.
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    let timedOut = false;
    const timeoutId = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, TITLE_ODDS_TIMEOUT_MS);
    setState({ status: "loading", payload: null, error: null, key: requestKey });
    const current = () => controllerRef.current === controller;
    const fail = (error) => setState({ status: "error", payload: null, error, key: requestKey });
    (async () => {
      try {
        const res = await fetch("/api/trade/title-odds", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (!current()) return;
        if (timedOut) return fail("timeout");
        if (controller.signal.aborted) return;
        if (!res.ok) {
          return fail(typeof data?.error === "string" ? data.error : `HTTP ${res.status}`);
        }
        if (!data || (data.state !== "ok" && data.state !== "unavailable")) {
          return fail("invalid_payload");
        }
        setState({ status: "ok", payload: data, error: null, key: requestKey });
      } catch {
        if (!current()) return;
        if (timedOut) return fail("timeout");
        if (controller.signal.aborted) return;
        fail("network");
      } finally {
        clearTimeout(timeoutId);
      }
    })();
    return () => {
      clearTimeout(timeoutId);
      controller.abort();
    };
    // `body` identity is folded into `requestKey`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey, attempt]);

  // Only this trade's answer is ever shown.
  const mine = state.key === requestKey;
  const status = mine ? state.status : "loading";
  const payload = status === "ok" ? state.payload : null;
  const unavailableReason = payload && payload.state !== "ok" ? payload.reason : null;
  const rows =
    payload && payload.state === "ok" ? titleOddsRows(payload, payload.perspectiveOwnerId) : [];
  const retryCode = status === "error" ? state.error : unavailableReason;
  const retry = titleOddsRetryable(retryCode) ? (
    <Button size="sm" variant="ghost" onClick={() => setAttempt((n) => n + 1)}>
      Retry
    </Button>
  ) : null;

  return (
    <section
      className={styles.why}
      aria-labelledby={headingId}
      aria-busy={status === "loading" || undefined}
      data-testid="war-room-title-odds"
      data-state={payload ? payload.state : status}
    >
      <h3 id={headingId} className={styles.sectionTitle}>
        This season&apos;s odds
      </h3>
      {status === "loading" ? (
        <p className={styles.muted} data-testid="title-odds-loading">
          Simulating this season with and without the trade…
        </p>
      ) : status === "error" ? (
        <p className={styles.muted} data-testid="title-odds-error">
          Season odds are unavailable: {titleOddsErrorText(state.error)}. {retry}
        </p>
      ) : unavailableReason ? (
        <p className={styles.muted} data-testid="title-odds-unavailable">
          Season odds are unavailable: {titleOddsReasonText(unavailableReason)}. {retry}
        </p>
      ) : (
        <>
          <div
            className={styles.tableWrap}
            role="region"
            aria-label="Playoff and title odds before and after the trade"
            tabIndex={0}
          >
            <table className={styles.table}>
              <caption className={styles.srOnly}>
                Each team&apos;s chance to make the playoffs and to win the title this season,
                before and after the trade, with the change in percentage points
              </caption>
              <thead>
                <tr>
                  <th scope="col">Team</th>
                  <th scope="col">Make playoffs</th>
                  <th scope="col">Win title</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.key} data-team={r.key} data-mine={r.mine || undefined}>
                    <th scope="row" className={styles.playerCell}>
                      <span className={styles.playerName}>{r.name}</span>
                      {r.mine ? <span className={styles.playerPos}>Your team</span> : null}
                    </th>
                    {r.unavailable ? (
                      <td className={styles.wrap} colSpan={2}>
                        <span className={styles.muted}>Not simulated: {r.unavailable}.</span>
                      </td>
                    ) : (
                      <>
                        <td className={styles.wrap}>
                          <OddsCell cell={r.playoff} />
                        </td>
                        <td className={styles.wrap}>
                          <OddsCell
                            cell={r.championship}
                            unavailable={r.championshipUnavailable}
                          />
                        </td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className={styles.note}>
            Changes are in percentage points. Each range is a 95% interval that covers the
            simulation&apos;s own randomness only.
            {payload.counterpartyInferred
              ? " The other team is taken to be the current holder of the players you receive."
              : ""}
          </p>
        </>
      )}
      <p className={styles.note}>Context only: this does not change the recommendation.</p>
      <p className={styles.note} role="note" data-testid="title-odds-disclosure">
        {ODDS_EXPERIMENTAL_DISCLOSURE}
      </p>
    </section>
  );
}
