"use client";

/**
 * TradeTools — seed the trade tools from one scouted roster (Manager
 * Intelligence Batch D, C6-MGR-02).
 *
 * The user picks assets from this manager's roster and opens the Trade
 * Calculator, Analyze Trade or the Package Builder with them pre-filled.
 * Display and link-building only (`lib/manager-trade-tools.js`): values are
 * the canonical board's as GET /api/manager-intel/league published them, and
 * each tool re-values what it receives on that same board under the active
 * package model — nothing here prices anything.
 *
 * An asset the board does not name and price is listed as UNRESOLVED with
 * its reason and cannot be selected, so no tool ever shows it at 0.
 * Analyze Trade and the Package Builder appear only for the league whose
 * rosters the site has loaded (`tradeTools.leagueScoped`); any other league
 * offers the generic calculator seed only.
 */

import { useId, useMemo, useState } from "react";
import { Button } from "@/components/ds";
import {
  describeShareTruncation,
  encodeTrade,
  shareLinkLimits,
} from "@/lib/trade-share";
import {
  calculatorSeedHref,
  calculatorSeedTrade,
  leagueScopedToolsAvailable,
  packageBuilderSeedHref,
  resolvedSeedKeys,
  rosterSeedAssets,
  seedPicksNote,
  selectedSeedAssets,
  tradeToolsScopeNote,
  unresolvedReasonText,
} from "@/lib/manager-trade-tools";
import { formatValue } from "@/lib/manager-intel";
import styles from "./managers.module.css";

export default function TradeTools({ manager, tradeTools }) {
  const assets = useMemo(
    () => rosterSeedAssets(manager, tradeTools),
    [manager, tradeTools],
  );
  const [selected, setSelected] = useState(() => new Set());
  const input = { manager, assets, selectedKeys: selected, tradeTools };
  const chosen = selectedSeedAssets(assets, selected);
  const calcHref = calculatorSeedHref(input, encodeTrade);
  const scoped = leagueScopedToolsAvailable(tradeTools);
  const builderHref = packageBuilderSeedHref(input);
  const limits = shareLinkLimits(calculatorSeedTrade(input));
  const scopeNote = tradeToolsScopeNote(tradeTools);
  const picksNote = seedPicksNote(manager);
  const unresolved = assets.filter((a) => !a.resolved).length;
  const name = manager?.displayName || "this manager";
  const model = tradeTools?.packageModel;
  // useId, not the roster id: the drilldown renders once in the wide table
  // and once in the phone stack, and duplicate ids would bind each label to
  // the hidden copy's checkbox.
  const listId = `trade-seed-${useId().replace(/:/g, "")}`;

  const toggle = (key) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <section aria-label={`Trade tools for ${name}`} className={styles.seed}>
      <h4>Trade tools</h4>
      <p className={styles.note}>
        Pick assets from {name}&apos;s roster to pre-fill the tools. Each tool
        values them on the canonical board
        {model?.label ? ` with ${model.label}` : ""}.
      </p>
      {scopeNote ? <p className={styles.note}>{scopeNote}</p> : null}

      <div className={styles.seedActions}>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setSelected(new Set(resolvedSeedKeys(assets)))}
          disabled={!assets.some((a) => a.resolved)}
        >
          Select all priced
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => setSelected(new Set())}
          disabled={!selected.size}
        >
          Clear
        </Button>
        <span className={styles.muted} aria-live="polite">
          {chosen.length} selected
          {unresolved ? ` · ${unresolved} unresolved` : ""}
        </span>
      </div>

      <ul
        className={styles.seedList}
        id={listId}
        aria-label={`${name}'s assets`}
      >
        {assets.map((a) => {
          const id = `${listId}-${a.key}`;
          return (
            <li key={a.key} className={styles.seedRow}>
              <input
                type="checkbox"
                id={id}
                checked={selected.has(a.key)}
                disabled={!a.resolved}
                onChange={() => toggle(a.key)}
              />
              <label htmlFor={id} className={styles.assetName}>
                {a.label}
                <span className={styles.muted}>
                  {a.detail ? ` ${a.detail}` : ""}
                  {a.resolved
                    ? ""
                    : ` · Unresolved: ${unresolvedReasonText(a.reason)}`}
                </span>
              </label>
              <span className={styles.assetValue}>{formatValue(a.value)}</span>
            </li>
          );
        })}
      </ul>
      {picksNote ? <p className={styles.note}>{picksNote}</p> : null}

      <p className={styles.tradeLinks}>
        {calcHref ? (
          <a href={calcHref} className={styles.link}>
            Open in Trade Calculator
          </a>
        ) : (
          <span className={styles.muted}>
            Select at least one priced asset to open the Trade Calculator
          </span>
        )}
        {scoped ? (
          <>
            {" · "}
            {calcHref ? (
              <a href={calcHref} className={styles.link}>
                Analyze Trade
              </a>
            ) : (
              <span className={styles.muted}>Analyze Trade</span>
            )}
            {" · "}
            {builderHref ? (
              <a href={builderHref} className={styles.link}>
                Package Builder
              </a>
            ) : (
              <span className={styles.muted}>Package Builder</span>
            )}
          </>
        ) : null}
      </p>
      {scoped ? (
        <p className={styles.note}>
          Analyze Trade reads on the calculator for your selected team once you
          add what you would send. The Package Builder opens with {name} as the
          counterparty
          {chosen.length === 1 && chosen[0].kind === "player"
            ? ` and ${chosen[0].label} as the target`
            : ""}
          .
        </p>
      ) : null}
      {calcHref && !limits.complete ? (
        <p className={styles.note} role="status">
          The link carries at most part of this selection: it has{" "}
          {describeShareTruncation(limits.reasons)}.
        </p>
      ) : null}
    </section>
  );
}
