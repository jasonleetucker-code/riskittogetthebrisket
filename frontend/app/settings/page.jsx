"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useDynastyData } from "@/components/useDynastyData";
import { useSettings, SETTINGS_DEFAULTS as DEFAULTS } from "@/components/useSettings";
// Known sites with their default configurations
const SITE_DEFAULTS = {
  ktc:           { label: "KeepTradeCut",   include: true,  weight: 1.2,  max: 9999,  tep: true  },
};

const IDP_SITE_DEFAULTS = {
  idpTradeCalc:  { label: "IDP Trade Calc", include: true, weight: 1.0, max: 9998, tep: true },
};

const ALPHA_PRESETS = [
  { label: "Balanced", value: 1.40 },
  { label: "Standard", value: 1.678 },
  { label: "Star-heavy", value: 1.90 },
];


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
      <label style={{ minWidth: 140, fontSize: "0.82rem" }}>{label}</label>
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
  const { loading, error, siteKeys } = useDynastyData();
  const { settings, update, updateSiteWeight, reset } = useSettings();
  const [hydrated, setHydrated] = useState(true);

  function getSiteConfig(siteKey) {
    const defaults = SITE_DEFAULTS[siteKey] || IDP_SITE_DEFAULTS[siteKey] || { include: true, weight: 1.0, max: 9999, tep: true };
    return { ...defaults, ...(settings.siteWeights[siteKey] || {}) };
  }

  function resetToDefaults() {
    reset();
  }

  // Determine which sites are present in actual data
  const activeSites = useMemo(() => {
    const offSites = siteKeys.filter((k) => SITE_DEFAULTS[k]);
    const idpSites = siteKeys.filter((k) => IDP_SITE_DEFAULTS[k]);
    return { offense: offSites.length > 0 ? offSites : Object.keys(SITE_DEFAULTS), idp: idpSites.length > 0 ? idpSites : Object.keys(IDP_SITE_DEFAULTS) };
  }, [siteKeys]);

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
          label="LAM Strength"
          value={settings.lamStrength}
          min={0} max={1} step={0.05}
          onChange={(v) => update("lamStrength", v)}
          hint="League scoring adjustment intensity"
        />
        <SliderRow
          label="Scarcity Strength"
          value={settings.scarcityStrength}
          min={0} max={1} step={0.05}
          onChange={(v) => update("scarcityStrength", v)}
          hint="Position scarcity premium"
        />
        <SliderRow
          label="TE Premium"
          value={settings.tepMultiplier}
          min={1.0} max={1.5} step={0.05}
          onChange={(v) => update("tepMultiplier", v)}
          hint="TE boost for non-TEP sites"
        />
      </Section>

      <Section title="Trade Calculation" defaultOpen>
        <div style={{ marginBottom: 10 }}>
          <label style={{ fontSize: "0.82rem", display: "block", marginBottom: 4 }}>
            Alpha (Star Player Bonus)
          </label>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <input
              type="range" min={1.0} max={2.0} step={0.001}
              value={settings.alpha}
              onChange={(e) => update("alpha", parseFloat(e.target.value))}
              style={{ flex: 1 }}
            />
            <span className="badge" style={{ minWidth: 52, textAlign: "center" }}>{settings.alpha}</span>
          </div>
          <div style={{ display: "flex", gap: 6, marginTop: 6 }}>
            {ALPHA_PRESETS.map((p) => (
              <button
                key={p.label}
                className="button"
                onClick={() => update("alpha", p.value)}
                style={{
                  fontSize: "0.68rem",
                  padding: "2px 8px",
                  opacity: settings.alpha === p.value ? 1 : 0.6,
                  fontWeight: settings.alpha === p.value ? 700 : 400,
                }}
              >
                {p.label} ({p.value})
              </button>
            ))}
          </div>
          <div className="muted" style={{ fontSize: "0.66rem", marginTop: 4 }}>
            Higher = elite players worth exponentially more. 1.0 = linear, 1.678 = standard.
          </div>
        </div>
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
            <option value="scoring">Scoring Adjusted</option>
            <option value="scarcity">Scarcity Adjusted</option>
          </select>
        </div>
        <ToggleRow
          label="Show LAM detail columns"
          checked={settings.showLamCols}
          onChange={(v) => update("showLamCols", v)}
          hint="Raw, Scoring, Final, Delta"
        />
        <ToggleRow
          label="Show source site columns"
          checked={settings.showSiteCols}
          onChange={(v) => update("showSiteCols", v)}
          hint="Per-site value columns in rankings"
        />
      </Section>

      <Section title="Offense Value Sources" defaultOpen>
        <div style={{ fontSize: "0.72rem", marginBottom: 8 }} className="muted">
          Toggle sources on/off and adjust their weight in the composite calculation.
        </div>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Source</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>On</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>Weight</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>Max</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>TEP</th>
            </tr>
          </thead>
          <tbody>
            {activeSites.offense.map((key) => {
              const cfg = getSiteConfig(key);
              return (
                <tr key={key} style={{ borderBottom: "1px solid var(--border)", opacity: cfg.include ? 1 : 0.4 }}>
                  <td style={{ padding: "4px 8px" }}>{cfg.label || key}</td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input type="checkbox" checked={cfg.include} onChange={(e) => updateSiteWeight(key, "include", e.target.checked)} />
                  </td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input
                      type="number" min={0} max={3} step={0.1}
                      value={cfg.weight} onChange={(e) => updateSiteWeight(key, "weight", parseFloat(e.target.value) || 0)}
                      style={{ width: 56, textAlign: "center" }} className="input"
                    />
                  </td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input
                      type="number" min={1000} max={20000} step={100}
                      value={cfg.max} onChange={(e) => updateSiteWeight(key, "max", parseInt(e.target.value) || 9999)}
                      style={{ width: 72, textAlign: "center" }} className="input"
                    />
                  </td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input type="checkbox" checked={cfg.tep} onChange={(e) => updateSiteWeight(key, "tep", e.target.checked)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Section>

      <Section title="IDP Value Sources" defaultOpen={false}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.78rem" }}>
          <thead>
            <tr style={{ borderBottom: "1px solid var(--border)" }}>
              <th style={{ textAlign: "left", padding: "4px 8px" }}>Source</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>On</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>Weight</th>
              <th style={{ textAlign: "center", padding: "4px 4px" }}>Max</th>
            </tr>
          </thead>
          <tbody>
            {activeSites.idp.map((key) => {
              const cfg = getSiteConfig(key);
              return (
                <tr key={key} style={{ borderBottom: "1px solid var(--border)", opacity: cfg.include ? 1 : 0.4 }}>
                  <td style={{ padding: "4px 8px" }}>{cfg.label || key}</td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input type="checkbox" checked={cfg.include} onChange={(e) => updateSiteWeight(key, "include", e.target.checked)} />
                  </td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input
                      type="number" min={0} max={3} step={0.1}
                      value={cfg.weight} onChange={(e) => updateSiteWeight(key, "weight", parseFloat(e.target.value) || 0)}
                      style={{ width: 56, textAlign: "center" }} className="input"
                    />
                  </td>
                  <td style={{ textAlign: "center", padding: "4px 4px" }}>
                    <input
                      type="number" min={500} max={10000} step={100}
                      value={cfg.max} onChange={(e) => updateSiteWeight(key, "max", parseInt(e.target.value) || 5000)}
                      style={{ width: 72, textAlign: "center" }} className="input"
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
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
          {status.playerCount != null && <div>Players: {status.playerCount}</div>}
          {status.lastUpdate && <div>Last update: {status.lastUpdate}</div>}
          {status.nextUpdate && <div>Next update: {status.nextUpdate}</div>}
          {status.version && <div>Version: {status.version}</div>}
          {status.uptime && <div>Uptime: {status.uptime}</div>}
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
