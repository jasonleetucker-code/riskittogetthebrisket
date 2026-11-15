"use client";

/**
 * /managers/leaderboards — scoped leaderboards (Manager Intelligence
 * Batch F, C6-MGR-02).
 *
 * Every board ranks ONE named, visible population — the signed-in user's
 * saved managers (`?population=saved`, from each manager's last activity
 * read; no Sleeper call) or the current teams of one league
 * (`?population=league&league=<id>`, the Batch C read) — and says which
 * population and how many members it ranked.  There is no "all of Sleeper"
 * board.  Ranks, values and reasons come from GET
 * /api/manager-intel/leaderboard (`src/intel/manager_leaderboard.py`);
 * `lib/manager-saved.js` labels them.  A member without a value is listed
 * unranked with the reason — never ranked last, never shown as 0.
 *
 * PRIVATE: it sits under /managers, on no public prefix
 * (lib/public-routes.js), so the middleware's session gate covers it.
 */

import { useCallback, useEffect, useState } from "react";
import {
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Panel,
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import {
  ACTIVITY_WINDOWS,
  LEAGUE_ID_RE,
  errorMessage,
  formatDate,
  managerLookupHref,
} from "@/lib/manager-intel";
import {
  POPULATIONS,
  boardCountText,
  boardRows,
  leaderboardHref,
  leaderboardQuery,
  populationText,
  readLeaderboardParams,
} from "@/lib/manager-saved";
import styles from "../managers.module.css";
import saved from "../saved.module.css";

function Board({ board, population }) {
  const rows = boardRows(board);
  return (
    <Panel title={board.label} subtitle={boardCountText(board, population)}>
      {rows.length ? (
        <ol className={saved.boardList} aria-label={`${board.label} — ${population.label}`}>
          {rows.map((r) => {
            const href = r.userId ? managerLookupHref(r.userId) : null;
            return (
              <li key={r.id} className={saved.boardRow}>
                <span className={saved.boardRank}>{r.rank == null ? "—" : r.rank}</span>
                <span className={saved.boardName}>
                  {href ? (
                    <a href={href} className={styles.link}>
                      {r.name}
                    </a>
                  ) : (
                    <span>{r.name}</span>
                  )}
                  {r.sub ? <span className={styles.muted}>{r.sub}</span> : null}
                  {r.reason ? (
                    <span className={styles.muted}>Unranked: {r.reason}</span>
                  ) : null}
                  {population.kind === "saved" && r.asOf ? (
                    <span className={styles.muted}>as of {formatDate(r.asOf)}</span>
                  ) : null}
                </span>
                <span className={saved.boardValue}>{r.value}</span>
              </li>
            );
          })}
        </ol>
      ) : (
        <p className={styles.note}>Nobody to rank in this population.</p>
      )}
    </Panel>
  );
}

export default function LeaderboardsPage() {
  const [population, setPopulation] = useState("saved");
  const [leagueInput, setLeagueInput] = useState("");
  const [windowValue, setWindowValue] = useState("30d");
  const [state, setState] = useState({ phase: "idle", data: null, error: null });

  const run = useCallback(async ({ population: pop, leagueId, window: win }) => {
    const url = leaderboardQuery({ population: pop, leagueId, window: win });
    if (!url) {
      setState({ phase: "error", data: null, error: "Enter a Sleeper league id (digits only)." });
      return;
    }
    setState({ phase: "loading", data: null, error: null });
    try {
      const response = await fetch(url, { cache: "no-store", credentials: "same-origin" });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setState({ phase: "error", data: null, error: errorMessage(response.status, body) });
        return;
      }
      setState({ phase: "ready", data: body, error: null });
      const href = leaderboardHref({ population: pop, leagueId });
      if (href) {
        try {
          window.history.replaceState(null, "", href);
        } catch {
          /* address bar is a convenience */
        }
      }
    } catch {
      setState({ phase: "error", data: null, error: errorMessage(0, null) });
    }
  }, []);

  useEffect(() => {
    const initial = readLeaderboardParams(window.location.search);
    setPopulation(initial.population);
    setLeagueInput(initial.leagueId);
    if (initial.population === "saved") run({ population: "saved" });
    else if (initial.leagueId) run({ population: "league", leagueId: initial.leagueId });
  }, [run]);

  const choose = (next) => {
    setPopulation(next);
    if (next === "saved") run({ population: "saved" });
    else setState({ phase: "idle", data: null, error: null });
  };

  const submit = (event) => {
    event.preventDefault();
    run({ population: "league", leagueId: leagueInput.trim(), window: windowValue });
  };

  const data = state.data;
  const pop = data?.population;
  const anyMembers = (pop?.n ?? 0) > 0;

  return (
    <div className={`${styles.page} psi-editorial`}>
      <PageHeader
        title="Manager leaderboards"
        description="Rank a population you can see — your saved managers, or the teams of one league. Every board names its population and how many it ranked."
      />
      <div className={saved.controls}>
        <SegmentedControl
          label="Population"
          options={POPULATIONS}
          value={population}
          onChange={choose}
        />
      </div>
      {population === "league" ? (
        <form className={styles.search} onSubmit={submit} role="search">
          <Field label="Sleeper league id">
            <Input
              value={leagueInput}
              onChange={(event) => setLeagueInput(event.target.value)}
              maxLength={24}
              inputMode="numeric"
              autoComplete="off"
            />
          </Field>
          <Field label="Activity window">
            <Select value={windowValue} onChange={(event) => setWindowValue(event.target.value)}>
              {ACTIVITY_WINDOWS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </Select>
          </Field>
          <Button
            type="submit"
            variant="primary"
            loading={state.phase === "loading"}
            disabled={!LEAGUE_ID_RE.test(leagueInput.trim())}
          >
            Rank this league
          </Button>
        </form>
      ) : null}
      <p className={styles.note}>
        <a href="/managers" className={styles.link}>
          Back to Manager Intelligence
        </a>
      </p>

      {state.phase === "error" ? (
        <Banner tone="negative" title="Leaderboard unavailable">
          {state.error}
        </Banner>
      ) : null}
      {state.phase === "loading" ? (
        <Panel title="Building leaderboards">
          <SkeletonTable rows={6} columns={3} />
        </Panel>
      ) : null}
      {state.phase === "idle" && population === "league" ? (
        <EmptyState
          title="Pick a league"
          description="Enter a Sleeper league id, or open a league's leaderboard from a manager's Leagues list on Manager Intelligence."
        />
      ) : null}

      {state.phase === "ready" && pop ? (
        <section className={saved.population} aria-label="Population">
          <h2>{populationText(pop)}</h2>
          {pop.kind === "league" && pop.window ? (
            <p className={styles.note}>
              Activity counts cover the {pop.window} window of the {pop.season} season.
            </p>
          ) : null}
          {data.note ? <p className={styles.note}>{data.note}</p> : null}
          <p className={styles.note}>{data.rankingRule}</p>
          {data.status === "partial" ? (
            <Banner tone="warning" title="Partly read">
              Part of this league could not be read from Sleeper; metrics that depend on it
              are left unranked rather than counted low.
            </Banner>
          ) : null}
          {!anyMembers ? (
            <EmptyState
              title={pop.kind === "saved" ? "No saved managers" : "No teams"}
              description={
                pop.kind === "saved"
                  ? "Save managers from Manager Intelligence to rank them here."
                  : "This league has no current teams to rank."
              }
            />
          ) : (
            <div className={saved.boards}>
              {(data.boards || []).map((b) => (
                <Board key={b.key} board={b} population={pop} />
              ))}
            </div>
          )}
        </section>
      ) : null}
    </div>
  );
}
