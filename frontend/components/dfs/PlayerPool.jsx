"use client";

/**
 * PlayerPool — the slate's player table with per-row controls (lock /
 * exclude, the owner's projection override, a selection boost).  Code-split
 * from the /dfs page chunk (React.lazy).  Display only: projections, salaries
 * and identities come from the slate snapshot; nothing here computes a value.
 */

import React, { useMemo, useState } from "react";
import { Button, DataTable, EmptyState, Input, SegmentedControl } from "@/components/ds";
import { filterAthletes, formatPoints, formatSalary, pointsPerK, positionsIn, setPlayerRule } from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

function ProjectionCell({ athlete }) {
  const p = formatPoints(athlete.projection);
  if (p === null) return <span className={styles.missing}>No projection</span>;
  return (
    <span className="ds-mono">
      {p}
      {athlete.projection_source === "platform_season_average" ? (
        <abbr className={styles.sourceMark} title="Platform season average — an observation, not a forecast">
          {" "}avg
        </abbr>
      ) : null}
    </span>
  );
}

export default function PlayerPool({ athletes, rules, setRules, overrides, setOverrides, boosts, setBoosts }) {
  const [position, setPosition] = useState("ALL");
  const [query, setQuery] = useState("");
  const visible = useMemo(() => filterAthletes(athletes, { position, query }), [athletes, position, query]);
  const lockSet = new Set(rules.locks);
  const excludeSet = new Set(rules.excludes);

  const poolColumns = [
    { key: "name", header: "Player", render: (a) => <span className={styles.player}>{a.name}</span> },
    { key: "positions", header: "Pos", accessor: (a) => a.positions.join("/") },
    { key: "team", header: "Team", hideBelow: "sm", accessor: (a) => `${a.team}${a.opponent ? ` v ${a.opponent}` : ""}` },
    { key: "salary", header: "Salary", numeric: true, render: (a) => formatSalary(a.salary) },
    { key: "projection", header: "Proj", numeric: true, render: (a) => <ProjectionCell athlete={a} /> },
    {
      key: "value",
      header: "Pts/$1K",
      numeric: true,
      hideBelow: "md",
      accessor: (a) => pointsPerK(a),
      render: (a) => (pointsPerK(a) == null ? "—" : pointsPerK(a).toFixed(2)),
    },
    {
      key: "override",
      header: "Your proj",
      sortable: false,
      hideBelow: "md",
      render: (a) => (
        <Input
          data-numeric
          inputMode="decimal"
          className={styles.cellInput}
          aria-label={`Your projection for ${a.name} (replaces the forecast for this build)`}
          value={overrides[a.player_id] ?? ""}
          onChange={(e) => setOverrides((m) => ({ ...m, [a.player_id]: e.target.value }))}
        />
      ),
    },
    {
      key: "boost",
      header: "Boost %",
      sortable: false,
      hideBelow: "md",
      render: (a) => (
        <Input
          data-numeric
          inputMode="decimal"
          className={styles.cellInput}
          aria-label={`Selection boost % for ${a.name} (preference only, not a forecast)`}
          value={boosts[a.player_id] ?? ""}
          onChange={(e) => setBoosts((m) => ({ ...m, [a.player_id]: e.target.value }))}
        />
      ),
    },
    {
      key: "rule",
      header: "Rule",
      sortable: false,
      render: (a) => {
        const locked = lockSet.has(a.player_id);
        const excluded = excludeSet.has(a.player_id);
        const unprojected = a.projection === null || a.projection === undefined;
        return (
          <span className={styles.ruleButtons}>
            <Button
              size="sm"
              variant={locked ? "primary" : "ghost"}
              aria-pressed={locked}
              aria-label={`${locked ? "Unlock" : "Lock"} ${a.name}`}
              disabled={unprojected && !locked}
              title={unprojected ? "A player needs a projection before they can be locked" : undefined}
              onClick={() => setRules((r) => setPlayerRule(r, a.player_id, locked ? null : "lock"))}
            >
              Lock
            </Button>
            <Button
              size="sm"
              variant={excluded ? "primary" : "ghost"}
              aria-pressed={excluded}
              aria-label={`${excluded ? "Include" : "Exclude"} ${a.name}`}
              onClick={() => setRules((r) => setPlayerRule(r, a.player_id, excluded ? null : "exclude"))}
            >
              Exclude
            </Button>
          </span>
        );
      },
    },
  ];

  return (
    <>
      <div className={styles.filters}>
        <SegmentedControl
          label="Position"
          options={[{ value: "ALL", label: "All" }, ...positionsIn(athletes).map((p) => ({ value: p, label: p }))]}
          value={position}
          onChange={setPosition}
        />
        <Input
          type="search"
          aria-label="Search players"
          placeholder="Search player or team"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <DataTable
        caption="Slate player pool"
        columns={poolColumns}
        rows={visible}
        rowKey={(a) => a.player_id}
        density="compact"
        defaultSort={{ key: "projection", direction: "desc" }}
        maxHeight="32rem"
        emptyState={<EmptyState title="No players match" description="Clear the filter or search." />}
      />
    </>
  );
}
