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
 *     format      (n) => string — magnitude formatter (default abs + locale)
 *     confidence  0..1 optional — fills 0-3 ticks
 *     srLabel     string — override the generated screen-reader sentence
 *
 *   A11y: emits an aria-label like "up 340, high confidence"; the visual
 *   glyphs are aria-hidden.
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
  const fmt =
    format || ((n) => Math.abs(n).toLocaleString("en-US", { maximumFractionDigits: 1 }));
  const bucket = confidenceBucket(confidence);
  const label =
    srLabel ||
    `${dir === "flat" ? "unchanged" : `${dir} ${fmt(value)}`}${
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
      <span aria-hidden="true">{dir === "flat" ? "0" : fmt(value)}</span>
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
