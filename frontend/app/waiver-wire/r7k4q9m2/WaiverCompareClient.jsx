"use client";

/**
 * Waiver Wire Comparison — pick a team, see what it owns, see the best
 * available players.  A value VIEWER, deliberately: no replacement line,
 * no drop advice, no comparison math.  Every number comes from
 * /api/public/waiver-compare (the plain KTC / IDPTC average); this file
 * only filters, sorts and pages it via lib/waiver-compare.js.
 */
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Banner,
  Button,
  DataTable,
  EmptyState,
  Field,
  PageHeader,
  Panel,
  Select,
  SkeletonTable,
} from "@/components/ds";
import {
  AGE_ALL,
  AGE_MIN,
  POSITION_FILTERS,
  SORT_OPTIONS,
  WAIVER_PAGE_SIZE,
  ageLimitLabel,
  formatAge,
  formatTimestamp,
  formatValue,
  recordsFor,
  selectPlayers,
} from "@/lib/waiver-compare";
import styles from "./waiver-compare.module.css";

const ENDPOINT = "/api/public/waiver-compare";
const TEAM_PARAM = "team";

function readTeamParam() {
  if (typeof window === "undefined") return "";
  try {
    return new URL(window.location.href).searchParams.get(TEAM_PARAM) || "";
  } catch {
    return "";
  }
}

function writeTeamParam(rosterId) {
  if (typeof window === "undefined") return;
  try {
    const url = new URL(window.location.href);
    if (rosterId) url.searchParams.set(TEAM_PARAM, rosterId);
    else url.searchParams.delete(TEAM_PARAM);
    window.history.replaceState(null, "", url.toString());
  } catch {
    /* URL state is a convenience only */
  }
}

function SourceDetail({ player, sources }) {
  return (
    <div className={styles.detail}>
      <span>
        {sources?.ktc?.label || "KTC"}:{" "}
        <strong>{player.ktc == null ? "Not listed" : formatValue(player.ktc)}</strong>
      </span>
      <span>
        {sources?.idptc?.label || "IDP Trade Calculator"}:{" "}
        <strong>{player.idptc == null ? "Not listed" : formatValue(player.idptc)}</strong>
      </span>
      <span>
        Combined: <strong>{formatValue(player.value)}</strong>
      </span>
    </div>
  );
}

function PlayerTable({ caption, rows, sources, emptyTitle }) {
  const [expanded, setExpanded] = useState(() => new Set());
  const toggle = useCallback((row) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(row.id)) next.delete(row.id);
      else next.add(row.id);
      return next;
    });
  }, []);

  const columns = useMemo(
    () => [
      {
        key: "name",
        header: "Player",
        render: (r) => <span className={styles.playerName}>{r.name}</span>,
      },
      { key: "pos", header: "Pos", render: (r) => r.pos || "—" },
      { key: "team", header: "Team", render: (r) => r.team || "FA" },
      { key: "age", header: "Age", numeric: true, render: (r) => formatAge(r.age) },
      {
        key: "value",
        header: "Value",
        numeric: true,
        render: (r) => (
          <span className={r.value == null ? styles.missing : styles.valueCell}>
            {formatValue(r.value)}
          </span>
        ),
      },
    ],
    [],
  );

  return (
    <DataTable
      caption={caption}
      columns={columns}
      rows={rows}
      rowKey="id"
      density="compact"
      presorted
      onRowClick={toggle}
      isRowExpanded={(r) => expanded.has(r.id)}
      rowExpandLabel={(r) => `Source values for ${r.name}`}
      renderAfterRow={(r) =>
        expanded.has(r.id) ? (
          <tr>
            <td colSpan={columns.length}>
              <SourceDetail player={r} sources={sources} />
            </td>
          </tr>
        ) : null
      }
      emptyState={<EmptyState title={emptyTitle} />}
    />
  );
}

