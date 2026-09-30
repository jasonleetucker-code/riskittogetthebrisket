"use client";

/**
 * SourcePulls — owner-triggered pulls from connected sources into the slate's
 * point-in-time record (today: Daily Fantasy Fuel projections + game context).
 * Manual and cached on the server; nothing is scheduled.  Lazily loaded.
 */

import React, { useState } from "react";
import { Banner, Button } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

const SUPPORTED = new Set(["nfl", "nba", "nhl"]);

export default function SourcePulls({ snapshotId, sport }) {
  const [busy, setBusy] = useState(false);
  const [out, setOut] = useState(null);
  const [error, setError] = useState(null);
  if (!SUPPORTED.has(sport)) return null;

  const pull = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/dfs/sources/dailyfantasyfuel/pull", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ snapshotId }),
      });
      const body = await errorBody(res);
      if (!res.ok) setError(errorMessage(body, "The source could not be pulled."));
      else setOut(body);
    } catch {
      setError("The source could not be pulled.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={styles.providerBox}>
      <Button variant="ghost" onClick={pull} loading={busy}>
        Pull Daily Fantasy Fuel projections + game lines
      </Button>
      {out ? (
        <p className={styles.note} role="status">
          Matched {out.matched} of {out.slateAthletes} players ({out.rows} source rows
          {out.quarantined?.length ? `, ${out.quarantined.length} set aside as ambiguous or salary-mismatched` : ""}),{" "}
          recorded at {new Date(out.fetchedAt).toLocaleString()}
          {out.fromCache ? " (cached copy)" : ""}. Stored as a separate source; your own projections are unchanged.
        </p>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Source pull">
          {error}
        </Banner>
      ) : null}
    </div>
  );
}
