"use client";

import { useCallback, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import { useDynastyData } from "@/components/useDynastyData";
import { useAuthContext } from "@/app/AppShellWrapper";
import { FailureState, HelpModal, InfoTip } from "@/components/ds";
import {
  useSettings,
  SETTINGS_DEFAULTS as DEFAULTS,
} from "@/components/useSettings";
import { useUserState } from "@/components/useUserState";
import {
  WEIGHT_PRESETS,
  presetToWeights,
  detectActivePreset,
} from "@/lib/weight-presets";
import { RANKING_SOURCES } from "@/lib/dynasty-data";
import { ROS_SOURCES } from "@/lib/ros-sources";
import PushNotificationToggle from "@/components/PushNotificationToggle";
import CustomAlertsConfigurator from "@/components/CustomAlertsConfigurator";

// The settings page enumerates the canonical ranking registry directly
// so a newly registered source automatically shows up here without any
// further editing.  No per-source overrides — every source contributes
// at its declared weight (currently 1.0 across the board; see
// `RANKING_SOURCES` in dynasty-data.js and `_RANKING_SOURCES` in
// src/api/data_contract.py).  The registry is the single source of
// truth for weight, scope, depth, and retail/expert classification.

function Section({ title, defaultOpen = true, children }) {
  const [open, setOpen] = useState(defaultOpen);
  // aria-expanded + aria-controls were both missing, so assistive tech
  // announced twelve identical buttons with no state and no
  // relationship to the panels they toggle.
  const bodyId = useId();
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <button
        className="button-reset"
        onClick={() => setOpen(!open)}
        aria-expanded={open}
        aria-controls={bodyId}
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          width: "100%",
          padding: "8px 0",
          minHeight: 44,
          cursor: "pointer",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>{title}</h3>
        <span
          className="muted"
          aria-hidden="true"
          style={{ fontSize: "1.2rem", width: 24, textAlign: "center" }}
        >
          {open ? "−" : "+"}
        </span>
      </button>
      <div id={bodyId} hidden={!open} style={open ? { marginTop: 10 } : undefined}>
        {children}
      </div>
    </div>
  );
}

/**
 * A labelled cluster of sections.
 *
 * The page was twelve peer accordions in one flat list, mixing everyday
 * preferences (superflex, TEP), power-user model tuning (two per-source
 * weight tables), personal data (watchlist, alerts) and operator
 * surfaces (server status, guest passes).  Nothing said which was
 * which, so finding anything meant opening things until you hit it.
 * Same sections, same order within each group — now under headings that
 * say what kind of setting lives there.
 */
function SettingsGroup({ title, description, children }) {
  return (
    <div style={{ marginTop: "var(--space-lg)" }}>
      <h2
        style={{
          margin: "0 0 2px",
          fontSize: "0.78rem",
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--subtext)",
        }}
      >
        {title}
      </h2>
      {description ? (
        <p className="muted" style={{ margin: "0 0 8px", fontSize: "0.72rem" }}>
          {description}
        </p>
      ) : null}
      {children}
    </div>
  );
}

