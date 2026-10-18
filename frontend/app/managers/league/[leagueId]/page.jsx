"use client";

/**
 * /managers/league/[leagueId] — League scouting (Manager Intelligence
 * Batch C, C6-MGR-02).
 *
 * Every current team in one Sleeper league: roster strength on the
 * canonical board, draft capital, recent activity and tendencies, with a
 * drilldown per team and a link to look that manager up in Manager
 * Intelligence.  Reached from a manager's league list on /managers.
 *
 * Batch D: each drilldown carries Trade tools (../../TradeTools.jsx) that
 * seed the Trade Calculator, Analyze Trade and the Package Builder with
 * chosen assets from that roster; `?manager=<user id>` opens that manager's
 * row on load.
 *
 * PRIVATE: it sits under /managers, which is on no public prefix
 * (lib/public-routes.js), so the middleware's session gate covers it; its
 * data comes from the session-gated GET /api/manager-intel/league.
 *
 * Display layer only: `src/intel/manager_league.py` computes every total,
 * rank, count and coverage state; `lib/manager-intel.js` sorts and labels.
 * A withheld total or rank reads "—" (never 0); unknown pick ownership is
 * "Unknown", never "no picks".  Wide screens get a sortable table; narrow
 * screens the same rows stacked, sharing one sort.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams } from "next/navigation";
import {
  Banner,
  DataTable,
  EmptyState,
  Field,
  PageHeader,
  Panel,
  PlayerNameButton,
  SegmentedControl,
  Select,
  SkeletonTable,
} from "@/components/ds";
import {
  ACTIVITY_WINDOWS,
  LEAGUE_ID_RE,
  SCOUT_SORTS,
  activityPairs,
  defaultScoutDirection,
  errorMessage,
  formatBadge,
  formatDate,
  formatValue,
  leagueScoutQuery,
  managerLookupHref,
  pickOriginText,
  pickOwnershipText,
  positionStrengthRows,
  rankText,
  readFocusManager,
  recordText,
  rosterSlotsText,
  rosterValueText,
  scoutCoverageProblems,
  scoutPicksText,
  scoutRows,
  slotLabel,
  sortScoutRows,
  valueReasonText,
} from "@/lib/manager-intel";
import { Tendencies } from "../../ManagerActivity";
import TradeTools from "../../TradeTools";
import styles from "../../managers.module.css";

function ScoutProfile({ scout }) {
  if (!scout) {
    return (
      <p className={styles.note}>No Manager Scout profile for this manager.</p>
    );
  }
  const t = scout.tradeTendencies || {};
  const w = scout.waiverTendencies || {};
  const shape = t.packageShape || {};
  const pickShare = t.pickShareOfReceived;
  return (
    <dl className={styles.analytics}>
      <div>
        <dt>Trades on record</dt>
        <dd>
          {t.state === "unavailable" ? "Unavailable" : formatValue(t.sampleSize)}
        </dd>
      </div>
      {t.sampleSize ? (
        <>
          <div>
            <dt>Consolidating / expanding</dt>
            <dd>
              {formatValue(shape.consolidating)} / {formatValue(shape.expanding)}
            </dd>
          </div>
          <div>
            <dt>Picks share of received</dt>
            <dd>
              {pickShare?.value == null
                ? "—"
                : `${Math.round(pickShare.value * 100)}% (n = ${pickShare.sampleSize})`}
            </dd>
          </div>
        </>
      ) : null}
      <div>
        <dt>Waiver / FA claims on record</dt>
        <dd>
          {w.state === "unavailable" ? "Unavailable" : formatValue(w.sampleSize)}
        </dd>
      </div>
    </dl>
  );
}

function ManagerDetail({ manager, payload }) {
  const roster = manager.roster;
  const capital = manager.draftCapital;
  const lookup = managerLookupHref(manager.ownerUserId);
  const positions = positionStrengthRows(roster);
  const unknownPicks = capital?.picks == null ? pickOwnershipText(capital) : "";
  return (
    <div className={styles.scoutDetail} data-focus-roster={manager.rosterId}>
      <div className={styles.scoutDetailHead}>
        <span className={styles.muted}>
          {recordText(manager.record)} record · {rosterSlotsText(roster)}
        </span>
        {lookup ? (
          <a href={lookup} className={styles.link}>
            Look up {manager.displayName || "this manager"} in Manager
            Intelligence
          </a>
        ) : null}
      </div>

      <div className={styles.scoutDetailGrid}>
        <section aria-label="Position strength">
          <h4>Position strength</h4>
          <table className={styles.miniTable}>
            <caption className={styles.srOnly}>
              Rostered players by position, with canonical board value and
              league rank.
            </caption>
            <thead>
              <tr>
                <th scope="col">Pos</th>
                <th scope="col">Players</th>
                <th scope="col">Value</th>
                <th scope="col">Rank</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => (
                <tr key={p.position}>
                  <th scope="row">{p.position}</th>
                  <td>
                    {p.count}
                    {p.unpriced ? (
                      <span className={styles.muted}> ({p.unpriced} unpriced)</span>
                    ) : null}
                  </td>
                  <td>{formatValue(p.pricedValue)}</td>
                  <td>{rankText(p.rank)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {roster?.valueNote ? (
            <p className={styles.note}>
              {roster.valueNote === "canonical_board_is_superflex"
                ? "Totals and ranks withheld: the canonical board is a Superflex board and this league is not Superflex."
                : "Totals and ranks withheld: the canonical board is not loaded."}
            </p>
          ) : null}
        </section>

        <section aria-label="Top players">
          <h4>Most valuable players</h4>
          <ul className={styles.assetList}>
            {(roster?.players || []).slice(0, 8).map((p) => (
              <li key={p.playerId} className={styles.assetRow}>
                <span className={styles.assetName}>
                  <PlayerNameButton
                    name={p.name || `Player ${p.playerId}`}
                    playerId={p.playerId}
                  />
                  <span className={styles.muted}>
                    {" "}
                    {p.position || ""} · {slotLabel(p.slot)}
                  </span>
                </span>
                <span
                  className={styles.assetValue}
                  title={
                    p.value == null ? valueReasonText(p.valueReason) : undefined
                  }
                >
                  {formatValue(p.value)}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section aria-label="Draft capital">
          <h4>Draft capital</h4>
          {unknownPicks ? (
            <p className={styles.note}>{unknownPicks}</p>
          ) : capital?.available === false ? (
            <p className={styles.note}>
              Picks held are read for the current season only.
            </p>
          ) : capital?.picks?.length ? (
            <ul className={styles.assetList}>
              {capital.picks.map((pick) => (
                <li key={pick.pickId || pick.label} className={styles.assetRow}>
                  <span className={styles.assetName}>
                    {pick.label}
                    <span className={styles.muted}> {pickOriginText(pick)}</span>
                  </span>
                  <span
                    className={styles.assetValue}
                    title={
                      pick.value == null
                        ? valueReasonText(pick.valueReason)
                        : undefined
                    }
                  >
                    {formatValue(pick.value)}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.muted}>Holds no picks in the read classes.</p>
          )}
        </section>

        <section aria-label="Activity">
          <h4>Activity · {windowLabel(payload)}</h4>
          <dl className={styles.analytics}>
            {activityPairs(manager.activity).map((p) => (
              <div key={p.label}>
                <dt>{p.label}</dt>
                <dd>{p.value}</dd>
              </div>
            ))}
            <div>
              <dt>Last activity (season)</dt>
              <dd>{formatDate(manager.activity?.lastActivityAt)}</dd>
            </div>
          </dl>
        </section>
      </div>

      <TradeTools manager={manager} tradeTools={payload?.tradeTools} />

      {manager.tendenciesSource === "manager_scout" ? (
        <section aria-label="Manager Scout">
          <h4>Manager Scout (our league&apos;s history)</h4>
          <ScoutProfile scout={manager.scout} />
        </section>
      ) : (
        <Tendencies tendencies={manager.tendencies} />
      )}
    </div>
  );
}

function windowLabel(payload) {
  if (payload?.windowApplied === "season")
    return `${payload?.season || "this"} season`;
  const w = ACTIVITY_WINDOWS.find((x) => x.value === payload?.window);
  return w ? `last ${w.label}` : "";
}

export default function LeagueScoutPage() {
  const params = useParams();
  const leagueId = String(params?.leagueId || "");
  const valid = LEAGUE_ID_RE.test(leagueId);
  const [win, setWin] = useState("30d");
  const [state, setState] = useState({
    phase: valid ? "loading" : "error",
    data: null,
    error: valid ? null : "That is not a Sleeper league id.",
  });
  const [sort, setSort] = useState({ key: "valueRank", direction: "asc" });
  const [expanded, setExpanded] = useState(() => new Set());
  // Batch D: `?manager=<user id>` (from a searched manager's league list)
  // opens that manager's row — and with it the trade tools — once, on load.
  const focusRef = useRef(null);
  if (focusRef.current === null)
    focusRef.current =
      typeof window === "undefined"
        ? ""
        : readFocusManager(window.location.search);

  useEffect(() => {
    if (!valid) return undefined;
    let cancelled = false;
    setState((prev) => ({ phase: "loading", data: prev.data, error: null }));
    fetch(leagueScoutQuery(leagueId, win), {
      cache: "no-store",
      credentials: "same-origin",
    })
      .then(async (response) => {
        const body = await response.json().catch(() => ({}));
        if (cancelled) return;
        if (!response.ok) {
          setState({
            phase: "error",
            data: null,
            error: errorMessage(response.status, body),
          });
          return;
        }
        setState({ phase: "ready", data: body, error: null });
      })
      .catch(() => {
        if (!cancelled)
          setState({ phase: "error", data: null, error: errorMessage(0, null) });
      });
    return () => {
      cancelled = true;
    };
  }, [leagueId, valid, win]);

  const data = state.data;
  const rows = useMemo(() => scoutRows(data), [data]);
  const sorted = useMemo(
    () => sortScoutRows(rows, sort.key, sort.direction),
    [rows, sort],
  );
  useEffect(() => {
    const focus = focusRef.current;
    if (!focus || !rows.length) return;
    focusRef.current = "";
    const row = rows.find((r) => String(r.source?.ownerUserId || "") === focus);
    if (!row) return;
    setExpanded((prev) => new Set(prev).add(row.id));
    requestAnimationFrame(() => {
      const target = [
        ...document.querySelectorAll(`[data-focus-roster="${row.rosterId}"]`),
      ].find((el) => el.offsetParent !== null);
      target?.scrollIntoView?.({ block: "start" });
    });
  }, [rows]);
  const ranked = data?.ranking?.rankedRosters || 0;
  const problems = useMemo(() => scoutCoverageProblems(data), [data]);

  const toggle = useCallback((id) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const onSortChange = useCallback((next) => {
    setSort(next || { key: "valueRank", direction: "asc" });
  }, []);

  const columns = useMemo(
    () => [
      {
        key: "name",
        header: "Manager",
        sortable: true,
        accessor: (row) => row.name,
        render: (row) => (
          <span className={styles.playerCell}>
            <button
              type="button"
              className={styles.expand}
              aria-expanded={expanded.has(row.id)}
              aria-label={`${expanded.has(row.id) ? "Hide" : "Show"} details for ${row.name}`}
              onClick={() => toggle(row.id)}
            >
              {expanded.has(row.id) ? "−" : "+"}
            </button>
            <span>
              <span className={styles.leagueName}>{row.name}</span>
              {row.teamName ? (
                <span className={styles.muted}> · {row.teamName}</span>
              ) : null}
            </span>
          </span>
        ),
      },
      {
        key: "valueRank",
        header: "Rank",
        numeric: true,
        sortable: true,
        firstDirection: "asc",
        headerInfo:
          "Rank among this league's rosters by canonical board value (Superflex / TE-premium board) of priced players. — means withheld or unranked.",
        accessor: (row) => row.valueRank,
        render: (row) => rankText(row.valueRank, ranked),
      },
      {
        key: "rosterValue",
        header: "Roster value",
        numeric: true,
        sortable: true,
        accessor: (row) => row.rosterValue,
        render: (row) => rosterValueText(row.source.roster),
      },
      {
        key: "pickValue",
        header: "Picks",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        headerInfo:
          "Picks held and their canonical value at the generic season + round grade. Unknown means pick ownership could not be read.",
        accessor: (row) => row.pickValue,
        render: (row) => scoutPicksText(row.source.draftCapital),
      },
      {
        key: "trades",
        header: "Trades",
        numeric: true,
        sortable: true,
        accessor: (row) => row.trades,
        render: (row) => formatValue(row.trades),
      },
      {
        key: "adds",
        header: "Adds",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        accessor: (row) => row.adds,
        render: (row) => formatValue(row.adds),
      },
      {
        key: "drops",
        header: "Drops",
        numeric: true,
        sortable: true,
        hideBelow: "lg",
        accessor: (row) => row.drops,
        render: (row) => formatValue(row.drops),
      },
      {
        key: "tendency",
        header: "Tendencies",
        accessor: (row) => row.tendency,
      },
    ],
    [expanded, toggle, ranked],
  );

  const renderAfterRow = useCallback(
    (row) =>
      expanded.has(row.id) ? (
        <tr className={styles.detailRow}>
          <td colSpan={columns.length}>
            <ManagerDetail manager={row.source} payload={data} />
          </td>
        </tr>
      ) : null,
    [expanded, columns.length, data],
  );

  const league = data?.league;

  return (
    <div className={`${styles.page} psi-editorial`}>
      <PageHeader
        title="League scouting"
        description="Every manager in one league: roster strength on the canonical board, draft capital, recent activity and tendencies."
      />
      <p className={styles.note}>
        <a href="/managers" className={styles.link}>
          ← Manager Intelligence
        </a>
      </p>

      {state.phase === "error" ? (
        <Banner tone="negative" title="Scouting failed">
          {state.error}
        </Banner>
      ) : null}

      {state.phase === "loading" && !data ? (
        <Panel title="Reading the league">
          <p className={styles.note}>
            Reading every roster and week from Sleeper — this can take a few
            seconds.
          </p>
          <SkeletonTable rows={10} columns={6} />
        </Panel>
      ) : null}

      {data && league ? (
        <>
          <section className={styles.identity} aria-label="League">
            <h2>{league.name || "Unnamed league"}</h2>
            <p className={styles.note}>
              {[
                league.season ? `${league.season} season` : null,
                formatBadge(league.format),
                `${data.managerCount} teams`,
                league.registryLeague ? "our league" : null,
              ]
                .filter(Boolean)
                .join(" · ")}
            </p>
          </section>

          {data.status === "partial" ? (
            <Banner tone="warning" title="Not everything could be read">
              <ul className={styles.problemList}>
                {problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </Banner>
          ) : null}
          {!data.hasBoard ? (
            <Banner tone="info" title="Values unavailable">
              The canonical board is not loaded right now, so values show as —.
            </Banner>
          ) : null}
          {data.ranking?.withheld === "canonical_board_is_superflex" ? (
            <Banner tone="info" title="Ranks withheld">
              This league is not Superflex. The canonical board is a Superflex /
              TE-premium board, so player values are shown but roster totals
              and ranks are not.
            </Banner>
          ) : null}

          <div className={styles.filters}>
            <SegmentedControl
              label="Window"
              value={data.windowApplied === "season" ? "season" : win}
              onChange={setWin}
              options={ACTIVITY_WINDOWS}
            />
            <div className={styles.stackOnly}>
              <Field label="Sort by">
              <Select
                value={sort.key}
                onChange={(event) =>
                  setSort({
                    key: event.target.value,
                    direction: defaultScoutDirection(event.target.value),
                  })
                }
              >
                {SCOUT_SORTS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
              </Field>
            </div>
          </div>

          <Panel
            title="Managers"
            subtitle={`${data.managerCount} teams · activity over ${windowLabel(data)}`}
          >
            <div className={styles.tableOnly}>
              <DataTable
                columns={columns}
                rows={sorted}
                rowKey={(row) => row.id}
                caption="Every team in this league with roster value rank, picks, activity and tendencies."
                density="compact"
                presorted
                sort={sort}
                onSortChange={onSortChange}
                renderAfterRow={renderAfterRow}
                emptyState={<EmptyState title="No teams in this league" />}
              />
            </div>
            <ol className={styles.scoutStack} aria-label="Managers">
              {sorted.map((row) => (
                <li key={row.id}>
                  <details
                    open={expanded.has(row.id)}
                    onToggle={(event) => {
                      if (event.currentTarget.open !== expanded.has(row.id))
                        toggle(row.id);
                    }}
                  >
                    <summary>
                      <span className={styles.leagueName}>{row.name}</span>
                      <span className={styles.muted}>
                        {" "}
                        {rankText(row.valueRank, ranked)}
                      </span>
                    </summary>
                    {expanded.has(row.id) ? (
                      <ManagerDetail manager={row.source} payload={data} />
                    ) : null}
                  </details>
                  <dl className={styles.scoutStackFacts}>
                    <div>
                      <dt>Roster value</dt>
                      <dd>{rosterValueText(row.source.roster)}</dd>
                    </div>
                    <div>
                      <dt>Picks</dt>
                      <dd>{scoutPicksText(row.source.draftCapital)}</dd>
                    </div>
                    <div>
                      <dt>Trades · adds</dt>
                      <dd>
                        {formatValue(row.trades)} · {formatValue(row.adds)}
                      </dd>
                    </div>
                    <div>
                      <dt>Tendencies</dt>
                      <dd>{row.tendency || "—"}</dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ol>
            <p className={styles.note}>{data.ranking?.note}</p>
            <p className={styles.note}>{data.draftCapital?.valueNote}</p>
          </Panel>

          <details className={styles.about}>
            <summary>What this includes</summary>
            <p>
              Current owners only — former members of the league are not shown.
              Activity counts come from Sleeper&apos;s completed transactions
              and draft picks; a move possibly made by a roster&apos;s previous
              owner is not credited.{" "}
              {league.registryLeague
                ? "Tendencies for our own league come from Manager Scout."
                : `Tendencies are counts over the window's trades; fewer than ${data.tendencies?.minSample} is an insufficient sample.`}{" "}
              Read from Sleeper&apos;s public API at lookup time
              {data.cached ? " (cached for up to 10 minutes)" : ""}.
            </p>
          </details>
        </>
      ) : null}
    </div>
  );
}
