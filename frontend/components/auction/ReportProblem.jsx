"use client";

/**
 * "Report a problem" for rehearsals.  The server pins every report to the
 * room's committed revision, rules version, pool version and deployed code
 * SHA (src/auction/feedback.py), so a rehearsal defect can be replayed from
 * the command log.  Reporters see their own reports; the commissioner sees
 * every report in the room.  Filing a report never changes the room.
 */
import { useEffect, useState } from "react";
import { Button, Field, Input, Panel, Select } from "@/components/ds";
import { auctionFetch, formatRoomTime } from "@/lib/auction-client";
import styles from "@/app/auction/auction.module.css";

function newKey() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `r${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}

export default function ReportProblem({ view, players, roomId }) {
  const [open, setOpen] = useState(false);
  const [what, setWhat] = useState("");
  const [expected, setExpected] = useState("");
  const [when, setWhen] = useState("");
  const [lot, setLot] = useState("");
  const [msg, setMsg] = useState(null);
  const [pending, setPending] = useState(false);
  const [reports, setReports] = useState(null);
  const isCommish = view.me.role === "commissioner";
  const path = `/rooms/${encodeURIComponent(roomId)}/reports`;

  const load = () =>
    auctionFetch(path)
      .then((d) => setReports(d.reports))
      .catch(() => setReports(null));

  useEffect(() => {
    if (open) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, roomId]);

  const lots = view.public.auctions || [];
  const nameOf = (a) => players?.[a.player]?.name || a.player;

  const submit = async () => {
    if (!what.trim()) {
      setMsg({ tone: "negative", text: "Say what happened." });
      return;
    }
    setPending(true);
    setMsg(null);
    const chosen = lots.find((a) => a.id === lot);
    try {
      const rep = await auctionFetch(path, {
        method: "POST",
        headers: { "Idempotency-Key": newKey() },
        body: {
          what_happened: what,
          expected: expected || undefined,
          observed_when: when || undefined,
          auction: lot || undefined,
          player_label: chosen ? nameOf(chosen) : undefined,
          client_revision: view.revision,
        },
      });
      setMsg({ tone: "positive", text: `Report #${rep.id} saved at room revision ${rep.revision}. Thank you.` });
      setWhat("");
      setExpected("");
      setWhen("");
      setLot("");
      load();
    } catch (err) {
      setMsg({ tone: "negative", text: err?.body?.message || "Could not save the report — try again." });
    } finally {
      setPending(false);
    }
  };

  return (
    <Panel
      title="Report a problem"
      subtitle="Something wrong or confusing? It is saved with this room's exact state so it can be replayed."
      dense
      actions={
        <Button size="sm" variant="ghost" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
          {open ? "Close" : "Report"}
        </Button>
      }
    >
      {open ? (
        <div className={styles.col}>
          <Field label="What happened?">
            <Input value={what} maxLength={2000} onChange={(e) => setWhat(e.target.value)} placeholder="e.g. my $5 bid showed as $6" />
          </Field>
          <Field label="What did you expect?">
            <Input value={expected} maxLength={2000} onChange={(e) => setExpected(e.target.value)} />
          </Field>
          <Field label="Which lot? (optional)">
            <Select value={lot} onChange={(e) => setLot(e.target.value)}>
              <option value="">Not about one lot</option>
              {lots.map((a) => (
                <option key={a.id} value={a.id}>
                  {nameOf(a)} ({a.status})
                </option>
              ))}
            </Select>
          </Field>
          <Field label="About when? (optional)" hint="Your own words are fine — the server records the exact time too.">
            <Input value={when} maxLength={120} onChange={(e) => setWhen(e.target.value)} placeholder="e.g. around 7:40 PM" />
          </Field>
          <div className={styles.row}>
            <Button size="sm" variant="primary" disabled={pending} onClick={submit}>
              {pending ? "Saving…" : "Send report"}
            </Button>
          </div>
          {msg ? <p className={styles.muted} role={msg.tone === "negative" ? "alert" : "status"}>{msg.text}</p> : null}
          {reports && reports.length ? (
            <>
              <p className={styles.muted}>{isCommish ? "All reports in this room" : "Your reports"}</p>
              <ul className={styles.feed}>
                {reports.map((r) => (
                  <li key={r.id}>
                    <time>{formatRoomTime(r.roomNow)}</time>
                    <strong>#{r.id}</strong> rev {r.revision}
                    {r.playerLabel ? ` · ${r.playerLabel}` : ""} — {r.whatHappened}
                    {r.expected ? ` (expected: ${r.expected})` : ""}
                    <span className={styles.sub}> code {String(r.codeSha).slice(0, 9)}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}
