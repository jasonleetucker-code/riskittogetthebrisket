"use client";

/**
 * ResultsImport — after a slate: import the platform's contest-standings file
 * and see how the forecasts you imported for this slate held up (projected
 * ownership vs realized %Drafted, projection vs actual points) plus how often
 * identical lineups recurred in the field.  Evaluation only — it changes no
 * weight or model.  The server computes; this renders.  Lazily loaded.
 */

import React, { useState } from "react";
import { Banner, DataTable, Field, Input } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import { errorBody } from "@/lib/dfs-download";
import styles from "./dfs-workspace.module.css";

function Stat({ label, s, unit }) {
  if (!s) return <li>{label}: not available (nothing to compare).</li>;
  const sign = s.bias > 0 ? "+" : "";
  return (
    <li>
      {label}: {s.n} players · average miss {s.mae}
      {unit} · bias {sign}
      {s.bias}
      {unit} ({s.bias > 0 ? "forecast too high" : s.bias < 0 ? "forecast too low" : "no lean"})
    </li>
  );
}

function money(cents) {
  if (cents == null) return "unknown";
  const sign = cents < 0 ? "-" : "";
  return `${sign}$${(Math.abs(cents) / 100).toFixed(2)}`;
}

function Settlement({ s }) {
  if (!s) return null;
  if (s.state === "no_owner_entries") return <p className={styles.note}>None of your entries were found in the file.</p>;
  if (s.state === "unavailable") return <p className={styles.note}>Winnings could not be settled: {s.reason}</p>;
  return (
    <>
      <p className={styles.note}>
        {s.contestName}: {s.entries} entr{s.entries === 1 ? "y" : "ies"}, fees {money(s.feesCents)}, winnings{" "}
        {s.state === "complete" ? money(s.knownWinningsCents) : `at least ${money(s.knownWinningsCents)} (${s.entriesWithUnknownPayout} unknown)`}
        , net {money(s.netCents)}
        {s.roi != null ? ` (ROI ${Math.round(s.roi * 100)}%)` : ""}.
        {s.fieldSizeCheck === "disagrees" ? ` The file has ${s.fieldSize} entries but the contest declares ${s.declaredFieldSize} — ranks may be off.` : ""}
        {s.rankDisagreements ? ` ${s.rankDisagreements} rank(s) differ from the file's own Rank column.` : ""}
      </p>
      <DataTable
        caption="Your entries"
        columns={[
          { key: "entryName", header: "Entry" },
          { key: "points", header: "Points", numeric: true },
          { key: "rank", header: "Rank", numeric: true, render: (r) => (r.rank == null ? "—" : r.tiedWith ? `${r.rank} (tied)` : r.rank) },
          {
            key: "payout",
            header: "Won",
            numeric: true,
            render: (r) =>
              r.payout.state === "exact" ? money(r.payout.eachCents) : r.payout.state === "noncash" ? "ticket / non-cash" : "unknown",
          },
        ]}
        rows={s.rows}
        rowKey={(r) => r.entryId}
        density="compact"
      />
    </>
  );
}

export default function ResultsImport({ snapshotId, contestId }) {
  const [username, setUsername] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const onFile = async (e) => {
    const f = e.target.files?.[0];
    if (!f) return;
    setBusy(true);
    setError(null);
    try {
      const standingsCsv = await f.text();
      const res = await fetch("/api/dfs/results", {
        method: "POST",
        credentials: "same-origin",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          snapshotId,
          standingsCsv,
          ...(contestId ? { contestId } : {}),
          ...(username.trim() ? { ownerUsername: username.trim() } : {}),
        }),
      });
      const body = await errorBody(res);
      if (!res.ok) setError(errorMessage(body, "The results file could not be imported."));
      else setResult(body);
    } catch {
      setError("The results file could not be read.");
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  };

  const ev = result?.evaluation;
  const dup = result?.duplication;
  return (
    <fieldset className={styles.objective}>
      <legend>After the slate: results</legend>
      <Field label="Your platform username (optional)" hint={contestId ? "Settles your entries against the selected contest's payouts." : "Select a contest above to settle winnings."}>
        <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" />
      </Field>
      <Field
        label="Contest standings file (from the platform)"
        hint="Checks how your imported ownership and projections held up. Changes nothing."
      >
        <input type="file" accept=".csv,text/csv" onChange={onFile} disabled={busy} />
      </Field>
      {busy ? (
        <p className={styles.note} role="status">
          Reading results…
        </p>
      ) : null}
      {ev ? (
        <>
          <Settlement s={result.settlement} />
          <ul className={styles.list}>
            <Stat label="Projected ownership" s={ev.ownership} unit=" pts" />
            <Stat label="Projections" s={ev.projection} unit=" fpts" />
          </ul>
          {ev.ownershipBands?.length ? (
            <DataTable
              caption="Projected vs realized ownership by band"
              columns={[
                { key: "band", header: "Projected band" },
                { key: "n", header: "Players", numeric: true },
                { key: "meanForecast", header: "Avg projected %", numeric: true },
                { key: "meanRealized", header: "Avg realized %", numeric: true },
              ]}
              rows={ev.ownershipBands}
              rowKey={(b) => b.band}
              density="compact"
            />
          ) : null}
          <p className={styles.note}>
            {ev.notInResults
              ? `${ev.notInResults} player(s) you forecast are not in the results file and were left out, not counted as 0%. `
              : ""}
            {result.quarantined?.length ? `${result.quarantined.length} results row(s) could not be matched to one player and were set aside. ` : ""}
            {ev.note}
          </p>
          {dup ? (
            <p className={styles.note}>
              Field duplication: {dup.lineupsCompared} readable lineups, {dup.distinctLineups} distinct;{" "}
              {dup.entriesInDuplicatedLineups} entries shared a lineup with someone else (most copies of one lineup:{" "}
              {dup.maxCopies}). {result.field.unresolvedLineups ? `${result.field.unresolvedLineups} lineup(s) could not be read and are not counted.` : ""}
            </p>
          ) : null}
          <p className={styles.note}>The results-file layout is not yet verified against an official template.</p>
        </>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Results not imported">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
