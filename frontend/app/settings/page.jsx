"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useSettings, SETTINGS_DEFAULTS as DEFAULTS } from "@/components/useSettings";
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
  return (
    <div className="card" style={{ marginBottom: 10 }}>
      <button
        className="button-reset"
        onClick={() => setOpen(!open)}
        style={{
          display: "flex", justifyContent: "space-between", alignItems: "center",
          width: "100%", padding: "8px 0", minHeight: 44, cursor: "pointer",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>{title}</h3>
        <span className="muted" style={{ fontSize: "1.2rem", width: 24, textAlign: "center" }}>{open ? "−" : "+"}</span>
      </button>
      {open && <div style={{ marginTop: 10 }}>{children}</div>}
    </div>
  );
}

function SliderRow({ label, value, min, max, step, onChange, hint }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
      <label style={{ minWidth: 100, fontSize: "0.82rem" }}>{label}</label>
      <input
        type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        style={{ flex: 1 }}
      />
      <span className="badge" style={{ minWidth: 48, textAlign: "center" }}>{value}</span>
      {hint && <span className="muted" style={{ fontSize: "0.66rem" }}>{hint}</span>}
    </div>
  );
}

function ToggleRow({ label, checked, onChange, hint }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
      <label style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.82rem", cursor: "pointer" }}>
        <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
        {label}
      </label>
      {hint && <span className="muted" style={{ fontSize: "0.66rem" }}>{hint}</span>}
    </div>
  );
}

