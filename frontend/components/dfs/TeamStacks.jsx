"use client";

/**
 * TeamStacks — sport-neutral stacking: "at least M teams (or games) each
 * supplying N+ players", optionally counting only some positions (an NHL 3-2
 * skater stack is two entries; an NBA game stack is one).  Lazily loaded from
 * /dfs.  Entries are validated here and sent verbatim; the backend enforces
 * them as hard constraints and names them when they conflict.
 */

import React, { useState } from "react";
import { Banner, Button, Field, Input, SegmentedControl } from "@/components/ds";
import { positionsIn } from "@/lib/dfs";
import { teamStackEntry } from "@/lib/dfs-rules";
import styles from "./dfs-workspace.module.css";

const EMPTY = { scope: "team", size: "3", count: "1", positions: [] };

export default function TeamStacks({ stacks, onChange, athletes, slotCount, singleGame }) {
  const positions = positionsIn(athletes);
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);

  const add = () => {
    const { entry, error: err } = teamStackEntry(singleGame ? { ...draft, scope: "team" } : draft, slotCount);
    if (err) {
      setError(err);
      return;
    }
    setError(null);
    onChange([...stacks, entry]);
    setDraft(EMPTY);
  };

  const togglePosition = (p) =>
    setDraft((d) => ({
      ...d,
      positions: d.positions.includes(p) ? d.positions.filter((x) => x !== p) : [...d.positions, p],
    }));

  return (
    <fieldset className={styles.objective}>
      <legend>Team &amp; game stacks</legend>
      {stacks.length ? (
        <ul className={styles.list}>
          {stacks.map((s, i) => (
            <li key={`${s.label}-${i}`}>
              {s.label}{" "}
              <Button size="sm" variant="ghost" onClick={() => onChange(stacks.filter((_, j) => j !== i))} aria-label={`Remove ${s.label}`}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>No team stacks. Each one is a hard constraint; conflicts are reported, never relaxed.</p>
      )}
      <div className={styles.controlGrid}>
        {singleGame ? null : (
          <SegmentedControl
            label="Stack by"
            options={[
              { value: "team", label: "Team" },
              { value: "game", label: "Game" },
            ]}
            value={draft.scope}
            onChange={(v) => setDraft({ ...draft, scope: v })}
          />
        )}
        <Field label="Players per stack">
          <Input data-numeric inputMode="numeric" value={draft.size} onChange={(e) => setDraft({ ...draft, size: e.target.value })} />
        </Field>
        <Field label="Number of stacks">
          <Input data-numeric inputMode="numeric" value={draft.count} onChange={(e) => setDraft({ ...draft, count: e.target.value })} />
        </Field>
      </div>
      {singleGame || !positions.length ? null : (
        <div className={styles.check} role="group" aria-label="Count only these positions (none checked = all)">
          <span className={styles.note}>Count only:</span>
          {positions.map((p) => (
            <label key={p} className={styles.check}>
              <input type="checkbox" checked={draft.positions.includes(p)} onChange={() => togglePosition(p)} />
              {p}
            </label>
          ))}
        </div>
      )}
      <div className={styles.actions}>
        <Button variant="secondary" onClick={add}>
          Add stack
        </Button>
      </div>
      {error ? (
        <Banner tone="negative" title="Stack not added">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
