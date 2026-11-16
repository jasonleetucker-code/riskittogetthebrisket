"use client";

import { Suspense, lazy, useCallback, useEffect, useId, useMemo, useState } from "react";
import Link from "next/link";
import { useDynastyData } from "@/components/useDynastyData";
import { useAuthContext } from "@/app/AppShellWrapper";
import { FailureState, InfoTip, Modal } from "@/components/ds";
import { useSettings } from "@/components/useSettings";
import { useUserState } from "@/components/useUserState";
import { RANKING_SOURCES, siteOverridesAreCustomized } from "@/lib/dynasty-data";
import { sourceVoteFields } from "@/lib/source-vote-state";
import { ROS_SOURCES } from "@/lib/ros-sources";
import {
  votingStatusAvailability,
  votingStatusBlock,
  votingStatusRows,
} from "@/lib/source-voting-status";
import PushNotificationToggle from "@/components/PushNotificationToggle";
import CustomAlertsConfigurator from "@/components/CustomAlertsConfigurator";
import { useLeague } from "@/components/useLeague";

// Code-split (React.lazy, not next/dynamic — see CLAUDE.md "Perfect Draft"):
// the editor sits in a collapsed section and loads only when opened.
const TradeProtectionsEditor = lazy(() => import("@/components/TradeProtectionsEditor"));
// The Source Voting table (owner directive 2026-10-19 §8) is split the same
// way: a static import put DataTable + the ds status primitives on this
// page's critical path (page + shared chunks 180.1 -> 208.3 KB, measured);
// lazy keeps that at 186.5 KB and loads the table just after first paint.
const SourceVotingStatus = lazy(() => import("@/components/SourceVotingStatus"));

// Custom source mixes are switched off on the server
// (`_SOURCE_OVERRIDES_DISABLED` in src/api/data_contract.py): a stored
// include/weight mix is accepted and ignored, and the board is always the
// canonical consensus blend.  The Ranking Sources table therefore offers no
// operable include/weight control; it shows the registry's own declared
// state, disabled, and says why.
const CUSTOM_MIX_OFF_NOTE =
  "Custom source mixes are switched off. Every value on the site uses the " +
  "canonical consensus blend, so the include switches and weights below are " +
  "shown for reference only and cannot be changed.";

// Status colour is SECONDARY to the label text (never colour alone).  The
// tone comes from the backend status code via lib/source-voting-status.js.
const STATUS_TONE_COLOR = {
  positive: "var(--green)",
  warning: "var(--amber)",
  negative: "var(--red)",
  neutral: "var(--subtext)",
};

