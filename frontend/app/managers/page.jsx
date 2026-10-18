"use client";

/**
 * /managers — Manager Intelligence (C6-MGR-02, Batch A).
 *
 * Look up any Sleeper username and see that manager's dynasty portfolio
 * aggregated across every league they play in this season: which players
 * they own, in how many leagues, against how many leagues that could roster
 * that position, and each player's canonical board value.
 *
 * Private decision intelligence (signed-in only).  Display layer only:
 * `lib/manager-intel.js` filters and formats; every count, exposure share
 * and value is backend-computed (`src/intel/manager_portfolio.py`).  A
 * player the board does not price shows "—", never 0.
 *
 * Batch D: each readable league also links to its scouting view opened on
 * this manager's trade tools (Trade Calculator / Analyze Trade / Package
 * Builder seeds — ./TradeTools.jsx).
 *
 * Batches B1 + B2 add Recent trades / Acquisitions / Activity tabs, and
 * B3 a Draft capital tab plus Tendencies under Recent trades
 * (./ManagerActivity.jsx).  Batch C: each league in the Leagues list links
 * to its league scouting view (./league/[leagueId]/page.jsx).  Their DATA is fetched only when one of them is
 * first opened, so the portfolio never waits on it.  The code is imported
 * statically on purpose: a React.lazy split was measured to re-group shared
 * ds chunks (PageHeader / Select / Field moved out of a shared chunk into
 * /trades' page chunk, 23.6 KB -> 25.4 KB against a 26 KB budget) — the same
 * collateral class as CLAUDE.md's Perfect Draft note.  /managers carries no
 * budget; the static import leaves every budgeted page byte-identical.
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Banner,
  Button,
  CollapsiblePanel,
  DataTable,
  EmptyState,
  Field,
  Input,
  PageHeader,
  Panel,
  PlayerNameButton,
  Select,
  SkeletonTable,
  StatTile,
  Tabs,
  tabId,
  tabPanelId,
} from "@/components/ds";
import {
  SCOPES,
  USERNAME_RE,
  errorMessage,
  exposureText,
  filterOptions,
  filterPlayers,
  formatBadge,
  formatValue,
  leagueScoutHref,
  leagueStateLabel,
  leagueTradeToolsHref,
  playerLeagueRows,
  profileQuery,
  readRecent,
  recordText,
  rememberRecent,
  summaryTiles,
} from "@/lib/manager-intel";
import ManagerActivity from "./ManagerActivity";
import styles from "./managers.module.css";

const PAGE_TITLE = "Manager Intelligence";

const RESULT_TABS = [
  { id: "portfolio", label: "Portfolio" },
  { id: "trades", label: "Recent trades" },
  { id: "acquisitions", label: "Acquisitions" },
  { id: "activity", label: "Activity" },
  { id: "draft", label: "Draft capital" },
];
const TAB_PREFIX = "manager-intel";

function readInitialUsername() {
  if (typeof window === "undefined") return "";
  const value =
    new URLSearchParams(window.location.search).get("username") || "";
  return USERNAME_RE.test(value) ? value : "";
}

export default function ManagersPage() {
  const [input, setInput] = useState("");
  const [scope, setScope] = useState("dynasty");
  const [recent, setRecent] = useState([]);
  const [state, setState] = useState({
    phase: "idle",
    profile: null,
    error: null,
  });
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState("");
  const [team, setTeam] = useState("");
  const [expanded, setExpanded] = useState(() => new Set());
  const [tab, setTab] = useState("portfolio");
  // The activity view mounts on first open and then stays mounted (hidden
  // on Portfolio), so switching tabs never refetches.
  const [activityOpened, setActivityOpened] = useState(false);

  const lookup = useCallback(async (username, nextScope) => {
    const name = String(username || "").trim();
    if (!USERNAME_RE.test(name)) {
      setState({
        phase: "error",
        profile: null,
        error: "Enter a Sleeper username (letters, numbers and underscores).",
      });
      return;
    }
    setState({ phase: "loading", profile: null, error: null });
    setExpanded(new Set());
    setTab("portfolio");
    setActivityOpened(false);
    setQuery("");
    setPosition("");
    setTeam("");
    try {
      const response = await fetch(profileQuery(name, nextScope), {
        cache: "no-store",
        credentials: "same-origin",
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        setState({
          phase: "error",
          profile: null,
          error: errorMessage(response.status, body),
        });
        return;
      }
      setRecent(rememberRecent(body?.manager?.username || name));
      setState({ phase: "ready", profile: body, error: null });
      try {
        const url = new URL(window.location.href);
        url.searchParams.set("username", name);
        window.history.replaceState(null, "", url.toString());
      } catch {
        /* address bar is a convenience */
      }
    } catch {
      setState({ phase: "error", profile: null, error: errorMessage(0, null) });
    }
  }, []);

  useEffect(() => {
    setRecent(readRecent());
    const initial = readInitialUsername();
    if (initial) {
      setInput(initial);
      lookup(initial, "dynasty");
    }
  }, [lookup]);

  const selectTab = useCallback((next) => {
    setTab(next);
    if (next !== "portfolio") setActivityOpened(true);
  }, []);

  const submit = (event) => {
    event.preventDefault();
    lookup(input, scope);
  };

  const profile = state.profile;
  const players = profile?.players || [];
  const leagues = profile?.leagues || [];
  const visible = useMemo(
    () => filterPlayers(players, { query, position, team }),
    [players, query, position, team],
  );
  const positions = useMemo(
    () => filterOptions(players, "position"),
    [players],
  );
  const teams = useMemo(() => filterOptions(players, "nflTeam"), [players]);
  const tiles = useMemo(() => summaryTiles(profile), [profile]);

  const toggle = useCallback((playerId) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(playerId)) next.delete(playerId);
      else next.add(playerId);
      return next;
    });
  }, []);

  const columns = useMemo(
    () => [
      {
        key: "name",
        header: "Player",
        sortable: true,
        accessor: (row) => row.name || row.playerId,
        render: (row) => (
          <span className={styles.playerCell}>
            <button
              type="button"
              className={styles.expand}
              aria-expanded={expanded.has(row.playerId)}
              aria-label={`${expanded.has(row.playerId) ? "Hide" : "Show"} leagues for ${row.name || row.playerId}`}
              onClick={() => toggle(row.playerId)}
            >
              {expanded.has(row.playerId) ? "−" : "+"}
            </button>
            <PlayerNameButton
              name={row.name || `Player ${row.playerId}`}
              playerId={row.playerId}
            />
          </span>
        ),
      },
      {
        key: "position",
        header: "Pos",
        sortable: true,
        accessor: (row) => row.position || "—",
      },
      {
        key: "nflTeam",
        header: "Team",
        sortable: true,
        hideBelow: "sm",
        accessor: (row) => row.nflTeam || "—",
      },
      {
        key: "age",
        header: "Age",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        accessor: (row) => row.age,
        render: (row) => (row.age == null ? "—" : row.age),
      },
      {
        key: "leaguesOwned",
        header: "Leagues",
        numeric: true,
        sortable: true,
        // Exposure already leads with the owned count ("2 / 3"), so the
        // phone layout drops this column to keep Value on screen.
        hideBelow: "sm",
        accessor: (row) => row.leaguesOwned,
      },
      {
        key: "exposure",
        header: "Exposure",
        numeric: true,
        sortable: true,
        headerInfo:
          "Leagues this manager rosters the player in, out of the leagues that could " +
          "roster his position (IDP players are measured against IDP leagues only).",
        accessor: (row) => row.exposure?.share,
        render: (row) => exposureText(row.exposure),
      },
      {
        key: "value",
        header: "Value",
        numeric: true,
        sortable: true,
        headerInfo:
          "Canonical board value (Superflex / TE-premium board). — means the board does not price him.",
        accessor: (row) => row.value,
        render: (row) => formatValue(row.value),
      },
      {
        key: "overallRank",
        header: "Rank",
        numeric: true,
        sortable: true,
        hideBelow: "md",
        firstDirection: "asc",
        accessor: (row) => row.overallRank,
        render: (row) => formatValue(row.overallRank),
      },
    ],
    [expanded, toggle],
  );

  const renderAfterRow = useCallback(
    (row) => {
      if (!expanded.has(row.playerId)) return null;
      const detail = playerLeagueRows(row, leagues);
      return (
        <tr className={styles.detailRow}>
          <td colSpan={columns.length}>
            <ul
              className={styles.detailList}
              aria-label={`Leagues for ${row.name || row.playerId}`}
            >
              {detail.map((d) => (
                <li key={d.leagueId}>
                  <span>{d.name}</span>
                  <span className={styles.muted}>{d.slot}</span>
                  {d.format ? (
                    <span className={styles.muted}>{d.format}</span>
                  ) : null}
                </li>
              ))}
            </ul>
          </td>
        </tr>
      );
    },
    [expanded, leagues, columns.length],
  );

  const manager = profile?.manager;
  const unreadable = leagues.filter(
    (l) => l.state === "unavailable" || l.state === "rate_limited",
  );

  return (
    <div className={`${styles.page} psi-editorial`}>
      <PageHeader
        title={PAGE_TITLE}
        description="Search any Sleeper username to see their dynasty portfolio across every league they play in this season."
      />

      <form className={styles.search} onSubmit={submit} role="search">
        <Field label="Sleeper username">
          <Input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="e.g. sleeperuser"
            autoComplete="off"
            spellCheck={false}
            maxLength={40}
          />
        </Field>
        <Field label="League type">
          <Select
            value={scope}
            onChange={(event) => setScope(event.target.value)}
          >
            {SCOPES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </Select>
        </Field>
        <Button
          type="submit"
          variant="primary"
          loading={state.phase === "loading"}
        >
          Look up
        </Button>
      </form>

      {recent.length ? (
        <div className={styles.recent}>
          <span className={styles.muted}>Recent:</span>
          <ul aria-label="Recent searches">
            {recent.map((name) => (
              <li key={name}>
                <button
                  type="button"
                  className={styles.chip}
                  onClick={() => {
                    setInput(name);
                    lookup(name, scope);
                  }}
                >
                  {name}
                </button>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {state.phase === "error" ? (
        <Banner tone="negative" title="Lookup failed">
          {state.error}
        </Banner>
      ) : null}

      {state.phase === "loading" ? (
        <Panel title="Reading leagues">
          <p className={styles.note}>
            Reading every league from Sleeper — this can take a few seconds.
          </p>
          <SkeletonTable rows={8} columns={6} />
        </Panel>
      ) : null}

      {state.phase === "idle" ? (
        <EmptyState
          title="Look up a manager"
          description="Ownership, exposure and canonical value across all of a manager's leagues, plus their recent trades, acquisitions, activity, draft capital and trade tendencies. Career records arrive in a later batch."
        />
      ) : null}

      {state.phase === "ready" && profile ? (
        <>
          <section className={styles.identity} aria-label="Manager">
            <h2>{manager?.displayName || manager?.username}</h2>
            <p className={styles.note}>
              @{manager?.username} · {profile.season} season ·{" "}
              {profile.leaguesInScope}{" "}
              {SCOPES.find(
                (s) => s.value === profile.scope,
              )?.label.toLowerCase()}{" "}
              league{profile.leaguesInScope === 1 ? "" : "s"}
              {Object.entries(profile.leagueCounts || {})
                .filter(([s, n]) => s !== profile.scope && n)
                .map(([s, n]) => ` · ${n} ${s}`)
                .join("")}
            </p>
          </section>

          {profile.status === "partial" ? (
            <Banner tone="warning" title="Some leagues could not be read">
              {unreadable.length} league{unreadable.length === 1 ? "" : "s"}{" "}
              could not be read from Sleeper, so this portfolio is incomplete.
              They are listed below.
            </Banner>
          ) : null}
          {profile.truncated ? (
            <Banner tone="info" title="Large account — partially shown">
              Only the first {profile.maxLeagues} leagues were read.
            </Banner>
          ) : null}
          {!profile.hasBoard ? (
            <Banner tone="info" title="Values unavailable">
              The canonical board is not loaded right now, so values show as —.
            </Banner>
          ) : null}

          <Tabs
            idPrefix={TAB_PREFIX}
            label="Manager views"
            tabs={RESULT_TABS}
            active={tab}
            onChange={selectTab}
          />

          {activityOpened ? (
            <div
              role="tabpanel"
              // One mounted view serves the three activity tabs, so it takes
              // the active tab's panel id (each tab's aria-controls target).
              id={tabPanelId(TAB_PREFIX, tab === "portfolio" ? "trades" : tab)}
              aria-labelledby={tabId(
                TAB_PREFIX,
                tab === "portfolio" ? "trades" : tab,
              )}
              hidden={tab === "portfolio"}
            >
              <ManagerActivity
                username={manager?.username || state.profile?.query}
                scope={profile.scope}
                profile={profile}
                tab={tab}
              />
            </div>
          ) : null}

          <div
            role="tabpanel"
            id={tabPanelId(TAB_PREFIX, "portfolio")}
            aria-labelledby={tabId(TAB_PREFIX, "portfolio")}
            hidden={tab !== "portfolio"}
            className={styles.tabPanel}
          >
            {tiles.length ? (
              <div className={styles.tiles}>
                {tiles.map((t) => (
                  <StatTile
                    key={t.key}
                    label={t.label}
                    value={t.value}
                    meta={t.meta}
                    bare
                  />
                ))}
              </div>
            ) : null}

            <Panel
              title="Portfolio"
              subtitle={`${formatValue(visible.length)} of ${formatValue(players.length)} players`}
            >
              <div className={styles.filters}>
                <Field label="Search players">
                  <Input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                  />
                </Field>
                <Field label="Position">
                  <Select
                    value={position}
                    onChange={(event) => setPosition(event.target.value)}
                  >
                    <option value="">All positions</option>
                    {positions.map((p) => (
                      <option key={p} value={p}>
                        {p}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Field label="NFL team">
                  <Select
                    value={team}
                    onChange={(event) => setTeam(event.target.value)}
                  >
                    <option value="">All teams</option>
                    {teams.map((t) => (
                      <option key={t} value={t}>
                        {t}
                      </option>
                    ))}
                  </Select>
                </Field>
              </div>
              <DataTable
                columns={columns}
                rows={visible}
                rowKey={(row) => row.playerId}
                caption="Players this manager owns, with league count, exposure and canonical value."
                density="compact"
                renderAfterRow={renderAfterRow}
                emptyState={
                  <EmptyState
                    title={
                      players.length
                        ? "No players match these filters"
                        : "No players owned"
                    }
                    description={
                      players.length
                        ? "Clear a filter to see more."
                        : "This manager holds no roster in any readable league of this type."
                    }
                  />
                }
              />
              <p className={styles.note}>{profile.valueBasis?.note}</p>
            </Panel>

            {/* A controlled Panel with `collapsed` and no toggle handler could
                never open; CollapsiblePanel owns the state.  Open by default
                now that each league carries its "Scout this league" link. */}
            <CollapsiblePanel
              title="Leagues"
              subtitle={`${leagues.length} in scope · scout any league or open its trade tools`}
            >
              <ul className={styles.leagueList}>
                {leagues.map((l) => (
                  <li key={l.leagueId}>
                    <span className={styles.leagueName}>
                      {l.name || "Unnamed league"}
                    </span>
                    <span className={styles.muted}>
                      {formatBadge(l.format)}
                    </span>
                    <span className={styles.muted}>
                      {l.state === "ok"
                        ? `${recordText(l.record)} · ${formatValue(l.playerCount)} players${l.coOwned ? " · co-owner" : ""}`
                        : leagueStateLabel(l.state)}
                    </span>
                    {leagueScoutHref(l.leagueId) ? (
                      <a
                        href={leagueScoutHref(l.leagueId)}
                        className={styles.link}
                      >
                        Scout this league
                        <span className={styles.srOnly}>
                          : {l.name || "unnamed league"}
                        </span>
                      </a>
                    ) : null}
                    {l.state === "ok" &&
                    leagueTradeToolsHref(l.leagueId, manager?.userId) ? (
                      <a
                        href={leagueTradeToolsHref(l.leagueId, manager?.userId)}
                        className={styles.link}
                      >
                        Trade tools
                        <span className={styles.srOnly}>
                          : {manager?.displayName || manager?.username} in{" "}
                          {l.name || "unnamed league"}
                        </span>
                      </a>
                    ) : null}
                  </li>
                ))}
              </ul>
            </CollapsiblePanel>

            <details className={styles.about}>
              <summary>What this includes</summary>
              <p>
                Current-season leagues only. Recent trades, acquisitions,
                activity and draft capital are in their own tabs; career records
                are not included yet. Data comes from Sleeper&apos;s public API
                at lookup time
                {profile.cached ? " (cached for up to 15 minutes)" : ""}.
              </p>
            </details>
          </div>
        </>
      ) : null}
    </div>
  );
}
