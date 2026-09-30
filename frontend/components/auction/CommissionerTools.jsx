"use client";

/**
 * Commissioner readiness tools for the auction room (milestones D/E).
 *
 * Preflight (reports, decides nothing), the consolidated rule-confirmation
 * screen, pre-start timing, the points-for order preview, and member
 * recovery (reset link, replace a lost account).  Nothing here can reveal a
 * maximum bid or act for a manager.
 */
import { useCallback, useEffect, useState } from "react";
import { Badge, Banner, Button, Field, Input } from "@/components/ds";
import { auctionFetch, formatActiveSeconds } from "@/lib/auction-client";
import styles from "@/app/auction/auction.module.css";

const TONE = { ok: "positive", warn: "warning", fail: "negative" };

export function Preflight({ roomId, revision }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  const load = useCallback(() => {
    auctionFetch(`/rooms/${encodeURIComponent(roomId)}/preflight`)
      .then((d) => (setData(d), setErr(null)))
      .catch((e) => setErr(e.message));
  }, [roomId]);
  useEffect(() => {
    load();
  }, [load, revision]);
  return (
    <div className={styles.col}>
      <h3 className={styles.player}>
        Preflight {data ? <Badge tone={TONE[data.status]}>{data.status}</Badge> : null}
      </h3>
      {err ? <Banner tone="warning">{err}</Banner> : null}
      <ul className={styles.rules}>
        {(data?.items || []).map((i) => (
          <li key={i.key}>
            <Badge tone={TONE[i.status]}>{i.status}</Badge> {i.text}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function RulesConfirmation({ view, run, meta }) {
  const pub = view.public;
  const setup = pub.status === "setup";
  const proposed = meta?.proposedRules || {};
  const binding = meta?.bindingRules || {};
  const unconfirmed = new Set(pub.unconfirmed_rules || []);
  const [picked, setPicked] = useState(() => new Set());
  const [timing, setTiming] = useState({
    auction: String((pub.rules.auction_active_seconds || 0) / 3600),
    extension: String((pub.rules.extension_active_seconds || 0) / 3600),
    timeout: String((pub.rules.nomination_timeout_active_seconds || 0) / 3600),
  });
  const toggle = (k) =>
    setPicked((s) => {
      const n = new Set(s);
      n.has(k) ? n.delete(k) : n.add(k);
      return n;
    });
  const saveTiming = () => {
    const hrs = (v) => Math.round(Number(v) * 3600);
    run("configure", {
      kind: "configure",
      rules: {
        auction_active_seconds: hrs(timing.auction),
        extension_active_seconds: hrs(timing.extension),
        nomination_timeout_active_seconds: hrs(timing.timeout),
      },
    });
  };
  return (
    <div className={styles.col}>
      <h3 className={styles.player}>Rules</h3>
      <p className={styles.muted}>Owner rules (binding):</p>
      <ul className={styles.rules}>
        {Object.entries(binding).map(([k, v]) => (
          <li key={k}>{v}</li>
        ))}
      </ul>
      <p className={styles.muted}>
        Proposed rules — fine for mocks; an official room cannot start until each is confirmed. Changing timing voids earlier confirmations.
      </p>
      <ul className={styles.rules}>
        {Object.entries(proposed).map(([k, v]) => (
          <li key={k}>
            <label className={styles.row}>
              {setup && unconfirmed.has(k) ? <input type="checkbox" checked={picked.has(k)} onChange={() => toggle(k)} /> : null}
              {unconfirmed.has(k) ? null : <Badge tone="positive">confirmed</Badge>} {v}
            </label>
          </li>
        ))}
      </ul>
      {setup ? (
        <>
          <div>
            <Button size="sm" disabled={!picked.size} onClick={() => run("confirm", { kind: "confirm_rules", keys: [...picked] }).then(() => setPicked(new Set()))}>
              Confirm {picked.size || ""} selected rule{picked.size === 1 ? "" : "s"}
            </Button>
          </div>
          <div className={styles.formGrid}>
            <Field label="Lot clock (active hours)" hint={`Now ${formatActiveSeconds(pub.rules.auction_active_seconds)}`}>
              <Input inputMode="decimal" data-numeric value={timing.auction} onChange={(e) => setTiming((t) => ({ ...t, auction: e.target.value }))} />
            </Field>
            <Field label="Late-bid extension (active hours)">
              <Input inputMode="decimal" data-numeric value={timing.extension} onChange={(e) => setTiming((t) => ({ ...t, extension: e.target.value }))} />
            </Field>
            <Field label="Nomination turn (active hours)">
              <Input inputMode="decimal" data-numeric value={timing.timeout} onChange={(e) => setTiming((t) => ({ ...t, timeout: e.target.value }))} />
            </Field>
          </div>
          <div>
            <Button size="sm" onClick={saveTiming}>
              Save timing
            </Button>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function PointsForOrder({ view, roomId, run }) {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(null);
  if (view.public.status !== "setup") return null;
  const load = () =>
    auctionFetch(`/rooms/${encodeURIComponent(roomId)}/points-for-preview`)
      .then((d) => (setData(d), setErr(null)))
      .catch((e) => setErr(e.message));
  return (
    <div className={styles.col}>
      <h3 className={styles.player}>Nomination order by points-for</h3>
      <p className={styles.muted}>Lowest points-for nominates first. You supply or confirm the official order; this only previews Sleeper's numbers.</p>
      <div>
        <Button size="sm" onClick={load}>
          Preview from Sleeper
        </Button>
      </div>
      {err ? <Banner tone="warning">{err}</Banner> : null}
      {data ? (
        <>
          <Banner tone={data.final ? "info" : "warning"} title={`Season ${data.season} — ${data.final ? "final" : "not final"}`}>
            {data.note}
            {data.ties?.length ? ` Tied rosters are flagged — decide their order yourself.` : ""}
          </Banner>
          <ol className={styles.rules}>
            {data.seatOrder.map((sid, i) => (
              <li key={sid}>
                {data.seatNames[sid]} — {data.order[i]?.points_for?.toFixed(2)} PF
              </li>
            ))}
          </ol>
          <div>
            <Button
              size="sm"
              disabled={!data.complete}
              onClick={() =>
                run("order", {
                  kind: "set_order",
                  order: data.seatOrder,
                  basis: `points-for ${data.season}${data.final ? " (final)" : " (preview, not final)"}`,
                })
              }
            >
              Apply this order
            </Button>
          </div>
        </>
      ) : null}
    </div>
  );
}

export function Members({ view, roomId }) {
  const members = view.commissioner?.members || [];
  const me = view.me.user?.id;
  const [link, setLink] = useState(null);
  const [reason, setReason] = useState("");
  const [msg, setMsg] = useState(null);
  const act = async (fn) => {
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg(e.message);
    }
  };
  return (
    <div className={styles.col}>
      <h3 className={styles.player}>Members</h3>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Handle</th>
              <th scope="col">Seat</th>
              <th scope="col">Recovery</th>
            </tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id}>
                <td>
                  {m.handle}
                  <span className={styles.sub}>{m.role}</span>
                </td>
                <td>{m.seat_id || "—"}</td>
                <td>
                  {m.user_id !== me ? (
                    <div className={styles.row}>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() =>
                          act(async () => {
                            const out = await auctionFetch(`/rooms/${roomId}/members/${m.user_id}/reset-link`, { method: "POST", body: {} });
                            setLink(`${window.location.origin}${out.resetPath}`);
                          })
                        }
                      >
                        Reset link
                      </Button>
                      <Button
                        size="sm"
                        variant="danger"
                        disabled={!reason.trim() || m.role === "commissioner"}
                        onClick={() =>
                          act(() => auctionFetch(`/rooms/${roomId}/members/${m.user_id}/remove`, { method: "POST", body: { reason } }))
                        }
                      >
                        Replace person
                      </Button>
                    </div>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Field label="Reason for replacing a person (recorded)" hint="The seat keeps its money, bids and players. Invite the new person to the same seat afterwards.">
        <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} />
      </Field>
      {link ? (
        <div>
          <p className={styles.muted}>One-time reset link, valid 24 hours. Send it privately. The member is told a link was issued.</p>
          <p className={styles.secret}>{link}</p>
        </div>
      ) : null}
      {msg ? <Banner tone="negative">{msg}</Banner> : null}
    </div>
  );
}
