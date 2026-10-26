"use client";

/**
 * Trade Desk (Part 12) — the user's private list of trade ideas.
 *
 * Statuses are what the user marked; the app cannot see whether a trade was
 * sent, accepted or rejected, so it never sets one. The only thing it observes
 * is the roster check (are the players still where the package needs them?),
 * shown beside the status, never instead of it. Recommendation only: nothing
 * here sends or proposes a trade.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import {
  Badge,
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  Select,
  SkeletonTable,
} from "@/components/ds";
import { buildShareUrl } from "@/lib/trade-share";
import {
  DESK_STATUSES,
  deskErrorText,
  lastMarked,
  loadDesk,
  removeDeskItem,
  deskDecisionText,
  rosterCheckText,
  statusLabel,
  updateDeskItem,
} from "@/lib/trade-desk";
import styles from "./trade-desk.module.css";

const SOURCE_LABELS = {
  best_offers: "Best offer by opponent",
  package_builder: "Package Builder",
  golden_upgrades: "Golden Upgrades",
  suggestions: "Suggestions",
  arbitrage_scan: "Package scan",
  calculator: "Trade Calculator",
  manual: "Added by you",
};

function calcUrl(item) {
  const asName = (a) => a.boardRowName || a.name;
  try {
    return buildShareUrl({
      sides: [
        { name: item.myTeam, players: item.send.map(asName) },
        { name: item.opponent, players: item.receive.map(asName) },
      ],
    });
  } catch {
    return null;
  }
}

function fmtDate(iso) {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "an unknown date"
    : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function DeskItem({ item, onChange, busy }) {
  const [note, setNote] = useState(item.note || "");
  useEffect(() => setNote(item.note || ""), [item.note]);
  const marked = lastMarked(item);
  const url = useMemo(() => calcUrl(item), [item]);
  const check = item.rosterCheck;
  return (
    <li className={styles.row}>
      <header className={styles.head}>
        <strong>
          {item.myTeam} → {item.opponent}
        </strong>
        <span className={styles.muted}>
          {SOURCE_LABELS[item.source] || "Saved"}
        </span>
      </header>
      <div className={styles.pair}>
        <div>
          <h4 className={styles.label}>You send</h4>
          <ul className={styles.assets}>
            {item.send.map((a) => (
              <li key={`s-${a.assetId || a.name}`}>{a.name}</li>
            ))}
          </ul>
        </div>
        <div>
          <h4 className={styles.label}>You receive</h4>
          <ul className={styles.assets}>
            {item.receive.map((a) => (
              <li key={`r-${a.assetId || a.name}`}>{a.name}</li>
            ))}
          </ul>
        </div>
      </div>
      <p className={check?.state === "changed" ? styles.caution : styles.muted}>
        {rosterCheckText(check)}
      </p>
      {deskDecisionText(item, fmtDate) ? (
        <p className={styles.muted} data-testid="desk-item-decision">
          {deskDecisionText(item, fmtDate)}
        </p>
      ) : null}
      <div className={styles.controls}>
        <Field label="Status">
          <Select
            value={item.status}
            disabled={busy}
            onChange={(e) =>
              onChange("update", item.id, { status: e.target.value })
            }
          >
            {DESK_STATUSES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Note">
          <Input
            value={note}
            maxLength={500}
            disabled={busy}
            onChange={(e) => setNote(e.target.value)}
            onBlur={() => {
              // The server trims, so compare trimmed: a trailing space is not
              // an edit and must not PATCH on every blur.
              if (note.trim() !== (item.note || ""))
                onChange("update", item.id, { note });
            }}
          />
        </Field>
      </div>
      <footer className={styles.foot}>
        <span className={styles.muted}>
          {marked
            ? `You marked ${statusLabel(marked.status)} on ${fmtDate(marked.at)}`
            : null}
        </span>
        <span className={styles.actions}>
          {url ? (
            <Button as={Link} href={url} size="sm" variant="secondary">
              Open in Trade Calculator
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => onChange("remove", item.id)}
          >
            Remove
          </Button>
        </span>
      </footer>
    </li>
  );
}

export default function TradeDeskView({ leagueKey }) {
  const [desk, setDesk] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("all");
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!leagueKey) return undefined;
    let live = true;
    setDesk(null);
    setError("");
    loadDesk(leagueKey).then((res) => {
      if (!live) return;
      if (res.ok) setDesk(res.desk);
      else setError(deskErrorText(res.code));
    });
    return () => {
      live = false;
    };
  }, [leagueKey]);

  const change = useCallback(
    async (kind, id, patch) => {
      const seq = ++requestSeq.current;
      setBusy(true);
      setError("");
      const res =
        kind === "remove"
          ? await removeDeskItem(leagueKey, id)
          : await updateDeskItem(leagueKey, id, patch);
      // Only the newest request may paint: an older response landing late
      // must not show a desk from before the user's latest change.
      if (seq !== requestSeq.current) return;
      if (res.ok) setDesk(res.desk);
      else setError(deskErrorText(res.code));
      setBusy(false);
    },
    [leagueKey],
  );

  const items = useMemo(() => {
    const all = Array.isArray(desk?.items) ? desk.items : [];
    return filter === "all" ? all : all.filter((i) => i.status === filter);
  }, [desk, filter]);

  if (!leagueKey) {
    return (
      <EmptyState
        title="Choose a league"
        description="The Trade Desk is kept per league."
      />
    );
  }
  return (
    <section className={`${styles.view} psi-editorial`} aria-label="Trade Desk">
      <p className={styles.muted}>
        Your private list of trade ideas. Save packages from the views above and
        mark where each one stands. The app cannot see whether a trade was sent,
        accepted or rejected, so statuses are only what you mark. Nothing here
        sends a trade.
      </p>
      {error ? <Banner tone="negative">{error}</Banner> : null}
      {desk === null && !error ? <SkeletonTable rows={3} /> : null}
      {desk ? (
        <>
          <div className={styles.controls}>
            <Field label="Show">
              <Select
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
              >
                <option value="all">All ({desk.count})</option>
                {DESK_STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Badge tone="outline">
              {desk.count} of {desk.limit}
            </Badge>
          </div>
          {items.length ? (
            <ol className={styles.list}>
              {items.map((item) => (
                <DeskItem
                  key={item.id}
                  item={item}
                  onChange={change}
                  busy={busy}
                />
              ))}
            </ol>
          ) : (
            <EmptyState
              title={
                desk.count
                  ? "Nothing with this status"
                  : "Your Trade Desk is empty"
              }
              description={
                desk.count
                  ? "Choose another status to see your other ideas."
                  : "Use Save to Trade Desk on any offer, package or upgrade."
              }
            />
          )}
        </>
      ) : null}
    </section>
  );
}
