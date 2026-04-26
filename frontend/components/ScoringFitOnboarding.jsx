"use client";

import { useEffect, useState } from "react";

/**
 * One-time onboarding banner for the IDP scoring-fit lens.
 *
 * Shows the FIRST time a user lands on `/rankings` after the lens
 * has data available for their league.  Three short panels with
 * "Next" / "Got it" buttons that explain what the lens is, how
 * to toggle it, and what the cyan numbers mean.  After dismissal
 * the localStorage flag prevents re-display.
 *
 * Designed to be unobtrusive — bottom-right card, dismissable,
 * keyboard-accessible.  Doesn't block the rankings UI.
 */

const _STORAGE_KEY = "scoring_fit_onboarding_dismissed_v1";

const _STEPS = [
  {
    title: "What's Scoring Fit?",
    body: (
      <>
        Your league&apos;s stacked scoring rules pay differently than
        the consensus market: a sack here is worth ~11 pts when sack +
        sack yards + QB hit + TFL all stack, vs ~4 pts elsewhere.
        Scoring Fit shows where this divergence creates buy-low and
        sell-high opportunities.
      </>
    ),
  },
  {
    title: "How to use it",
    body: (
      <>
        Click <strong>&ldquo;Apply Scoring Fit&rdquo;</strong> in the
        lens row above to re-rank IDPs by your league&apos;s rules.
        Tune the strength on{" "}
        <a href="/settings" style={{ color: "var(--cyan)" }}>/settings</a>{" "}
        — start at 30%, dial up if you trust the lens.
      </>
    ),
  },
  {
    title: "Reading the numbers",
    body: (
      <>
        Cyan <strong>+1234</strong> next to a player means your
        league&apos;s scoring values them ~1,234 points HIGHER than the
        consensus does. Click any IDP for the &ldquo;What&apos;s
        driving the scoring fit&rdquo; breakdown showing exactly
        which stats earn them their delta.
      </>
    ),
  },
];

export default function ScoringFitOnboarding({ enabled = false }) {
  const [step, setStep] = useState(0);
  const [dismissed, setDismissed] = useState(true);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const flag = window.localStorage.getItem(_STORAGE_KEY);
      if (!flag) setDismissed(false);
    } catch {
      // localStorage disabled — default to NOT showing rather than
      // re-showing on every page load (worse UX).
    }
  }, []);

  function dismiss() {
    setDismissed(true);
    try {
      if (typeof window !== "undefined") {
        window.localStorage.setItem(_STORAGE_KEY, "1");
      }
    } catch {
      // best-effort
    }
  }

  if (dismissed || !enabled) return null;

  const current = _STEPS[step];
  const isLast = step >= _STEPS.length - 1;

  return (
    <div
      role="dialog"
      aria-label="Scoring Fit introduction"
      style={{
        position: "fixed",
        bottom: 16,
        right: 16,
        maxWidth: 360,
        zIndex: 1200,
        background: "rgba(20, 25, 36, 0.97)",
        border: "1px solid var(--cyan, #22d3ee)",
        borderRadius: 8,
        padding: "14px 16px",
        boxShadow: "0 6px 24px rgba(0, 0, 0, 0.4)",
        fontSize: "0.78rem",
        lineHeight: 1.5,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <strong style={{ color: "var(--cyan)", fontSize: "0.84rem" }}>
          {current.title}
        </strong>
        <button
          type="button"
          onClick={dismiss}
          aria-label="Dismiss"
          style={{
            background: "transparent",
            border: "none",
            color: "var(--muted)",
            fontSize: "1.1rem",
            cursor: "pointer",
            lineHeight: 1,
            padding: 0,
            marginLeft: 8,
          }}
        >
          ×
        </button>
      </div>
      <div style={{ marginBottom: 12 }}>
        {current.body}
      </div>
      <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "space-between" }}>
        <span className="muted" style={{ fontSize: "0.66rem" }}>
          {step + 1} / {_STEPS.length}
        </span>
        <div style={{ display: "flex", gap: 6 }}>
          {step > 0 && (
            <button
              type="button"
              onClick={() => setStep((s) => s - 1)}
              className="button"
              style={{ fontSize: "0.7rem", padding: "3px 10px" }}
            >
              Back
            </button>
          )}
          {isLast ? (
            <button
              type="button"
              onClick={dismiss}
              className="button button-primary"
              style={{ fontSize: "0.7rem", padding: "3px 10px" }}
            >
              Got it
            </button>
          ) : (
            <button
              type="button"
              onClick={() => setStep((s) => s + 1)}
              className="button button-primary"
              style={{ fontSize: "0.7rem", padding: "3px 10px" }}
            >
              Next
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
