"use client";

/**
 * RuleBuilder — owner group rules ("at least / at most / exactly N of these")
 * and conditional rules ("if A then B", "if A then not B", "if A then at least
 * N of group B").  Lazily loaded from /dfs.
 *
 * Keyboard-native: native multi-selects and buttons, no drag.  The backend
 * enforces every rule as a hard constraint and, when rules conflict, names the
 * conflicting ones — nothing here relaxes a rule.
 */

import React, { useState } from "react";
import { Banner, Button, Field, Input, Select } from "@/components/ds";
import { RULE_TYPES, ruleError, ruleIsConditional, ruleNeedsCount } from "@/lib/dfs-rules";
import styles from "./dfs-workspace.module.css";

function PlayerPicker({ label, athletes, value, onChange }) {
  return (
    <Field label={label} hint="Hold Ctrl / Cmd to choose several.">
      <select
        multiple
        className={`ds-input ${styles.multi}`}
        value={value}
        onChange={(e) => onChange(Array.from(e.target.selectedOptions, (o) => o.value))}
      >
        {athletes.map((a) => (
          <option key={a.player_id} value={a.player_id}>
            {a.name} · {a.positions.join("/")} · {a.team}
          </option>
        ))}
      </select>
    </Field>
  );
}

const EMPTY = { type: "at_least", n: "1", players: [], when: [], then: [] };

export default function RuleBuilder({ athletes, rules, onChange }) {
  const [draft, setDraft] = useState(EMPTY);
  const [error, setError] = useState(null);
  const byId = new Map(athletes.map((a) => [a.player_id, a]));
  const names = (ids) => ids.map((id) => byId.get(id)?.name || id).join(", ");

  const add = () => {
    const err = ruleError(draft);
    if (err) {
      setError(err);
      return;
    }
    const type = RULE_TYPES.find((t) => t.value === draft.type);
    onChange([...rules, { ...draft, label: `${type.label} (${rules.length + 1})` }]);
    setDraft(EMPTY);
    setError(null);
  };

  const describe = (r) => {
    if (r.type === "if_then") return `If ${names(r.when)}, then ${names(r.then)}`;
    if (r.type === "if_not") return `If ${names(r.when)}, then not ${names(r.then)}`;
    if (r.type === "if_then_n") return `If ${names(r.when)}, then at least ${r.n} of ${names(r.then)}`;
    const word = { at_least: "At least", at_most: "At most", exactly: "Exactly" }[r.type];
    return `${word} ${r.n} of ${names(r.players)}`;
  };

  return (
    <fieldset className={styles.objective}>
      <legend>Player rules</legend>
      {rules.length ? (
        <ul className={styles.list}>
          {rules.map((r, i) => (
            <li key={r.label}>
              {describe(r)}{" "}
              <Button size="sm" variant="ghost" onClick={() => onChange(rules.filter((_, j) => j !== i))} aria-label={`Remove rule: ${describe(r)}`}>
                Remove
              </Button>
            </li>
          ))}
        </ul>
      ) : (
        <p className={styles.note}>No player rules. Rules are hard constraints; conflicts are reported, never relaxed.</p>
      )}
      <div className={styles.controlGrid}>
        <Field label="Rule">
          <Select value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })} options={RULE_TYPES} />
        </Field>
        {ruleNeedsCount(draft.type) ? (
          <Field label="N">
            <Input data-numeric inputMode="numeric" value={draft.n} onChange={(e) => setDraft({ ...draft, n: e.target.value })} />
          </Field>
        ) : null}
      </div>
      {ruleIsConditional(draft.type) ? (
        <div className={styles.importGrid}>
          <PlayerPicker label="A (if any of these)" athletes={athletes} value={draft.when} onChange={(v) => setDraft({ ...draft, when: v })} />
          <PlayerPicker label="B" athletes={athletes} value={draft.then} onChange={(v) => setDraft({ ...draft, then: v })} />
        </div>
      ) : (
        <PlayerPicker label="Players" athletes={athletes} value={draft.players} onChange={(v) => setDraft({ ...draft, players: v })} />
      )}
      <div className={styles.actions}>
        <Button variant="secondary" onClick={add}>
          Add rule
        </Button>
      </div>
      {error ? (
        <Banner tone="negative" title="Rule not added">
          {error}
        </Banner>
      ) : null}
    </fieldset>
  );
}
