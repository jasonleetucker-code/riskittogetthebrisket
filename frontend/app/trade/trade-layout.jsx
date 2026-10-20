"use client";

/**
 * trade-layout.jsx — the TC-D workspace pieces of /trade (D1).
 *
 * The page is laid out in five layers (docs/trade/TRADE_CALCULATOR_UX_AUDIT.md
 * §7, TC-D in the completion workstream):
 *
 *   1. Trade Builder            #trade-builder
 *   2. Immediate Result         #trade-result     (raw, VA, adjusted, the meter)
 *   3. Final Decision           #trade-decision   (the War Room; echoed here)
 *   4. Supporting Intelligence  #trade-intelligence
 *   5. Ideas & tools            #trade-tools
 *
 * Desktop (>= 1024): two columns, layers 2 + the decision echo sticky on the
 * right.  Below 1024: one column in that order, a section nav, and the
 * persistent verdict bar (the tray) that links to the decision.
 *
 * PURE PRESENTATION, like ./trade-sections.jsx: totals come from
 * lib/trade-logic (`adjustedSideTotals`), the decision is the War Room's
 * `POST /api/trade/analyze` answer, verbatim.  Nothing here computes a value,
 * a band or a recommendation.
 */

import { useEffect, useRef, useState } from "react";
import { Badge, DataTable, Tabs, tabId, tabPanelId } from "@/components/ds";
import { DECISION_TONES } from "@/lib/trade-war-room";
import styles from "./trade.module.css";

/**
 * True below the 768 px canonical breakpoint (the phone layout), after mount.
 * The first render is always the wide layout -- the server has no viewport --
 * and the phone layout takes over on the first effect.  /trade's body renders
 * only after the player pool loads on the client, so nothing visibly swaps.
 */
export const NARROW_QUERY = "(max-width: 767.98px)";
export function useNarrowViewport(query = NARROW_QUERY) {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return undefined;
    const mql = window.matchMedia(query);
    const onChange = () => setNarrow(Boolean(mql.matches));
    onChange();
    mql.addEventListener?.("change", onChange);
    return () => mql.removeEventListener?.("change", onChange);
  }, [query]);
  return narrow;
}

/** Anchors of the five layers, in reading order. */
export const TRADE_LAYERS = [
  { id: "trade-builder", label: "Build" },
  { id: "trade-result", label: "Result" },
  { id: "trade-decision", label: "Decision" },
  { id: "trade-intelligence", label: "Evidence" },
  { id: "trade-tools", label: "Tools" },
];

/** Contextual section navigation (below 1024 px; hidden on the desktop workspace). */
export function TradeSectionNav() {
  return (
    <nav className={styles.sectionNav} aria-label="Trade sections">
      {TRADE_LAYERS.map((layer) => (
        <a key={layer.id} href={`#${layer.id}`} className={styles.sectionNavLink}>
          {layer.label}
        </a>
      ))}
    </nav>
  );
}

const rounded = (v) => Math.round(Number(v)).toLocaleString();

/**
 * Layer 2's package table for a two-team trade: raw, Value Adjustment and the
 * adjusted total per side, straight from `sideTotals` (adjusted = raw + VA,
 * nothing else), on the DataTable primitive.  VA is the difference of the
 * rounded figures, the same rule the side cards use, so the visible parts
 * always add up; no VA reads as a dash, never "+0".  The gap and the band are
 * the meter's, directly below — not repeated here.
 */
export function ImmediateResultTable({ sides, sideTotals }) {
  const totals = [sideTotals[0], sideTotals[1]];
  if (sides.length < 2 || totals.some((t) => !t)) return null;
  const va = (t) =>
    t.adjustment > 0 ? `+${(Math.round(t.adjusted) - Math.round(t.raw)).toLocaleString()}` : "—";
  const rows = [
    { id: "raw", measure: "Raw", a: rounded(totals[0].raw), b: rounded(totals[1].raw) },
    { id: "va", measure: "Value Adjustment", a: va(totals[0]), b: va(totals[1]) },
    {
      id: "adjusted",
      measure: "Adjusted",
      a: rounded(totals[0].adjusted),
      b: rounded(totals[1].adjusted),
    },
  ];
  const columns = [
    { key: "measure", header: "Package" },
    { key: "a", header: `Side ${sides[0].label}`, numeric: true },
    { key: "b", header: `Side ${sides[1].label}`, numeric: true },
  ];
  return (
    <div className={styles.resultTable} data-testid="trade-immediate-result">
      <DataTable
        columns={columns}
        rows={rows}
        rowKey="id"
        caption="Package totals per side: raw, Value Adjustment, adjusted"
        density="compact"
        rowClassName={(row) => (row.id === "adjusted" ? styles.resultTableTotal : "")}
      />
    </div>
  );
}