export default function SettingsPage() {
  const { loading, error, rows, rawData } = useDynastyData();
  const { settings, update, updateSiteWeight, resetSiteWeights, reset } = useSettings();
  const { state: userState, serverBacked, setNotifications } = useUserState();
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
    if (clean && (!clean.includes("@") || !clean.split("@")[1]?.includes("."))) {
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

  // Derived TE-premium multiplier from the backend.  Comes from
  // ``rankingsOverride.tepMultiplierDerived`` which the backend
  // stamps on every /api/data + override response.  The number is
  // computed from the operator's Sleeper league ``bonus_rec_te``
  // (0.0 → 1.0, 0.5 → 1.15, 1.0 → 1.30, ...) and represents the
  // "auto" baseline the slider shows when the user has not
  // explicitly overridden it.
  const tepDerivedFromLeague = (() => {
    const v = Number(rawData?.rankingsOverride?.tepMultiplierDerived);
    return Number.isFinite(v) ? v : 1.0;
  })();
  const bonusRecTeFromLeague = (() => {
    const v = Number(rawData?.rankingsOverride?.bonusRecTe);
    return Number.isFinite(v) && v >= 0 ? v : 0.0;
  })();
  // Effective slider value.  null/undefined in settings → show the
  // derived value (auto); a finite number → show the user's override.
  // Coerce any noise (strings, NaN) back to the derived baseline.
  const tepSliderValue = (() => {
    const raw = settings?.tepMultiplier;
    if (raw === null || raw === undefined) return tepDerivedFromLeague;
    const n = Number(raw);
    return Number.isFinite(n) ? n : tepDerivedFromLeague;
  })();
  const tepIsAuto =
    settings?.tepMultiplier === null ||
    settings?.tepMultiplier === undefined;

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
      offense: RANKING_SOURCES
        .filter((s) => s.scope === "overall_offense")
        .map(decorate),
      idp: RANKING_SOURCES
        .filter((s) => s.scope === "overall_idp")
        .map(decorate),
    };
  }, [rows, settings?.siteWeights]);

  if (!hydrated) return null;

  return (
    <section className="card">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <h1 style={{ marginTop: 0 }}>Settings</h1>
          <p className="muted" style={{ marginTop: 4 }}>
            Tuning controls that affect valuations, trade calculations, and rankings display.
          </p>
        </div>
        <button className="button" onClick={resetToDefaults} style={{ fontSize: "0.76rem" }}>
          Reset Defaults
        </button>
      </div>

      {loading && <p>Loading data...</p>}
      {!!error && <p style={{ color: "var(--red)" }}>{error}</p>}

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
        <SliderRow
          label="TE Premium"
          value={tepSliderValue}
          min={1.0} max={1.5} step={0.05}
          onChange={(v) => update("tepMultiplier", v)}
          hint={
            tepIsAuto
              ? `Auto: ${tepDerivedFromLeague.toFixed(3)}× (Sleeper bonus_rec_te = ${bonusRecTeFromLeague.toFixed(2)})`
              : `Custom override (auto would be ${tepDerivedFromLeague.toFixed(3)}× from bonus_rec_te = ${bonusRecTeFromLeague.toFixed(2)})`
          }
        />
        {!tepIsAuto && (
          <div style={{ marginTop: 4, marginBottom: 6 }}>
            <button
              type="button"
              className="button-reset"
              style={{
                fontSize: "0.7rem",
                color: "var(--accent-gold, #FFC704)",
                textDecoration: "underline",
                cursor: "pointer",
                padding: 0,
              }}
              onClick={() => update("tepMultiplier", null)}
            >
              Reset to Auto (derive from my Sleeper league)
            </button>
          </div>
        )}
        <p className="muted" style={{ fontSize: "0.68rem", marginTop: 4, marginBottom: 0 }}>
          By default, this is <strong>derived from your Sleeper league&apos;s{" "}
          <span style={{ fontFamily: "var(--mono)", fontSize: "0.64rem" }}>
            bonus_rec_te
          </span></strong>{" "}
          scoring setting: 0.0 (standard) → 1.00, 0.5 (TEP-1.5) → 1.15,
          1.0 (TEP-2.0) → 1.30.  Dragging the slider opts into a manual
          override on top of that.  Applied on the backend to every TE&apos;s
          per-source contributions from rankings sources that don&apos;t
          already bake TE premium into their ranks.  Sources tagged{" "}
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
          in the Ranking Sources table below pass through unchanged, so there is
          no double-boost. Changing the slider re-runs the canonical ranking
          pipeline with the new multiplier, so every page (rankings, trade
          calculator, edge) sees the same TEP-adjusted values.
        </p>
      </Section>

      <Section title="Trade Calculation" defaultOpen>
        <SliderRow
          label="Trade History Window"
          value={settings.tradeHistoryWindowDays}
          min={30} max={730} step={30}
          onChange={(v) => update("tradeHistoryWindowDays", v)}
          hint={`${settings.tradeHistoryWindowDays} days`}
        />
        <SliderRow
          label="Suggestion Pool Cap"
          value={settings.ktcSuggestionTopN ?? 150}
          min={50} max={300} step={10}
          onChange={(v) => update("ktcSuggestionTopN", v)}
          hint={`Top ${settings.ktcSuggestionTopN ?? 150} KTC offense players considered for trade suggestions`}
        />
        <p
          className="muted"
          style={{ fontSize: "0.7rem", marginTop: 4, marginBottom: 0 }}
        >
          Default 150 fits a standard 12-team Superflex league.  Raise
          for deeper formats (14-team 2QB, deep-IDP keeper) where the
          bottom-50 of your roster pool sits below KTC #150 but is
          genuinely traded.  Picks + IDP are unaffected by this cap.
        </p>
      </Section>

      <Section title="Rankings Display" defaultOpen>
        <div style={{ marginBottom: 8 }}>
          <label style={{ fontSize: "0.82rem", marginRight: 8 }}>Sort Basis</label>
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
        <div style={{ fontSize: "0.72rem", marginBottom: 10 }} className="muted">
          Every registered source contributes equally (default weight 1.0) to the
          blended consensus rank.  Toggle a source off or adjust its weight to
          recompute the board with your own mix.  Changing any knob flips the
          rankings page into override mode so your settings materially affect
          the displayed rank and value; clearing the overrides returns to the
          canonical server blend.  IDP Trade Calculator is the IDP backbone and
          also feeds offense via its secondary scope.  Backend registry:{" "}
          <code style={{ fontFamily: "var(--mono)" }}>src/api/data_contract.py</code>.
        </div>
        <div style={{ display: "flex", gap: 8, marginBottom: 10, flexWrap: "wrap" }}>
          {Object.values(WEIGHT_PRESETS).map((preset) => {
            const active = detectActivePreset(settings?.siteWeights) === preset.key;
            return (
              <button
                key={preset.key}
                type="button"
                className={`button${active ? " button-primary" : ""}`}
                style={{ fontSize: "0.72rem" }}
                title={preset.description}
                onClick={() => update("siteWeights", presetToWeights(preset.key))}
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
        <p className="muted" style={{ fontSize: "0.72rem", marginTop: 0, marginBottom: 10 }}>
          The ROS engine is a separate short-term contender layer.{" "}
          <strong>It never modifies dynasty rankings or trade-calculator math.</strong>{" "}
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
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginTop: 14 }}>
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
                Math.max(1000, Math.min(100000, parseInt(e.target.value) || 10000)),
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
          .  Overrides apply on the next admin Refresh — scheduled scrapes
          run with registry defaults.
        </p>
      </Section>

      <Section title="Pick Settings" defaultOpen={false}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", marginBottom: 8 }}>
          <label style={{ fontSize: "0.82rem" }}>Current Draft Year</label>
          <input
            type="number" min={2024} max={2030}
            value={settings.pickCurrentYear}
            onChange={(e) => update("pickCurrentYear", parseInt(e.target.value) || 2026)}
            className="input" style={{ width: 80 }}
          />
        </div>
        <p className="muted" style={{ fontSize: "0.72rem" }}>
          Picks from future years are automatically discounted in trade calculations:
          current year = 100%, +1 year = 85%, +2 years = 72%, +3+ years = 60%.
        </p>
      </Section>

      <Section title="Notifications" defaultOpen={false}>
        {serverBacked ? (
          <>
            <ToggleRow
              label="Email me daily signal alerts"
              checked={!!userState?.notificationsEnabled}
              onChange={toggleEnabled}
              hint="Buy/sell/injury/roster digest, sent once per day when you have live signals."
            />
            <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 8, flexWrap: "wrap" }}>
              <label style={{ fontSize: "0.82rem", minWidth: 100 }}>Email address</label>
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
              <button className="button" onClick={saveEmail} style={{ fontSize: "0.76rem" }}>
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
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: 6, color: "var(--green)" }}>
                {emailStatus}
              </div>
            )}
            <p className="muted" style={{ fontSize: "0.7rem", marginTop: 10, marginBottom: 0 }}>
              Alerts fire once per day when the signal engine finds something notable on your
              roster — buy-low / sell-high opportunities, injury news, rookie or pick movement.
              We only email you when there&apos;s a change worth acting on.
            </p>
            <div style={{ marginTop: 14, paddingTop: 12, borderTop: "1px solid var(--border)" }}>
              <PushNotificationToggle enabled={!!serverBacked} />
            </div>
          </>
        ) : (
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            Sign in to enable email notifications.  Your notification preferences
            are stored on the server and apply across devices.
          </p>
        )}
      </Section>

      <Section title="Custom alerts" defaultOpen={false}>
        <CustomAlertsConfigurator enabled={!!serverBacked} players={rows} />
      </Section>

      <Section title="Data & Admin" defaultOpen={false}>
        <ServerStatusPanel />
      </Section>

      <Section title="Guest access" defaultOpen={false}>
        <GuestPassPanel />
      </Section>

      <div className="muted" style={{ fontSize: "0.72rem", marginTop: 12, padding: "8px 0", borderTop: "1px solid var(--border)" }}>
        Settings are saved automatically to your browser. They affect trade calculations, rankings display, and value composites.
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
              <th className="settings-src-col-role" style={{ textAlign: "left", padding: "6px 8px" }}>Role</th>
              <th style={{ textAlign: "center", padding: "6px 8px" }} title="Include this source in rank blending">On</th>
              <th style={{ textAlign: "right", padding: "6px 8px" }} title="Weight applied to this source in the blend. Default 1.0">Weight</th>
              <th className="settings-src-col-covered" style={{ textAlign: "right", padding: "6px 8px" }}>Covered</th>
              <th className="settings-src-col-status" style={{ textAlign: "center", padding: "6px 8px" }}>Status</th>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
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
                          title="This source's raw ranks already bake in TE premium, so the global TE Premium slider does not need to compensate for it."
                          style={{
                            fontSize: "0.58rem",
                            padding: "1px 5px",
                            background: "var(--green-dim, rgba(80,200,120,0.18))",
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
                  <td className="settings-src-col-role" style={{ padding: "6px 8px", fontSize: "0.72rem" }}>
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
                        if (Number.isFinite(v) && v >= 0) onWeight?.(src.key, v);
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
          setFeedback(`Refresh failed (HTTP ${res.status}): ${text.slice(0, 120)}`);
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
              <th className="settings-src-col-role" style={{ textAlign: "left", padding: "6px 8px" }}>Type</th>
              <th style={{ textAlign: "center", padding: "6px 8px" }}>On</th>
              <th style={{ textAlign: "right", padding: "6px 8px" }}>Weight</th>
              <th className="settings-src-col-status" style={{ textAlign: "center", padding: "6px 8px" }}>Default</th>
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
                  Math.abs(Number(ov.weight) - Number(src.baseWeight ?? 1.0)) > 1e-6);
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
                    <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap" }}>
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
                    <div style={{ fontSize: "0.66rem", color: "var(--subtext)", marginTop: 2 }}>
                      {src.key}
                    </div>
                  </td>
                  <td className="settings-src-col-role" style={{ padding: "6px 8px", fontSize: "0.74rem", color: "var(--subtext)" }}>
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
                  <td style={{ padding: "6px 8px", textAlign: "right", fontFamily: "var(--mono)" }}>
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
                  <td className="settings-src-col-status" style={{ padding: "6px 8px", textAlign: "center", fontSize: "0.7rem", color: "var(--subtext)" }}>
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
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 10 }}>
        <button
          type="button"
          className="button button-primary"
          onClick={apply}
          disabled={submitting}
        >
          {submitting ? "Refreshing..." : "Apply now (admin refresh)"}
        </button>
        <span style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
          {feedback || "Triggers POST /api/ros/refresh — re-runs the orchestrator with these overrides."}
        </span>
      </div>
    </div>
  );
}


