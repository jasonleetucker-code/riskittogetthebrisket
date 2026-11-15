"use client";

/**
 * EntriesExport — fill a build's lineups into the owner's EXISTING platform
 * entries (the entry file downloaded from the platform).  Nothing is
 * submitted: the owner uploads the returned file themselves.  The layout is
 * unverified, entries the server cannot resolve are left untouched, and the
 * counts say so.  Lazily loaded from /dfs.
 */

import React, { useState } from "react";
import { Banner, Button, Field } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody, saveResponseAsFile } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

export default function EntriesExport({ buildId }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [done, setDone] = useState(null);

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setError(null);
    setDone(null);
    try {
      const entriesCsv = await f.text();
      const res = await fetch(`/api/dfs/builds/${buildId}/export-entries`, {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entriesCsv }),
      });
      if (!res.ok) {
        setError(errorMessage(await errorBody(res), "The entry file could not be filled."));
        return;
      }
      const assigned = Number(res.headers.get("x-dfs-entries-assigned") || 0);
      const untouched = Number(res.headers.get("x-dfs-entries-untouched") || 0);
      await saveResponseAsFile(res, "entries.csv");
      setDone({ assigned, untouched });
    } catch {
      setError("The entry file could not be read.");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  return (
    <div className={styles.providerBox}>
      <Field
        label="Fill my existing entries (platform entry file)"
        hint="Choose the entry CSV the platform lets you download. Lineups go into those entry IDs in order; you upload the result yourself."
      >
        <input type="file" accept=".csv,text/csv" onChange={onFile} disabled={busy} />
      </Field>
      {busy ? <p className={styles.note} role="status">Filling entries…</p> : null}
      {done ? (
        <p className={styles.note} role="status">
          Filled {done.assigned} entr{done.assigned === 1 ? "y" : "ies"}.
          {done.untouched ? ` ${done.untouched} left untouched (unreadable lineups or more entries than lineups).` : ""} The
          entry-file layout is not yet verified against an official template — check it before uploading.
        </p>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Entries not filled">
          {error}
        </Banner>
      ) : null}
    </div>
  );
}
