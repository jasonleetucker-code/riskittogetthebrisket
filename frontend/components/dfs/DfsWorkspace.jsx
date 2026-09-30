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
  DataTable,
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
  ownerAdjustments,
  capabilitiesFor,
  errorMessage,
  exposureCountFor,
  formatPoints,
  formatSalary,
  readStoredContext,
  rulesToConstraints,
  readinessCopy,
  rulesetFor,
  singleLineupForm,
  statusCopy,
  statusTone,
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
const PlayerPool = lazy(() => import("./PlayerPool"));

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
  maxPerTeam: "",
  stack: false,
  stackMin: "1",
  stackBringBack: "0",
};

function LineupTable({ lineup, cap }) {
  const columns = [
    { key: "slot", header: "Slot", sortable: false },
    { key: "name", header: "Player", sortable: false },
    { key: "team", header: "Team", sortable: false, hideBelow: "sm", render: (p) => `${p.team}${p.opponent ? ` v ${p.opponent}` : ""}` },
    { key: "salary", header: "Salary", numeric: true, sortable: false, render: (p) => formatSalary(p.salary) },
    {
      key: "projection",
      header: "Proj",
      numeric: true,
      sortable: false,
      // The slot's multiplier (Showdown captain 1.5×) is shown, never hidden in the number.
      render: (p) => {
        const base = p.ownerOverride != null ? p.ownerOverride : p.projection;
        const shown =
          p.slotMultiplier && p.slotMultiplier !== 1
            ? `${formatPoints(p.slotProjection)} (${formatPoints(base)} × ${p.slotMultiplier})`
            : formatPoints(p.slotProjection ?? p.projection);
        return p.ownerOverride != null ? `${shown} · yours` : shown;
      },
    },
  ];
  return (
    <div className={styles.lineup}>
      <DataTable
        caption={`Lineup ${lineup.index}: ${formatPoints(lineup.projection)} projected points, ${formatSalary(lineup.salary)} of ${formatSalary(cap)}`}
        columns={columns}
        rows={lineup.players}
        rowKey={(p) => `${p.slot}-${p.playerId}`}
        density="compact"
      />
      <p className={styles.lineupTotals}>
        <span>
          Projected <strong className="ds-mono">{formatPoints(lineup.projection)}</strong>
        </span>
        <span>
          Salary <strong className="ds-mono">{formatSalary(lineup.salary)}</strong>
        </span>
        <span>
          Remaining <strong className="ds-mono">{formatSalary(lineup.salaryRemaining)}</strong>
        </span>
      </p>
    </div>
  );
}

/**
 * Fetch-then-save, not a bare <a download>: an export can be refused at
 * export time (rule set superseded, lineup no longer valid), and a plain
 * link would save that JSON refusal as if it were the CSV.
 */