function SliderRow({ label, value, min, max, step, onChange, hint }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 8,
      }}
    >
      <label style={{ minWidth: 100, fontSize: "0.82rem" }}>{label}</label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1 }}
      />
      <span className="badge" style={{ minWidth: 48, textAlign: "center" }}>
        {value}
      </span>
      {hint && (
        <span className="muted" style={{ fontSize: "0.66rem" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

function ToggleRow({ label, checked, onChange, hint }) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 6,
      }}
    >
      <label
        style={{
          display: "flex",
          alignItems: "center",
          gap: 8,
          fontSize: "0.82rem",
          cursor: "pointer",
        }}
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
        />
        {label}
      </label>
      {hint && (
        <span className="muted" style={{ fontSize: "0.66rem" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

export default function SettingsPage() {
  const { loading, error, failure, rows, rawData, retry } = useDynastyData();
  // Only to point an operator at where the moved panels went; nothing
  // on this page is gated by it.
  const { isAdmin } = useAuthContext();
  const {
    settings,
    hydrated: settingsHydrated,
    update,
    updateSiteWeight,
    resetSiteWeights,
    reset,
  } = useSettings();
  const {
    state: userState,
    serverBacked,
    setNotifications,
    toggleWatchlist,
  } = useUserState();
  const [watchAddName, setWatchAddName] = useState("");
  const [hydrated, setHydrated] = useState(true);
  const [emailDraft, setEmailDraft] = useState("");
  const [emailStatus, setEmailStatus] = useState("");

  // Keep the email input in sync with the server-backed value on
  // hydrate.  A user who clears the field and saves empty should see
  // the input stay empty (not snap back to the server value).
  useEffect(() => {
    if (userState?.notificationsEmail) {
      setEmailDraft(String(userState.notificationsEmail));
    }
  }, [userState?.notificationsEmail]);

  const saveEmail = useCallback(() => {
    const clean = emailDraft.trim();
    if (
      clean &&
      (!clean.includes("@") || !clean.split("@")[1]?.includes("."))
    ) {
      setEmailStatus("That doesn't look like a valid email address.");
      return;
    }
    setNotifications({ email: clean || null });
    setEmailStatus(clean ? "Saved." : "Email cleared.");
    setTimeout(() => setEmailStatus(""), 2500);
  }, [emailDraft, setNotifications]);

  const toggleEnabled = useCallback(
    (next) => {
      setNotifications({ enabled: next });
    },
    [setNotifications],
  );

  function resetToDefaults() {
    reset();
  }

  // TE Premium input value.  The backend stamps the operator's
  // current default (``rankingsOverride.tepMultiplierDerived``, the
  // hardcoded non-native default 1.15 — TEP-1.5 platform; Sleeper
  // never exposes ``bonus_rec_te`` here); we use that as the displayed
  // value when the user has not set an explicit override, falling back
  // to 1.15 if the field is missing.
  const tepDefault = (() => {
    const v = Number(rawData?.rankingsOverride?.tepMultiplierDerived);
    return Number.isFinite(v) ? v : 1.15;
  })();
  const tepSliderValue = (() => {
    const raw = settings?.tepMultiplier;
    if (raw === null || raw === undefined) return tepDefault;
    const n = Number(raw);
    return Number.isFinite(n) ? n : tepDefault;
  })();
  // AUTO is nullish and ONLY nullish.  This used to also count an
  // explicit 1.15 as "default", which made the two states render
  // identically — the caption said "Default 1.15×" whether the backend
  // was measuring the TE basis or being overridden by a flat number, and
  // the reset link was hidden in both.  They do materially different
  // things, so the UI has to be able to tell you which one you are on.
  const tepIsAuto =
    settings?.tepMultiplier === null || settings?.tepMultiplier === undefined;

  // Parallel "TEP-native" multiplier — the per-bucket boost applied
  // to TEP-native sources (DN SF-TEP, Yahoo Boone, FP Fitzmaurice)
  // on TE rows.  Mirrors the non-TEP knob above; default 1.10.
  const tepNativeDefault = (() => {
    const v = Number(rawData?.rankingsOverride?.tepNativeMultiplierDerived);
    return Number.isFinite(v) ? v : 1.1;
  })();
  const tepNativeInputValue = (() => {
    const raw = settings?.tepNativeMultiplier;
    if (raw === null || raw === undefined) return tepNativeDefault;
    const n = Number(raw);
    return Number.isFinite(n) ? n : tepNativeDefault;
  })();
  const tepNativeIsDefault =
    settings?.tepNativeMultiplier === null ||
    settings?.tepNativeMultiplier === undefined;

  // Split the canonical registry into offense / IDP groups by the
  // declared scope field.  idpTradeCalc is listed under IDP (its
  // primary backbone scope) even though its `extraScopes` also
  // contribute to offense rankings — that's a calculation detail.
  //
  // Live/Idle status is derived from ACTUAL ROW COVERAGE across
  // `rows[*].canonicalSites`, NOT from the payload's `data.sites`
  // array.  The scraper's `sites` array omits CSV-enriched sources
  // (the backend's `_enrich_from_source_csvs` pass can populate
  // `canonicalSiteValues.dlfSf` / `.dlfIdp` / etc. for players even
  // when those keys are absent from `sites`), so a `sites`-based
  // check would mark DLF/DN/FP as Idle even though they are
  // actively contributing to the blended rankings.  Counting rows
  // with a finite positive `canonicalSites[src.key]` entry is the
  // honest status signal.
  const sourcesByGroup = useMemo(() => {
    const coverage = new Map();
    for (const src of RANKING_SOURCES) coverage.set(src.key, 0);
    for (const r of rows || []) {
      const cs = r?.canonicalSites;
      if (!cs || typeof cs !== "object") continue;
      for (const src of RANKING_SOURCES) {
        const v = Number(cs[src.key]);
        if (Number.isFinite(v) && v > 0) {
          coverage.set(src.key, (coverage.get(src.key) || 0) + 1);
        }
      }
    }
    const decorate = (src) => {
      const covered = coverage.get(src.key) || 0;
      const ov = (settings?.siteWeights || {})[src.key] || {};
      const userInclude = ov.include === false ? false : true;
      const userWeight =
        Number.isFinite(Number(ov.weight)) && Number(ov.weight) >= 0
          ? Number(ov.weight)
          : Number(src.weight ?? 1);
      return {
        ...src,
        covered,
        live: covered > 0,
        userInclude,
        userWeight,
        defaultWeight: Number(src.weight ?? 1),
        isTepPremium: src.isTepPremium === true,
      };
    };
    return {
      offense: RANKING_SOURCES.filter((s) => s.scope === "overall_offense").map(
        decorate,
      ),
      idp: RANKING_SOURCES.filter((s) => s.scope === "overall_idp").map(
        decorate,
      ),
    };
  }, [rows, settings?.siteWeights]);

  if (!hydrated) return null;

  return (
    <section className="card">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div>
          <h1 style={{ marginTop: 0 }}>Settings</h1>
          <p className="muted" style={{ marginTop: 4 }}>
            Tuning controls that affect valuations, trade calculations, and
            rankings display.
          </p>
        </div>
        <button
          className="button"
          onClick={resetToDefaults}
          style={{ fontSize: "0.76rem" }}
        >
          Reset Defaults
        </button>
      </div>

      {loading && <p role="status">Loading data…</p>}
      {/* Was a bare red <p>: no role, so nothing was announced; no
          primitive, so it looked like nothing else in the app; and no
          kind, so "you are signed out" and "the backend is down" and
          "the board is empty" were one sentence in one colour. */}
      {failure ? <FailureState failure={failure} onRetry={retry} /> : null}

      <SettingsGroup
        title="League &amp; scoring"
        description="How your league is set up. These change what the numbers mean."
      >
      <Section title="League Format" defaultOpen>
        <div style={{ display: "flex", gap: 10, marginBottom: 10 }}>
          <select
            className="select"
            value={settings.leagueFormat}
            onChange={(e) => update("leagueFormat", e.target.value)}
          >
            <option value="superflex">Superflex</option>
            <option value="standard">Standard (1QB)</option>
          </select>
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 8,
          }}
        >
          <label style={{ minWidth: 140, fontSize: "0.82rem" }}>
            TEP — non-native
          </label>
          <input
            type="number"
            min={1.0}
            max={1.5}
            step={0.01}
            value={tepSliderValue}
            // Wheel-scrolling a focused number input silently mutates
            // it (and a stray tick here pins TEP to an explicit
            // override that overrides the league default).  Blur on
            // wheel so only deliberate typing changes the value.
            onWheel={(e) => e.currentTarget.blur()}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (Number.isFinite(n)) {
                update("tepMultiplier", Math.max(1.0, Math.min(1.5, n)));
              }
            }}
            style={{
              width: 90,
              padding: "4px 8px",
              fontSize: "0.82rem",
              fontFamily: "var(--mono)",
            }}
          />
          <span className="muted" style={{ fontSize: "0.66rem" }}>
            {tepIsAuto
              ? `Auto — the measured TE-basis curve, ~${tepDefault.toFixed(2)}× and up, on non-TEP sources`
              : `Custom ${Number(tepSliderValue).toFixed(2)}× flat — overrides the measured curve`}
          </span>
        </div>
        {!tepIsAuto && (
          <div style={{ marginTop: 4, marginBottom: 6 }}>
            <button
              type="button"
              className="button-reset"
              style={{
                fontSize: "0.7rem",
                color: "var(--accent-gold, #4f9bec)",
                textDecoration: "underline",
                cursor: "pointer",
                padding: 0,
              }}
              onClick={() => update("tepMultiplier", null)}
            >
              Reset to auto (measured curve)
            </button>
          </div>
        )}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            marginBottom: 8,
          }}
        >
          <label style={{ minWidth: 140, fontSize: "0.82rem" }}>
            TEP — native
          </label>
          <input
            type="number"
            min={1.0}
            max={1.5}
            step={0.01}
            value={tepNativeInputValue}
            onWheel={(e) => e.currentTarget.blur()}
            onChange={(e) => {
              const n = parseFloat(e.target.value);
              if (Number.isFinite(n)) {
                update("tepNativeMultiplier", Math.max(1.0, Math.min(1.5, n)));
              }
            }}
            style={{
              width: 90,
              padding: "4px 8px",
              fontSize: "0.82rem",
              fontFamily: "var(--mono)",
            }}
          />
          <span className="muted" style={{ fontSize: "0.66rem" }}>
            {tepNativeIsDefault
              ? `Default ${tepNativeDefault.toFixed(2)}× — applied to TEP-native sources on TE rows`
              : `Custom ${Number(tepNativeInputValue).toFixed(2)}× — TEP-native sources on TE rows`}
          </span>
        </div>
        {!tepNativeIsDefault && (
          <div style={{ marginTop: 4, marginBottom: 6 }}>
            <button
              type="button"
              className="button-reset"
              style={{
                fontSize: "0.7rem",
                color: "var(--accent-gold, #4f9bec)",
                textDecoration: "underline",
                cursor: "pointer",
                padding: 0,
              }}
              onClick={() => update("tepNativeMultiplier", null)}
            >
              Reset to default ({tepNativeDefault.toFixed(2)}×)
            </button>
          </div>
        )}
        <p
          className="muted"
          style={{ fontSize: "0.68rem", marginTop: 4, marginBottom: 0 }}
        >
          Applied at blend time, on TE rows only.
          <InfoTip label="the two TE Premium multipliers">
          Two parallel TE Premium multipliers, both applied at blend time on TE
          rows only. <strong>Non-native</strong> covers sources whose published
          board doesn&apos;t already bake in TE premium (DLF, FBG, FP consensus,
          Flock, DD, DraftSharks). <strong>Native</strong> covers sources tagged{" "}
          <span
            style={{
              fontFamily: "var(--mono)",
              fontSize: "0.62rem",
              padding: "0 4px",
              border: "1px solid var(--green, #4ade80)",
              color: "var(--green, #4ade80)",
              borderRadius: 3,
            }}
          >
            TEP NATIVE
          </span>{" "}
          (IDPTC, DN SfTep, Yahoo Boone, FP Fitzmaurice) — their boards already
          publish some TE premium so the smaller default (1.10×) is a
          calibration nudge, not a fresh boost. KTC (standard SF and SF-TE++) is
          the canonical baseline and passes through both knobs unchanged.
          Changing either value re-runs the canonical ranking pipeline so every
          page (rankings, trade calculator, edge) sees the same values.
        </InfoTip>
        </p>
      </Section>

      </SettingsGroup>

      <SettingsGroup
        title="How values are calculated"
        description="Tuning for the valuation engine. The defaults are sensible; change these only if you want a different board."
      >
      <Section title="Trade Calculation" defaultOpen>
        <SliderRow
          label="Trade History Window"
          value={settings.tradeHistoryWindowDays}
          min={30}
          max={730}
          step={30}
          onChange={(v) => update("tradeHistoryWindowDays", v)}
          hint={`${settings.tradeHistoryWindowDays} days`}
        />
        <SliderRow
          label="Suggestion Pool Cap"
          value={settings.ktcSuggestionTopN ?? 150}
          min={50}
          max={300}
          step={10}
          onChange={(v) => update("ktcSuggestionTopN", v)}
          hint={`Top ${settings.ktcSuggestionTopN ?? 150} KTC offense players considered for trade suggestions`}
        />
        <p
          className="muted"
          style={{ fontSize: "0.7rem", marginTop: 4, marginBottom: 0 }}
        >
          Default 150 suits a standard 12-team Superflex league.
          <InfoTip label="the suggestion pool cap">
            <p>
              Raise it for deeper formats (14-team 2QB, deep-IDP keeper) where
              the bottom 50 of your roster pool sits below KTC #150 but is
              genuinely traded.
            </p>
            <p>Picks and IDP are unaffected by this cap.</p>
          </InfoTip>
        </p>
      </Section>

      <Section title="Valuation" defaultOpen>
        <div
          style={{ fontSize: "0.72rem", marginBottom: 10 }}
          className="muted"
        >
          This is the only setting that changes the numbers themselves. It
          applies everywhere — rankings, the trade calculator, exports.
        </div>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: "0.82rem", marginRight: 8 }}>
            Value basis
          </label>
          {/* A <select> has no honest indeterminate state — a blank
              option would read as a third choice — so this one stays
              disabled until settings hydrate instead. The displayed
              value is still the default for that one frame, but the
              control cannot be acted on while it might be about to
              change under the user's cursor. The /rankings and /trade
              toggles get the stronger treatment (no highlight at all);
              see the note above `getHydratedSnapshot` in useSettings. */}
          <select
            className="select"
            value={settings.valuationMode}
            disabled={!settingsHydrated}
            aria-busy={!settingsHydrated}
            onChange={(e) => update("valuationMode", e.target.value)}
          >
            <option value="market">Market</option>
            <option value="leagueAdjusted">My league</option>
          </select>
        </div>
        <div
          style={{ fontSize: "0.72rem", lineHeight: 1.55 }}
          className="muted"
        >
          <p>
            <strong>Market</strong> — the blended consensus board exactly as the
            pipeline computes it. Shared by every league on the same scoring
            settings.
          </p>
          <p>
            <strong>My league</strong> — takes that board and re-prices it by
            how scarce each position actually is here. We solve your exact
            starting lineup against the 12 real rosters, measure the drop-off
            from the best player at a position to the last startable one, and
            scale every player at that position by up to ±10%. Thin positions
            lift; deep positions trim. Ranks and tiers are recomputed on the
            backend.
          </p>
          {/* The two definitions above are the choice being made and
              stay visible.  The rest — scope, exclusions, interaction
              with custom weights — is reference material a user reads
              once, so it moves behind a button instead of occupying
              three paragraphs above the next control. */}
          <HelpModal
            title="How the league-adjusted board works"
            label="What this changes"
          >
            <h3>What it does not include, deliberately</h3>
            <p>
              <strong>No tight-end premium.</strong> Our market anchor is
              already KTC&apos;s TE++ board, so applying another would count the
              same premium twice.
            </p>
            <p>
              <strong>No player projections.</strong> No source we can use
              publishes raw statistical categories yet, so there is nothing to
              re-score under your rules.
            </p>
            <p>
              <strong>No per-player judgment.</strong> The adjustment is
              identical for every player at a position, so it can never reorder
              your RBs against each other.
            </p>
            <h3>What it does change</h3>
            <p>
              How positions — and <strong>players versus draft picks</strong> —
              are priced against one another. Picks carry no scarcity
              measurement, so they stay at market value while players move
              around them. That is enough to shift most ranks and to change
              trade verdicts.
            </p>
            <h3>When it does not apply</h3>
            <p>
              Not applied while custom source weights are active: the two cannot
              be combined correctly yet, so the board stays on your custom
              market values.
            </p>
          </HelpModal>
        </div>
      </Section>

      <Section title="Rankings Display" defaultOpen>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: "0.82rem", marginRight: 8 }}>
            Sort Basis
          </label>
          <select
            className="select"
            value={settings.rankingsSortBasis}
            onChange={(e) => update("rankingsSortBasis", e.target.value)}
          >
            <option value="full">Our Value</option>
            <option value="raw">Raw Composite</option>
          </select>
        </div>
        <ToggleRow
          label="Show source site columns"
          checked={settings.showSiteCols}
          onChange={(v) => update("showSiteCols", v)}
          hint="Per-site value columns in rankings"
        />
      </Section>

      <Section title="Ranking Sources" defaultOpen>
        <div
          style={{ fontSize: "0.72rem", marginBottom: 10 }}
          className="muted"
        >
          Every registered source contributes equally (default weight 1.0) to
          the blended consensus rank. Toggle a source off or adjust its weight
          to recompute the board with your own mix. Changing any knob flips the
          rankings page into override mode so your settings materially affect
          the displayed rank and value; clearing the overrides returns to the
          canonical server blend. IDP Trade Calculator is the IDP backbone and
          also feeds offense via its secondary scope. Backend registry:{" "}
          <code style={{ fontFamily: "var(--mono)" }}>
            src/api/data_contract.py
          </code>
          .
        </div>
        <div
          style={{
            display: "flex",
            gap: 8,
            marginBottom: 10,
            flexWrap: "wrap",
          }}
        >
          {Object.values(WEIGHT_PRESETS).map((preset) => {
            const active =
              detectActivePreset(settings?.siteWeights) === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                className={`button${active ? " button-primary" : ""}`}
                style={{ fontSize: "0.72rem" }}
                title={preset.description}
                onClick={() =>
                  update("siteWeights", presetToWeights(preset.key))
                }
              >
                {preset.label}
                {active ? " ✓" : ""}
              </button>
            );
          })}
          <button
            className="button"
            onClick={resetSiteWeights}
            style={{ fontSize: "0.72rem" }}
          >
            Reset source weights
          </button>
        </div>
        <SourceTable
          title="Offense"
          sources={sourcesByGroup.offense}
          onToggle={(key, include) => updateSiteWeight(key, "include", include)}
          onWeight={(key, weight) => updateSiteWeight(key, "weight", weight)}
        />
        <div style={{ height: 12 }} />
        <SourceTable
          title="IDP"
          sources={sourcesByGroup.idp}
          onToggle={(key, include) => updateSiteWeight(key, "include", include)}
          onWeight={(key, weight) => updateSiteWeight(key, "weight", weight)}
        />
      </Section>

      <Section title="Rest-of-Season Engine" defaultOpen={false}>
        <p
          className="muted"
          style={{ fontSize: "0.72rem", marginTop: 0, marginBottom: 10 }}
        >
          The ROS engine is a separate short-term contender layer.{" "}
          <strong>
            It never modifies dynasty rankings or trade-calculator math.
          </strong>{" "}
          These flags only control which surfaces show ROS context.
        </p>
        <ToggleRow
          label="Enable ROS engine"
          checked={settings.rosEnabled !== false}
          onChange={(v) => update("rosEnabled", v)}
          hint="Master switch.  Off hides every ROS-driven surface (Power v2, Championship tab, Trade-deadline dashboard, ROS Fit panel, player tags)."
        />
        <ToggleRow
          label="Use ROS-driven Power Rankings"
          checked={!!settings.useRosPowerRankings}
          onChange={(v) => update("useRosPowerRankings", v)}
          hint="Swap the /league Power tab from the v1 PPG/all-play formula to the ROS-driven 9-input v2.  Defaults off until you've validated v2 against a few weeks of standings."
        />
        <ToggleRow
          label="Use ROS-driven Playoff Odds"
          checked={!!settings.useRosPlayoffOdds}
          onChange={(v) => update("useRosPlayoffOdds", v)}
          hint="When enabled, the playoff Monte Carlo uses ROS-blended weekly score distributions instead of empirical-only.  PR-future toggle for the playoff-odds section swap; ROS Championship tab uses ROS by default."
        />
        <ToggleRow
          label="Show ROS Fit panel on Trade Calculator"
          checked={settings.showRosTradePanel !== false}
          onChange={(v) => update("showRosTradePanel", v)}
          hint="Adds an informational panel below the per-source winner table on /trade.  Surfaces buyer/seller direction + per-player tags.  Does NOT change trade math."
        />
        <ToggleRow
          label="Show ROS context tags on player popups"
          checked={settings.showRosTags !== false}
          onChange={(v) => update("showRosTags", v)}
          hint="Appends a Short-term context section to PlayerPopup with ROS value, rank, tier, and tags like Win-now target / Seller cash-out / Rebuilder hold."
        />
        <div
          style={{
            display: "flex",
            gap: 10,
            alignItems: "center",
            marginTop: 14,
          }}
        >
          <label style={{ fontSize: "0.82rem", minWidth: 200 }}>
            Monte Carlo simulations
          </label>
          <input
            type="number"
            min={1000}
            max={100000}
            step={1000}
            value={settings.rosSimulationCount ?? 10000}
            onChange={(e) =>
              update(
                "rosSimulationCount",
                Math.max(
                  1000,
                  Math.min(100000, parseInt(e.target.value) || 10000),
                ),
              )
            }
            className="input"
            style={{ width: 100 }}
          />
          <span style={{ fontSize: "0.72rem", color: "var(--subtext)" }}>
            higher = tighter tails, slower section load
          </span>
        </div>
        <RosSourceTable
          overrides={settings.rosSourceOverrides || {}}
          onToggle={(key, enabled) => {
            const next = { ...(settings.rosSourceOverrides || {}) };
            const cur = next[key] || {};
            next[key] = { ...cur, enabled };
            update("rosSourceOverrides", next);
          }}
          onWeight={(key, weight) => {
            const next = { ...(settings.rosSourceOverrides || {}) };
            const cur = next[key] || {};
            next[key] = { ...cur, weight };
            update("rosSourceOverrides", next);
          }}
          onResetSource={(key) => {
            const next = { ...(settings.rosSourceOverrides || {}) };
            delete next[key];
            update("rosSourceOverrides", next);
          }}
        />
        <p
          className="muted"
          style={{ fontSize: "0.7rem", marginTop: 12, marginBottom: 0 }}
        >
          Diagnostic + scrape-now controls live at{" "}
          <a href="/tools/ros-data-health" style={{ color: "var(--cyan)" }}>
            /tools/ros-data-health
          </a>
          . Overrides apply on the next admin Refresh — scheduled scrapes run
          with registry defaults.
        </p>
      </Section>

      </SettingsGroup>

      <SettingsGroup
        title="Alerts &amp; lists"
        description="What the site tells you about, and which players you are tracking."
      >
      <Section title="Notifications" defaultOpen={false}>
        {serverBacked ? (
          <>
            <ToggleRow
              label="Email me daily signal alerts"
              checked={!!userState?.notificationsEnabled}
              onChange={toggleEnabled}
              hint="Buy/sell/injury/roster digest, sent once per day when you have live signals."
            />
            <div
              style={{
                display: "flex",
                gap: 8,
                alignItems: "center",
                marginTop: 8,
                flexWrap: "wrap",
              }}
            >
              <label style={{ fontSize: "0.82rem", minWidth: 100 }}>
                Email address
              </label>
              <input
                type="email"
                className="input"
                value={emailDraft}
                placeholder="you@example.com"
                onChange={(e) => setEmailDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveEmail();
                }}
                style={{ flex: "1 1 260px", maxWidth: 360 }}
              />
              <button
                className="button"
                onClick={saveEmail}
                style={{ fontSize: "0.76rem" }}
              >
                Save
              </button>
              {emailDraft && (
                <button
                  className="button"
                  onClick={() => {
                    setEmailDraft("");
                    setNotifications({ email: null });
                    setEmailStatus("Email cleared.");
                    setTimeout(() => setEmailStatus(""), 2500);
                  }}
                  style={{ fontSize: "0.76rem" }}
                >
                  Clear
                </button>
              )}
            </div>
            {emailStatus && (
              <div
                className="muted"
                style={{
                  fontSize: "0.72rem",
                  marginTop: 6,
                  color: "var(--green)",
                }}
              >
                {emailStatus}
              </div>
            )}
            <p
              className="muted"
              style={{ fontSize: "0.7rem", marginTop: 10, marginBottom: 0 }}
            >
              Alerts fire once per day when the signal engine finds something
              notable on your roster — buy-low / sell-high opportunities, injury
              news, rookie or pick movement. We only email you when there&apos;s
              a change worth acting on.
            </p>
            <div
              style={{
                marginTop: 14,
                paddingTop: 12,
                borderTop: "1px solid var(--border)",
              }}
            >
              <PushNotificationToggle enabled={!!serverBacked} />
            </div>
          </>
        ) : (
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            Sign in to enable email notifications. Your notification preferences
            are stored on the server and apply across devices.
          </p>
        )}
      </Section>

      <Section title="Watchlist" defaultOpen={false}>
        <div
          style={{
            fontSize: "0.78rem",
            color: "var(--subtext)",
            marginBottom: 8,
          }}
        >
          Players you star (here or via the ☆ on Rankings / a player card).
          {serverBacked
            ? " Synced across your devices."
            : " Saved on this device."}
        </div>
        <div
          style={{
            display: "flex",
            gap: 6,
            marginBottom: 10,
            flexWrap: "wrap",
          }}
        >
          <input
            className="input"
            value={watchAddName}
            placeholder="Add player by name"
            list="brisket-watchlist-player-list"
            onChange={(e) => setWatchAddName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && watchAddName.trim()) {
                toggleWatchlist(watchAddName.trim());
                setWatchAddName("");
              }
            }}
            style={{ flex: "1 1 220px", minWidth: 180, fontSize: "0.8rem" }}
          />
          <datalist id="brisket-watchlist-player-list">
            {(rows || [])
              .map((p) => p?.name || p?.displayName)
              .filter((n) => typeof n === "string" && n.length > 0)
              .slice(0, 800)
              .map((n) => (
                <option key={n} value={n} />
              ))}
          </datalist>
          <button
            type="button"
            className="button"
            disabled={!watchAddName.trim()}
            onClick={() => {
              if (watchAddName.trim()) {
                toggleWatchlist(watchAddName.trim());
                setWatchAddName("");
              }
            }}
          >
            Add
          </button>
        </div>
        {(userState?.watchlist || []).length === 0 ? (
          <div style={{ fontSize: "0.78rem", color: "var(--subtext)" }}>
            No players on your watchlist yet.
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            {(userState.watchlist || []).map((name) => (
              <div
                key={name}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  gap: 10,
                  fontSize: "0.82rem",
                  borderBottom: "1px solid var(--border)",
                  padding: "4px 0",
                }}
              >
                <span>{name}</span>
                <button
                  type="button"
                  className="button-reset"
                  title="Remove from watchlist"
                  onClick={() => toggleWatchlist(name)}
                  style={{
                    cursor: "pointer",
                    color: "var(--subtext)",
                    padding: "0 6px",
                  }}
                >
                  ☆ remove
                </button>
              </div>
            ))}
          </div>
        )}
      </Section>

      <Section title="Custom alerts" defaultOpen={false}>
        <CustomAlertsConfigurator enabled={!!serverBacked} players={rows} />
      </Section>

      </SettingsGroup>

      <div
        className="muted"
        style={{
          fontSize: "0.72rem",
          marginTop: 12,
          padding: "8px 0",
          borderTop: "1px solid var(--border)",
        }}
      >
        Settings are saved automatically to your browser. They affect trade
        calculations, rankings display, and value composites.
        {isAdmin ? (
          <>
            {" "}
            Server status, manual scrapes and guest passes moved to{" "}
            <Link href="/admin" style={{ color: "var(--cyan)" }}>
              Admin
            </Link>
            .
          </>
        ) : null}
      </div>
    </section>
  );
}

