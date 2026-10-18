"use client";

/**
 * Manager Intelligence — Career tab (C6-MGR-02 Batch E).
 *
 * Mounted by ./page.jsx the first time the Career tab opens (and kept
 * mounted after).  Display layer only: every season row, total, coverage
 * state and archetype comes from GET /api/manager-intel/career
 * (`src/intel/manager_career.py`); `lib/manager-intel.js` labels them.
 * A season the manager did not hold is absent (never a loss); an unread
 * bracket reads "Unknown" (never "Missed"); each total states the seasons
 * it covers; archetypes are evidence chips whose rule, threshold (a declared
 * PRIOR) and counts open in a drilldown.  Wide screens get a table; narrow
 * screens the same rows stacked.
 */

import { useEffect, useState } from "react";
import {
  Banner,
  EmptyState,
  Panel,
  SkeletonTable,
  StatTile,
} from "@/components/ds";
import {
  archetypeEvidenceRows,
  archetypeStateLabel,
  archetypeThresholdText,
  careerCoverageProblems,
  careerQuery,
  careerTiles,
  compareHref,
  errorMessage,
  excludedText,
  finishLabel,
  finishReasonText,
  formatBadge,
  heldText,
  recordText,
  shareText,
  suggestedArchetypes,
} from "@/lib/manager-intel";
import styles from "./managers.module.css";

function FinishCell({ row }) {
  const reason = finishReasonText(row.finishReason);
  return (
    <>
      {finishLabel(row)}
      {reason ? <span className={styles.muted}> · {reason}</span> : null}
    </>
  );
}

function SeasonNotes({ row }) {
  const held = heldText(row);
  const excluded = row.countsTowardTotals ? "" : excludedText(row.excludedReason);
  const parts = [held, excluded && `not in totals: ${excluded}`].filter(Boolean);
  return parts.length ? <span className={styles.muted}>{parts.join(" · ")}</span> : null;
}