function ServerStatusPanel() {
  const [status, setStatus] = useState(null);
  const [scraping, setScraping] = useState(false);
  const [scrapeMsg, setScrapeMsg] = useState("");

  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/status");
      if (res.ok) setStatus(await res.json());
      else setStatus({ error: `HTTP ${res.status}` });
    } catch {
      setStatus({ error: "Backend unreachable" });
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 30000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  async function triggerScrape() {
    setScraping(true);
    setScrapeMsg("");
    try {
      const res = await fetch("/api/scrape", { method: "POST" });
      const data = await res.json().catch(() => ({}));
      setScrapeMsg(data.error ? `Error: ${data.error}` : "Refresh triggered. Data will update shortly.");
      setTimeout(fetchStatus, 5000);
    } catch {
      setScrapeMsg("Failed to reach backend.");
    } finally {
      setScraping(false);
    }
  }

  const connected = status && !status.error;

  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
        <span
          style={{
            width: 8, height: 8, borderRadius: "50%",
            background: connected ? "var(--green)" : "var(--red)",
            display: "inline-block",
          }}
        />
        <span style={{ fontSize: "0.82rem", fontWeight: 600 }}>
          {connected ? "Backend Connected" : "Backend Offline"}
        </span>
      </div>

      {connected && (
        <div style={{ fontSize: "0.72rem", color: "var(--subtext)", marginBottom: 10 }}>
          {status.player_count != null && <div>Players: {status.player_count}</div>}
          {status.last_scrape && <div>Last update: {status.last_scrape}</div>}
          {status.next_scrape && <div>Next update: {status.next_scrape}</div>}
          {status?.contract?.version && <div>Contract: {status.contract.version}</div>}
          {status?.uptime?.last_ok && (
            <div>
              Uptime monitor:{" "}
              {status.uptime.consecutive_failures > 0
                ? `${status.uptime.consecutive_failures} consecutive failures (last ok ${status.uptime.last_ok})`
                : `healthy (last ok ${status.uptime.last_ok})`}
            </div>
          )}
        </div>
      )}

      {status?.error && (
        <div style={{ fontSize: "0.72rem", color: "var(--red)", marginBottom: 10 }}>
          {status.error}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <button
          className="button"
          onClick={triggerScrape}
          disabled={scraping}
          style={{ fontSize: "0.76rem" }}
        >
          {scraping ? "Refreshing..." : "Refresh Values"}
        </button>
        <button
          className="button"
          onClick={fetchStatus}
          style={{ fontSize: "0.76rem" }}
        >
          Check Status
        </button>
      </div>

      {scrapeMsg && (
        <div style={{ fontSize: "0.72rem", marginTop: 6, color: scrapeMsg.startsWith("Error") ? "var(--red)" : "var(--green)" }}>
          {scrapeMsg}
        </div>
      )}
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

function GuestPassPanel() {
  const [hours, setHours] = useState(12);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [freshToken, setFreshToken] = useState(null);
  const [passes, setPasses] = useState([]);
  const [listLoading, setListLoading] = useState(true);
  const [copyStatus, setCopyStatus] = useState("");

  const fetchList = useCallback(async () => {
    try {
      const res = await fetch("/api/admin/guest-passes", {
        cache: "no-store",
      });
      if (res.status === 403) {
        setError("Admin only.");
        setPasses([]);
        return;
      }
      if (!res.ok) {
        setError(`Server error (${res.status})`);
        return;
      }
      const body = await res.json();
      setPasses(Array.isArray(body?.passes) ? body.passes : []);
      setError("");
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setListLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchList();
  }, [fetchList]);

  async function generate() {
    setBusy(true);
    setError("");
    setFreshToken(null);
    setCopyStatus("");
    try {
      const res = await fetch("/api/admin/guest-pass", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          durationHours: Number(hours) || 12,
          note: String(note || "").trim(),
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(body?.message || body?.error || `HTTP ${res.status}`);
        return;
      }
      setFreshToken({
        token: body.token,
        expiresAtEpoch: body?.pass?.expiresAtEpoch,
        note: body?.pass?.note || "",
        id: body?.pass?.id,
      });
      setNote("");
      // Refresh the list so the new pass shows up.
      fetchList();
    } catch {
      setError("Could not reach the backend.");
    } finally {
      setBusy(false);
    }
  }

  async function copyToken(token) {
    try {
      await navigator.clipboard.writeText(token);
      setCopyStatus("Copied!");
      setTimeout(() => setCopyStatus(""), 2000);
    } catch {
      setCopyStatus("Copy failed — select the token manually.");
    }
  }

  async function revoke(id) {
    if (!window.confirm("Revoke this guest pass? The recipient will lose access.")) {
      return;
    }
    try {
      const res = await fetch(
        `/api/admin/guest-pass/${id}/revoke`,
        { method: "POST" },
      );
      if (!res.ok) {
        setError(`Revoke failed (${res.status})`);
        return;
      }
      fetchList();
    } catch {
      setError("Could not reach the backend.");
    }
  }

  return (
    <div>
      <p className="muted" style={{ fontSize: "0.76rem", margin: "0 0 12px" }}>
        Generate a temporary password to share with someone you want to
        give private-app access. They paste it into the login form's
        password field; their session expires automatically when the
        pass does. Plaintext tokens are shown ONCE — copy and share
        immediately.
      </p>

      {/* ── Generate form ─────────────────────────────────────── */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "auto 1fr auto",
          gap: 8,
          alignItems: "center",
          marginBottom: 10,
        }}
      >
        <label
          style={{
            fontSize: "0.74rem",
            color: "var(--subtext)",
            whiteSpace: "nowrap",
          }}
          title="How long the guest's session stays valid (1 hour to 720 hours / 30 days)."
        >
          Duration:
          <input
            type="number"
            min={1}
            max={720}
            step={1}
            value={hours}
            onChange={(e) =>
              setHours(Math.max(1, Math.min(720, Number(e.target.value) || 12)))
            }
            style={{
              marginLeft: 6,
              width: 64,
              fontFamily: "var(--mono)",
              fontSize: "0.82rem",
              padding: "4px 6px",
              background: "rgba(8,19,44,0.6)",
              border: "1px solid var(--border)",
              borderRadius: 4,
              color: "var(--text)",
            }}
          />
          <span style={{ marginLeft: 4 }}>hours</span>
        </label>
        <input
          type="text"
          placeholder="Optional note (e.g. 'Brent — preview')"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={100}
          style={{
            fontSize: "0.78rem",
            padding: "5px 8px",
            background: "rgba(8,19,44,0.6)",
            border: "1px solid var(--border)",
            borderRadius: 4,
            color: "var(--text)",
          }}
        />
        <button
          className="button"
          onClick={generate}
          disabled={busy}
          style={{ fontSize: "0.78rem", whiteSpace: "nowrap" }}
        >
          {busy ? "Generating…" : `Generate ${hours}h pass`}
        </button>
      </div>

      {error && (
        <div
          style={{
            fontSize: "0.74rem",
            color: "var(--red)",
            marginBottom: 8,
          }}
        >
          {error}
        </div>
      )}

      {/* ── Fresh-token reveal ────────────────────────────────── */}
      {freshToken && (
        <div
          className="card"
          style={{
            marginBottom: 12,
            padding: 10,
            border: "1px solid var(--green)",
            background: "rgba(52, 211, 153, 0.06)",
          }}
        >
          <div
            style={{
              fontSize: "0.7rem",
              color: "var(--green)",
              fontWeight: 700,
              textTransform: "uppercase",
              letterSpacing: "0.05em",
              marginBottom: 6,
            }}
          >
            New pass — copy NOW (won't be shown again)
          </div>
          <div
            style={{
              display: "flex",
              gap: 8,
              alignItems: "center",
              marginBottom: 6,
            }}
          >
            <code
              style={{
                fontFamily: "var(--mono)",
                fontSize: "0.82rem",
                padding: "6px 10px",
                background: "rgba(8,19,44,0.85)",
                border: "1px solid var(--border)",
                borderRadius: 4,
                flex: 1,
                wordBreak: "break-all",
              }}
            >
              {freshToken.token}
            </code>
            <button
              className="button"
              onClick={() => copyToken(freshToken.token)}
              style={{ fontSize: "0.74rem" }}
            >
              Copy
            </button>
          </div>
          {copyStatus && (
            <div
              style={{
                fontSize: "0.7rem",
                color: copyStatus === "Copied!" ? "var(--green)" : "var(--red)",
              }}
            >
              {copyStatus}
            </div>
          )}
          <div style={{ fontSize: "0.7rem", color: "var(--subtext)" }}>
            Expires {fmtPassExpiry(freshToken.expiresAtEpoch)} · #
            {freshToken.id}
            {freshToken.note ? ` · ${freshToken.note}` : ""}
          </div>
        </div>
      )}

      {/* ── Active + recent passes ────────────────────────────── */}
      <div style={{ fontWeight: 600, fontSize: "0.78rem", marginBottom: 6 }}>
        Recent passes
      </div>
      {listLoading ? (
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          Loading…
        </div>
      ) : passes.length === 0 ? (
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          No passes yet.
        </div>
      ) : (
        <div className="table-wrap" style={{ marginTop: 4 }}>
          <table style={{ width: "100%", fontSize: "0.74rem" }}>
            <thead>
              <tr style={{ color: "var(--subtext)", textAlign: "left" }}>
                <th style={{ padding: "4px 6px", width: 50 }}>#</th>
                <th style={{ padding: "4px 6px" }}>Note</th>
                <th style={{ padding: "4px 6px", width: 130 }}>Expires</th>
                <th style={{ padding: "4px 6px", width: 100 }}>Status</th>
                <th style={{ padding: "4px 6px", width: 80 }}></th>
              </tr>
            </thead>
            <tbody>
              {passes.map((p) => {
                const status = p.isRevoked
                  ? { label: "Revoked", color: "var(--red)" }
                  : p.isExpired
                    ? { label: "Expired", color: "var(--subtext)" }
                    : { label: "Active", color: "var(--green)" };
                return (
                  <tr
                    key={p.id}
                    style={{ borderTop: "1px solid var(--border-dim)" }}
                  >
                    <td
                      style={{
                        padding: "4px 6px",
                        fontFamily: "var(--mono)",
                        color: "var(--subtext)",
                      }}
                    >
                      {p.id}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      {p.note || (
                        <span className="muted">— no note —</span>
                      )}
                    </td>
                    <td
                      style={{ padding: "4px 6px", fontFamily: "var(--mono)" }}
                    >
                      {fmtPassExpiry(p.expiresAtEpoch)}
                    </td>
                    <td
                      style={{
                        padding: "4px 6px",
                        color: status.color,
                        fontWeight: 600,
                      }}
                    >
                      {status.label}
                    </td>
                    <td style={{ padding: "4px 6px", textAlign: "right" }}>
                      {p.isActive && (
                        <button
                          className="button"
                          onClick={() => revoke(p.id)}
                          style={{
                            fontSize: "0.68rem",
                            padding: "2px 8px",
                            borderColor: "var(--red)",
                            color: "var(--red)",
                          }}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function fmtPassExpiry(epoch) {
  if (!Number.isFinite(Number(epoch)) || Number(epoch) <= 0) return "—";
  const ms = Number(epoch) * 1000;
  const d = new Date(ms);
  const now = Date.now();
  const remainingMin = Math.round((ms - now) / 60000);
  if (remainingMin > 0 && remainingMin < 60) return `in ${remainingMin}m`;
  if (remainingMin > 0 && remainingMin < 60 * 24) {
    return `in ${Math.round(remainingMin / 60)}h`;
  }
  if (remainingMin > 0) {
    return `in ${Math.round(remainingMin / (60 * 24))}d`;
  }
  // Past — show absolute date.
  return d.toLocaleString();
}
