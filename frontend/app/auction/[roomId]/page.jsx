"use client";

/**
 * /auction/[roomId] — the shared rookie auction room.
 *
 * Pure presentation over the server's authorised snapshot (`/view`).  The
 * page never decides a winner, a price, a deadline or a balance: it renders
 * what the server committed and sends commands.  Countdown text interpolates
 * between snapshots for display only.  "You won" is never shown before the
 * server records the sale.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import { Badge, Banner, Button, EmptyState, Field, Input, PageHeader, Panel, Select } from "@/components/ds";
import {
  auctionFetch,
  dollars,
  formatActiveSeconds,
  formatRoomTime,
  parseDollars,
  sendCommand,
  useAuctionRoom,
  useNowTicker,
} from "@/lib/auction-client";
import { notifyApi, refreshBinding } from "@/lib/auction-notify";
import { Members, PointsForOrder, Preflight, RulesConfirmation } from "@/components/auction/CommissionerTools";
import ReportProblem from "@/components/auction/ReportProblem";
import styles from "../auction.module.css";

// Code-split: the optimizer loads only for seat holders, after the room paints.
// React.lazy, not next/dynamic (see CLAUDE.md "Perfect Draft": next/dynamic
// moved Next's loadable runtime into every page's shared chunk).
const AuctionAdvicePanel = lazy(() => import("@/components/auction/AuctionAdvicePanel"));

function useCommand(roomId, onAccepted) {
  const [pending, setPending] = useState(null);
  const [msg, setMsg] = useState(null);
  const run = async (label, body) => {
    setPending(label);
    setMsg(null);
    try {
      const out = await sendCommand(roomId, body);
      onAccepted?.(out);
      return out;
    } catch (err) {
      setMsg({ tone: err.unknown ? "warning" : "negative", text: err.message });
      return null;
    } finally {
      setPending(null);
    }
  };
  return { run, pending, msg, setMsg };
}

function remainingFor(a, view, now) {
  if (a.status !== "open") return 0;
  const pub = view.public;
  if (pub.paused || !pub.active_now) return a.remaining_active_seconds;
  // Inside the active window the remaining active time runs 1:1 with the
  // clock until the window ends; the server snapshot stays authoritative.
  const elapsed = Math.max(0, now - view.serverNow);
  return Math.max(0, a.remaining_active_seconds - elapsed);
}

function StatusStrip({ view, sync, now }) {
  const pub = view.public;
  const syncLabel = { live: "Live", connecting: "Connecting", reconnecting: "Reconnecting…", offline: "Offline" }[sync];
  const roomState = pub.paused
    ? `Paused (${pub.paused.kind})`
    : pub.status === "setup"
      ? "Setup"
      : pub.status === "complete"
        ? "Complete"
        : pub.status === "draining"
          ? `Draining — ${pub.drain_reason === "money_spent" ? "all money spent" : "all nominations used"}`
          : pub.active_now
            ? "Bidding open"
            : `Nightly pause · resumes ${formatRoomTime(pub.next_active_start)}`;
  return (
    <div className={styles.strip} role="status" aria-live="polite">
      <span>
        <span className={`${styles.dot} ${sync === "live" ? styles.dotLive : styles.dotWarn}`} aria-hidden="true" />
        Sync <strong>{syncLabel}</strong> · rev {view.revision}
      </span>
      <span>
        Room <strong>{roomState}</strong>
      </span>
      <span>
        Open lots <strong>{pub.open_count}</strong> / {pub.rules.max_open}
      </span>
      <span>
        Room time <strong>{formatRoomTime(view.roomNow + Math.max(0, now - view.serverNow))}</strong>
        {view.clockOffset ? " (mock virtual clock)" : ""}
      </span>
      <span>{pub.window_text}</span>
    </div>
  );
}

function MyMoney({ view }) {
  const p = view.me.private;
  if (!p) return null;
  return (
    <Panel title="Your money" dense subtitle="Leading prices are reserved. Only spendable money backs new bids.">
      <dl className={styles.ledger}>
        <dt>Balance (after purchases)</dt>
        <dd>{dollars(p.balance)}</dd>
        <dt>Reserved — lots you lead</dt>
        <dd>{dollars(p.committed)}</dd>
      </dl>
      <dl className={`${styles.ledger} ${styles.ledgerKey}`}>
        <dt>Spendable now</dt>
        <dd>{dollars(p.spendable)}</dd>
      </dl>
      <dl className={styles.ledger}>
        <dt>Conditional proxy exposure</dt>
        <dd>{dollars(p.conditional_exposure)}</dd>
      </dl>
      <p className={styles.muted}>
        Private maximums are instructions, not reservations: each can only execute up to what is spendable at that moment.
      </p>
    </Panel>
  );
}

function BidCell({ a, mine, roomId, disabled, onAccepted }) {
  const [value, setValue] = useState("");
  const { run, pending, msg } = useCommand(roomId, onAccepted);
  const submit = async (e) => {
    e.preventDefault();
    const n = parseDollars(value);
    if (n == null) return;
    const out = await run("bid", { kind: "bid", auction: a.id, max: n });
    if (out) setValue("");
  };
  return (
    <form className={styles.bidForm} onSubmit={submit}>
      <Input
        id={`bid-${a.id}`}
        aria-label={`Your maximum bid for lot ${a.id}`}
        className={styles.bidInput}
        inputMode="numeric"
        data-numeric
        placeholder={mine ? `$${mine.max}` : `$${a.price + (a.leader ? 1 : 0)}`}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        disabled={disabled}
      />
      <Button type="submit" size="sm" variant="secondary" loading={pending === "bid"} disabled={disabled || parseDollars(value) == null}>
        Set max
      </Button>
      {msg ? (
        <span role="alert" className={styles.sub}>
          {msg.text}
        </span>
      ) : null}
    </form>
  );
}

function OpenAuctions({ view, players, roomId, now, onAccepted }) {
  const pub = view.public;
  const seatName = Object.fromEntries(pub.seats.map((s) => [s.id, s.name]));
  const myBids = Object.fromEntries((view.me.private?.my_bids || []).map((b) => [b.auction, b]));
  const open = pub.auctions.filter((a) => a.status === "open");
  const canBid = Boolean(view.me.seat) && !pub.paused && pub.active_now && ["running", "draining"].includes(pub.status);
  const [withdrawing, setWithdrawing] = useState(null);
  const [watched, setWatched] = useState(() => new Set());
  const toggleWatch = async (aid) => {
    try {
      const out = await notifyApi.watch(roomId, aid, !watched.has(aid));
      setWatched(new Set(out.watched));
    } catch {
      /* non-binding convenience; the lot is unaffected */
    }
  };
  const withdraw = async (aid) => {
    setWithdrawing(aid);
    try {
      await sendCommand(roomId, { kind: "withdraw", auction: aid });
      onAccepted?.();
    } catch {
      /* surfaced by the next snapshot */
    } finally {
      setWithdrawing(null);
    }
  };
  return (
    <Panel title="Open lots" subtitle="Prices are public. Maximums are private — nobody, including the commissioner, sees yours." flush>
      {open.length === 0 ? (
        <EmptyState title="No open lots" description={pub.status === "setup" ? "The room has not started." : "Waiting for the next nomination."} />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col" className={styles.num}>
                  Price
                </th>
                <th scope="col">Leader</th>
                <th scope="col" className={styles.num}>
                  Time left
                </th>
                <th scope="col">You</th>
                <th scope="col" className={styles.num}>
                  Bid
                </th>
              </tr>
            </thead>
            <tbody>
              {open.map((a) => {
                const p = players?.[a.player] || {};
                const mine = myBids[a.id];
                const leading = a.leader === view.me.seat;
                let you = "—";
                if (leading) you = <Badge tone="positive">Leading</Badge>;
                else if (mine && mine.active) you = mine.capped ? <Badge tone="warning">Capped at {dollars(mine.effective_max)}</Badge> : <Badge tone="negative">Outbid</Badge>;
                else if (mine && !mine.active) you = <Badge>Proxy off</Badge>;
                return (
                  <tr key={a.id} className={leading ? styles.mine : undefined}>
                    <td>
                      <span className={styles.player}>{p.name || a.player}</span>
                      <span className={styles.sub}>
                        {p.pos || "—"} · {a.id} · round {a.round} · nominated by {seatName[a.nominator]}
                        {a.extensions ? ` · extended ×${a.extensions}` : ""}
                      </span>
                    </td>
                    <td className={styles.num}>{dollars(a.price)}</td>
                    <td>{seatName[a.leader]}</td>
                    <td className={styles.num}>
                      {formatActiveSeconds(remainingFor(a, view, now))}
                      <span className={styles.sub}>closes {formatRoomTime(a.deadline)}</span>
                    </td>
                    <td>
                      {you}
                      {mine ? <span className={styles.sub}>your max {dollars(mine.max)}</span> : null}
                    </td>
                    <td className={styles.num}>
                      {view.me.seat ? <BidCell a={a} mine={mine} roomId={roomId} disabled={!canBid} onAccepted={onAccepted} /> : "—"}
                      <Button size="sm" variant="ghost" aria-pressed={watched.has(a.id)} onClick={() => toggleWatch(a.id)}>
                        {watched.has(a.id) ? "Watching" : "Watch"}
                      </Button>
                      {mine && mine.active && !leading ? (
                        <Button size="sm" variant="ghost" onClick={() => withdraw(a.id)} loading={withdrawing === a.id} disabled={!canBid}>
                          Turn proxy off
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function Nominate({ view, players, roomId, onAccepted }) {
  const pub = view.public;
  const me = view.me.private;
  const [q, setQ] = useState("");
  const { run, pending, msg } = useCommand(roomId, onAccepted);
  const taken = new Set(pub.auctions.map((a) => a.player));
  const list = useMemo(() => {
    const rows = Object.entries(players || {})
      .filter(([pid]) => !taken.has(pid))
      .map(([pid, p]) => ({ pid, ...p }));
    const needle = q.trim().toLowerCase();
    return rows
      .filter((r) => !needle || String(r.name).toLowerCase().includes(needle) || String(r.pos).toLowerCase() === needle)
      .sort((x, y) => (y.value || 0) - (x.value || 0))
      .slice(0, 40);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [players, q, pub.auctions.length]);
  if (!me) return null;
  const queue = me.queue?.players || [];
  const onClock = me.on_clock;
  const canAct = onClock && !pub.paused && pub.active_now && pub.status === "running";
  const saveQueue = (players2, auto) => run("queue", { kind: "set_queue", players: players2, auto });
  return (
    <Panel
      title="Nominate"
      subtitle={
        onClock
          ? `You are on the nomination clock (round ${onClock.round})${onClock.deadline ? ` — turn passes ${formatRoomTime(onClock.deadline)} if unused` : ""}.`
          : pub.status === "running"
            ? pub.open_count >= pub.rules.max_open
              ? "All twelve lots are open. The nomination clock is paused — nobody is penalised."
              : "Not your turn yet."
            : "Nominations are closed."
      }
    >
      <div className={styles.col}>
        <Field label="Search the rookie pool" hint={pub.pool.label}>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name or position" />
        </Field>
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Rookie</th>
                <th scope="col" className={styles.num}>
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.pid}>
                  <td>
                    <span className={styles.player}>{r.name}</span>
                    <span className={styles.sub}>{r.pos || "—"}</span>
                  </td>
                  <td className={styles.num}>
                    <div className={styles.bidForm}>
                      <Button size="sm" variant={canAct ? "primary" : "secondary"} disabled={!canAct || Boolean(pending)} onClick={() => run("nominate", { kind: "nominate", player: r.pid })}>
                        Nominate at $0
                      </Button>
                      <Button size="sm" variant="ghost" disabled={queue.includes(r.pid) || Boolean(pending)} onClick={() => saveQueue([...queue, r.pid], me.queue?.auto || false)}>
                        Queue
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {onClock ? (
          <div>
            <Button variant="ghost" onClick={() => run("pass", { kind: "pass_nomination" })} disabled={!canAct || Boolean(pending)}>
              Pass this nomination
            </Button>
          </div>
        ) : null}
        <div>
          <h3 className={styles.player}>Your private nomination queue</h3>
          {queue.length === 0 ? (
            <p className={styles.muted}>Empty. Queue players so your turn is never wasted while you are away.</p>
          ) : (
            <ol className={styles.rules}>
              {queue.map((pid) => (
                <li key={pid}>
                  {players?.[pid]?.name || pid}{" "}
                  <Button size="sm" variant="ghost" onClick={() => saveQueue(queue.filter((x) => x !== pid), me.queue?.auto || false)}>
                    Remove
                  </Button>
                </li>
              ))}
            </ol>
          )}
          <label className={styles.row}>
            <input type="checkbox" checked={Boolean(me.queue?.auto)} onChange={(e) => saveQueue(queue, e.target.checked)} disabled={Boolean(pending)} />
            I authorise nominating the first still-eligible queued player at $0 when my turn and a slot arrive.
          </label>
        </div>
        {msg ? <Banner tone={msg.tone}>{msg.text}</Banner> : null}
      </div>
    </Panel>
  );
}

function Budgets({ view }) {
  const pub = view.public;
  return (
    <Panel title="Budgets" dense flush subtitle={`Opening pool ${dollars(pub.total_opening_pool)}`}>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Manager</th>
              <th scope="col" className={styles.num}>
                Balance
              </th>
              <th scope="col" className={styles.num}>
                Reserved
              </th>
              <th scope="col" className={styles.num}>
                Won
              </th>
              <th scope="col" className={styles.num}>
                Noms left
              </th>
            </tr>
          </thead>
          <tbody>
            {pub.order.map((sid) => {
              const s = pub.seats.find((x) => x.id === sid);
              return (
                <tr key={sid} className={sid === view.me.seat ? styles.mine : undefined}>
                  <td>
                    {s.name}
                    {s.is_bot ? <span className={styles.sub}>bot</span> : null}
                  </td>
                  <td className={styles.num}>{s.balance == null ? <Badge tone="negative">missing</Badge> : dollars(s.balance)}</td>
                  <td className={styles.num}>{dollars(s.committed)}</td>
                  <td className={styles.num}>{s.won}</td>
                  <td className={styles.num}>{s.rights_left}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function Results({ view, players }) {
  const pub = view.public;
  const seatName = Object.fromEntries(pub.seats.map((s) => [s.id, s.name]));
  const sold = pub.auctions.filter((a) => a.status === "closed").slice().reverse();
  return (
    <Panel
      title="Sold"
      flush
      actions={
        <div className={styles.row}>
          <Button size="sm" variant="ghost" as="a" href={`/api/auction/rooms/${pub.room_id}/export?format=csv`}>
            CSV
          </Button>
          <Button size="sm" variant="ghost" as="a" href={`/api/auction/rooms/${pub.room_id}/export?format=json`}>
            JSON
          </Button>
        </div>
      }
    >
      {sold.length === 0 ? (
        <EmptyState title="Nothing sold yet" />
      ) : (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col">Winner</th>
                <th scope="col" className={styles.num}>
                  Price
                </th>
                <th scope="col">Closed</th>
              </tr>
            </thead>
            <tbody>
              {sold.map((a) => (
                <tr key={a.id} className={a.winner === view.me.seat ? styles.mine : undefined}>
                  <td>
                    <span className={styles.player}>{players?.[a.player]?.name || a.player}</span>
                    <span className={styles.sub}>{players?.[a.player]?.pos || ""} · round {a.round}</span>
                  </td>
                  <td>{seatName[a.winner]}</td>
                  <td className={styles.num}>{dollars(a.price)}</td>
                  <td>{formatRoomTime(a.closed_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function describeEvent(e, seatName, players) {
  const d = e.data || {};
  const who = (s) => seatName[s] || s;
  const pl = (p) => players?.[p]?.name || d.player_name || p;
  switch (e.type) {
    case "nominated":
      return `${who(d.seat)} nominated ${pl(d.player)}${d.via === "queue" ? " (from queue)" : ""}`;
    case "price":
      return `${pl(d.player)}: ${who(d.leader)} leads at $${d.price}${d.extended ? " — clock extended" : ""}`;
    case "sold":
      return `SOLD: ${pl(d.player)} to ${who(d.seat)} for $${d.price}`;
    case "outbid":
      return `You were outbid on ${pl(d.player)} ($${d.price})`;
    case "bid_accepted":
      return `Your maximum of $${d.max} on ${d.auction} was accepted${d.capped ? ` — capped at $${d.effective_max} by available money` : ""}`;
    case "nomination_turn":
      return `${who(d.seat)} is on the nomination clock (round ${d.round})`;
    case "nomination_passed":
      return `${who(d.seat)}'s round-${(d.right || "").slice(1).split(".")[0]} nomination passed (${d.reason === "timeout" ? "timed out" : "passed"})`;
    case "paused":
      return `Room paused${d.reason ? `: ${d.reason}` : ""}`;
    case "resumed":
      return `Room resumed${d.min_remaining_active_seconds ? ` — every open lot has at least ${formatActiveSeconds(d.min_remaining_active_seconds)} of active time` : ""}`;
    case "started":
      return "The auction started. Opening budgets are frozen.";
    case "draining":
      return d.reason === "money_spent" ? "All money is spent — no new nominations; open lots finish normally." : "All nominations are used — open lots finish normally.";
    case "complete":
      return "The auction is complete.";
    case "budget_adjusted":
      return `Commissioner adjusted ${who(d.seat)} by $${d.amount}: ${d.reason}`;
    case "queue_skipped":
      return `Queued player ${pl(d.player)} skipped — no longer eligible`;
    case "proxy_disabled":
      return `Your proxy on ${d.auction} is off`;
    default:
      return e.type.replace(/_/g, " ");
  }
}

function Activity({ view, players }) {
  const seatName = Object.fromEntries(view.public.seats.map((s) => [s.id, s.name]));
  return (
    <Panel title="Activity" dense>
      <ul className={styles.feed} aria-live="off">
        {view.events.map((e) => (
          <li key={`${e.revision}-${e.idx}`}>
            <time>{formatRoomTime(e.at)}</time>
            {describeEvent(e, seatName, players)}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Inbox({ roomId, revision }) {
  const [data, setData] = useState(null);
  useEffect(() => {
    notifyApi
      .inbox(roomId)
      .then(setData)
      .catch(() => setData(null));
  }, [roomId, revision]);
  if (!data) return null;
  const unreadHere = data.items.filter((i) => !i.read_at).length;
  return (
    <Panel
      title={`Your alerts${unreadHere ? ` (${unreadHere} new)` : ""}`}
      dense
      actions={
        <div className={styles.row}>
          {unreadHere ? (
            <Button size="sm" variant="ghost" onClick={() => notifyApi.markRead({ ids: data.items.map((i) => i.id) }).then(() => notifyApi.inbox(roomId).then(setData))}>
              Mark read
            </Button>
          ) : null}
          <Button size="sm" variant="ghost" as={Link} href="/auction/notifications">
            Phone alerts
          </Button>
        </div>
      }
    >
      {data.items.length === 0 ? (
        <p className={styles.muted}>Nothing yet. Alerts for your seat are kept here even when your phone is off.</p>
      ) : (
        <ul className={styles.feed}>
          {data.items.map((i) => (
            <li key={i.id}>
              <time>{formatRoomTime(i.room_now)}</time>
              <strong>{i.title}</strong> — {i.body}
              {!i.read_at ? <Badge tone="accent">new</Badge> : null}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function Rules({ view }) {
  const r = view.public.rules;
  return (
    <Panel title="Rules in this room" dense collapsible={false}>
      <ul className={styles.rules}>
        <li>Opening bid $0; a player can be won for $0. Positive bids are whole dollars.</li>
        <li>Set a private maximum. The price is the least needed to win: A max $50 vs B max $39 → A leads at $40. Equal maximums go to the earlier accepted bid.</li>
        <li>Leading prices are reserved: with $50 and a $45 lead you have $5 for everything else.</li>
        <li>
          Up to {r.max_open} lots open at once; {r.rounds} nomination turns each (not a purchase requirement — win none or many).
        </li>
        <li>
          Each lot runs {formatActiveSeconds(r.auction_active_seconds)} of active time. A price change inside the final {formatActiveSeconds(r.extension_active_seconds)} extends it to at least that much.
        </li>
        <li>
          {view.public.window_text}.{view.public.window?.enabled ? " Nothing binding happens during the nightly pause; clocks stop and resume at 8 AM." : ""}
        </li>
        {r.nomination_timeout_active_seconds ? <li>An unused nomination turn passes after {formatActiveSeconds(r.nomination_timeout_active_seconds)} of active time.</li> : null}
        <li>Non-leaders may turn a proxy off; the leader cannot withdraw or go below the price.</li>
      </ul>
      {view.public.unconfirmed_rules.length ? (
        <p className={styles.muted}>
          Proposed rules not yet confirmed for an official room: {view.public.unconfirmed_rules.length}. They are fine for mocks.
        </p>
      ) : null}
    </Panel>
  );
}

function Trades({ view, players, roomId }) {
  const pub = view.public;
  const me = view.me.private;
  const seat = view.me.seat;
  const { run, pending, msg } = useCommand(roomId);
  const [form, setForm] = useState({ to: "", give: "", get: "", giveLots: [], getLots: [], note: "", hours: "24" });
  if (!me || !seat) return null;
  const seatName = Object.fromEntries(pub.seats.map((s) => [s.id, s.name]));
  const owned = (sid) => pub.auctions.filter((a) => a.status === "closed" && a.owner === sid);
  const lotName = (aid) => {
    const a = pub.auctions.find((x) => x.id === aid);
    return a ? players?.[a.player]?.name || a.player : aid;
  };
  const canAct = !pub.paused && pub.active_now && ["running", "draining"].includes(pub.status);
  const trades = me.trades || [];
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const toggleLot = (k, aid) =>
    setForm((f) => ({ ...f, [k]: f[k].includes(aid) ? f[k].filter((x) => x !== aid) : [...f[k], aid] }));
  const submit = async (e) => {
    e.preventDefault();
    const give = form.give === "" ? 0 : parseDollars(form.give);
    const get = form.get === "" ? 0 : parseDollars(form.get);
    if (give == null || get == null || !form.to) return;
    const out = await run("offer", {
      kind: "offer_trade",
      to: form.to,
      give_dollars: give,
      get_dollars: get,
      give_lots: form.giveLots,
      get_lots: form.getLots,
      external_note: form.note,
      expires_hours: Number(form.hours) || 24,
    });
    if (out) setForm({ to: "", give: "", get: "", giveLots: [], getLots: [], note: "", hours: "24" });
  };
  const describe = (t) => {
    const parts = [];
    if (t.give_dollars) parts.push(`${seatName[t.from]} sends $${t.give_dollars}`);
    if (t.get_dollars) parts.push(`${seatName[t.to]} sends $${t.get_dollars}`);
    if (t.give_lots.length) parts.push(`${seatName[t.from]} sends ${t.give_lots.map(lotName).join(", ")}`);
    if (t.get_lots.length) parts.push(`${seatName[t.to]} sends ${t.get_lots.map(lotName).join(", ")}`);
    if (t.external_note) parts.push(`outside the room: ${t.external_note}`);
    return parts.join(" · ");
  };
  return (
    <Panel
      title="Trades"
      dense
      subtitle="Auction dollars and players won here. Offers do not reserve money: both sides' spendable money is re-checked when it settles."
    >
      <div className={styles.col}>
        {trades.length ? (
          <ul className={styles.feed}>
            {trades.map((t) => (
              <li key={t.id}>
                <strong>{t.id}</strong> {describe(t)} — <Badge>{t.status.replace(/_/g, " ")}</Badge>
                {t.status === "open" && t.to === seat ? (
                  <span className={styles.row}>
                    <Button
                      size="sm"
                      variant="primary"
                      disabled={!canAct || Boolean(pending)}
                      onClick={() => run("accept", { kind: "respond_trade", trade: t.id, version: t.version, accept: true })}
                    >
                      Accept
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      disabled={Boolean(pending)}
                      onClick={() => run("decline", { kind: "respond_trade", trade: t.id, version: t.version, accept: false })}
                    >
                      Decline
                    </Button>
                  </span>
                ) : null}
                {["open", "awaiting_verification"].includes(t.status) && t.from === seat ? (
                  <Button size="sm" variant="ghost" disabled={Boolean(pending)} onClick={() => run("cancel", { kind: "cancel_trade", trade: t.id })}>
                    Withdraw
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.muted}>No trades yet.</p>
        )}
        <form onSubmit={submit} className={styles.col}>
          <div className={styles.formGrid}>
            <Field label="Trade with">
              <Select
                value={form.to}
                onChange={set("to")}
                options={[
                  { value: "", label: "Choose a manager" },
                  ...pub.seats.filter((s) => s.id !== seat).map((s) => ({ value: s.id, label: s.name })),
                ]}
              />
            </Field>
            <Field label="You send ($)" hint={`Spendable now: $${me.spendable}`}>
              <Input inputMode="numeric" data-numeric value={form.give} onChange={set("give")} placeholder="0" />
            </Field>
            <Field label="You receive ($)">
              <Input inputMode="numeric" data-numeric value={form.get} onChange={set("get")} placeholder="0" />
            </Field>
            <Field label="Expires after (hours)">
              <Input inputMode="numeric" data-numeric value={form.hours} onChange={set("hours")} />
            </Field>
          </div>
          {owned(seat).length ? (
            <fieldset className={styles.row}>
              <legend className={styles.muted}>Players you send</legend>
              {owned(seat).map((a) => (
                <label key={a.id} className={styles.row}>
                  <input type="checkbox" checked={form.giveLots.includes(a.id)} onChange={() => toggleLot("giveLots", a.id)} /> {lotName(a.id)}
                </label>
              ))}
            </fieldset>
          ) : null}
          {form.to && owned(form.to).length ? (
            <fieldset className={styles.row}>
              <legend className={styles.muted}>Players you receive</legend>
              {owned(form.to).map((a) => (
                <label key={a.id} className={styles.row}>
                  <input type="checkbox" checked={form.getLots.includes(a.id)} onChange={() => toggleLot("getLots", a.id)} /> {lotName(a.id)}
                </label>
              ))}
            </fieldset>
          ) : null}
          <Field
            label="Anything outside this room (optional)"
            hint="For example a Sleeper veteran or a future pick. The commissioner must verify that side before any dollars move."
          >
            <Input value={form.note} onChange={set("note")} maxLength={300} />
          </Field>
          <div>
            <Button type="submit" disabled={!canAct || !form.to || Boolean(pending)} loading={pending === "offer"}>
              Send offer
            </Button>
          </div>
        </form>
        {msg ? <Banner tone={msg.tone}>{msg.text}</Banner> : null}
      </div>
    </Panel>
  );
}

function Commissioner({ view, roomId, onAccepted }) {
  const pub = view.public;
  const { run, pending, msg } = useCommand(roomId, onAccepted);
  const [invite, setInvite] = useState(null);
  const [inviteSeat, setInviteSeat] = useState("");
  const [inviteHandle, setInviteHandle] = useState("");
  const [reason, setReason] = useState("");
  const [err, setErr] = useState(null);
  const [meta, setMeta] = useState(null);
  useEffect(() => {
    auctionFetch("/meta")
      .then(setMeta)
      .catch(() => setMeta(null));
  }, []);
  const setup = pub.status === "setup";
  const humans = new Set((view.commissioner?.members || []).map((m) => m.seat_id).filter(Boolean));

  const makeInvite = async () => {
    setErr(null);
    try {
      const out = await auctionFetch(`/rooms/${roomId}/invites`, {
        method: "POST",
        body: { seat: inviteSeat || null, role: inviteSeat ? "manager" : "observer", intendedHandle: inviteHandle || null },
      });
      setInvite(`${window.location.origin}${out.joinPath}`);
    } catch (x) {
      setErr(x.message);
    }
  };
  const clock = async (seconds) => {
    setErr(null);
    try {
      await auctionFetch(`/rooms/${roomId}/clock`, { method: "POST", body: { advanceSeconds: seconds } });
      onAccepted?.();
    } catch (x) {
      setErr(x.message);
    }
  };
  const clone = async () => {
    try {
      const out = await auctionFetch(`/rooms/${roomId}/clone`, { method: "POST", body: {} });
      window.location.href = `/auction/${out.roomId}`;
    } catch (x) {
      setErr(x.message);
    }
  };
  const moveSeat = (i, delta) => {
    const order = pub.order.slice();
    const j = i + delta;
    if (j < 0 || j >= order.length) return;
    [order[i], order[j]] = [order[j], order[i]];
    run("order", { kind: "set_order", order, basis: "commissioner manual order" });
  };

  return (
    <Panel title="Commissioner" subtitle="Room controls. You cannot see anyone's private maximum.">
      <div className={styles.col}>
        {setup ? (
          <>
            <p className={styles.muted}>
              Budget source: {view.budgetProvenance?.source || "—"}
              {view.budgetProvenance?.season ? ` · season ${view.budgetProvenance.season}` : ""}
              {view.budgetProvenance?.unmatchedSeats?.length ? ` · could not match: ${view.budgetProvenance.unmatchedSeats.join(", ")}` : ""}
            </p>
            <div className={styles.tableWrap}>
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th scope="col">#</th>
                    <th scope="col">Seat</th>
                    <th scope="col" className={styles.num}>
                      Budget
                    </th>
                    <th scope="col">Bot</th>
                    <th scope="col">Order</th>
                  </tr>
                </thead>
                <tbody>
                  {pub.order.map((sid, i) => {
                    const s = pub.seats.find((x) => x.id === sid);
                    return (
                      <tr key={sid}>
                        <td className={styles.num}>{i + 1}</td>
                        <td>
                          {s.name}
                          <span className={styles.sub}>
                            {sid} · {s.budget_source}
                            {humans.has(sid) ? " · claimed" : ""}
                          </span>
                        </td>
                        <td className={styles.num}>
                          <Input
                            aria-label={`Budget for ${s.name}`}
                            className={styles.bidInput}
                            data-numeric
                            defaultValue={s.opening_budget ?? ""}
                            placeholder="missing"
                            onBlur={(e) => {
                              const n = parseDollars(e.target.value);
                              if (n != null && n !== s.opening_budget) run("budget", { kind: "set_seat", seat: sid, patch: { opening_budget: n }, reason: "commissioner override before start" });
                            }}
                          />
                        </td>
                        <td>
                          <input
                            type="checkbox"
                            aria-label={`${s.name} is a bot`}
                            checked={s.is_bot}
                            disabled={humans.has(sid)}
                            onChange={(e) => run("bot", { kind: "set_seat", seat: sid, patch: { is_bot: e.target.checked } })}
                          />
                        </td>
                        <td>
                          <Button size="sm" variant="ghost" aria-label={`Move ${s.name} earlier`} onClick={() => moveSeat(i, -1)} disabled={i === 0}>
                            ↑
                          </Button>
                          <Button size="sm" variant="ghost" aria-label={`Move ${s.name} later`} onClick={() => moveSeat(i, 1)} disabled={i === pub.order.length - 1}>
                            ↓
                          </Button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <p className={styles.muted}>Nomination order runs top to bottom and repeats each round. For the real draft this is points-for, lowest first, as you confirm it.</p>
            <div>
              <Button variant="primary" onClick={() => run("start", { kind: "start" })} loading={pending === "start"}>
                Start the auction
              </Button>
            </div>
          </>
        ) : null}

        <Preflight roomId={roomId} revision={view.revision} />
        <PointsForOrder view={view} roomId={roomId} run={run} />
        <RulesConfirmation view={view} run={run} meta={meta} />
        <Members view={view} roomId={roomId} />
        {(view.commissioner?.pendingTrades || []).map((t) => (
          <div key={t.id} className={styles.col}>
            <p>
              <strong>Verify {t.id}</strong>: outside-the-room side is &ldquo;{t.external_note}&rdquo;. Dollars: {t.from} sends ${t.give_dollars},{" "}
              {t.to} sends ${t.get_dollars}.
            </p>
            <div className={styles.row}>
              <Button size="sm" disabled={!reason.trim()} onClick={() => run("verify", { kind: "verify_trade", trade: t.id, approve: true, reason })}>
                Verified — settle
              </Button>
              <Button
                size="sm"
                variant="ghost"
                disabled={!reason.trim()}
                onClick={() => run("verify", { kind: "verify_trade", trade: t.id, approve: false, reason })}
              >
                Reject
              </Button>
              <span className={styles.muted}>Record how you verified it in the reason field below.</span>
            </div>
          </div>
        ))}
        <div className={styles.formGrid}>
          <Field label="Invite a seat" hint="Single-use link, expires in 7 days. A handle lock makes it usable only by that handle.">
            <Select
              value={inviteSeat}
              onChange={(e) => setInviteSeat(e.target.value)}
              options={[
                { value: "", label: "Observer (no seat)" },
                ...pub.seats.filter((s) => !s.is_bot).map((s) => ({ value: s.id, label: `${s.id} · ${s.name}` })),
              ]}
            />
          </Field>
          <Field label="Lock to handle (optional)">
            <Input value={inviteHandle} onChange={(e) => setInviteHandle(e.target.value)} placeholder="their Sleeper username" />
          </Field>
        </div>
        <div>
          <Button onClick={makeInvite}>Create invitation link</Button>
        </div>
        {invite ? (
          <div>
            <p className={styles.muted}>Shown once. Send it privately to that person only.</p>
            <p className={styles.secret}>{invite}</p>
          </div>
        ) : null}

        {!setup && pub.status !== "complete" ? (
          <>
            <Field label="Reason (shown to everyone)">
              <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
            </Field>
            <div className={styles.row}>
              {pub.paused ? (
                <Button variant="primary" onClick={() => run("resume", { kind: "resume", reason })}>
                  Resume
                </Button>
              ) : (
                <Button onClick={() => run("pause", { kind: "pause", reason })} disabled={!reason.trim()}>
                  Pause room
                </Button>
              )}
            </div>
          </>
        ) : null}

        {pub.room_type === "mock" && !setup ? (
          <div>
            <p className={styles.muted}>Mock virtual clock — jumps this room only.</p>
            <div className={styles.row}>
              {[
                ["+10 min", 600],
                ["+1 hour", 3600],
                ["+13 hours", 13 * 3600],
                ["+1 day", 86400],
              ].map(([label, s]) => (
                <Button key={label} size="sm" onClick={() => clock(s)}>
                  {label}
                </Button>
              ))}
            </div>
          </div>
        ) : null}
        {pub.room_type === "mock" ? (
          <div>
            <Button variant="ghost" onClick={clone}>
              New run with this configuration
            </Button>
          </div>
        ) : null}
        {msg ? <Banner tone={msg.tone}>{msg.text}</Banner> : null}
        {err ? <Banner tone="negative">{err}</Banner> : null}
      </div>
    </Panel>
  );
}

export default function AuctionRoomPage() {
  const { roomId } = useParams();
  const { view, sync, error } = useAuctionRoom(roomId);
  const [pool, setPool] = useState(null);
  const now = useNowTicker(1000);

  useEffect(() => {
    refreshBinding();
  }, []);

  useEffect(() => {
    if (!roomId) return;
    auctionFetch(`/rooms/${encodeURIComponent(roomId)}/pool`)
      .then(setPool)
      .catch(() => setPool(null));
  }, [roomId]);

  // A command's own response only carries its revision; the long-poll wakes
  // on that commit and delivers the authoritative snapshot.
  const onAccepted = () => {};

  if (error) {
    return (
      <section className={`${styles.page} psi-editorial`}>
        <PageHeader className={styles.hero} eyebrow="Rookie auction" title="Auction room" />
        <Banner tone="negative" title={error.status === 401 ? "Sign in required" : "Unavailable"}>
          {error.message} <Link href="/auction">Go to the auction lobby</Link>
        </Banner>
      </section>
    );
  }
  if (!view) {
    return (
      <section className={`${styles.page} psi-editorial`} aria-busy="true">
        <PageHeader className={styles.hero} eyebrow="Rookie auction" title="Auction room" description="Loading the room…" />
      </section>
    );
  }
  const pub = view.public;
  const players = pool?.players;
  const mySeat = pub.seats.find((s) => s.id === view.me.seat);
  return (
    <section className={`${styles.page} psi-editorial`}>
      <PageHeader
        className={styles.hero}
        eyebrow={`Rookie auction · ${pub.room_type === "mock" ? "MOCK" : "OFFICIAL"}`}
        title={pub.name}
        description={mySeat ? `You are ${mySeat.name} (${view.me.role}).` : `You are an ${view.me.role}.`}
        actions={
          <Button variant="ghost" as={Link} href="/auction">
            All rooms
          </Button>
        }
      />
      {pub.room_type === "mock" ? (
        <Banner tone="info" title="Mock room">
          Practice only. Results never touch real rosters, budgets, Sleeper or official price history.
        </Banner>
      ) : null}
      {!pub.pool.is_official_class ? <Banner tone="warning" title="Player pool is a fixture">{pub.pool.label}</Banner> : null}
      {pub.paused ? (
        <Banner tone="warning" title={pub.paused.kind === "outage" ? "Paused after a service interruption" : "Paused by the commissioner"}>
          {pub.paused.reason || "No binding actions until the room resumes."} Clocks are frozen.
        </Banner>
      ) : null}
      {sync !== "live" ? <Banner tone="warning">Connection {sync}. Nothing you see is stale-accepted: bids only count once the server confirms them.</Banner> : null}
      <StatusStrip view={view} sync={sync} now={now} />
      <div className={styles.grid}>
        <div className={styles.col}>
          <OpenAuctions view={view} players={players} roomId={roomId} now={now} onAccepted={onAccepted} />
          {view.me.seat && pub.status === "running" ? <Nominate view={view} players={players} roomId={roomId} onAccepted={onAccepted} /> : null}
          <Results view={view} players={players} />
          <Activity view={view} players={players} />
        </div>
        <div className={styles.col}>
          <MyMoney view={view} />
          {view.me.seat && players && pub.status !== "setup" && pub.status !== "complete" ? (
            <Suspense fallback={null}>
              <AuctionAdvicePanel view={view} pool={players} roomId={roomId} />
            </Suspense>
          ) : null}
          <Inbox roomId={roomId} revision={view.revision} />
          {view.me.seat && pub.status !== "setup" ? <Trades view={view} players={players} roomId={roomId} /> : null}
          <Budgets view={view} />
          {view.me.role === "commissioner" ? <Commissioner view={view} roomId={roomId} onAccepted={onAccepted} /> : null}
          <Rules view={view} />
          <ReportProblem view={view} players={players} roomId={roomId} />
        </div>
      </div>
    </section>
  );
}
