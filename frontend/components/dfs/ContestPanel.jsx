"use client";

/**
 * ContestPanel — enter, check, save and reload a contest for the selected
 * platform × sport × format.  Display layer only: the backend
 * (`src/dfs/contests.py`) validates the ladder, computes rake / overlay,
 * exact tie payouts and the entry cap.  Nothing here recomputes money.
 *
 * The spend limit is used for one check and never stored or inferred.
 */

import React, { useEffect, useState } from "react";
import { Banner, Button, Field, Input, Select, StatusIndicator } from "@/components/ds";
import { errorMessage } from "@/lib/dfs";
import {
  EMPTY_CONTEST_FORM,
  contestPayload,
  contestToForm,
  economicsCopy,
  formatCents,
  presetsForShape,
  shapeLabel,
} from "@/lib/dfs-contests";
import styles from "./dfs-workspace.module.css";

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

function pct(v) {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;
}

function Money({ cents }) {
  const v = formatCents(cents);
  return v === null ? <span className={styles.missing}>unknown</span> : <span className="ds-mono">{v}</span>;
}

function ContestReport({ result, presets }) {
  const { report, entryCap } = result;
  const d = report.derived;
  const econ = d.economics;
  const tie = report.tiePreview;
  const fitting = presetsForShape(presets, d.payoutShape.shape);
  return (
    <div className={styles.summary} aria-live="polite">
      {report.errors.length ? (
        <Banner tone="negative" title="This contest cannot be evaluated yet">
          <ul className={styles.list}>
            {report.errors.map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      {report.warnings.length ? (
        <Banner tone="warning" title="Check these before relying on the contest">
          <ul className={styles.list}>
            {report.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Banner>
      ) : null}
      <dl className={styles.facts}>
        <div>
          <dt>Shape</dt>
          <dd>{shapeLabel(d.payoutShape.shape)}</dd>
        </div>
        <div>
          <dt>Paid places</dt>
          <dd className="ds-mono">
            {d.paidPlaces} ({pct(d.paidShare)})
          </dd>
        </div>
        <div>
          <dt>Cash prizes</dt>
          <dd>
            <Money cents={d.cashPrizeCents} />
          </dd>
        </div>
        <div>
          <dt>First place</dt>
          <dd>
            <Money cents={d.firstPlaceCents} /> {d.firstPlaceShareOfCash != null ? `(${pct(d.firstPlaceShareOfCash)})` : ""}
          </dd>
        </div>
        <div>
          <dt>Min cash</dt>
          <dd>
            <Money cents={d.minCashCents} />
          </dd>
        </div>
        <div>
          <dt>Economics</dt>
          <dd>
            {economicsCopy(econ.state)}
            {econ.effectiveRake != null ? ` · effective rake ${pct(econ.effectiveRake)}` : ""}
          </dd>
        </div>
      </dl>
      {econ.note ? <p className={styles.note}>{econ.note}</p> : null}
      {tie ? (
        <p className={styles.note}>
          Two entries tied for first:{" "}
          {tie.state === "exact"
            ? `${formatCents(tie.eachCents)} each (ranks 1 and 2 pooled and split).`
            : tie.state === "exact_fraction"
              ? `${tie.exact} cents each — not a whole cent; the platform's rounding is unverified.`
              : "unavailable — set the contest's tie rule to compute it."}
        </p>
      ) : null}
      {!d.exactEvAllowed ? (
        <p className={styles.note}>Exact contest value is suppressed for this contest (see the notes above).</p>
      ) : null}
      <div>
        <h3 className={styles.subhead}>Entry cap</h3>
        {entryCap.upperBound != null ? (
          <p className={styles.note}>
            You can enter at most <strong className="ds-mono">{entryCap.upperBound}</strong> more
            {entryCap.totalFeeCentsAtBound != null ? ` (${formatCents(entryCap.totalFeeCentsAtBound)} in fees)` : ""} —
            limited by {entryCap.binding.map((b) => b.replace(/([A-Z])/g, " $1").toLowerCase()).join(", ")}.
          </p>
        ) : (
          <p className={styles.note}>
            Not computed — missing: {entryCap.missing.map((m) => m.replace(/([A-Z])/g, " $1").toLowerCase()).join(", ")}.
          </p>
        )}
        <p className={styles.note}>
          {entryCap.note} Recommended count: {entryCap.recommendation.state} — {entryCap.recommendation.reason}
        </p>
      </div>
      {fitting.length ? (
        <div>
          <h3 className={styles.subhead}>Strategy presets for this contest</h3>
          <ul className={styles.list}>
            {fitting.map((p) => (
              <li key={p.id}>
                <strong>{p.label}</strong> — {p.objective.description}{" "}
                <StatusIndicator status="neutral">Not available yet</StatusIndicator>{" "}
                <span className={styles.note}>{p.unsupportedReason}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

export default function ContestPanel({ platform, sport, format }) {
  const [form, setForm] = useState(EMPTY_CONTEST_FORM);
  const [spendLimit, setSpendLimit] = useState("");
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState([]);
  const [current, setCurrent] = useState(null); // { contestId, version }
  const [presets, setPresets] = useState([]);
  const [nonCash, setNonCash] = useState(0);

  const refresh = async () => {
    const r = await api("/contests");
    if (r.ok) setSaved(r.body.contests || []);
  };

  useEffect(() => {
    let live = true;
    api("/presets").then((r) => live && r.ok && setPresets(r.body.presets || []));
    api("/contests").then((r) => live && r.ok && setSaved(r.body.contests || []));
    return () => {
      live = false;
    };
  }, []);

  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const ctx = { platform, sport, format };
  const matchingSaved = saved.filter((c) => c.platform === platform && c.sport === sport && c.format === format);

  const check = async () => {
    setBusy(true);
    setError(null);
    const r = await api("/contests/validate", {
      method: "POST",
      body: JSON.stringify({ contest: contestPayload(form, ctx), spendLimit: spendLimit || null }),
    });
    setBusy(false);
    if (!r.ok) {
      setResult(null);
      setError(errorMessage(r.body, "The contest could not be checked."));
      return;
    }
    setResult(r.body);
  };

  const save = async () => {
    setBusy(true);
    setError(null);
    const r = await api("/contests", {
      method: "POST",
      body: JSON.stringify({ contest: contestPayload(form, ctx), contestId: current?.contestId ?? null }),
    });
    setBusy(false);
    if (!r.ok) {
      setError(errorMessage(r.body, "The contest could not be saved."));
      return;
    }
    setCurrent({ contestId: r.body.contestId, version: r.body.version });
    await refresh();
    await check();
  };

  const load = async (id) => {
    if (!id) {
      setCurrent(null);
      setForm(EMPTY_CONTEST_FORM);
      setResult(null);
      setNonCash(0);
      return;
    }
    const r = await api(`/contests/${encodeURIComponent(id)}`);
    if (!r.ok) {
      setError(errorMessage(r.body, "The contest could not be loaded."));
      return;
    }
    const f = contestToForm(r.body.contest);
    setNonCash(f.nonCashBands);
    setForm(f);
    setCurrent({ contestId: r.body.contestId, version: r.body.version });
    setResult(null);
  };

  return (
    <div>
      {matchingSaved.length ? (
        <label className={styles.inline}>
          <span>Saved contests</span>
          <Select
            aria-label="Saved contests"
            value={current?.contestId || ""}
            onChange={(e) => load(e.target.value)}
            options={[
              { value: "", label: "New contest" },
              ...matchingSaved.map((c) => ({ value: c.contestId, label: `${c.name} (v${c.version})` })),
            ]}
          />
        </label>
      ) : null}
      <div className={styles.controlGrid}>
        <Field label="Contest name">
          <Input value={form.name} onChange={set("name")} />
        </Field>
        <Field label="Entry">
          <Select
            value={form.entryMethod}
            onChange={set("entryMethod")}
            options={[
              { value: "cash", label: "Paid entry" },
              { value: "ticket", label: "Ticket" },
              { value: "free", label: "Free" },
            ]}
          />
        </Field>
        {form.entryMethod !== "free" ? (
          <Field label="Entry fee ($)">
            <Input data-numeric inputMode="decimal" value={form.entryFee} onChange={set("entryFee")} />
          </Field>
        ) : null}
        <Field label="Capacity">
          <Input data-numeric inputMode="numeric" value={form.capacity} onChange={set("capacity")} />
        </Field>
        <Field label="Current entries" hint="Blank = unknown">
          <Input data-numeric inputMode="numeric" value={form.currentEntries} onChange={set("currentEntries")} />
        </Field>
        <Field label="Guaranteed">
          <Select
            value={form.guaranteed}
            onChange={set("guaranteed")}
            options={[
              { value: "unknown", label: "Unknown" },
              { value: "yes", label: "Yes" },
              { value: "no", label: "No" },
            ]}
          />
        </Field>
        <Field label="Max entries per user">
          <Input data-numeric inputMode="numeric" value={form.maxEntriesPerUser} onChange={set("maxEntriesPerUser")} />
        </Field>
        <Field label="Your existing entries" hint="Blank = unknown">
          <Input data-numeric inputMode="numeric" value={form.existingUserEntries} onChange={set("existingUserEntries")} />
        </Field>
        <Field label="Tie rule">
          <Select
            value={form.tieRule}
            onChange={set("tieRule")}
            options={[
              { value: "unknown", label: "Unknown" },
              { value: "split_positions", label: "Tied entries split the tied places' prizes" },
            ]}
          />
        </Field>
      </div>
      <Field label="Payout table" hint="One rank or range per line, e.g. 1 $1,000 · 2-5 $100 · 6-50 $20">
        <textarea
          className={`ds-input ${styles.textarea}`}
          value={form.payoutText}
          onChange={set("payoutText")}
          rows={5}
          spellCheck={false}
        />
      </Field>
      <label className={styles.check}>
        <input type="checkbox" checked={form.hypothetical} onChange={set("hypothetical")} />
        This ladder is hypothetical (my assumption, not the contest's real payouts)
      </label>
      <div className={styles.controlGrid}>
        <Field label="Your spend limit for this contest ($)" hint="Used for the entry cap only; never stored or guessed.">
          <Input data-numeric inputMode="decimal" value={spendLimit} onChange={(e) => setSpendLimit(e.target.value)} />
        </Field>
      </div>
      {nonCash ? (
        <Banner tone="warning" title="This saved contest has non-cash prizes">
          {nonCash} ticket / non-cash band(s) cannot be edited in the payout table, so saving from this form is
          disabled to avoid dropping them.
        </Banner>
      ) : null}
      <div className={styles.actions}>
        <Button variant="secondary" onClick={check} loading={busy}>
          Check contest
        </Button>
        <Button variant="primary" onClick={save} loading={busy} disabled={Boolean(nonCash)}>
          {current ? `Save as version ${current.version + 1}` : "Save contest"}
        </Button>
      </div>
      {error ? (
        <Banner tone="negative" title="Contest refused">
          {error}
        </Banner>
      ) : null}
      {result ? <ContestReport result={result} presets={presets} /> : null}
    </div>
  );
}
