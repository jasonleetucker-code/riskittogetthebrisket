"use client";

/**
 * AutoSlates — the primary way a slate reaches /dfs (DFS-AUTO): nothing to
 * download or upload.  Lists the automatically populated slates for the
 * selected sport + platform with their freshness, opens Main (or the next
 * slate to lock) by default, and says plainly what an automatic slate cannot
 * do yet (upload files: no permitted source publishes platform player IDs).
 *
 * Display only: slates, freshness and every number come from /api/dfs/auto/*.
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { Banner, Button, StatusIndicator } from "@/components/ds";
import { PLATFORMS, errorMessage, formatAge, formatLockEt, freshnessCopy, pickDefaultAutoSlate } from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

async function api(path, init) {
  const res = await fetch(`/api/dfs${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

const POLL_MS = 15000;
const MAX_POLLS = 8;

export default function AutoSlates({ sport, platform, selectedHash, onSelected, onAvailability }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [busyId, setBusyId] = useState(null);
  const autoOpened = useRef(false);
  const polls = useRef(0);
  const hasSelection = useRef(Boolean(selectedHash));
  hasSelection.current = Boolean(selectedHash);

  const select = useCallback(
    async (autoSlateId) => {
      setBusyId(autoSlateId);
      setError(null);
      const r = await api("/auto/slates/select", { method: "POST", body: JSON.stringify({ autoSlateId }) });
      setBusyId(null);
      if (!r.ok) {
        setError(errorMessage(r.body, "That slate could not be opened."));
        return;
      }
      onSelected(r.body);
    },
    [onSelected],
  );

  useEffect(() => {
    let live = true;
    let timer = null;
    autoOpened.current = false;
    polls.current = 0;
    setData(null);
    setError(null);
    const load = async () => {
      const q = new URLSearchParams({ sport, platform });
      const r = await api(`/auto/slates?${q}`);
      if (!live) return;
      if (!r.ok) {
        setError(errorMessage(r.body, "Automatic slates are unavailable."));
        onAvailability?.(false);
        return;
      }
      setData(r.body);
      const first = pickDefaultAutoSlate(r.body.slates, platform);
      // "Unavailable" only when nothing is coming: a queued refresh is not a dead end.
      onAvailability?.(Boolean(first) || Boolean(r.body.refreshQueued && !r.body.slates?.length));
      if (first && !autoOpened.current && !hasSelection.current) {
        autoOpened.current = true;
        select(first.autoSlateId);
      }
      // Nothing built yet but a refresh is running: look again shortly.
      if (!r.body.slates?.length && r.body.refreshQueued && polls.current < MAX_POLLS) {
        polls.current += 1;
        timer = setTimeout(load, POLL_MS);
      }
    };
    load();
    return () => {
      live = false;
      if (timer) clearTimeout(timer);
    };
  }, [sport, platform, select]);

  const platformLabel = PLATFORMS.find((p) => p.value === platform)?.label || platform;
  if (error) {
    return (
      <Banner tone="warning" title="Automatic slates unavailable">
        {error} The platform&apos;s salary file still works under Advanced.
      </Banner>
    );
  }
  if (!data) {
    return (
      <p className={styles.note} aria-live="polite">
        Loading automatic slates…
      </p>
    );
  }
  const slates = (data.slates || []).filter((s) => s.platform === platform);
  if (!slates.length) {
    const waiting = `Fetching ${platformLabel} slates now — this takes under a minute.`;
    return (
      <p className={styles.note} role="status">
        {data.reason || (data.refreshQueued ? waiting : `No automatic ${platformLabel} slates right now.`)}
      </p>
    );
  }
  return (
    <div>
      <ul className={styles.autoList} aria-label={`${platformLabel} slates`}>
        {slates.map((s) => {
          const f = freshnessCopy(s.freshness?.state);
          const active = Boolean(selectedHash) && selectedHash === s.contentHash;
          const degraded = s.freshness?.degraded?.length ? ` · ${s.freshness.degraded.join(", ")}` : "";
          return (
            <li key={s.autoSlateId} className={active ? styles.autoActive : undefined}>
              <div className={styles.autoHead}>
                <strong>{s.label}</strong>
                <StatusIndicator status={f.status}>{f.label}</StatusIndicator>
                {s.freshness?.locked ? <StatusIndicator status="neutral">Locked</StatusIndicator> : null}
              </div>
              <span className={styles.meta}>
                Locks {formatLockEt(s.lockAt)} · {s.summary?.games} games · {s.summary?.players} players ·{" "}
                {s.summary?.projected} projected · checked {formatAge(s.freshness?.ageMinutes)}
                {degraded}
              </span>
              <div>
                <Button
                  size="sm"
                  className={styles.wrapBtn}
                  variant={active ? "primary" : "secondary"}
                  onClick={() => select(s.autoSlateId)}
                  loading={busyId === s.autoSlateId}
                  disabled={Boolean(busyId) || Boolean(s.freshness?.locked) || active}
                >
                  {active ? "In use" : "Use this slate"}
                </Button>
              </div>
            </li>
          );
        })}
      </ul>
      <p className={styles.note} role="note">
        {data.derivationNote} Salaries, status and projections refresh automatically. Upload files need the
        platform&apos;s own player IDs, which no permitted free source publishes — load the platform file under Advanced
        for an upload-ready slate.
      </p>
    </div>
  );
}