/** The words for every non-answer state of the decision echo. */
export const SUMMARY_STATE_TEXT = {
  "no-team": "Pick your team to get a decision for your roster.",
  idle: "Add assets to both sides to get a decision.",
  "side-choice": "Tell the War Room which side is yours to get a decision.",
  loading: "Analyzing this trade…",
  error: "The personalized analysis did not finish. The package result above is unaffected.",
  // Owner closeout 2026-10-18, decision 10: a YES / NO only where the engine
  // can identify the user's side AND account for every side -- today, two-team
  // trades.  Never a fabricated binary for another shape.
  multi:
    "No YES / NO for a trade with more than two teams: the decision engine can only judge your side of a two-team trade.",
};

/** The backend's confidence LEVEL as words (never a probability). */
const CONFIDENCE_LEVEL_WORDS = {
  HIGH: "High confidence",
  MEDIUM: "Medium confidence",
  LOW: "Low confidence",
};

/**
 * Layer 3's echo in the sticky desktop column: the War Room's headline and
 * confidence level, verbatim, with a link to the full analysis.  It is the
 * SAME decision, never a second one -- the War Room owns the request and
 * reports it through `onDecision`.  Deliberately short (owner directive
 * 2026-10-19: no conclusion repeated across panels): the reasons and the
 * numbers live in the War Room only.  While a new answer computes there is
 * no decision to echo -- never the previous trade's.
 */
export function DecisionSummary({ summary }) {
  const raw = summary?.status || "idle";
  const status = raw === "updating" ? "loading" : raw;
  const decision = status === "ok" ? summary?.decision || null : null;
  const level = CONFIDENCE_LEVEL_WORDS[decision?.confidence?.level] || null;
  return (
    <section
      className={styles.decisionSummary}
      aria-labelledby="trade-decision-summary-title"
      data-testid="decision-summary"
      data-decision-state={decision ? "ok" : status}
    >
      <h2 id="trade-decision-summary-title" className={styles.layerTitle}>
        Final decision
      </h2>
      {decision ? (
        <div>
          <p className={styles.summaryLine}>
            <span className="ds-visually-hidden">Final decision: </span>
            <Badge
              tone={DECISION_TONES[decision.headline]}
              data-testid="decision-summary-headline"
            >
              {decision.headlineText}
            </Badge>
          </p>
          {level ? (
            <p className={styles.summaryNote} data-testid="decision-summary-confidence">
              {level}
            </p>
          ) : null}
        </div>
      ) : (
        // Not a live region (TC-E): progress is visible; only the final
        // decision change is announced (TradeVerdictAnnouncer).
        <p className={styles.summaryNote}>
          {SUMMARY_STATE_TEXT[status] || SUMMARY_STATE_TEXT.idle}
        </p>
      )}
      <a href="#trade-decision" className={styles.summaryLink}>
        {status === "multi" ? "About the War Room" : decision ? "Why: see the War Room" : "Go to the War Room"}
      </a>
    </section>
  );
}

/**
 * How long a final decision must hold before it is announced (TC-E).  The
 * War Room already debounces its request 700 ms after the last edit; this
 * second, shorter wait means a decision that is replaced while the user is
 * still editing is never read out at all.
 */
export const VERDICT_ANNOUNCE_DELAY_MS = 1000;

/** The words announced for a settled decision, or null when there is none. */
export function verdictAnnouncement(summary) {
  const decision = summary?.status === "ok" ? summary.decision : null;
  const headline = decision?.headlineText;
  if (!headline) return null;
  // The backend's own confidence level, verbatim (never a probability).
  const level = decision.confidence?.level;
  const confidence = typeof level === "string" && level ? level.toLowerCase() : "";
  return `Final decision: ${headline}${confidence ? `. Confidence: ${confidence}` : ""}.`;
}

/**
 * The page's ONE verdict announcement (TC-E; design choice, not an owner
 * decision -- the conservative accessibility default for TC-D2's open
 * "what to announce" question): a single visually hidden, POLITE live region
 * that reads the FINAL decision when it changes, after it has held for
 * VERDICT_ANNOUNCE_DELAY_MS.  Never the meter band (it moves on every edit and
 * is read in place), never "Analyzing…", never a decision being replaced, and
 * the same decision is not repeated -- unless the trade was cleared and built
 * again, which is a new answer.  It reads the War Room's own decision
 * (`onDecision`), so it can never say something the page does not show.
 */
