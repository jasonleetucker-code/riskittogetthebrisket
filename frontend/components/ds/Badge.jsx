/**
 * Badge / StatusIndicator / Movement — the system's signal language.
 *
 * <Badge> — static categorical label (position, tier, source).
 *   tone: "neutral" | "accent" | "positive" | "negative" | "warning" |
 *         "info" | "outline"          (default "neutral")
 *   Rule: tones carry MEANING, not decoration. Positive/negative are for
 *   market/state semantics only — never "I wanted a green one".
 *
 * <StatusIndicator> — dot + label for system state (source health,
 *   pipeline status). Never color-alone: the label is required.
 *   status: "positive" | "negative" | "warning" | "info" | "neutral"
 *
 * <Movement> — the market-movement cluster: DIRECTION (SVG arrow, never
 *   color alone) + MAGNITUDE (tabular number) + optional CONFIDENCE
 *   (3-tick meter). This replaces raw red/green deltas everywhere.
 *   Props:
 *     delta       number — signed change; 0/undefined renders flat dash
 *     format      (n) => string — MAGNITUDE formatter: always receives
 *                 Math.abs(delta), never the sign (default: locale string)
 *     confidence  0..1 optional — fills 0-3 ticks
 *     srLabel     string — override the generated screen-reader sentence
 *
 *   A11y: emits an aria-label like "up 340, high confidence"; the visual
 *   glyphs are aria-hidden.
 *
 * <Confidence> — the same 3-tick meter, standalone, for values that
 *   carry confidence but have no DIRECTION (a projection, a rank, a
 *   probability). <Movement> can only annotate a delta; this annotates
 *   anything.
 *   Props:
 *     confidence  0..1 — same scale and buckets as Movement
 *     showWhen    "degraded" (default) | "always"
 *     limitedBy   string — names the ONE binding dimension ("role"),
 *                 not all of them
 *     srLabel     string — override the generated sentence
 *
 *   Why "degraded" is the default: on a surface where every value is
 *   confident, this renders NOTHING, so the page stays quiet and the
 *   deviation itself is the signal. A confidence marker beside every
 *   number is a wall of caveats that gets tuned out — which costs you
 *   the one place it mattered. Pass showWhen="always" only where a
 *   column must be uniformly populated (e.g. a value-comparison table).
 *
 *   NOT a status: confidence is never rendered in the positive/negative/
 *   warning palette. Low confidence means thin evidence, not a bad
 *   outcome, and those tones are reserved for state that IS good or bad.
 */
"use client";

import React from "react";
import { Icon } from "./Icon";

export function Badge({ tone = "neutral", className = "", children, ...rest }) {
  return (
    <span className={`ds-badge ds-badge--${tone} ${className}`.trim()} {...rest}>
      {children}
    </span>
  );
}

export function StatusIndicator({ status = "neutral", children, className = "", ...rest }) {
  return (
    <span
      className={`ds-badge ds-badge--outline ${className}`.trim()}
      {...rest}
    >
      <span className={`ds-status-dot ds-status-dot--${status}`} aria-hidden="true" />
      {children}
    </span>
  );
}

const TICK_HEIGHTS = [5, 8, 11];

export function confidenceBucket(confidence) {
  if (confidence == null || Number.isNaN(confidence)) return null;
  const c = Math.max(0, Math.min(1, confidence));
  if (c >= 0.67) return 3;
  if (c >= 0.34) return 2;
  if (c > 0) return 1;
  return 0;
}

const CONFIDENCE_WORDS = { 0: "no", 1: "low", 2: "medium", 3: "high" };

export function Movement({
  delta,
  format,
  confidence,
  srLabel,
  className = "",
  ...rest
}) {
  const value = Number(delta) || 0;
  const dir = value > 0 ? "up" : value < 0 ? "down" : "flat";
  // `format` is a MAGNITUDE formatter: it always receives Math.abs(delta)
  // (direction is carried by the arrow + label word, so a custom
  // formatter can never produce "down -5%" double-negation).
  const magnitude = Math.abs(value);
  const display = format
    ? format(magnitude)
    : magnitude.toLocaleString("en-US", { maximumFractionDigits: 1 });
  const bucket = confidenceBucket(confidence);
  const label =
    srLabel ||
    `${dir === "flat" ? "unchanged" : `${dir} ${display}`}${
      bucket != null ? `, ${CONFIDENCE_WORDS[bucket]} confidence` : ""
    }`;

  return (
    <span
      className={`ds-movement ds-movement--${dir} ${className}`.trim()}
      role="img"
      aria-label={label}
      {...rest}
    >
      <Icon
        name={dir === "up" ? "arrow-up" : dir === "down" ? "arrow-down" : "dash"}
        size={10}
        className="ds-movement__arrow"
      />
      <span aria-hidden="true">{dir === "flat" ? "0" : display}</span>
      {bucket != null ? (
        <span className="ds-movement__ticks" aria-hidden="true">
          {TICK_HEIGHTS.map((h, i) => (
            <span
              key={i}
              className={`ds-movement__tick${i < bucket ? " ds-movement__tick--on" : ""}`}
              style={{ height: h }}
            />
          ))}
        </span>
      ) : null}
    </span>
  );
}

export function Confidence({
  confidence,
  showWhen = "degraded",
  limitedBy,
  srLabel,
  className = "",
  ...rest
}) {
  const bucket = confidenceBucket(confidence);
  // Nothing known about confidence => claim nothing. An absent marker
  // and a "no confidence" marker are different statements.
  if (bucket == null) return null;
  // The quiet-by-default rule: a fully-confident value renders NOTHING,
  // so the marker's presence is itself the signal.
  if (showWhen !== "always" && bucket >= 3) return null;

  const label =
    srLabel ||
    `${CONFIDENCE_WORDS[bucket]} confidence${limitedBy ? `, limited by ${limitedBy}` : ""}`;

  return (
    <span
      className={`ds-confidence ds-confidence--${bucket} ${className}`.trim()}
      role="img"
      aria-label={label}
      {...rest}
    >
      <span className="ds-confidence__ticks" aria-hidden="true">
        {TICK_HEIGHTS.map((h, i) => (
          <span
            key={i}
            className={`ds-confidence__tick${i < bucket ? " ds-confidence__tick--on" : ""}`}
            style={{ height: h }}
          />
        ))}
      </span>
    </span>
  );
}
