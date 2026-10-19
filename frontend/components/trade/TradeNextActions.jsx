"use client";

/**
 * TradeNextActions — "Next steps" for the trade being built (TC-B /
 * TCM-O11, O12, O13, L01).
 *
 *   Balance        where the page's own balancing suggestions are, or why
 *                  there are none (never a second balancer);
 *   Explore        deep links into the existing engines on /arbitrage —
 *                  Package Scan (finder), Package Builder, Best Trade,
 *                  Golden Upgrades — opened for this team and partner;
 *   Partner        Manager Scout's evidence for THIS package from the
 *                  counterparty's own completed trades (counts with their
 *                  samples, never a likelihood), plus links to the league
 *                  tendencies table and Manager Intelligence;
 *   Evidence       the Trade Database pre-filtered to these assets;
 *   Save           the trade to the private Trade Desk (`source:
 *                  "calculator"`), which never sends anything.
 *
 * Display and navigation only: every link target and body comes from
 * `lib/trade-next-actions.js`; partner evidence is fetched only when the
 * user opens it.  Loaded on demand from /trade (React.lazy).
 */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Button } from "@/components/ds";
import ManagerEvidence from "@/components/trade/ManagerEvidence";
import SaveToDeskButton from "@/components/trade/SaveToDeskButton";
import {
  MANAGER_INTEL_HREF,
  MANAGER_SCOUT_HREF,
  arbitrageHref,
  balanceStep,
  deskBodyFromCalculator,
  deskReasonText,
  offerEvidenceBody,
  offerEvidenceUrl,
  tradeDatabaseHref,
  tradeParties,
  tradePartiesText,
} from "@/lib/trade-next-actions";
import styles from "./trade-next-actions.module.css";

const ENGINE_LINKS = [
  {
    tool: "scan",
    label: "Find trades with this partner",
    note: "Package Scan: real rosters, gains on our board, plausible on theirs.",
    needsOpponent: true,
  },
  {
    tool: "builder",
    label: "Package Builder",
    note: "Build packages around one asset you want or want to move.",
  },
  {
    tool: "best",
    label: "Best trade to send each team",
    note: "One strongest offer per opponent.",
  },
  {
    tool: "golden",
    label: "Golden Upgrades",
    note: "Same-position upgrades your league's markets undervalue.",
  },
];

function PartnerEvidence({ sides, parties, leagueKey }) {
  const [open, setOpen] = useState(false);
  const [state, setState] = useState({ status: "idle", evidence: null, error: null, key: "" });
  const body = useMemo(() => offerEvidenceBody({ sides, parties }), [sides, parties]);
  const key = JSON.stringify([leagueKey, body]);
  // "Try again" (TC-E): re-asks the same question after an error.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!open || !body) return undefined;
    if (state.key === key && state.status !== "idle" && state.status !== "error") return undefined;
    const ctl = new AbortController();
    setState({ status: "loading", evidence: null, error: null, key });
    fetch(offerEvidenceUrl(leagueKey), {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: ctl.signal,
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (ctl.signal.aborted) return;
        if (!res.ok) {
          setState({ status: "error", evidence: null, error: data?.error || `HTTP ${res.status}`, key });
          return;
        }
        setState({ status: "ok", evidence: data, error: null, key });
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setState({ status: "error", evidence: null, error: "network", key });
      });
    return () => ctl.abort();
    // `state` is read only to skip a repeat of the same question.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, key, attempt]);

  if (!body) return null;
  const current = state.key === key ? state : { status: "idle" };
  return (
    <div className={styles.partner} data-testid="trade-partner-evidence">
      <p className={styles.note}>
        <span className={styles.label}>Partner</span> {parties.opponent}
      </p>
      {!open ? (
        <Button size="sm" variant="ghost" onClick={() => setOpen(true)}>
          Show {parties.opponent}&apos;s trade history for this package
        </Button>
      ) : current.status === "ok" ? (
        <ManagerEvidence
          evidence={current.evidence}
          team={parties.opponent}
          defaultOpen
        />
      ) : current.status === "error" ? (
        <p className={styles.itemNote} role="status">
          Manager history unavailable right now ({current.error}).{" "}
          <Button size="sm" variant="ghost" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        </p>
      ) : (
        <p className={styles.itemNote} role="status">
          Reading {parties.opponent}&apos;s completed trades…
        </p>
      )}
      <p className={styles.itemNote}>
        Counts from their own completed trades, with the sample size — never a
        likelihood that they accept.
      </p>
    </div>
  );
}