export function TradeVerdictAnnouncer({ summary, delayMs = VERDICT_ANNOUNCE_DELAY_MS }) {
  const [spoken, setSpoken] = useState("");
  const lastRef = useRef(null);
  const text = verdictAnnouncement(summary);
  const status = summary?.status || "idle";
  const settled = status !== "loading" && status !== "updating";
  useEffect(() => {
    if (!text) {
      // No answer on screen any more (cleared, incomplete, error, 3+ teams):
      // the next decision is a new one and will be read, even if its words
      // match the last one.  Emptying a live region speaks nothing.
      if (settled) {
        lastRef.current = null;
        setSpoken("");
      }
      return undefined;
    }
    if (text === lastRef.current) return undefined;
    const timer = setTimeout(() => {
      lastRef.current = text;
      setSpoken(text);
    }, delayMs);
    return () => clearTimeout(timer);
  }, [text, settled, delayMs]);
  return (
    <div
      className="ds-visually-hidden"
      role="status"
      aria-live="polite"
      aria-atomic="true"
      data-testid="trade-verdict-announcer"
    >
      {spoken}
    </div>
  );
}

/**
 * Layer 4's drilldowns (TC-D2; UX audit §7.1): one tab per question.  Only
 * the ACTIVE panel is rendered, so a panel's chunk and its request wait for
 * the user to open it (the same contract the folded panels had).
 */
export const INTEL_TABS = [
  { id: "value", label: "Value" },
  { id: "roster", label: "Roster" },
  { id: "season", label: "Season" },
  { id: "market", label: "Market" },
  { id: "reasoning", label: "Reasoning" },
];

export function TradeIntelTabs({ active, onChange, panels }) {
  const current = INTEL_TABS.some((t) => t.id === active) ? active : INTEL_TABS[0].id;
  const render = panels?.[current];
  return (
    <div className={styles.intel}>
      <Tabs
        idPrefix="trade-intel"
        label="Supporting intelligence"
        tabs={INTEL_TABS}
        active={current}
        onChange={onChange}
        className={styles.intelTabs}
      />
      <div
        role="tabpanel"
        id={tabPanelId("trade-intel", current)}
        aria-labelledby={tabId("trade-intel", current)}
        className={styles.intelPanel}
        data-intel-tab={current}
        tabIndex={0}
      >
        {typeof render === "function" ? render() : null}
      </div>
    </div>
  );
}

const signed = (n) => {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  const v = Math.round(Number(n));
  return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v).toLocaleString()}`;
};

/**
 * The persistent summary for a 3+-team trade (TC-D2): each team's own package
 * gap and the band of the widest one -- the multi-team meter's own numbers
 * (`multiTeamNetSummary`, per-team rule), never a second reading -- linking to
 * the result.  It is PRELIMINARY and says so: the final per-team answer is the
 * War Room's (POST /api/trade/analyze-multi), never computed here.
 */
export function MultiTeamSummaryBar({ sides, summary, evalState, finalBySide = null }) {
  const empty = evalState?.state === "empty";
  const incomplete = evalState?.state === "incomplete";
  return (
    <div className="trade-sticky-tray" data-testid="trade-multi-summary">
      <a href="#trade-result" className={styles.multiSummary}>
        <span className={styles.multiSummaryNets}>
          {sides.map((s, i) => (
            <span key={s.id ?? s.label} className={styles.multiSummaryNet}>
              <span className={styles.summaryLabel}>{s.label}</span>{" "}
              {empty || incomplete ? "—" : signed(summary?.nets?.[i])}
            </span>
          ))}
        </span>
        <span className={styles.multiSummaryVerdict}>
          {finalBySide && !empty && !incomplete
            ? `Final: ${sides
                .map(
                  (s, i) =>
                    `${s.label} ${
                      {
                        FAIR: "fair",
                        NOT_FAIR: "not fair",
                        UNABLE: "unable to determine",
                      }[finalBySide[i]?.fairness] || "—"
                    }`,
                )
                .join(" · ")} — each team's decision is in the War Room`
            : empty
              ? "Add assets to compare"
              : incomplete
                ? `Incomplete — ${evalState.unpriced?.length || 0} unpriced, no verdict`
                : summary?.worstIndex == null || summary?.worst == null
                  ? "Preliminary — widest gap unknown"
                  : `Preliminary · ${summary.verdict?.label || ""} · widest gap Side ${
                      sides[summary.worstIndex]?.label ?? summary.worstIndex + 1
                    } ${signed(summary.nets?.[summary.worstIndex])} · final result in the War Room`}
        </span>
      </a>
    </div>
  );
}
