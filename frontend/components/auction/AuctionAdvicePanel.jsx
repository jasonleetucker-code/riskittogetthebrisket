"use client";

/**
 * Private Perfect Draft advice inside the auction room (milestone C).
 *
 * Lazy-loaded (React.lazy from the room page) so the optimizer never weighs
 * on the room's first paint, and pure display: it never places a bid, never
 * changes the room, and never sends its settings anywhere.  If advice is
 * unavailable or slow, the auction is unaffected — the room says so here.
 */
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { Badge, Banner, Panel, SegmentedControl } from "@/components/ds";
import { auctionFetch, dollars } from "@/lib/auction-client";
import { ESTIMATE_LABEL, buildAdviceInput } from "@/lib/auction-advice";
import { STRATEGIES, applyDraftProgress, optimizeDraft } from "@/lib/perfect-draft";
import styles from "@/app/auction/auction.module.css";

const REASONS = {
  no_seat: "You don't hold a seat in this room.",
  budget_missing: "Your budget is missing — the commissioner must set it.",
  no_roster_context: "No roster context for this seat.",
  seat_has_no_league_roster: "This seat is not a league roster (mock seat), so there is no roster to plan against.",
  board_is_for_another_league: "The loaded board is for another league; advice is withheld rather than mixed.",
  perfect_draft_disabled: "Perfect Draft is switched off.",
  no_board_loaded: "No player board is loaded right now.",
  context_error: "Roster context failed to load.",
};

function storageKey(roomId, seat) {
  return `auction_advice_strategy__${roomId}__${seat}`;
}

export default function AuctionAdvicePanel({ view, pool, roomId }) {
  const seat = view?.me?.seat;
  const [ctx, setCtx] = useState(null);
  const [ctxErr, setCtxErr] = useState(null);
  const [strategy, setStrategy] = useState("balanced");

  useEffect(() => {
    try {
      const s = window.localStorage.getItem(storageKey(roomId, seat));
      if (s && STRATEGIES.includes(s)) setStrategy(s);
    } catch {
      /* private mode: default strategy */
    }
  }, [roomId, seat]);

  useEffect(() => {
    let alive = true;
    auctionFetch(`/rooms/${encodeURIComponent(roomId)}/advice-context`)
      .then((d) => alive && (setCtx(d), setCtxErr(null)))
      .catch((e) => alive && setCtxErr(e.message));
    return () => {
      alive = false;
    };
  }, [roomId]);

  const built = useMemo(
    () => (ctx && pool ? buildAdviceInput({ view, pool, adviceCtx: ctx, strategy, applyDraftProgress }) : null),
    [view, pool, ctx, strategy],
  );
  const deferred = useDeferredValue(built);
  const result = useMemo(() => (deferred?.input ? optimizeDraft(deferred.input) : null), [deferred]);
  const recalculating = built !== deferred;

  const pickStrategy = (s) => {
    setStrategy(s);
    try {
      window.localStorage.setItem(storageKey(roomId, seat), s);
    } catch {
      /* ignore */
    }
  };

  const plan = result?.plan;
  return (
    <Panel
      title="Perfect Draft — your private plan"
      subtitle="Computed on this device from your own view. Advice only: it never bids for you."
      dense
    >
      <div className={styles.col}>
        {ctxErr ? <Banner tone="warning">Advice is unavailable ({ctxErr}). Bidding is unaffected.</Banner> : null}
        {built && !built.input ? <Banner tone="info">{REASONS[built.reason] || "Advice is unavailable for this seat."}</Banner> : null}
        <SegmentedControl
          label="Strategy"
          value={strategy}
          onChange={pickStrategy}
          options={[
            { value: "balanced", label: "Balanced" },
            { value: "winNow", label: "Win now" },
            { value: "longTerm", label: "Long term" },
          ]}
        />
        {built?.input ? (
          <>
            <dl className={styles.ledger}>
              <dt>Free cash (spendable)</dt>
              <dd>{dollars(built.input.budget)}</dd>
              <dt>Held: leading or won</dt>
              <dd>{built.held.length}</dd>
              <dt>Open roster spots after those</dt>
              <dd>{built.progress.openRosterSpots}</dd>
            </dl>
            {plan && plan.players.length ? (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption className={styles.muted}>
                    Recommended plan: {plan.players.length} more rookie{plan.players.length === 1 ? "" : "s"}, about {dollars(Math.round(plan.spend))}
                    {recalculating ? " · updating…" : ""}
                  </caption>
                  <thead>
                    <tr>
                      <th scope="col">Rookie</th>
                      <th scope="col" className={styles.num}>
                        Expected
                      </th>
                      <th scope="col" className={styles.num}>
                        Plan max
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.players.map((p) => (
                      <tr key={p.id}>
                        <td>
                          <span className={styles.player}>{p.name}</span>
                          <span className={styles.sub}>
                            {p.pos || "—"}
                            {p.lot ? ` · open lot ${p.lot} at ${dollars(p.lotPrice)}` : " · not yet nominated"}
                          </span>
                        </td>
                        <td className={styles.num}>{dollars(Math.round(p.price))}</td>
                        <td className={styles.num}>{dollars(p.planMaxBid)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className={styles.muted}>No further purchase improves your roster at these prices. Keeping your money is a valid plan.</p>
            )}
            {built.held.length ? (
              <p className={styles.muted}>
                Already counted:{" "}
                {built.held.map((h) => (
                  <Badge key={h.id} tone={h.state === "won" ? "positive" : "accent"}>
                    {h.name} {dollars(h.price)} {h.state}
                  </Badge>
                ))}
              </p>
            ) : null}
            <p className={styles.muted}>
              {ESTIMATE_LABEL} Plan max is this plan's indifference price for you alone — it assumes the rest of the plan, and you choose whether to enter it.
              {built.unpriced ? ` ${built.unpriced} rookie(s) have no board value and are left out rather than priced.` : ""}
              {ctx?.valuesAsOf ? ` Values as of ${ctx.valuesAsOf}.` : ""}
            </p>
          </>
        ) : null}
      </div>
    </Panel>
  );
}