function ExportButton({ buildId }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const onClick = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/dfs/builds/${buildId}/export`, { credentials: "same-origin", cache: "no-store" });
      if (!res.ok) {
        let body = null;
        try {
          body = await res.json();
        } catch {
          body = null;
        }
        setError(errorMessage(body, "Export refused."));
        return;
      }
      const blob = await res.blob();
      const disposition = res.headers.get("content-disposition") || "";
      const name = /filename="([^"]+)"/.exec(disposition)?.[1] || `${buildId}.csv`;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch {
      setError("The export could not be downloaded.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <Button variant="primary" onClick={onClick} loading={busy}>
        Download upload CSV
      </Button>
      {error ? (
        <Banner tone="negative" title="Export refused">
          {error}
        </Banner>
      ) : null}
    </>
  );
}

function BuildResult({ build, ruleset }) {
  const r = build.result;
  const conflict = r.shortfall?.conflict;
  return (
    <div className={styles.result}>
      <div className={styles.resultHead}>
        <StatusIndicator status={statusTone(r.status)}>
          {r.status.replaceAll("_", " ")} · {r.built} of {r.requested}
        </StatusIndicator>
        {build.researchOnly ? <StatusIndicator status="warning">Research only</StatusIndicator> : null}
        <span className={styles.meta}>
          Highest projected points · not contest-evaluated · {build.solver} · {r.elapsedMs} ms
        </span>
      </div>
      <p className={styles.note}>{statusCopy(r.status, r.built)}</p>
      {build.disclosures?.length ? (
        <Banner tone="info" title={build.contest ? `Built for: ${build.contest.name}` : build.preset ? `Built for: ${build.preset.label}` : "What this build is"}>
          <ul className={styles.list}>
            {build.disclosures.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {r.built > 1 ? <p className={styles.note}>{build.methodNote}</p> : null}
      {r.shortfall ? (
        <Banner
          tone={r.built ? "warning" : "negative"}
          title={r.built ? `${r.shortfall.missing} lineup(s) short` : "No lineup could be built"}
        >
          {conflict?.described?.length ? (
            <>
              <p>These of your constraints cannot all hold together with the official rules:</p>
              <ul className={styles.list}>
                {conflict.described.map((d) => (
                  <li key={d}>{d}</li>
                ))}
              </ul>
              <p>Nothing was relaxed. Remove or loosen one of them and build again.</p>
            </>
          ) : conflict?.message ? (
            <p>{conflict.message}</p>
          ) : (
            <p>Reason: {String(r.shortfall.reason || "unknown").replaceAll("_", " ")}.</p>
          )}
        </Banner>
      ) : null}
      {r.excludedUnprojected?.length ? (
        <p className={styles.note}>
          {r.excludedUnprojected.length} player(s) without a projection were left out — missing is never scored as
          zero.
        </p>
      ) : null}
      {r.lineups.map((lu) => (
        <LineupTable key={lu.index} lineup={lu} cap={ruleset?.salaryCap} />
      ))}
      {r.built > 1 ? (
        <DataTable
          caption="Exposure across the built lineups"
          columns={[
            { key: "name", header: "Player" },
            { key: "count", header: "Lineups", numeric: true },
            { key: "share", header: "Share", numeric: true, render: (x) => `${Math.round((x.share || 0) * 100)}%` },
            { key: "cap", header: "Cap", numeric: true, render: (x) => (x.cap == null ? "—" : x.cap) },
          ]}
          rows={r.exposure}
          rowKey={(x) => x.playerId}
          density="compact"
          defaultSort={{ key: "count", direction: "desc" }}
        />
      ) : null}
      {r.built ? (
        <div className={styles.exportRow}>
          <ExportButton buildId={build.buildId} />
          <p className={styles.note}>
            {build.ruleset.exportVerification === "verified"
              ? "Format verified against the platform template."
              : "Upload format not yet verified against an official platform template — check it before uploading."}{" "}
            Downloading submits nothing; you upload it yourself.
          </p>
        </div>
      ) : null}
      <details className={styles.provenance}>
        <summary>Provenance and limits</summary>
        <dl className={styles.facts}>
          <div>
            <dt>Build</dt>
            <dd className="ds-mono">{build.buildId}</dd>
          </div>
          <div>
            <dt>Rule set</dt>
            <dd className="ds-mono">{build.ruleset.key}</dd>
          </div>
          <div>
            <dt>Snapshot</dt>
            <dd className="ds-mono" title={build.snapshot.contentHash}>
              {build.snapshot.contentHash.slice(0, 12)}
            </dd>
          </div>
          <div>
            <dt>Constraints</dt>
            <dd className="ds-mono">{build.constraintsHash.slice(0, 12)}</dd>
          </div>
          <div>
            <dt>Built</dt>
            <dd className="ds-mono">{new Date(build.createdAt).toLocaleString()}</dd>
          </div>
        </dl>
        <ul className={styles.list}>
          {build.limits.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </details>
    </div>
  );
}

export default function DfsWorkspace() {
  const [caps, setCaps] = useState(null);
  const [capsError, setCapsError] = useState(null);
  const [sport, setSport] = useState("nfl");
  const [platform, setPlatform] = useState("draftkings");
  const [format, setFormat] = useState("classic");
  const [salaryText, setSalaryText] = useState("");
  const [projectionText, setProjectionText] = useState("");
  const [useAverage, setUseAverage] = useState(false);
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
  const [overrides, setOverrides] = useState({});
  const [boosts, setBoosts] = useState({});

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
    setOverrides({});
    setBoosts({});
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
        usePlatformAverage: useAverage,
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
    setOverrides({});
    setBoosts({});
  };

  const runBuild = async (lineupsOverride) => {
    const effective = lineupsOverride === 1 ? singleLineupForm(form) : form;
    const { payload, errors } = buildConstraints(effective, rules);
    const extra = rulesToConstraints(groupRules);
    if (extra.groups.length) payload.groups = extra.groups;
    if (extra.conditionals.length) payload.conditionals = extra.conditionals;
    const adj = ownerAdjustments(overrides, boosts);
    if (Object.keys(adj.errors).length) {
      setBuildError(Object.values(adj.errors)[0]);
      return;
    }
    if (Object.keys(adj.payload.projectionOverrides).length) payload.projectionOverrides = adj.payload.projectionOverrides;
    if (Object.keys(adj.payload.boosts).length) payload.boosts = adj.payload.boosts;
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
                  setOverrides({});
                  setBoosts({});
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
              <BuildResult build={build} ruleset={ruleset} />
            </Panel>
          ) : null}
        </>
      )}
    </div>
  );
}
