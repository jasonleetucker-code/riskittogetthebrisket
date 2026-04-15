"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useSettings, SETTINGS_DEFAULTS as DEFAULTS } from "@/components/useSettings";
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
          width: "100%", padding: 0, cursor: "pointer",
        }}
      >
        <h3 style={{ margin: 0, fontSize: "0.92rem" }}>{title}</h3>
        <span className="muted">{open ? "−" : "+"}</span>
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
  const { loading, error, rows } = useDynastyData();
  const { settings, update, updateSiteWeight, resetSiteWeights, reset } = useSettings();
  const [hydrated, setHydrated] = useState(true);

  function resetToDefaults() {
    reset();
  }

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
          value={settings.tepMultiplier}
          min={1.0} max={1.5} step={0.05}
          onChange={(v) => update("tepMultiplier", v)}
          hint="Global TE value boost — compensates non-TEP sources"
        />
        <p className="muted" style={{ fontSize: "0.68rem", marginTop: 4, marginBottom: 0 }}>
          Applied to every TE&apos;s blended value. Sources already baking TE premium
          into their raw ranks are tagged{" "}
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
          in the Ranking Sources table below. Set to 1.00 to disable the boost
          entirely, or increase it if your non-TEP sources (DLF SF, KTC, etc.)
          are under-valuing TEs for your league.
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
        <div style={{ display: "flex", gap: 8, marginBottom: 10 }}>
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
      <div className="table-wrap">
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "0.76rem",
          }}
        >
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "6px 8px" }}>Source</th>
              <th style={{ textAlign: "left", padding: "6px 8px" }}>Role</th>
              <th style={{ textAlign: "center", padding: "6px 8px" }} title="Include this source in rank blending">On</th>
              <th style={{ textAlign: "right", padding: "6px 8px" }} title="Weight applied to this source in the blend. Default 1.0">Weight</th>
              <th style={{ textAlign: "right", padding: "6px 8px" }}>Covered</th>
              <th style={{ textAlign: "center", padding: "6px 8px" }}>Status</th>
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
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontWeight: 600 }}>{src.displayName}</span>
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
                    </div>
                  </td>
                  <td style={{ padding: "6px 8px", fontSize: "0.72rem" }}>
                    {role}
                  </td>
                  <td style={{ padding: "6px 8px", textAlign: "center" }}>
                    <input
                      type="checkbox"
                      checked={enabled}
                      onChange={(e) => onToggle?.(src.key, e.target.checked)}
                      aria-label={`Include ${src.displayName} in blend`}
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
                      className="input"
                      style={{
                        width: 60,
                        textAlign: "right",
                        fontFamily: "var(--mono)",
                        fontSize: "0.76rem",
                      }}
                      aria-label={`${src.displayName} weight`}
                    />
                  </td>
                  <td
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
