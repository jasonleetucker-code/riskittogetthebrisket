"use client";

/**
 * LateSwap — plan swaps for entries already made on the platform.  Slots whose
 * game has started (or whose start time is unknown) are kept exactly; only
 * players whose game has not started can come in.  The server plans; this
 * renders.  Nothing is submitted — the owner downloads an entry file and
 * uploads it themselves.  Lazily loaded from /dfs.
 */

import React, { useState } from "react";
import { Banner, Button, DataTable, Field, Input, StatusIndicator } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody, saveResponseAsFile } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

const STATUS = {
  swap_recommended: ["info", "Swap recommended"],
  keep: ["neutral", "Keep"],
  all_locked: ["neutral", "All slots locked"],
  no_legal_swap: ["warning", "No legal swap"],
  entry_unresolved: ["negative", "Entry unreadable — untouched"],
};

async function post(path, body) {
  return fetch(`/api/dfs${path}`, {
    method: "POST",
    credentials: "same-origin",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export default function LateSwap({ snapshotId, athletes }) {
  const [entriesCsv, setEntriesCsv] = useState("");
  const [asOf, setAsOf] = useState("");
  const [plan, setPlan] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const names = new Map((athletes || []).map((a) => [a.player_id, a.name]));
  const name = (pid) => (pid ? names.get(pid) || pid : "empty");

  const body = () => {
    const b = { snapshotId, entriesCsv };
    // Blank = the server's clock. A chosen time is a labelled what-if.
    if (asOf) b.asOf = new Date(asOf).toISOString();
    return b;
  };

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      setEntriesCsv(await f.text());
      setPlan(null);
    } catch {
      setError("The entry file could not be read.");
    }
  };

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await post("/late-swap", body());
      const json = await errorBody(res);
      if (!res.ok) setError(errorMessage(json, "Late swap could not be planned."));
      else setPlan(json);
    } catch {
      setError("Late swap could not be planned.");
    } finally {
      setBusy(false);
    }
  };

  const download = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await post("/late-swap/export", body());
      if (!res.ok) setError(errorMessage(await errorBody(res), "The entry file could not be written."));
      else await saveResponseAsFile(res, "late-swap.csv");
    } catch {
      setError("The entry file could not be written.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <fieldset className={styles.objective}>
      <legend>Late swap</legend>
      <p className={styles.note}>
        Slots whose game has started — or whose start time is unknown — are kept exactly. Only players whose game has not
        started can come in. Each entry is planned on its own. Nothing is submitted.
      </p>
      <div className={styles.controlGrid}>
        <Field label="Entry file (from the platform)">
          <input type="file" accept=".csv,text/csv" onChange={onFile} disabled={busy} />
        </Field>
        <Field label="Plan as of (optional)" hint="Blank = now. A chosen time is a what-if.">
          <Input type="datetime-local" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
        </Field>
      </div>
      <div className={styles.actions}>
        <Button variant="secondary" onClick={run} loading={busy} disabled={!entriesCsv}>
          Plan late swap
        </Button>
        {plan?.counts?.swap_recommended || plan?.counts?.keep || plan?.counts?.all_locked ? (
          <Button variant="ghost" onClick={download} disabled={busy}>
            Download updated entry file
          </Button>
        ) : null}
      </div>
      {plan ? (
        <>
          <p className={styles.note} role="status">
            As of {new Date(plan.asOf).toLocaleString()} ({plan.clockSource === "server" ? "now" : "your chosen time"}):{" "}
            {plan.playersByLockState.locked} players locked, {plan.playersByLockState.open} open,{" "}
            {plan.playersByLockState.unknown} with an unknown start (treated as locked). {plan.methodNote}
          </p>
          <DataTable
            caption="Late-swap plan by entry"
            columns={[
              { key: "entryId", header: "Entry" },
              {
                key: "status",
                header: "Status",
                render: (p) => {
                  const [tone, label] = STATUS[p.status] || ["neutral", p.status];
                  return <StatusIndicator status={tone}>{label}</StatusIndicator>;
                },
              },
              {
                key: "changes",
                header: "Changes",
                sortable: false,
                render: (p) =>
                  p.changes?.length ? (
                    <ul className={styles.list}>
                      {p.changes.map((c) => (
                        <li key={`${c.slot}-${c.in}`}>
                          {c.slot}: {name(c.out)} → {name(c.in)}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <span className={styles.missing}>{p.reason || "—"}</span>
                  ),
              },
              {
                key: "openSlotGain",
                header: "Gain",
                numeric: true,
                render: (p) => (p.openSlotGain == null ? "—" : `${p.openSlotGain > 0 ? "+" : ""}${p.openSlotGain.toFixed(2)}`),
              },
            ]}
            rows={plan.entries}
            rowKey={(p) => p.entryId}
            density="compact"
          />
          <p className={styles.note}>
            The entry-file layout is not yet verified against an official template — check it before uploading.
          </p>
        </>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Late swap">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