// "Reset Defaults" restores this device's preferences, but a team choice is
// not a preference: wiping it silently re-points every league-scoped page at
// whatever team auto-selection picks next.  These keys survive the reset.
const RESET_PRESERVED_KEYS = [
  "selectedTeam",
  "selectedTeamTouched",
  "selectedTeamsByLeague",
  "selectedTeamTouchedByLeague",
];

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
        {/* A function child mounts only while open, so a lazily loaded
            panel's chunk is fetched when someone opens it, not on page load. */}
        {typeof children === "function" ? (open ? children() : null) : children}
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
  // `useId` rather than a slug of `label`: two rows could share a label,
  // and a duplicate `id` silently points both labels at the first input.
  const inputId = useId();
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 10,
        marginBottom: 8,
      }}
    >
      {/* `htmlFor`, because the label is a SIBLING of the input, not a
          wrapper.  Without it a screen reader announces "slider, 365" —
          every valuation control on this page was unnamed, which is the
          page that changes what every number in the app means. */}
      <label htmlFor={inputId} style={{ minWidth: 100, fontSize: "0.82rem" }}>
        {label}
      </label>
      <input
        id={inputId}
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
  const { loading, failure, rows, rawData, retry } = useDynastyData();
  // Stable ids so each sibling <label> can point at its control.  Every
  // numeric valuation control on this page reached assistive tech
  // unnamed until 2026-08-18 — the labels were siblings, not wrappers.
  const emailInputId = useId();
  const customMixNoteId = useId();
  // Only to point an operator at where the moved panels went; nothing
  // on this page is gated by it.
  const { isAdmin } = useAuthContext();
  const { settings, update, resetSiteWeights, reset } = useSettings();
  const [confirmResetOpen, setConfirmResetOpen] = useState(false);
  // A mix saved on this device before custom mixes were switched off.  It
  // is ignored by the server; the page names it and offers to clear it.
  const hasSavedSourceMix = useMemo(
    () => siteOverridesAreCustomized(settings?.siteWeights),
    [settings?.siteWeights],
  );
  const {
    state: userState,
    serverBacked,
    setNotifications,
    toggleWatchlist,
  } = useUserState();
  const { selectedLeague, selectedLeagueKey } = useLeague();
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

  // Confirmed reset: restore defaults, then put the team selection back.
  // `update("selectedTeam", …)` marks the selection touched, so the saved
  // touched flags are restored after it (RESET_PRESERVED_KEYS order).
  function resetToDefaults() {
    const kept = RESET_PRESERVED_KEYS.map((key) => [key, settings?.[key]]);
    reset();
    for (const [key, value] of kept) {
      if (value !== undefined) update(key, value);
    }
    setConfirmResetOpen(false);
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
  // Parallel "TEP-native" multiplier — the per-bucket boost applied
  // to TEP-native sources (DN SF-TEP, Yahoo Boone, FP Fitzmaurice)
  // on TE rows.  Mirrors the non-TEP knob above; default 1.10.
  const tepNativeDefault = (() => {
    const v = Number(rawData?.rankingsOverride?.tepNativeMultiplierDerived);
    return Number.isFinite(v) ? v : 1.1;
  })();
  // Split the canonical registry into offense / IDP groups by the
  // declared scope field.  idpTradeCalc is listed under IDP (its
  // primary backbone scope) even though its `extraScopes` also
  // contribute to offense rankings — that's a calculation detail.
  //
  // Status and "Voting on" are the BACKEND's: the contract's
  // `sourceVotingStatus` block (src/sources/voting_status.py), read through
  // lib/source-voting-status.js — the same block the Source Voting table
  // above renders.  They used to be computed here from
  // `rows[*].canonicalSites`, which only says a source has a value on a row,
  // not that it voted: a stale or held source still showed a green "Live",
  // and before the board loaded every source showed "Idle".  A source the
  // block does not report is labelled as such — never "Live", never 0.
  const votingBlock = votingStatusBlock(rawData);
  const votingByKey = useMemo(() => {
    const map = new Map();
    if (!votingStatusAvailability(votingBlock).available) return map;
    for (const row of votingStatusRows(votingBlock)) map.set(row.key, row);
    return map;
  }, [votingBlock]);
  const statusPendingLabel = loading && !rawData ? "Loading…" : "Not reported";
  const sourcesByGroup = useMemo(() => {
    const decorate = (src) => {
      // Private sources carry a backend vote state.  A source that is not
      // voting (Signals IDP in shadow) is shown with its state and offers
      // no include/weight control — a control would imply it moves the
      // blend, and it does not.
      const vote = sourceVoteFields(
        rawData?.privateSourceAvailability?.[src.key],
      );
      const backend = votingByKey.get(src.key) || null;
      let statusLabel = statusPendingLabel;
      let statusTone = "neutral";
      if (backend) {
        statusLabel = backend.statusLabel;
        statusTone = backend.tone;
      } else if (vote.nonVoting) {
        statusLabel = vote.voteLabel;
      }
      return {
        ...src,
        ...vote,
        statusLabel,
        statusTone,
        statusReason: backend?.reason || null,
        playersVoting: backend ? backend.playersContributing : null,
        picksVoting: backend ? backend.picksContributing : null,
        defaultWeight: Number(src.weight ?? 1),
        isTepPremium: src.isTepPremium === true,
      };
    };
    return {
      offense: RANKING_SOURCES.filter((s) => s.scope === "overall_offense").map(
        decorate,
      ),
      // Family-scoped IDP boards (Signals DL / LB / DB) are IDP sources too.
      idp: RANKING_SOURCES.filter(
        (s) => s.scope === "overall_idp" || s.scope === "position_idp",
      ).map(decorate),
    };
  }, [votingByKey, statusPendingLabel, rawData?.privateSourceAvailability]);

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
            Preferences for trade tools, rankings display and alerts. None of
            them changes a player&apos;s dynasty value.
          </p>
        </div>
        <button
          type="button"
          className="button"
          onClick={() => setConfirmResetOpen(true)}
          style={{ fontSize: "0.76rem" }}
        >
          Reset Defaults
        </button>
      </div>

      {/* Reset used to fire on one click and wipe every key in this
          device's settings — including the team selected in every league,
          the FAAB risk posture and hidden Rankings columns, none of which
          live on this page.  It now asks first, says what it resets, and
          keeps the team selection. */}
      <Modal
        open={confirmResetOpen}
        onClose={() => setConfirmResetOpen(false)}
        title="Reset settings to defaults?"
      >
        <div data-testid="settings-reset-confirm" style={{ fontSize: "0.82rem" }}>
          <p style={{ marginTop: 0 }}>
            This restores the defaults for every preference saved on this
            device, including ones set on other pages: the FAAB risk posture
            on Waivers and the hidden columns on Rankings.
          </p>
          <p>
            Your selected team in each league is kept. Your watchlist, custom
            alerts and notification settings are not affected.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button
              type="button"
              className="button"
              onClick={() => setConfirmResetOpen(false)}
            >
              Cancel
            </button>
            <button
              type="button"
              className="button button-primary"
              onClick={resetToDefaults}
            >
              Reset settings
            </button>
          </div>
        </div>
      </Modal>

      {loading && <p role="status">Loading data…</p>}
      {/* Was a bare red <p>: no role, so nothing was announced; no
          primitive, so it looked like nothing else in the app; and no
          kind, so "you are signed out" and "the backend is down" and
          "the board is empty" were one sentence in one colour. */}
      {failure ? <FailureState failure={failure} onRetry={retry} /> : null}

      <SettingsGroup
        title="League &amp; scoring"
        description="How the board reads your league. These are facts of the league, not preferences."
      >
      <Section title="League Format" defaultOpen>
        {/* The Superflex / Standard (1QB) selector is gone: it wrote
            `leagueFormat` to this device's settings and nothing anywhere
            read it (verified 2026-11-16 — no reader in app/, components/,
            lib/ or the backend), so choosing "Standard" changed no number.
            The format is a fact of the league, not a preference. */}
        <p
          className="muted"
          data-testid="league-format-note"
          style={{ fontSize: "0.72rem", marginTop: 0, marginBottom: 10 }}
        >
          League format is not a setting: values come from the board built
          for your league&apos;s own scoring settings.
        </p>
        {/* The MANUAL TE-premium override is withdrawn (DEFECT-02, held for
            owner approval).  The two inputs used to post
            ``tep_multiplier`` / ``tep_native_multiplier`` from
            localStorage, which re-ran the blend and returned a different
            canonical ``rankDerivedValue`` per device; the server now ignores
            them (``data_contract._TEP_OVERRIDES_DISABLED``) and
            ``useDynastyData`` no longer sends them.  Shown read-only so the
            premium the board applies stays visible. */}
        <div
          data-testid="tep-premium-readonly"
          style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}
        >
          <div style={{ fontSize: "0.82rem" }}>
            TE premium — <strong>automatic</strong>
          </div>
          <span className="muted" style={{ fontSize: "0.66rem" }}>
            {`Non-TEP sources: the measured TE-basis curve, ~${tepDefault.toFixed(2)}× and up. ` +
              `TEP-native sources: ${tepNativeDefault.toFixed(2)}×. Applied at blend time, on TE rows only.`}
          </span>
          <span className="muted" style={{ fontSize: "0.66rem" }}>
            Manual TE-premium overrides are no longer applied: every device sees the
            same canonical values.
          </span>
        </div>
      </Section>

      </SettingsGroup>

      <SettingsGroup
        title="How values are calculated"
        description="How the board is built, and how the trade and rankings tools use it. Nothing here changes a player's dynasty value."
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
          Values are always the market board. This is not a setting.
        </div>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: "0.82rem", marginRight: 8 }}>
            Value basis
          </label>
          {/* Read-only on purpose.  The "My league" lens was withdrawn
              2026-08-14 (CLAUDE.md, "valuation_mode: accepted, ignored,
              and stamped"): the server ignores the request and every
              fetch helper reads the basis through readValuationMode(),
              which is always market.  The control stays only so the
              basis is visible, so it shows market whatever an old
              device still has in localStorage, and it offers no other
              choice.  Do not re-thread a selector here. */}
          <select
            aria-label="Valuation mode"
            className="select"
            value="market"
            disabled
          >
            <option value="market">Market</option>
          </select>
        </div>
        <div
          style={{ fontSize: "0.72rem", lineHeight: 1.55 }}
          className="muted"
        >
          <p>
            <strong>Market</strong> — the blended consensus board from the
            canonical pipeline, shared by every league on the same scoring
            settings. Rankings, the trade calculator and exports all read it.
            The automatic TE premium above applies to it; custom source
            weights do not (they are switched off).
          </p>
          <p>
            The &quot;My league&quot; positional-scarcity lens was withdrawn and
            no longer changes any number. A device that still has it saved
            shows the market board like every other.
          </p>
        </div>
      </Section>

      <Section title="Rankings Display" defaultOpen>
        {/* "Sort Basis" (Our Value / Raw Composite) is gone: it wrote
            `rankingsSortBasis` and no page read it, so neither choice
            changed any order (verified 2026-11-16). */}
        <ToggleRow
          label="Show source site columns"
          checked={settings.showSiteCols}
          onChange={(v) => update("showSiteCols", v)}
          hint="Per-site value columns in rankings"
        />
      </Section>

      {/* Owner directive 2026-10-19 §8: every source's actual voting
          status on the canonical board — Last Updated, Freshness, Voting
          Weight, Status and why.  Read from the contract's
          `sourceVotingStatus` (already loaded; no second fetch).  Same
          component as /tools/source-health. */}
      <Section title="Source Voting" defaultOpen>
        <div
          style={{ fontSize: "0.72rem", marginBottom: 10 }}
          className="muted"
        >
          How each ranking source votes on the site&apos;s consensus values
          right now: when it last genuinely updated, how much voting power its
          freshness keeps, the weight it votes with, and why. This is exactly
          how the board is built: custom source weights are switched off.
          Full diagnostics are on{" "}
          <Link href="/tools/source-health">Source Health</Link>.
        </div>
        {!rawData && failure ? (
          <p className="muted" style={{ fontSize: "0.72rem" }}>
            Source voting status needs the board data, which did not load (see
            the message above).
          </p>
        ) : (
          <Suspense
            fallback={
              <p className="muted" role="status" style={{ fontSize: "0.72rem" }}>
                Loading source voting status…
              </p>
            }
          >
            <SourceVotingStatus
              block={votingStatusBlock(rawData)}
              loading={loading && !rawData}
              context="source voting status"
            />
          </Suspense>
        )}
      </Section>

      <Section title="Ranking Sources" defaultOpen>
        {/* This copy used to promise that toggling a source or changing its
            weight "recomputes the board with your own mix".  The server has
            ignored every custom mix since 2026-08-14
            (`_SOURCE_OVERRIDES_DISABLED`), so the switches, weights and the
            three weight presets changed nothing while the page said they
            did.  The presets are gone; the table shows the registry's own
            declared state, disabled. */}
        <p
          id={customMixNoteId}
          data-testid="custom-mix-off-note"
          style={{ fontSize: "0.76rem", marginTop: 0, marginBottom: 8 }}
        >
          <strong>{CUSTOM_MIX_OFF_NOTE}</strong>
        </p>
        <div
          style={{ fontSize: "0.72rem", marginBottom: 10 }}
          className="muted"
        >
          The registered sources and the role each plays. IDP Trade Calculator
          is the IDP backbone and also feeds offense via its secondary scope.
          Status and &quot;Voting on&quot; come from the board&apos;s own
          source voting report (see Source Voting above). Backend registry:{" "}
          <code style={{ fontFamily: "var(--mono)" }}>
            src/api/data_contract.py
          </code>
          .
        </div>
        {hasSavedSourceMix ? (
          <div
            data-testid="saved-source-mix"
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              marginBottom: 10,
              flexWrap: "wrap",
              fontSize: "0.72rem",
            }}
          >
            <span className="muted">
              This device still has a custom source mix saved from before. It
              is not applied to any value.
            </span>
            <button
              type="button"
              className="button"
              onClick={resetSiteWeights}
              style={{ fontSize: "0.72rem" }}
            >
              Clear saved source mix
            </button>
          </div>
        ) : null}
        <SourceTable
          title="Offense"
          sources={sourcesByGroup.offense}
          describedBy={customMixNoteId}
        />
        <div style={{ height: 12 }} />
        <SourceTable
          title="IDP"
          sources={sourcesByGroup.idp}
          describedBy={customMixNoteId}
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
        {/* Two controls were removed here (verified 2026-11-16): the
            "Enable ROS engine" master switch, whose hint promised it hid
            every ROS surface, and the "Monte Carlo simulations" count.  Each
            wrote a setting (`rosEnabled`, `rosSimulationCount`) that no page
            and no request ever read, so neither changed anything.  The two
            toggles below ARE read (RosTradeFitPanel, PlayerPopup). */}
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
              <label
                htmlFor={emailInputId}
                style={{ fontSize: "0.82rem", minWidth: 100 }}
              >
                Email address
              </label>
              <input
                id={emailInputId}
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
            aria-label="Add player to watchlist by name"
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

      <SettingsGroup
        title="Trade recommendations"
        description="Personal rules for generated trade ideas in the selected league. They never change any value."
      >
      <Section title="Trade protections" defaultOpen={false}>
        {() => (
          <Suspense fallback={<p className="muted" role="status">Loading trade protections…</p>}>
            <TradeProtectionsEditor
              enabled={!!serverBacked}
              leagueKey={selectedLeagueKey}
              leagueName={selectedLeague?.displayName}
              players={rows}
            />
          </Suspense>
        )}
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
        Settings are saved automatically to your browser. They change what
        the trade tools and rankings show; none of them changes a player&apos;s
        dynasty value.
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

