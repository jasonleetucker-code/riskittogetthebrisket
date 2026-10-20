"use client";

// Asset picker for one team (design §8.2).  The list arrives ALREADY ORDERED
// by the server for the chosen sort; search and the offense / defense /
// picks / position filters only remove rows, so the order the user sees is
// the server's.  Picks always form their own segment ordered by season,
// round and origin (server rule), never interleaved by value.
//
// Rendered as a <ul role="listbox"> WITHOUT aria-posinset / aria-setsize and
// without numbered markup: an asset's position in a value-ordered list is not
// something this page publishes as a number.

import { useId, useMemo, useState } from "react";
import { Input } from "@/components/ds/Input";
import { Select } from "@/components/ds/Select";
import { SegmentedControl } from "@/components/ds/SegmentedControl";
import { Button } from "@/components/ds/Button";
import {
  ASSET_GROUPS,
  POSITION_LABELS,
  SORTS,
  SORT_LABELS,
  filterAssets,
  positionsPresent,
} from "@/lib/trade-advisor";
import styles from "./trade-advisor.module.css";

function assetMeta(a, inTrade) {
  const parts = [];
  if (a.kind === "pick") parts.push("Draft pick");
  else {
    if (a.position) parts.push(POSITION_LABELS[a.position] || a.position);
    if (a.nflTeam) parts.push(a.nflTeam);
  }
  if (!a.evaluable) parts.push("can't be evaluated right now");
  if (inTrade) parts.push("in this trade");
  return parts.join(" · ");
}

export function AdvisorAssetPicker({ teamName, entry, sort, onSort, inTrade, onAdd, onRetry }) {
  const uid = useId();
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState("all");
  const [position, setPosition] = useState("");
  const [active, setActive] = useState(-1);
  const [lastAdded, setLastAdded] = useState("");
  const data = entry?.data || null;
  const assets = data?.assets || [];
  const positions = useMemo(() => positionsPresent(assets, group), [assets, group]);
  const shown = useMemo(
    () => filterAssets(assets, { group, position: positions.includes(position) ? position : "", query }),
    [assets, group, position, positions, query],
  );
  const picksUnavailable = data?.pickOwnership === "unavailable";

  const add = (a) => {
    if (!a || inTrade.has(a.id)) return;
    onAdd(a);
    setLastAdded(`Added ${a.label}.`);
  };

  const onKeyDown = (e) => {
    if (!shown.length) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((i) => Math.min(shown.length - 1, i + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((i) => Math.max(0, i - 1));
    } else if (e.key === "Home") {
      e.preventDefault();
      setActive(0);
    } else if (e.key === "End") {
      e.preventDefault();
      setActive(shown.length - 1);
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (active >= 0) add(shown[active]);
    }
  };

  let body;
  if (!entry || (entry.status === "loading" && !data)) {
    body = (
      <p className={styles.pickerStatus} role="status" data-testid="advisor-assets-loading">
        Loading {teamName ? `${teamName}'s` : "this team's"} players and picks…
      </p>
    );
  } else if (entry.status === "error") {
    body = (
      <div role="alert" className={styles.analyzeRow}>
        <p className={styles.note}>{entry.error?.message || "This team's players and picks couldn't load."}</p>
        <Button size="sm" onClick={onRetry}>
          Try again
        </Button>
      </div>
    );
  } else if (shown.length === 0) {
    body = (
      <p className={styles.emptyLegs} data-testid="advisor-assets-empty">
        {group === "pick" && picksUnavailable
          ? "Pick ownership for this team can't be confirmed right now, so picks aren't listed."
          : "No players or picks match this filter."}
      </p>
    );
  } else {
    const listId = `${uid}-assets`;
    body = (
      <ul
        id={listId}
        role="listbox"
        aria-multiselectable="true"
        aria-label={`Players and picks${teamName ? ` on ${teamName}` : ""}`}
        aria-activedescendant={active >= 0 && shown[active] ? `${uid}-opt-${active}` : undefined}
        tabIndex={0}
        className={styles.assetList}
        onKeyDown={onKeyDown}
        data-testid="advisor-asset-list"
      >
        {shown.map((a, i) => {
          const taken = inTrade.has(a.id);
          return (
            <li
              key={a.id}
              id={`${uid}-opt-${i}`}
              role="option"
              aria-selected={taken}
              aria-disabled={taken ? true : undefined}
              className={`${styles.asset}${i === active ? ` ${styles.isActive}` : ""}`}
              // Keyboard users move with the listbox's arrow keys
              // (aria-activedescendant); an option focused by a pointer
              // still answers Enter / Space.
              tabIndex={-1}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  add(a);
                }
              }}
              onClick={() => {
                setActive(i);
                add(a);
              }}
            >
              <span>
                <span className={styles.assetName}>{a.label}</span>
                <span className={styles.assetMeta}>{assetMeta(a, taken)}</span>
              </span>
              <span className={styles.assetAction} aria-hidden="true">
                {taken ? "Added" : "Add"}
              </span>
            </li>
          );
        })}
      </ul>
    );
  }

  return (
    <div className={styles.picker}>
      <div className={styles.pickerControls}>
        <label className={`${styles.pickerSearch} ${styles.legRoute}`}>
          <span className={styles.label}>Search</span>
          <Input
            type="search"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setActive(-1);
            }}
            placeholder="Player or pick"
            autoComplete="off"
            spellCheck="false"
            enterKeyHint="search"
          />
        </label>
        <div className={`${styles.pickerSearch} ${styles.pickerGroups}`}>
          <SegmentedControl
            label="Show"
            value={group}
            onChange={(g) => {
              setGroup(g);
              setPosition("");
              setActive(-1);
            }}
            options={ASSET_GROUPS}
          />
        </div>
        {group !== "pick" ? (
          <label className={styles.legRoute}>
            <span className={styles.label}>Position</span>
            <Select
              value={positions.includes(position) ? position : ""}
              onChange={(e) => {
                setPosition(e.target.value);
                setActive(-1);
              }}
              options={[{ value: "", label: "All positions" }, ...positions.map((p) => ({ value: p, label: POSITION_LABELS[p] || p }))]}
            />
          </label>
        ) : null}
        <label className={styles.legRoute}>
          <span className={styles.label}>Sort players</span>
          <Select
            value={sort}
            onChange={(e) => onSort(e.target.value)}
            options={SORTS.map((s) => ({ value: s, label: SORT_LABELS[s] }))}
          />
        </label>
      </div>
      <p className={styles.note}>
        {picksUnavailable && group === "all"
          ? "Pick ownership for this team can't be confirmed right now, so picks aren't listed."
          : "Draft picks are listed by year and round."}
      </p>
      <p className={styles.pickerStatus} role="status">
        {lastAdded}
      </p>
      {body}
    </div>
  );
}
