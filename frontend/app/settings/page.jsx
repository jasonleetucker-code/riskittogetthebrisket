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
              ? `Auto from league (bonus_rec_te → ${tepDerivedFromLeague.toFixed(2)})`
              : `Custom override (auto would be ${tepDerivedFromLeague.toFixed(2)})`
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

      {/* IDP Scoring Fit — global toggle + weight slider.  When ON,
          IDP rows everywhere (rankings board, trade calculator, trade
          suggestions, trade finder, popup) substitute
          ``consensus + delta × scoringFitWeight`` for the consensus
          value.  Slider changes values + ranks instantly without a
          backend round-trip. */}
      <Section title="IDP Scoring Fit" defaultOpen>
        <div style={{ fontSize: "0.72rem", marginBottom: 10 }} className="muted">
          Adjusts IDP values + ranks based on how your league&apos;s stacked
          scoring rules rate each player vs the 19-source consensus market.
          Positive delta = your league overvalues consensus (buy-low candidate);
          negative = market overpays vs your scoring (sell-high). Backend
          stamps the raw delta; the slider controls how aggressively that
          delta moves the displayed value. Off = consensus board.
        </div>
        <ToggleRow
          label="Apply Scoring Fit globally"
          checked={!!settings.applyScoringFit}
          onChange={(v) => update("applyScoringFit", v)}
          hint="Affects /rankings, /trade, suggestions, finder, and player popups"
        />
        {/* Weight slider with preset buttons.  Disabled when toggle is off
            since the value would have no effect. */}
        <div style={{ marginTop: 12, opacity: settings.applyScoringFit ? 1 : 0.5 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
            <label style={{ fontSize: "0.82rem" }}>Adjustment strength</label>
            <code style={{ fontFamily: "var(--mono)", fontSize: "0.78rem", color: "var(--cyan)" }}>
              {Math.round((settings.scoringFitWeight ?? 0.30) * 100)}%
            </code>
          </div>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={Math.round((settings.scoringFitWeight ?? 0.30) * 100)}
            onChange={(e) => update("scoringFitWeight", Number(e.target.value) / 100)}
            disabled={!settings.applyScoringFit}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", gap: 6, marginTop: 8, flexWrap: "wrap" }}>
            {[
              { label: "Off", value: 0.0 },
              { label: "Conservative", value: 0.15 },
              { label: "Moderate", value: 0.30 },
              { label: "Strong", value: 0.50 },
              { label: "Full", value: 1.0 },
            ].map((preset) => {
              const cur = settings.scoringFitWeight ?? 0.30;
              const active = Math.abs(cur - preset.value) < 0.01;
              return (
                <button
                  key={preset.label}
                  type="button"
                  className={`button${active ? " button-primary" : ""}`}
                  style={{ fontSize: "0.72rem" }}
                  disabled={!settings.applyScoringFit}
                  onClick={() => update("scoringFitWeight", preset.value)}
                  title={`Apply delta at ${Math.round(preset.value * 100)}% strength`}
                >
                  {preset.label}
                  {active ? " ✓" : ""}
                </button>
              );
            })}
          </div>
          <div className="muted" style={{ fontSize: "0.68rem", marginTop: 6, lineHeight: 1.4 }}>
            Recommended: <strong>Moderate (30%)</strong> — a one-tier nudge for median deltas.
            Strong (50%) and Full (100%) are aggressive — only use if you fully trust the lens
            on your specific league&apos;s scoring rules.
          </div>
        </div>
        <ScoringFitHealth />
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
          </>
        ) : (
          <p className="muted" style={{ fontSize: "0.78rem" }}>
            Sign in to enable email notifications.  Your notification preferences
            are stored on the server and apply across devices.
          </p>
        )}
      </Section>

      <Section title="Data & Admin" defaultOpen={false}>
        <ServerStatusPanel />
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