function SeasonTable({ seasons }) {
  return (
    <>
      <table className={`${styles.miniTable} ${styles.tableOnly}`}>
        <caption className={styles.srOnly}>
          Every season this manager held a roster, newest first.
        </caption>
        <thead>
          <tr>
            <th scope="col">Season</th>
            <th scope="col">League</th>
            <th scope="col">Record</th>
            <th scope="col">Points for</th>
            <th scope="col">PF share</th>
            <th scope="col">Finish</th>
            <th scope="col">Notes</th>
          </tr>
        </thead>
        <tbody>
          {seasons.map((s) => (
            <tr key={`${s.leagueId}:${s.season}`}>
              <td>{s.season || "—"}</td>
              <td className={styles.leagueCell}>
                {s.leagueName || "Unnamed league"}
                <span className={styles.muted}> {formatBadge(s.format)}</span>
              </td>
              <td>{recordText(s.record)}</td>
              <td>{s.record?.pointsFor == null ? "—" : s.record.pointsFor.toFixed(1)}</td>
              <td>{shareText(s.pointsForShare)}</td>
              <td>
                <FinishCell row={s} />
              </td>
              <td>
                <SeasonNotes row={s} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <ul className={styles.scoutStack} aria-label="Seasons">
        {seasons.map((s) => (
          <li key={`${s.leagueId}:${s.season}`}>
            <strong>
              {s.season} · {s.leagueName || "Unnamed league"}
            </strong>
            <dl className={styles.scoutStackFacts}>
              <div>
                <dt>Record</dt>
                <dd>{recordText(s.record)}</dd>
              </div>
              <div>
                <dt>PF share</dt>
                <dd>{shareText(s.pointsForShare)}</dd>
              </div>
              <div>
                <dt>Finish</dt>
                <dd>
                  <FinishCell row={s} />
                </dd>
              </div>
            </dl>
            <SeasonNotes row={s} />
          </li>
        ))}
      </ul>
    </>
  );
}

export function ArchetypeChips({ archetypes, idPrefix = "arch" }) {
  const [open, setOpen] = useState(null);
  if (!archetypes) return null;
  const suggested = suggestedArchetypes(archetypes);
  const item = (archetypes.items || []).find((i) => i.key === open);
  return (
    <div className={styles.archetypes}>
      {suggested.length ? (
        <ul className={styles.archetypeChips} aria-label="Archetypes suggested by evidence">
          {suggested.map((a) => (
            <li key={a.key}>
              <button
                type="button"
                className={styles.chip}
                aria-expanded={open === a.key}
                aria-controls={`${idPrefix}-evidence`}
                onClick={() => setOpen(open === a.key ? null : a.key)}
              >
                {a.label}
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>
          No archetype is suggested by the evidence (or the samples are too small).
        </p>
      )}
      {item ? (
        <div id={`${idPrefix}-evidence`} className={styles.archetypeEvidence}>
          <p>{item.statement}</p>
          <dl className={styles.analytics}>
            <div>
              <dt>Rule</dt>
              <dd>{item.rule}</dd>
            </div>
            <div>
              <dt>Threshold</dt>
              <dd>{archetypeThresholdText(item)}</dd>
            </div>
            <div>
              <dt>Sample</dt>
              <dd>
                {item.sampleSize ?? "—"} {item.sampleUnit} (min {item.minSample?.value})
              </dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{item.source}</dd>
            </div>
            {archetypeEvidenceRows(item).map((r) => (
              <div key={r.key}>
                <dt>{r.label}</dt>
                <dd>{r.value}</dd>
              </div>
            ))}
          </dl>
          {item.evidenceComplete === false ? (
            <p className={styles.note}>
              Some of this evidence was only partly read, so the counts are a lower bound.
            </p>
          ) : null}
        </div>
      ) : null}
      <details className={styles.about}>
        <summary>Every archetype checked</summary>
        <ul className={styles.shapeList}>
          {(archetypes.items || []).map((a) => (
            <li key={a.key}>
              <span>{a.label}</span>
              <span className={styles.muted}>
                {archetypeStateLabel(a.state)} — {a.statement}
              </span>
            </li>
          ))}
        </ul>
        <p className={styles.note}>{archetypes.basis}</p>
      </details>
    </div>
  );
}

export default function ManagerCareer({ username, scope }) {
  const [state, setState] = useState({ phase: "loading", data: null, error: null });

  useEffect(() => {
    let cancelled = false;
    setState({ phase: "loading", data: null, error: null });
    fetch(careerQuery(username, scope), { cache: "no-store", credentials: "same-origin" })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (cancelled) return;
        if (!response.ok) {
          setState({ phase: "error", data: null, error: errorMessage(response.status, body) });
          return;
        }
        setState({ phase: "ready", data: body, error: null });
      })
      .catch(() => {
        if (!cancelled) setState({ phase: "error", data: null, error: errorMessage(0, null) });
      });
    return () => {
      cancelled = true;
    };
  }, [username, scope]);

  if (state.phase === "loading") {
    return (
      <Panel title="Reading league history">
        <p className={styles.note}>
          Walking each league back through its previous seasons — this can take a while.
        </p>
        <SkeletonTable rows={6} columns={6} />
      </Panel>
    );
  }
  if (state.phase === "error") {
    return (
      <Banner tone="negative" title="Career could not be read">
        {state.error}
      </Banner>
    );
  }
  const career = state.data;
  const tiles = careerTiles(career);
  const problems = careerCoverageProblems(career);
  const seasons = career.seasons || [];
  const compare = compareHref({ a: career.manager?.username });
  return (
    <div className={styles.tabPanel}>
      {problems.length || career.coverage?.budgetExhausted ? (
        <Banner tone="warning" title="Some history could not be read">
          {career.coverage?.budgetExhausted
            ? "The lookup's call budget ran out before every season was read. "
            : ""}
          <ul className={styles.problemList}>
            {problems.map((p) => (
              <li key={p.key}>{p.text}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {tiles.length ? (
        <div className={styles.tiles}>
          {tiles.map((t) => (
            <StatTile key={t.key} label={t.label} value={t.value} meta={t.meta} bare />
          ))}
        </div>
      ) : null}

      <Panel title="Archetypes" subtitle="Labelled evidence, not fact">
        <ArchetypeChips archetypes={career.archetypes} idPrefix="career-arch" />
      </Panel>

      <Panel
        title="Seasons"
        subtitle={`${seasons.length} season${seasons.length === 1 ? "" : "s"} held`}
      >
        {seasons.length ? (
          <SeasonTable seasons={seasons} />
        ) : (
          <EmptyState
            title="No seasons found"
            description="This manager held no roster in the readable history of these leagues."
          />
        )}
        <p className={styles.note}>
          Totals count complete seasons held all season. A season this manager did not
          hold is left out, never counted as a loss
          {career.coverage?.maxSeasonsPerLeague
            ? `; up to ${career.coverage.maxSeasonsPerLeague} seasons per league are read`
            : ""}
          .
        </p>
        {(career.leagues || []).some((l) => l.notHeldSeasons?.length) ? (
          <details className={styles.about}>
            <summary>Seasons not held</summary>
            <ul className={styles.shapeList}>
              {career.leagues
                .filter((l) => l.notHeldSeasons?.length)
                .map((l) => (
                  <li key={l.leagueId}>
                    <span>{l.name || "League"}</span>
                    <span className={styles.muted}>{l.notHeldSeasons.join(", ")}</span>
                  </li>
                ))}
            </ul>
          </details>
        ) : null}
      </Panel>

      {compare ? (
        <p className={styles.note}>
          <a href={compare} className={styles.link}>
            Compare this manager with another manager or a league
          </a>
        </p>
      ) : null}
    </div>
  );
}