export default function TradeNextActions({
  sides,
  leagueKey = "",
  myTeam = "",
  mySideIdx = null,
  sideTeamNames = [],
  evalState = "empty",
  isFair = false,
  balancerSideLabel = null,
  balancersPending = false,
  decisionRunId = null,
}) {
  const parties = useMemo(
    () => tradeParties({ sides, mySideIdx, myTeam, sideTeamNames }),
    [sides, mySideIdx, myTeam, sideTeamNames],
  );
  const db = useMemo(() => tradeDatabaseHref(sides), [sides]);
  const desk = useMemo(
    () => deskBodyFromCalculator({ sides, parties, leagueKey, decisionRunId }),
    [sides, parties, leagueKey, decisionRunId],
  );
  const balance = balanceStep({
    evalState,
    isFair,
    balancerSideLabel,
    balancersPending,
    sideCount: (sides || []).length,
  });
  const team = parties.myTeam || myTeam || "";

  return (
    <section className={styles.room} aria-labelledby="trade-next-title" data-testid="trade-next-actions">
      <h2 id="trade-next-title" className={styles.title}>
        Next steps
      </h2>
      <p className={styles.note}>
        Each step opens an existing tool for this trade. None of them changes the totals or the
        decision above.
      </p>
      <ul className={styles.list}>
        <li className={styles.item} data-testid="trade-next-balance" data-state={balance.state}>
          <span className={styles.label}>Balance</span>
          {balance.href ? (
            <a href={balance.href}>{balance.text}</a>
          ) : (
            <span className={styles.note}>{balance.text}</span>
          )}
        </li>
        {ENGINE_LINKS.map((link) => {
          const href =
            team && (!link.needsOpponent || parties.ok)
              ? arbitrageHref(link.tool, {
                  team,
                  opponent: link.needsOpponent ? parties.opponent : "",
                })
              : null;
          return (
            <li key={link.tool} className={styles.item} data-testid={`trade-next-${link.tool}`}>
              {href ? (
                <Button as={Link} href={href} size="sm" variant="ghost">
                  {link.label}
                </Button>
              ) : (
                <span className={styles.note}>{link.label}</span>
              )}
              <p className={styles.itemNote}>
                {href
                  ? link.note
                  : link.needsOpponent
                    ? tradePartiesText(parties.reason)
                    : tradePartiesText("no_team_selected")}
              </p>
            </li>
          );
        })}
        <li className={styles.item} data-testid="trade-next-database">
          {db.href ? (
            <Button as={Link} href={db.href} size="sm" variant="ghost">
              Real trades with these assets
            </Button>
          ) : (
            <span className={styles.note}>Real trades with these assets</span>
          )}
          <p className={styles.itemNote}>
            {db.href
              ? `Trade Database, filtered to this trade's assets${
                  db.unlinked
                    ? `; ${db.unlinked} player${db.unlinked === 1 ? "" : "s"} could not be identified and ${
                        db.unlinked === 1 ? "is" : "are"
                      } not in the filter`
                    : ""
                }.`
              : "Add an identifiable player or pick first."}
          </p>
        </li>
        <li className={styles.item} data-testid="trade-next-scout">
          <Button as={Link} href={MANAGER_SCOUT_HREF} size="sm" variant="ghost">
            League trade tendencies
          </Button>
          <p className={styles.itemNote}>Manager Scout, on Trade History.</p>
        </li>
        <li className={styles.item} data-testid="trade-next-managers">
          <Button as={Link} href={MANAGER_INTEL_HREF} size="sm" variant="ghost">
            Manager Intelligence
          </Button>
          <p className={styles.itemNote}>
            Any manager&apos;s portfolio across their leagues, by Sleeper username.
          </p>
        </li>
        <li className={styles.item} data-testid="trade-next-desk">
          {desk.body ? (
            <SaveToDeskButton body={desk.body} />
          ) : (
            <span className={styles.note}>Save to Trade Desk</span>
          )}
          <p className={styles.itemNote}>
            {desk.body
              ? desk.body.decisionRunId
                ? "Private watchlist; saving never sends a trade. The War Room's current answer is saved with it."
                : "Private watchlist; saving never sends a trade."
              : deskReasonText(desk.reason)}
          </p>
        </li>
      </ul>
      {parties.ok ? (
        <PartnerEvidence sides={sides} parties={parties} leagueKey={leagueKey} />
      ) : (
        <p className={styles.itemNote} data-testid="trade-partner-unavailable">
          Partner trade history: {tradePartiesText(parties.reason)}
        </p>
      )}
    </section>
  );
}