// ── ScoringFit health panel ─────────────────────────────────────────
// Renders inside the IDP Scoring Fit settings section.  Shows what
// the latest backend pass produced — counts, distribution, top movers,
// cache freshness — so the operator can spot silent regressions early
// (e.g. nflverse schema drift dropping the cross-walk size).
//
// Reads ``/api/idp-fit-health``, refreshes every 60s.
function ScoringFitHealth() {
  const [health, setHealth] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetchHealth = useCallback(async () => {
    try {
      const res = await fetch("/api/idp-fit-health");
      if (res.ok) setHealth(await res.json());
      else setHealth({ error: `HTTP ${res.status}` });
    } catch {
      setHealth({ error: "Backend unreachable" });
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHealth();
    const interval = setInterval(fetchHealth, 60000);
    return () => clearInterval(interval);
  }, [fetchHealth]);

  if (loading) {
    return (
      <div className="muted text-xs" style={{ marginTop: 12 }}>
        Loading scoring-fit health…
      </div>
    );
  }
  if (!health || health.error) {
    return (
      <div className="muted text-xs" style={{ marginTop: 12, color: "var(--red)" }}>
        Health endpoint unavailable: {health?.error || "unknown error"}
      </div>
    );
  }

  const dist = health.delta_distribution || {};
  const conf = health.confidence_breakdown || {};

  return (
    <div style={{ marginTop: 16, padding: 10, background: "rgba(20, 25, 36, 0.5)", borderRadius: 4, border: "1px solid var(--border)" }}>
      <div style={{ fontSize: "0.72rem", fontWeight: 600, marginBottom: 8, color: "var(--cyan)" }}>
        Pipeline health
        {!health.flag_on && (
          <span className="muted" style={{ marginLeft: 8, fontSize: "0.68rem", fontWeight: 400 }}>
            (flag is OFF — values shown reflect last build before flag flip)
          </span>
        )}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))", gap: 10, fontSize: "0.72rem" }}>
        <div>
          <div className="muted text-xs">IDP coverage</div>
          <div style={{ fontFamily: "var(--mono, monospace)" }}>
            {health.with_delta} / {health.idp_total} stamped (
            {health.idp_total > 0 ? Math.round(100 * health.with_delta / health.idp_total) : 0}%)
          </div>
        </div>
        <div>
          <div className="muted text-xs">Synthetic rookies</div>
          <div style={{ fontFamily: "var(--mono, monospace)" }}>{health.synthetic_rookies}</div>
        </div>
        <div>
          <div className="muted text-xs">Confidence</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.68rem" }}>
            H{conf.high || 0} M{conf.medium || 0} L{conf.low || 0} ·{" "}
            {conf.none_or_sentinel || 0} sentinel
          </div>
        </div>
        <div title="P25 / median / P75 of the per-IDP delta distribution.  Wide ranges mean the league diverges from consensus on a lot of players.">
          <div className="muted text-xs">Delta spread</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.68rem" }}>
            {dist.p25} / {dist.median} / {dist.p75}
          </div>
        </div>
        <div>
          <div className="muted text-xs">Cache age</div>
          <div style={{ fontFamily: "var(--mono, monospace)", fontSize: "0.68rem" }}>
            {health.cache_age_seconds?.sleeper_players != null
              ? `${Math.round(health.cache_age_seconds.sleeper_players / 60)}m`
              : "—"}{" "}/{" "}
            {health.cache_age_seconds?.league_context != null
              ? `${Math.round(health.cache_age_seconds.league_context / 60)}m`
              : "—"}
          </div>
        </div>
      </div>
      {health.top_positive?.length > 0 && (
        <div style={{ marginTop: 10, fontSize: "0.7rem" }}>
          <div className="muted text-xs">Top buy-low (largest positive delta)</div>
          <div style={{ fontFamily: "var(--mono, monospace)" }}>
            {health.top_positive.slice(0, 5).map((p) => `${p.name} ${p.position} +${Math.round(p.delta)}`).join(" · ")}
          </div>
        </div>
      )}
      {health.top_negative?.length > 0 && (
        <div style={{ marginTop: 6, fontSize: "0.7rem" }}>
          <div className="muted text-xs">Top sell-high (largest negative delta)</div>
          <div style={{ fontFamily: "var(--mono, monospace)" }}>
            {health.top_negative.slice(0, 5).map((p) => `${p.name} ${p.position} ${Math.round(p.delta)}`).join(" · ")}
          </div>
        </div>
      )}
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
