"use client";

// Shared Target Quality / Players to target / Sort controls for every
// /arbitrage discovery view (owner directive 2026-10-18).  Display + request
// shaping only: the server applies every filter during candidate generation
// (src/trade/discovery.py).  Labels and options come from the one vocabulary
// module, frontend/lib/trade-discovery.js.

import { Field, Input, Select } from "@/components/ds";
import {
  DISCOVERY_SORT_OPTIONS,
  PLAYER_SCOPE_OPTIONS,
  TARGET_QUALITY_OPTIONS,
} from "@/lib/trade-discovery";
import styles from "./discovery-controls.module.css";

export default function DiscoveryControls({
  value,
  onChange,
  disabled = false,
  idPrefix = "discovery",
  sortOptions = DISCOVERY_SORT_OPTIONS,
  showSort = true,
  showScope = true,
  scopeLabel = "Players to target",
}) {
  const set = (patch) => onChange?.({ ...value, ...patch });
  return (
    <div className={styles.bar} role="group" aria-label="Discovery filters">
      <Field label="Target quality" id={`${idPrefix}-quality`}>
        <Select
          value={value.targetQuality}
          onChange={(e) => set({ targetQuality: e.target.value })}
          disabled={disabled}
          options={TARGET_QUALITY_OPTIONS}
        />
      </Field>
      {showScope ? (
        <Field label={scopeLabel} id={`${idPrefix}-scope`}>
          <Select
            value={value.playersToTarget}
            onChange={(e) => set({ playersToTarget: e.target.value })}
            disabled={disabled}
            options={PLAYER_SCOPE_OPTIONS}
          />
        </Field>
      ) : null}
      {showSort ? (
        <Field label="Sort" id={`${idPrefix}-sort`}>
          <Select
            value={value.sort}
            onChange={(e) => set({ sort: e.target.value })}
            disabled={disabled}
            options={sortOptions}
          />
        </Field>
      ) : null}
      <details className={styles.advanced}>
        <summary>Advanced</summary>
        <Field
          label="Minimum incoming value"
          id={`${idPrefix}-min-value`}
          hint="Canonical value, 1–9,999. Blank = no minimum."
        >
          <Input
            type="number"
            inputMode="numeric"
            min={1}
            max={9999}
            step={100}
            value={value.minIncomingValue ?? ""}
            onChange={(e) => set({ minIncomingValue: e.target.value })}
            disabled={disabled}
            placeholder="None"
          />
        </Field>
      </details>
    </div>
  );
}