function SourceTable({ title, sources, onToggle, onWeight }) {
  if (!sources || !sources.length) {
    return (
      <div className="muted" style={{ fontSize: "0.76rem" }}>
        No {title.toLowerCase()} sources registered.
      </div>
    );
  }
  return (
    <div>
      <div style={{ fontWeight: 600, fontSize: "0.78rem", marginBottom: 6 }}>
        {title}
      </div>
      <div className="table-wrap settings-sources-wrap">
        <table className="settings-sources-table">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "6px 8px" }}>Source</th>
              <th
                className="settings-src-col-role"
                style={{ textAlign: "left", padding: "6px 8px" }}
              >
                Role
              </th>
              <th
                style={{ textAlign: "center", padding: "6px 8px" }}
                title="Include this source in rank blending"
              >
                On
              </th>
              <th
                style={{ textAlign: "right", padding: "6px 8px" }}
                title="Weight applied to this source in the blend. Default 1.0"
              >
                Weight
              </th>
              <th
                className="settings-src-col-covered"
                style={{ textAlign: "right", padding: "6px 8px" }}
              >
                Covered
              </th>
              <th
                className="settings-src-col-status"
                style={{ textAlign: "center", padding: "6px 8px" }}
              >
                Status
              </th>
            </tr>
          </thead>
          <tbody>
            {sources.map((src) => {
              const role = src.isRetail
                ? "Retail market"
                : src.isBackbone
                  ? "Backbone (IDP)"
                  : "Expert consensus";
              const statusLabel = src.live ? "Live" : "Idle";
              const statusColor = src.live ? "var(--green)" : "var(--subtext)";
              const enabled = src.userInclude !== false;
              return (
                <tr
                  key={src.key}
                  style={{
                    borderBottom: "1px solid var(--border-dim)",
                    opacity: enabled ? 1 : 0.45,
                  }}
                >
                  <td style={{ padding: "6px 8px" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ fontWeight: 600 }}>{src.displayName}</span>
                      {/* Role badge — visible only on mobile where the
                          dedicated Role column is hidden to save horizontal
                          space. */}
                      <span
                        className="badge settings-src-role-mobile"
                        style={{ fontSize: "0.58rem", padding: "1px 5px" }}
                      >
                        {role}
                      </span>
                      {/* Status dot — visible only on mobile; mirrors the
                          dedicated Status column. */}
                      <span
                        className="settings-src-status-mobile"
                        aria-label={statusLabel}
                        title={statusLabel}
                        style={{ background: statusColor }}
                      />
                      {src.isTepPremium && (
                        <span
                          className="badge"
                          style={{
                            fontSize: "0.58rem",
                            padding: "1px 5px",
                            background:
                              "var(--green-dim, rgba(80,200,120,0.18))",
                            color: "var(--green, #4ade80)",
                            border: "1px solid var(--green, #4ade80)",
                            borderRadius: 3,
                            letterSpacing: 0.3,
                            fontWeight: 700,
                          }}
                        >
                          TEP NATIVE
                        </span>
                      )}
                      {src.isTepPremium && (
                        <InfoTip label="TEP NATIVE">
                          This source&apos;s published ranks already bake in TE
                          premium, so the global TE Premium multiplier does not
                          need to compensate for it.
                        </InfoTip>
                      )}
                    </div>
                    <div
                      className="muted"
                      style={{ fontSize: "0.64rem", fontFamily: "var(--mono)" }}
                    >
                      {src.columnLabel} · {src.key}
                      <span className="settings-src-covered-mobile">
                        {" · "}
                        {src.covered} covered
                      </span>
                    </div>
                  </td>
                  <td
                    className="settings-src-col-role"
                    style={{ padding: "6px 8px", fontSize: "0.72rem" }}
                  >
                    {role}
                  </td>
                  <td style={{ padding: "6px 8px", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => onToggle?.(src.key, e.target.checked)}
                      aria-label={`Include ${src.displayName} in blend`}
                      className="settings-src-toggle"
                      style={{ cursor: "pointer" }}
                    />
                  </td>
                  <td
                    style={{
                      padding: "6px 8px",
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                    }}
                  >
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.1}
                      value={Number(src.userWeight).toFixed(1)}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        if (Number.isFinite(v) && v >= 0)
                          onWeight?.(src.key, v);
                      }}
                      disabled={!enabled}
                      className="input weight-input"
                      style={{
                        textAlign: "right",
                        fontFamily: "var(--mono)",
                      }}
                      aria-label={`${src.displayName} weight`}
                    />
                  </td>
                  <td
                    className="settings-src-col-covered"
                    style={{
                      padding: "6px 8px",
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                      color: "var(--subtext)",
                    }}
                  >
                    {src.covered}
                  </td>
                  <td
                    className="settings-src-col-status"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      fontSize: "0.68rem",
                      fontWeight: 700,
                      color: statusColor,
                    }}
                  >
                    {statusLabel}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RosSourceTable({ overrides, onToggle, onWeight, onResetSource }) {
  // Triggers an admin scrape with the user's overrides in the body.
  // Falls back to plain "no-body" call if the user hasn't customized
  // anything — server applies registry defaults either way.
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState("");

  const apply = async () => {
    setSubmitting(true);
    setFeedback("");
    try {
      const body = {};
      if (overrides && Object.keys(overrides).length > 0) {
        body.sourceOverrides = overrides;
      }
      const res = await fetch("/api/ros/refresh", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const text = await res.text().catch(() => "");
        if (res.status === 401) {
          setFeedback("Admin session required.");
        } else {
          setFeedback(
            `Refresh failed (HTTP ${res.status}): ${text.slice(0, 120)}`,
          );
        }
      } else {
        const data = await res.json().catch(() => ({}));
        setFeedback(
          `Refreshed ${data.ranSources?.length ?? "?"} sources · ` +
            `aggregate=${data.playerCount ?? "?"} players`,
        );
      }
    } catch (err) {
      setFeedback(`Network error: ${err.message || err}`);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ fontWeight: 600, fontSize: "0.78rem", marginBottom: 6 }}>
        ROS Sources ({ROS_SOURCES.length})
      </div>
      <div className="table-wrap settings-sources-wrap">
        <table className="settings-sources-table">
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "6px 8px" }}>Source</th>
              <th
                className="settings-src-col-role"
                style={{ textAlign: "left", padding: "6px 8px" }}
              >
                Type
              </th>
              <th style={{ textAlign: "center", padding: "6px 8px" }}>On</th>
              <th style={{ textAlign: "right", padding: "6px 8px" }}>Weight</th>
              <th
                className="settings-src-col-status"
                style={{ textAlign: "center", padding: "6px 8px" }}
              >
                Default
              </th>
            </tr>
          </thead>
          <tbody>
            {ROS_SOURCES.map((src) => {
              const ov = overrides?.[src.key] || {};
              const enabled = ov.enabled !== false;
              const weight = Number.isFinite(Number(ov.weight))
                ? Number(ov.weight)
                : Number(src.baseWeight ?? 1.0);
              const customized =
                ov.enabled === false ||
                (Number.isFinite(Number(ov.weight)) &&
                  Math.abs(Number(ov.weight) - Number(src.baseWeight ?? 1.0)) >
                    1e-6);
              const sourceTypeLabel = src.isRos
                ? "Real ROS"
                : src.isDynasty
                  ? "Dynasty proxy"
                  : src.sourceType || "—";
              return (
                <tr
                  key={src.key}
                  style={{
                    borderBottom: "1px solid var(--border-dim)",
                    opacity: enabled ? 1 : 0.45,
                  }}
                >
                  <td style={{ padding: "6px 8px" }}>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        flexWrap: "wrap",
                      }}
                    >
                      <span style={{ fontWeight: 600 }}>{src.displayName}</span>
                      {src.isIdp && (
                        <span
                          className="badge"
                          style={{
                            fontSize: "0.58rem",
                            padding: "1px 5px",
                            background: "rgba(80, 160, 255, 0.18)",
                            color: "var(--cyan)",
                            border: "1px solid var(--cyan)",
                            borderRadius: 3,
                          }}
                        >
                          IDP
                        </span>
                      )}
                      {src.isSuperflex && (
                        <span
                          className="badge"
                          style={{
                            fontSize: "0.58rem",
                            padding: "1px 5px",
                            border: "1px solid var(--subtext)",
                            color: "var(--subtext)",
                            borderRadius: 3,
                          }}
                        >
                          SF
                        </span>
                      )}
                    </div>
                    <div
                      style={{
                        fontSize: "0.66rem",
                        color: "var(--subtext)",
                        marginTop: 2,
                      }}
                    >
                      {src.key}
                    </div>
                  </td>
                  <td
                    className="settings-src-col-role"
                    style={{
                      padding: "6px 8px",
                      fontSize: "0.74rem",
                      color: "var(--subtext)",
                    }}
                  >
                    {sourceTypeLabel}
                  </td>
                  <td style={{ padding: "6px 8px", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => onToggle(src.key, e.target.checked)}
                      className="settings-src-toggle"
                      style={{ cursor: "pointer" }}
                    />
                  </td>
                  <td
                    style={{
                      padding: "6px 8px",
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                    }}
                  >
                    <input
                      type="number"
                      min={0}
                      max={5}
                      step={0.05}
                      value={weight.toFixed(2)}
                      onChange={(e) => {
                        const v = Number(e.target.value);
                        if (Number.isFinite(v) && v >= 0 && v <= 5) {
                          onWeight(src.key, v);
                        }
                      }}
                      className="input"
                      style={{ width: 64, textAlign: "right" }}
                      disabled={!enabled}
                    />
                  </td>
                  <td
                    className="settings-src-col-status"
                    style={{
                      padding: "6px 8px",
                      textAlign: "center",
                      fontSize: "0.7rem",
                      color: "var(--subtext)",
                    }}
                  >
                    {customized ? (
                      <button
                        type="button"
                        className="button-reset"
                        onClick={() => onResetSource(src.key)}
                        title="Reset to registry default"
                        style={{
                          color: "var(--cyan)",
                          textDecoration: "underline",
                          cursor: "pointer",
                          fontSize: "0.68rem",
                        }}
                      >
                        reset ({Number(src.baseWeight ?? 1.0).toFixed(2)})
                      </button>
                    ) : (
                      <span style={{ fontFamily: "var(--mono)" }}>
                        {Number(src.baseWeight ?? 1.0).toFixed(2)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 12,
          marginTop: 10,
        }}
      >
        <button
          type="button"
          className="button button-primary"
          onClick={apply}
          disabled={submitting}
        >
          {submitting ? "Refreshing..." : "Apply now (admin refresh)"}
        </button>
        <span style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
          {feedback ||
            "Triggers POST /api/ros/refresh — re-runs the orchestrator with these overrides."}
        </span>
      </div>
    </div>
  );
}

// ── Guest pass panel ──────────────────────────────────────────────────
//
// Generates time-bounded guest passwords the owner can share.  A pass
// gives a guest read access to the private surface for the chosen
// duration; the server-side session expires alongside the pass.  See
// ``src/api/guest_passes.py`` for the storage model + validation
// flow.  Endpoints:
//
//   POST /api/admin/guest-pass         — body {durationHours, note}
//   GET  /api/admin/guest-passes       — list active + expired/revoked
//   POST /api/admin/guest-pass/:id/revoke — kill a pass immediately
//
// Plaintext tokens are displayed exactly once — when the user clicks
// "Generate".  After that the panel only shows metadata (note, ID,
// expiry, status).  This mirrors how every "API key" UI works and
// prevents the token from leaking via DOM scraping or screenshot
// later.