export default function WaiverCompareClient() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [teamId, setTeamId] = useState("");
  const [position, setPosition] = useState("ALL");
  const [sort, setSort] = useState("value_desc");
  const [maxAge, setMaxAge] = useState(AGE_ALL);
  const [visible, setVisible] = useState(WAIVER_PAGE_SIZE);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await fetch(ENDPOINT, { cache: "no-store" });
      const body = await res.json().catch(() => null);
      if (!res.ok || !body?.ok) {
        const code = body?.error || `http_${res.status}`;
        throw new Error(code);
      }
      setData(body);
      setError(null);
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setTeamId(readTeamParam());
    load();
  }, [load]);

  // Any filter change restarts the waiver list at the top 50.
  useEffect(() => {
    setVisible(WAIVER_PAGE_SIZE);
  }, [position, sort, maxAge]);

  const teams = useMemo(() => data?.teams || [], [data]);
  const team = useMemo(
    () => teams.find((t) => String(t.rosterId) === String(teamId)) || null,
    [teams, teamId],
  );

  const roster = useMemo(() => {
    if (!team) return [];
    const recs = recordsFor(team.playerIds, data?.players);
    // The waiver age limit never applies to the roster.
    return selectPlayers(recs, { position, sort }).players;
  }, [team, data, position, sort]);

  const waivers = useMemo(() => {
    const recs = recordsFor(data?.waiverIds, data?.players);
    return selectPlayers(recs, { position, sort, maxAge });
  }, [data, position, sort, maxAge]);

  const shownWaivers = waivers.players.slice(0, visible);
  const sources = data?.values?.sources;

  const onTeamChange = (e) => {
    setTeamId(e.target.value);
    writeTeamParam(e.target.value);
  };

  const teamOptions = [
    { value: "", label: "Choose a team…" },
    ...teams.map((t) => ({
      value: String(t.rosterId),
      label: t.ownerName && t.ownerName !== t.teamName ? `${t.teamName} (${t.ownerName})` : t.teamName,
    })),
  ];

  const staleSources = sources
    ? Object.values(sources).filter((s) => s.staleness && s.staleness !== "fresh")
    : [];

  return (
    <div className={styles.page}>
      <PageHeader
        title="Waiver Wire Comparison"
        description={data?.league?.name || undefined}
        actions={
          <Button size="sm" variant="secondary" onClick={load} loading={loading && !!data}>
            Refresh
          </Button>
        }
      />

      {error && (
        <Banner tone="negative" title="Could not load the comparison">
          {error === "rosters_unavailable"
            ? "Sleeper rosters are unavailable right now. Try Refresh in a minute."
            : error === "values_unavailable"
              ? "Player values are not loaded on the server yet. Try again shortly."
              : "The server did not answer. Try Refresh."}
          {data ? " Showing the last data that loaded." : ""}
        </Banner>
      )}
      {data?.rosters?.state === "stale" && (
        <Banner tone="warning" title="Rosters may be out of date">
          Sleeper did not answer, so ownership is from {formatTimestamp(data.rosters.fetchedAt)}.
        </Banner>
      )}
      {staleSources.length > 0 && (
        <Banner tone="warning" title="Some values are stale">
          {staleSources.map((s) => `${s.label} last fetched ${formatTimestamp(s.fetchedAt)}`).join(" · ")}
        </Banner>
      )}

      <div className={styles.controls}>
        <div className={styles.teamControl}>
          <Field label="Select your team">
            <Select value={teamId} onChange={onTeamChange} options={teamOptions} disabled={!teams.length} />
          </Field>
        </div>
        <Field label="Position">
          <Select
            value={position}
            onChange={(e) => setPosition(e.target.value)}
            options={POSITION_FILTERS.map((p) => ({ value: p, label: p === "ALL" ? "All" : p }))}
          />
        </Field>
        <Field label="Sort by">
          <Select value={sort} onChange={(e) => setSort(e.target.value)} options={SORT_OPTIONS} />
        </Field>
        <div className={styles.ageControl}>
          <label className={styles.ageLabel} htmlFor="waiver-max-age">
            <span>Waiver max age</span>
            <span className={styles.ageValue}>{ageLimitLabel(maxAge)}</span>
          </label>
          <input
            id="waiver-max-age"
            type="range"
            min={AGE_MIN}
            max={AGE_ALL}
            step={1}
            value={maxAge}
            onChange={(e) => setMaxAge(Number(e.target.value))}
            aria-valuetext={ageLimitLabel(maxAge)}
          />
        </div>
      </div>

      {data && (
        <div className={styles.meta}>
          <span>Values updated {formatTimestamp(data.values?.asOf)}</span>
          <span>Rosters updated {formatTimestamp(data.rosters?.fetchedAt)}</span>
        </div>
      )}

      {!data && loading ? (
        <SkeletonTable rows={10} />
      ) : data ? (
        <div className={styles.columns}>
          <Panel
            flush
            title="Your roster"
            subtitle={team ? `${team.teamName} · ${roster.length} players` : "Select a team above"}
          >
            {team ? (
              <PlayerTable
                caption={`${team.teamName} roster with combined dynasty values`}
                rows={roster}
                sources={sources}
                emptyTitle="No rostered players at this position"
              />
            ) : (
              <EmptyState title="No team selected" description="Pick your team to see everyone you own." />
            )}
          </Panel>

          <Panel
            flush
            title="Available waivers"
            subtitle={`${waivers.players.length} available · ${ageLimitLabel(maxAge)}`}
            footer={
              <div className={styles.footer}>
                <span>
                  Showing {shownWaivers.length} of {waivers.players.length}
                  {waivers.hiddenUnknownAge > 0 ? ` · ${waivers.hiddenUnknownAge} hidden (age unknown)` : ""}
                </span>
                {shownWaivers.length < waivers.players.length && (
                  <Button size="sm" variant="secondary" onClick={() => setVisible((v) => v + WAIVER_PAGE_SIZE)}>
                    Load 50 more
                  </Button>
                )}
              </div>
            }
          >
            <PlayerTable
              caption="Best available waiver-wire players with combined dynasty values"
              rows={shownWaivers}
              sources={sources}
              emptyTitle="No available players match these filters"
            />
          </Panel>
        </div>
      ) : null}

      {data && (
        <p className={styles.note}>
          Value = average of {sources?.ktc?.label} ({sources?.ktc?.settings}) and {sources?.idptc?.label} (
          {sources?.idptc?.settings}). A player listed on only one site keeps that site&apos;s value; N/A
          means neither site lists the player. Waivers list every unrostered player at least one site values.
          Tap a player for the per-site values.
        </p>
      )}
    </div>
  );
}
