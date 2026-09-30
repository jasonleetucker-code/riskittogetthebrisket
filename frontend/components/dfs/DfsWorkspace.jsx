"use client";

/**
 * DfsWorkspace — the /dfs workflow: context → slate import → player pool
 * controls → build → results/export.
 *
 * Display layer only (see lib/dfs.js): the backend owns rules, identity,
 * the solver and every number here.  Capability honesty is structural:
 * contest-aware optimization is shown as unavailable with its reason, the
 * baseline objective is named on the button's result, research-only rule
 * sets are labelled at the context bar, on the build and on the export.
 */

import React, { Suspense, lazy, useCallback, useEffect, useMemo, useState } from "react";
import {
  Banner,
  Button,
  EmptyState,
  Field,
  Input,
  Panel,
  SegmentedControl,
  Select,
  StatusIndicator,
} from "@/components/ds";
import {
  FORMAT_LABELS,
  PLATFORMS,
  SPORTS,
  buildConstraints,
  exposureAdjustments,
  ownerAdjustments,
  capabilitiesFor,
  errorMessage,
  exposureCountFor,
  formatSalary,
  readStoredContext,
  rulesToConstraints,
  readinessCopy,
  rulesetFor,
  singleLineupForm,
  writeStoredContext,
} from "@/lib/dfs";
import styles from "./dfs-workspace.module.css";

// Code-split (React.lazy, the Perfect Draft pattern — not next/dynamic, which
// pulls Next's loadable runtime into every page's shared chunk). Keeps the
// contest editor out of the /dfs initial chunk and its 34 KB budget.
const ContestPanel = lazy(() => import("./ContestPanel"));
const ProviderSlates = lazy(() => import("./SlateSources"));
const DetectedFile = lazy(() => import("./SlateSources").then((m) => ({ default: m.DetectedFile })));

const ImportSummary = lazy(() => import("./SlateSummary"));
const RuleBuilder = lazy(() => import("./RuleBuilder"));
const TeamStacks = lazy(() => import("./TeamStacks"));
const PlayerPool = lazy(() => import("./PlayerPool"));
const LateSwap = lazy(() => import("./LateSwap"));
const ResultsImport = lazy(() => import("./ResultsImport"));
const BuildResult = lazy(() => import("./BuildResult"));

async function api(path, init) {
  const res = await fetch(`/api/dfs${path}`, {
    credentials: "same-origin",
    cache: "no-store",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  return { ok: res.ok, status: res.status, body };
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result || ""));
    r.onerror = () => reject(r.error);
    r.readAsText(file);
  });
}

const EMPTY_FORM = {
  lineups: "1",
  minUnique: "1",
  maxExposurePct: "",
  salaryMin: "",
  salaryMax: "",
  maxPerTeam: "",
  stack: false,
  stackMin: "1",
  stackBringBack: "0",
};

