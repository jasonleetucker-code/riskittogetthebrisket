"use client";

/**
 * SlateSources — where a slate can come from, and whether that source works
 * right now (owner addendum 2026-09-30: platform / slate ingestion).
 *
 * * `DetectedFile` tells the owner what a pasted / chosen platform file is
 *   (platform · sport · format) BEFORE import, and offers a one-click switch
 *   when it does not match the selected context — never a silent switch.
 * * `ProviderSlates` shows the licensed feed's real status. Unconnected is
 *   shown as unconnected, with the always-available CSV fallback named.
 *
 * Display only: detection and provider state come from /api/dfs/*.
 */

import React, { useEffect, useState } from "react";
import { Banner, Button, Field, Input, StatusIndicator } from "@/components/ds";
import { FORMAT_LABELS, PLATFORMS, SPORTS, errorMessage } from "@/lib/dfs";
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

const label = (list, v) => list.find((x) => x.value === v)?.label || v;

export function describeDetection(d) {
  if (!d || !d.platform) return null;
  const parts = [label(PLATFORMS, d.platform)];
  if (d.sport) parts.push(label(SPORTS, d.sport));
  if (d.format) parts.push(FORMAT_LABELS[d.format] || d.format);
  return parts.join(" · ");
}

export function DetectedFile({ text, context, onSwitch }) {
  const [result, setResult] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!text || !text.trim()) {
      setResult(null);
      setError(null);
      return undefined;
    }
    let live = true;
    const t = setTimeout(async () => {
      const r = await api("/slates/detect", { method: "POST", body: JSON.stringify({ salaryCsv: text }) });
      if (!live) return;
      if (r.ok) {
        setResult(r.body);
        setError(null);
      } else {
        setResult(null);
        setError(errorMessage(r.body, "The file could not be read."));
      }
    }, 350);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [text]);

  if (error) return <p className={styles.note} role="status">{error}</p>;
  if (!result) return null;
  const d = result.detection;
  const what = describeDetection(d);
  if (!what || !d.sport) {
    return (
      <Banner tone="warning" title="File not recognised">
        {d.reasons?.join(". ")}. Only DraftKings salary files and FanDuel player lists are supported.
      </Banner>
    );
  }
  const matches = d.platform === context.platform && d.sport === context.sport && d.format === context.format;
  const readiness = result.capability?.readiness;
  return (
    <div className={styles.detected} role="status">
      <StatusIndicator status={matches ? "positive" : "warning"}>Detected: {what}</StatusIndicator>
      {readiness === "not_implemented" || !result.capability ? (
        <span className={styles.note}> Recognised, but its roster rules are not encoded yet — it cannot be built.</span>
      ) : null}
      {!matches && readiness && readiness !== "not_implemented" ? (
        <Button size="sm" variant="secondary" onClick={() => onSwitch({ platform: d.platform, sport: d.sport, format: d.format })}>
          Switch to {what}
        </Button>
      ) : null}
    </div>
  );
}

export default function ProviderSlates({ sport, platform, onImported }) {
  const [info, setInfo] = useState(null);
  const [date, setDate] = useState("");
  const [slates, setSlates] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    api("/providers").then((r) => live && r.ok && setInfo(r.body));
    return () => {
      live = false;
    };
  }, []);

  if (!info) return null;
  const status = info.status?.sportsdataio;
  const cell = (info.matrix || []).find((c) => c.sport === sport && c.platform === platform);
  const connected = status?.state === "configured_unverified";

  const list = async () => {
    setBusy(true);
    setError(null);
    const q = new URLSearchParams({ sport, platform, date });
    const r = await api(`/provider-slates?${q}`);
    setBusy(false);
    if (!r.ok) {
      setSlates(null);
      setError(`${errorMessage(r.body, "The provider is unavailable.")} ${r.body?.detail?.fallback || ""}`);
      return;
    }
    setSlates(r.body.slates);
  };

  const load = async (id) => {
    setBusy(true);
    setError(null);
    const r = await api("/provider-slates/import", {
      method: "POST",
      body: JSON.stringify({ sport, date, providerSlateId: id }),
    });
    setBusy(false);
    if (!r.ok) {
      setError(errorMessage(r.body, "The slate could not be loaded."));
      return;
    }
    onImported(r.body);
  };

  return (
    <div className={styles.providerBox}>
      <h3 className={styles.subhead}>Load from a licensed feed</h3>
      <p className={styles.note}>
        <StatusIndicator status={connected ? "warning" : "neutral"}>
          SportsDataIO: {connected ? "connected, coverage unverified" : "not connected"}
        </StatusIndicator>{" "}
        {status?.note} {cell ? `${label(SPORTS, sport)} on ${label(PLATFORMS, platform)}: ${cell.reason}` : ""}
      </p>
      {connected ? null : (
        <p className={styles.note}>Use the platform&apos;s salary file above — that path always works.</p>
      )}
      {connected ? (
        <div className={styles.actions}>
          <Field label="Slate date">
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </Field>
          <Button variant="secondary" onClick={list} loading={busy} disabled={!date}>
            List slates
          </Button>
        </div>
      ) : null}
      {error ? (
        <Banner tone="negative" title="Provider unavailable">
          {error}
        </Banner>
      ) : null}
      {slates ? (
        slates.length ? (
          <ul className={styles.list}>
            {slates.map((s) => (
              <li key={s.providerSlateId}>
                {s.name} · {s.games} games · {s.players} players{" "}
                <Button size="sm" variant="secondary" onClick={() => load(s.providerSlateId)} disabled={busy}>
                  Load
                </Button>
              </li>
            ))}
          </ul>
        ) : (
          <p className={styles.note}>No slates for that date.</p>
        )
      ) : null}
    </div>
  );
}