/** "412 players + 24 picks" from the backend's voting counts; null when the
 *  board did not report this source (shown as "—", never 0). */
function votingOnText(src) {
  const players = Number.isFinite(src.playersVoting) ? src.playersVoting : null;
  const picks = Number.isFinite(src.picksVoting) ? src.picksVoting : null;
  if (players === null && picks === null) return null;
  const parts = [];
  if (players !== null) parts.push(`${players} player${players === 1 ? "" : "s"}`);
  if (picks !== null && picks > 0) parts.push(`${picks} pick${picks === 1 ? "" : "s"}`);
  return parts.join(" + ");
}

function SourceTable({ title, sources, describedBy }) {
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
                title="Custom source mixes are switched off; this cannot be changed"
              >
                On
              </th>
              <th
                style={{ textAlign: "right", padding: "6px 8px" }}
                title="The source's registry base weight. Custom weights are switched off; this cannot be changed"
              >
                Weight
              </th>
              <th
                className="settings-src-col-covered"
                style={{ textAlign: "right", padding: "6px 8px" }}
                title="Players (and picks) this source voted on in the current board, as the board reports it"
              >
                Voting on
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
              // Backend status (lib/source-voting-status.js label); a source
              // the board did not report says so — never "Live", never "Idle".
              const statusLabel = src.statusLabel;
              const statusColor =
                STATUS_TONE_COLOR[src.statusTone] || STATUS_TONE_COLOR.neutral;
              const votingOn = votingOnText(src);
              return (
                <tr
                  key={src.key}
                  data-testid={`settings-src-row-${src.key}`}
                  style={{ borderBottom: "1px solid var(--border-dim)" }}
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
                      {/* role="img": `aria-label` is PROHIBITED on a bare
                          <span>, which has no role to name — axe flags 21
                          of these.  The dot carries meaning (it mirrors
                          the Status column), so it is an image with a
                          name, not decoration to hide. */}
                      <span
                        role="img"
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
                        {votingOn ? `voting on ${votingOn}` : "voting not reported"}
                      </span>
                    </div>
                  </td>
                  <td
                    className="settings-src-col-role"
                    style={{ padding: "6px 8px", fontSize: "0.72rem" }}
                  >
                    {role}
                  </td>
                  {src.nonVoting ? (
                    <td
                      colSpan={2}
                      data-testid={`settings-src-vote-state-${src.key}`}
                      title="Collected and shown on Rankings; it does not vote, so there is nothing to include or weight."
                      style={{
                        padding: "6px 8px",
                        textAlign: "center",
                        fontSize: "0.68rem",
                        color: "var(--subtext)",
                      }}
                    >
                      {src.voteLabel}
                    </td>
                  ) : (
                    <>
                      {/* Disabled, showing the registry's own state (every
                          source included at its declared base weight):
                          custom mixes are switched off server-side, so an
                          operable control here would change nothing. */}
                      <td style={{ padding: "6px 8px", textAlign: "center" }}>
                        <input
                          type="checkbox"
                          checked
                          readOnly
                          disabled
                          aria-label={`Include ${src.displayName} in blend (custom mixes are switched off)`}
                          aria-describedby={describedBy}
                          className="settings-src-toggle"
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
                          value={Number(src.defaultWeight).toFixed(1)}
                          readOnly
                          disabled
                          className="input weight-input"
                          style={{
                            textAlign: "right",
                            fontFamily: "var(--mono)",
                          }}
                          aria-label={`${src.displayName} weight (custom weights are switched off)`}
                          aria-describedby={describedBy}
                        />
                      </td>
                    </>
                  )}
                  <td
                    className="settings-src-col-covered"
                    data-testid={`settings-src-voting-on-${src.key}`}
                    title={votingOn ? undefined : "The board did not report this source's voting"}
                    style={{
                      padding: "6px 8px",
                      textAlign: "right",
                      fontFamily: "var(--mono)",
                      color: "var(--subtext)",
                    }}
                  >
                    {votingOn ?? "—"}
                  </td>
                  <td
                    className="settings-src-col-status"
                    data-testid={`settings-src-status-${src.key}`}
                    title={src.statusReason || undefined}
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
        if (res.status === 401 || res.status === 403) {
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
                      aria-label={`${src.displayName} ROS source on`}
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
                      aria-label={`${src.displayName} ROS weight`}
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