export default function DfsWorkspace() {
  const [caps, setCaps] = useState(null);
  const [capsError, setCapsError] = useState(null);
  const [sport, setSport] = useState("nfl");
  const [platform, setPlatform] = useState("draftkings");
  const [format, setFormat] = useState("classic");
  const [salaryText, setSalaryText] = useState("");
  const [projectionText, setProjectionText] = useState("");
  const [useAverage, setUseAverage] = useState(false);
  const [ownershipText, setOwnershipText] = useState("");
  const [ownershipUnit, setOwnershipUnit] = useState("percent");
  // "" = the file's floor/ceiling percentiles are not stated: kept, never modelled.
  const [rangePct, setRangePct] = useState("");
  const [slate, setSlate] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importError, setImportError] = useState(null);
  const [rules, setRules] = useState({ locks: [], excludes: [] });
  const [form, setForm] = useState(EMPTY_FORM);
  const [building, setBuilding] = useState(false);
  const [build, setBuild] = useState(null);
  const [buildError, setBuildError] = useState(null);
  const [buildContext, setBuildContext] = useState({ contestId: null, presetId: null });
  const [groupRules, setGroupRules] = useState([]);
  const [teamStacks, setTeamStacks] = useState([]);
  const [overrides, setOverrides] = useState({});
  const [boosts, setBoosts] = useState({});
  const [exposure, setExposure] = useState({});

  useEffect(() => {
    const stored = readStoredContext();
    if (stored) {
      if (stored.sport) setSport(stored.sport);
      if (stored.platform) setPlatform(stored.platform);
      if (stored.format) setFormat(stored.format);
    }
    let live = true;
    api("/capabilities").then(({ ok, body }) => {
      if (!live) return;
      if (ok) setCaps(body);
      else setCapsError(errorMessage(body, "The DFS workspace is unavailable."));
    });
    return () => {
      live = false;
    };
  }, []);

  useEffect(() => {
    writeStoredContext({ sport, platform, format });
  }, [sport, platform, format]);

  const rows = useMemo(() => capabilitiesFor(caps?.matrix, sport, platform), [caps, sport, platform]);
  const row = rows.find((r) => r.format === format) || rows[0] || null;
  const ruleset = rulesetFor(caps, row);
  const readiness = readinessCopy(row?.readiness);
  const slateMatches = slate && ruleset && slate.ruleset?.key === ruleset.key;

  const changeContext = useCallback((next) => {
    if (next.sport) setSport(next.sport);
    if (next.platform) setPlatform(next.platform);
    if (next.format) setFormat(next.format);
    setBuild(null);
    setBuildError(null);
    setBuildContext({ contestId: null, presetId: null });
    setGroupRules([]);
    setTeamStacks([]);
    setOverrides({});
    setBoosts({});
    setExposure({});
  }, []);

  const onFile = async (e, setter) => {
    const f = e.target.files?.[0];
    if (!f) return;
    try {
      setter(await readFile(f));
    } catch {
      setImportError("That file could not be read.");
    }
  };

  const importSlate = async () => {
    if (!ruleset) return;
    setImporting(true);
    setImportError(null);
    setBuild(null);
    const { ok, body } = await api("/slates", {
      method: "POST",
      body: JSON.stringify({
        ruleset: ruleset.id,
        salaryCsv: salaryText,
        projectionCsv: projectionText || undefined,
        ownershipCsv: ownershipText || undefined,
        ownershipUnit: ownershipText ? ownershipUnit : undefined,
        usePlatformAverage: useAverage,
        ...(rangePct ? { floorPercentile: Number(rangePct), ceilingPercentile: 100 - Number(rangePct) } : {}),
      }),
    });
    setImporting(false);
    if (!ok) {
      setImportError(errorMessage(body, "Import failed."));
      return;
    }
    setSlate(body);
    setRules({ locks: [], excludes: [] });
    setGroupRules([]);
    setTeamStacks([]);
    setOverrides({});
    setBoosts({});
    setExposure({});
  };

  const runBuild = async (lineupsOverride) => {
    const effective = lineupsOverride === 1 ? singleLineupForm(form) : form;
    const { payload, errors } = buildConstraints(effective, rules);
    const extra = rulesToConstraints(groupRules);
    if (extra.groups.length) payload.groups = extra.groups;
    if (extra.conditionals.length) payload.conditionals = extra.conditionals;
    if (teamStacks.length) payload.teamStacks = teamStacks;
    const adj = ownerAdjustments(overrides, boosts);
    if (Object.keys(adj.errors).length) {
      setBuildError(Object.values(adj.errors)[0]);
      return;
    }
    if (Object.keys(adj.payload.projectionOverrides).length) payload.projectionOverrides = adj.payload.projectionOverrides;
    if (Object.keys(adj.payload.boosts).length) payload.boosts = adj.payload.boosts;
    // A per-player exposure range only means something across several lineups.
    if (lineupsOverride !== 1) {
      const exp = exposureAdjustments(exposure);
      if (Object.keys(exp.errors).length) {
        setBuildError(Object.values(exp.errors)[0]);
        return;
      }
      if (Object.keys(exp.payload.playerMinExposure).length) payload.playerMinExposure = exp.payload.playerMinExposure;
      if (Object.keys(exp.payload.playerMaxExposure).length) payload.playerMaxExposure = exp.payload.playerMaxExposure;
    }
    if (Object.keys(errors).length) {
      setBuildError(Object.values(errors)[0]);
      return;
    }
    setBuilding(true);
    setBuildError(null);
    const { ok, body } = await api("/builds", {
      method: "POST",
      body: JSON.stringify({
        snapshotId: slate.snapshotId,
        objective: "projection_baseline",
        mode: "research",
        constraints: payload,
        contestId: buildContext.contestId || undefined,
        presetId: buildContext.presetId || undefined,
      }),
    });
    setBuilding(false);
    if (!ok) {
      setBuildError(errorMessage(body, "Build failed."));
      return;
    }
    setBuild(body);
  };

  const athletes = slate?.athletes || [];


  const nLineups = Number(form.lineups);
  const exposureNote =
    form.maxExposurePct !== "" && Number.isInteger(nLineups)
      ? `= at most ${exposureCountFor(Number(form.maxExposurePct), nLineups)} of ${nLineups} lineups (rounded down)`
      : null;

  if (capsError) {
    return (
      <Banner tone="negative" title="DFS workspace unavailable">
        {capsError}
      </Banner>
    );
  }

  return (
    <div className={styles.workspace}>
      <section className={styles.context} aria-label="Slate context">
        <SegmentedControl label="Sport" options={SPORTS} value={sport} onChange={(v) => changeContext({ sport: v })} />
        <SegmentedControl
          label="Platform"
          options={PLATFORMS}
          value={platform}
          onChange={(v) => changeContext({ platform: v })}
        />
        {rows.length > 1 ? (
          <label className={styles.inline}>
            <span>Format</span>
            <Select
              aria-label="Contest format"
              value={row?.format || ""}
              onChange={(e) => changeContext({ format: e.target.value })}
              options={rows.map((r) => ({ value: r.format, label: FORMAT_LABELS[r.format] || r.format }))}
            />
          </label>
        ) : null}
        {caps ? <StatusIndicator status={readiness.status}>{readiness.label}</StatusIndicator> : null}
      </section>
      {caps && row && row.readiness !== "money_ready" ? (
        <p className={styles.note} role="note">
          {row.reason}
          {ruleset?.verification?.blocker ? ` ${ruleset.verification.blocker}` : ""}
        </p>
      ) : null}

      {!caps ? (
        <p className={styles.note} aria-live="polite">
          Loading capabilities…
        </p>
      ) : !ruleset ? (
        <EmptyState
          title={`${SPORTS.find((s) => s.value === sport)?.label} on ${PLATFORMS.find((p) => p.value === platform)?.label} is not available yet`}
          description={row?.reason || "No rule set is encoded for this combination."}
        />
      ) : (
        <>
          <Panel title="1 · Import slate" subtitle={`${ruleset.label} · ${ruleset.version} · cap ${formatSalary(ruleset.salaryCap)}`}>
            <div className={styles.importGrid}>
              <Field label={`${PLATFORMS.find((p) => p.value === platform)?.label} salary file (CSV)`} hint="Export it from the contest's lineup page, then choose it or paste it.">
                <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e, setSalaryText)} />
              </Field>
              <Field label="Projections (CSV, optional)" hint="Columns: ID or Name + Team, and Projection.">
                <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e, setProjectionText)} />
              </Field>
              <Field label="Salary CSV text">
                <textarea
                  className={`ds-input ${styles.textarea}`}
                  value={salaryText}
                  onChange={(e) => setSalaryText(e.target.value)}
                  rows={4}
                  spellCheck={false}
                />
              </Field>
              <Field label="Projection CSV text">
                <textarea
                  className={`ds-input ${styles.textarea}`}
                  value={projectionText}
                  onChange={(e) => setProjectionText(e.target.value)}
                  rows={4}
                  spellCheck={false}
                />
              </Field>
              <Field label="Floor / Ceiling columns are" hint="Optional StDev and P10…P90 columns need no label.">
                <Select
                  value={rangePct}
                  onChange={(e) => setRangePct(e.target.value)}
                  options={[
                    { value: "", label: "Not stated (kept, not used)" },
                    ...["10", "15", "20", "25"].map((p) => ({ value: p, label: `${p}th / ${100 - Number(p)}th percentile` })),
                  ]}
                />
              </Field>
              <Field label="Projected ownership (CSV, optional)" hint="Columns: ID or Name + Team, and Own%. Players not listed stay unknown, never 0%.">
                <input type="file" accept=".csv,text/csv" onChange={(e) => onFile(e, setOwnershipText)} />
              </Field>
              <Field label="Ownership values are">
                <Select
                  value={ownershipUnit}
                  onChange={(e) => setOwnershipUnit(e.target.value)}
                  options={[
                    { value: "percent", label: "Percent (35 = 35%)" },
                    { value: "fraction", label: "Fraction (0.35 = 35%)" },
                  ]}
                />
              </Field>
            </div>
            <Suspense fallback={null}>
              <DetectedFile
                text={salaryText}
                context={{ platform, sport, format: row?.format || format }}
                onSwitch={changeContext}
              />
            </Suspense>
            <label className={styles.check}>
              <input type="checkbox" checked={useAverage} onChange={(e) => setUseAverage(e.target.checked)} />
              Where a player has no projection, use the platform season average (labelled “avg”; it is not a
              forecast)
            </label>
            <div className={styles.actions}>
              <Button variant="primary" onClick={importSlate} loading={importing} disabled={!salaryText.trim()}>
                Import slate
              </Button>
            </div>
            {importError ? (
              <Banner tone="negative" title="Import refused">
                {importError}
              </Banner>
            ) : null}
            <Suspense fallback={null}>
              <ProviderSlates
                sport={sport}
                platform={platform}
                onImported={(snap) => {
                  setSlate(snap);
                  setRules({ locks: [], excludes: [] });
                  setGroupRules([]);
                  setTeamStacks([]);
    setTeamStacks([]);
                  setOverrides({});
                  setBoosts({});
                  setExposure({});
                  setBuild(null);
                }}
              />
            </Suspense>
            {slateMatches ? (
              <Suspense fallback={null}>
                <ImportSummary slate={slate} />
              </Suspense>
            ) : null}
          </Panel>

          <Panel
            title="2 · Contest"
            subtitle="Payouts, fees, entry limits and your spend limit. Checked by the server; used for contest-aware evaluation once it exists."
          >
            {/* Keyed by context: a contest entered for one platform/sport/format is
                never carried into another (different fees, rules, exports). */}
            <Suspense fallback={<p className={styles.note}>Loading contest editor…</p>}>
              <ContestPanel
                key={`${platform}.${sport}.${row?.format || format}`}
                platform={platform}
                sport={sport}
                format={row?.format || format}
                onContextChange={setBuildContext}
              />
            </Suspense>
          </Panel>

          {slateMatches ? (
            <Panel title="3 · Player pool" subtitle={`${rules.locks.length} locked · ${rules.excludes.length} excluded`}>
              <Suspense fallback={<p className={styles.note}>Loading player pool…</p>}>
                <PlayerPool
                  athletes={athletes}
                  rules={rules}
                  setRules={setRules}
                  overrides={overrides}
                  setOverrides={setOverrides}
                  boosts={boosts}
                  setBoosts={setBoosts}
                  exposure={exposure}
                  setExposure={setExposure}
                />
              </Suspense>
            </Panel>
          ) : null}

          {slateMatches ? (
            <Panel title="4 · Build">
              <fieldset className={styles.objective}>
                <legend>Objective</legend>
                {(caps.objectives || []).map((o) => (
                  <label key={o.id} className={styles.check}>
                    <input type="radio" name="objective" checked={o.id === "projection_baseline"} disabled={!o.available} readOnly />
                    <span>
                      <strong>{o.label}</strong>
                      {o.available ? "" : " — unavailable"}
                      <span className={styles.note}> {o.description}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
              <div className={styles.controlGrid}>
                <Field label="Lineups">
                  <Input data-numeric inputMode="numeric" value={form.lineups} onChange={(e) => setForm({ ...form, lineups: e.target.value })} />
                </Field>
                <Field label="Min unique players vs other lineups">
                  <Input data-numeric inputMode="numeric" value={form.minUnique} onChange={(e) => setForm({ ...form, minUnique: e.target.value })} />
                </Field>
                <Field label="Max exposure %" hint={exposureNote || "Portfolio builds only; locked players are exempt."}>
                  <Input data-numeric inputMode="decimal" value={form.maxExposurePct} onChange={(e) => setForm({ ...form, maxExposurePct: e.target.value })} />
                </Field>
                <Field label="Min salary">
                  <Input data-numeric inputMode="numeric" value={form.salaryMin} onChange={(e) => setForm({ ...form, salaryMin: e.target.value })} />
                </Field>
                <Field label="Max salary" hint="Leave salary on the table: cap your own spend below the platform cap.">
                  <Input data-numeric inputMode="numeric" value={form.salaryMax} onChange={(e) => setForm({ ...form, salaryMax: e.target.value })} />
                </Field>
                <Field label="Max players per team">
                  <Input data-numeric inputMode="numeric" value={form.maxPerTeam} onChange={(e) => setForm({ ...form, maxPerTeam: e.target.value })} />
                </Field>
              </div>
              {sport === "nfl" ? (
                <fieldset className={styles.objective}>
                  <legend>Stack (optional)</legend>
                  <label className={styles.check}>
                    <input type="checkbox" checked={form.stack} onChange={(e) => setForm({ ...form, stack: e.target.checked })} />
                    Pair the QB with same-team pass catchers
                  </label>
                  {form.stack ? (
                    <div className={styles.controlGrid}>
                      <Field label="Same-team WR/TE">
                        <Input data-numeric inputMode="numeric" value={form.stackMin} onChange={(e) => setForm({ ...form, stackMin: e.target.value })} />
                      </Field>
                      <Field label="Bring-back from opponent">
                        <Input data-numeric inputMode="numeric" value={form.stackBringBack} onChange={(e) => setForm({ ...form, stackBringBack: e.target.value })} />
                      </Field>
                    </div>
                  ) : null}
                </fieldset>
              ) : null}
              <Suspense fallback={null}>
                <RuleBuilder athletes={athletes} rules={groupRules} onChange={setGroupRules} />
                <TeamStacks
                  stacks={teamStacks}
                  onChange={setTeamStacks}
                  athletes={athletes}
                  slotCount={ruleset?.slots?.length || 0}
                  singleGame={ruleset?.eligibilityBasis === "platform_slots"}
                />
              </Suspense>
              <div className={styles.actions}>
                <Button variant="primary" onClick={() => runBuild(1)} loading={building}>
                  Optimal Lineup
                </Button>
                <Button variant="secondary" onClick={() => runBuild(null)} loading={building}>
                  Build Portfolio
                </Button>
              </div>
              {buildError ? (
                <Banner tone="negative" title="Build refused">
                  {buildError}
                </Banner>
              ) : null}
            </Panel>
          ) : null}

          {build && slateMatches ? (
            <Panel title="5 · Result">
              <Suspense fallback={null}>
                <BuildResult build={build} ruleset={ruleset} />
              </Suspense>
            </Panel>
          ) : null}

          {slate && slateMatches && ruleset?.platform === "draftkings" ? (
            <Panel title="6 · Late swap">
              <Suspense fallback={null}>
                <LateSwap snapshotId={slate.snapshotId} athletes={slate.athletes} />
              </Suspense>
            </Panel>
          ) : null}

          {slate && slateMatches && ruleset?.platform === "draftkings" ? (
            <Panel title="7 · Results">
              <Suspense fallback={null}>
                <ResultsImport snapshotId={slate.snapshotId} contestId={buildContext.contestId} />
              </Suspense>
            </Panel>
          ) : null}
        </>
      )}
    </div>
  );
}
