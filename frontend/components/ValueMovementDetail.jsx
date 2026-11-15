"use client";

/**
 * ValueMovementDetail — "Why it moved" for ONE asset: the contributing
 * evidence between the current board generation and the previous one, as
 * the temporal ledger recorded it. Evidence, not an asserted cause.
 *
 * Display only. Every number is a field of
 * GET /api/players/{player}/value-movement (owner:
 * src/history/movement.py::value_movement; row adapter
 * src/api/value_movement.py); labels come from lib/value-movement.js.
 * Nothing here computes a value, delta, weight, share or rank. The per-source
 * changes are labelled NOT ADDITIVE and are never presented as shares of the
 * value change. A source absent at one board reads "absent", never 0; a
 * quantity the ledger does not store reads "not recorded", never a guess.
 *
 * PRIVATE surface: the endpoint is session-gated. Player File only, never a
 * public /league page.
 *
 * Code-split: the Player File loads it with React.lazy + Suspense (the
 * repo's pattern — not next/dynamic, see CLAUDE.md "Perfect Draft") inside a
 * collapsed panel, so the fetch and the chunk cost nothing until opened.
 */
import React, { useEffect, useState } from "react";
import { Banner, Button, DataTable, Movement, SkeletonText } from "@/components/ds";
import {
  formatGeneration,
  formatSignedValue,
  formatValue,
  valueMovementView,
} from "@/lib/value-movement";
import styles from "./value-explain.module.css";

export function valueMovementUrl(playerKey) {
  return `/api/players/${encodeURIComponent(String(playerKey))}/value-movement`;
}

function classifyFailure(status) {
  if (status === 401) return "auth";
  if (status === 404) return "not_found";
  if (status === 503) return "not_ready";
  return "error";
}

const FAILURE_COPY = {
  auth: "Sign in to see why this value moved.",
  not_found: "This asset is not on the loaded board, so there is no movement to explain.",
  not_ready: "The board is not loaded on the server yet — try again shortly.",
  error: "The movement evidence could not be loaded.",
  network: "The movement evidence could not be loaded.",
};

function NotRecorded({ children = "not recorded" }) {
  return <span className={styles.unknown}>{children}</span>;
}

function SourceEnd({ end }) {
  if (end.present) {
    const shown = formatValue(end.value) ?? <NotRecorded />;
    return end.generationMatchNote ? (
      <span title={end.generationMatchNote}>
        {shown}
        <span className={styles.qualifier}> (by date)</span>
      </span>
    ) : (
      shown
    );
  }
  const seen = formatGeneration(end.lastObservedDate, end.lastObservedAt);
  return <span className={styles.unknown}>absent{seen ? ` (last seen ${seen})` : ""}</span>;
}

const SOURCE_COLUMNS = [
  {
    key: "source",
    header: "Source",
    render: (s) => (
      <span className={styles.wrap}>
        <span className={styles.sourceName}>{s.label}</span>
        {s.roleLabel ? <span className={styles.qualifier}> · {s.roleLabel}</span> : null}
      </span>
    ),
  },
  { key: "status", header: "Status", render: (s) => s.statusLabel },
  {
    key: "previous",
    header: "Before",
    numeric: true,
    render: (s) => <SourceEnd end={s.previous} />,
  },
  {
    key: "current",
    header: "After",
    numeric: true,
    render: (s) => <SourceEnd end={s.current} />,
  },
  {
    key: "delta",
    header: "Change",
    numeric: true,
    headerInfoLabel: "source change",
    headerInfo:
      "The source's own published value at the later board minus the earlier one. Not a share of the value change — the changes do not add up to it.",
    render: (s) =>
      s.delta == null ? (
        <>
          <span aria-hidden="true">—</span>
          <span className="ds-visually-hidden">no change computed — absent at one board</span>
        </>
      ) : (
        formatSignedValue(s.delta)
      ),
  },
];

function changedWord(flag, yes, no) {
  if (flag === true) return yes;
  if (flag === false) return no;
  return <NotRecorded />;
}

/** Pure view over one payload — rendered by the fetching wrapper and by tests. */
export function ValueMovementDetailView({ payload, customMix = false }) {
  const v = valueMovementView(payload);
  const header = (
    <>
      {customMix ? (
        <Banner tone="info" title="Compares the default board">
          <p className={styles.muted}>
            Your custom source mix re-weights the value shown above; the history ledger records
            the default board, so this compares default-board values.
          </p>
        </Banner>
      ) : null}
      <p className={styles.attribution} data-exact="false">
      <strong>Evidence, not a cause.</strong> What the history ledger recorded at each board.
      The source changes are not additive: they do not sum to the value change and cannot be
      read as shares of it.
      </p>
    </>
  );

  if (!v.ok) {
    return (
      <div className={styles.explain}>
        {header}
        <p className={styles.muted}>
          {v.statusCopy || "Movement evidence is not available."}
          {v.missingReasonLabel ? ` (${v.missingReasonLabel}.)` : ""}
        </p>
        {v.current?.date ? (
          <p className={styles.muted}>Latest recorded board: {v.current.date}.</p>
        ) : null}
      </div>
    );
  }

  const prev = v.previous;
  const cur = v.current;
  return (
    <div className={styles.explain}>
      {header}
      {v.currentIsLiveBoard === false ? (
        <Banner tone="info" title="History is behind the live board">
          <p className={styles.muted}>
            The latest board the ledger recorded is {formatGeneration(cur.date, cur.at)}; the
            board on screen is {formatGeneration(v.liveBoardDate, v.liveBoardAt) || "undated"}.
            The comparison below is between recorded boards.
          </p>
        </Banner>
      ) : null}

      <section aria-labelledby="vm-change">
        <h3 id="vm-change" className={styles.sectionTitle}>
          Between boards
        </h3>
        <dl className={styles.facts}>
          <div className={styles.fact}>
            <dt>Boards compared</dt>
            <dd>
              {formatGeneration(prev.date, prev.at)} → {formatGeneration(cur.date, cur.at)}
              {prev.fidelity === "nearest-prior" && v.comparatorBoardDate
                ? ` (not on the ${v.comparatorBoardDate} board — ${prev.fidelityLabel})`
                : ""}
            </dd>
          </div>
          {v.alignment && !v.alignment.sameBoards ? (
            <div className={styles.fact}>
              <dt>Rank change shown elsewhere</dt>
              <dd>
                compares different boards
                {v.alignment.reasons.length > 0 ? ` — ${v.alignment.reasons.join("; ")}` : ""}
              </dd>
            </div>
          ) : null}
          <div className={styles.fact}>
            <dt>Value</dt>
            <dd>
              {formatValue(prev.value) ?? <NotRecorded />} →{" "}
              {formatValue(cur.value) ?? <NotRecorded />}
              {v.valueChange != null ? (
                <>
                  {" "}
                  <Movement delta={v.valueChange} format={(n) => formatValue(n)} />
                </>
              ) : null}
            </dd>
          </div>
          <div className={styles.fact}>
            <dt>Rank</dt>
            <dd>
              {prev.rank != null ? `#${prev.rank}` : <NotRecorded>unranked</NotRecorded>} →{" "}
              {cur.rank != null ? `#${cur.rank}` : <NotRecorded>unranked</NotRecorded>}
              {v.rankChange != null ? (
                <>
                  {" "}
                  <Movement delta={v.rankChange} />
                </>
              ) : null}
            </dd>
          </div>
          <div className={styles.fact}>
            <dt>Tier</dt>
            <dd>{changedWord(v.tierChanged, "changed", "unchanged")}</dd>
          </div>
          <div className={styles.fact}>
            <dt>Confidence</dt>
            <dd>
              {prev.confidence || <NotRecorded />} → {cur.confidence || <NotRecorded />}
            </dd>
          </div>
          <div className={styles.fact}>
            <dt>Valuation constants</dt>
            <dd>
              {changedWord(
                v.pipelineVersionChanged,
                "changed between these boards",
                "unchanged between these boards",
              )}
              {v.methodologyCovers ? (
                <span className={styles.qualifier}> ({v.methodologyCovers})</span>
              ) : null}
            </dd>
          </div>
        </dl>
      </section>

      <section aria-labelledby="vm-sources">
        <h3 id="vm-sources" className={styles.sectionTitle}>
          Source evidence <span className={styles.qualifier}>(not additive)</span>
        </h3>
        {v.sources.length > 0 ? (
          <DataTable
            caption="Each recorded source's published value at the earlier and later board, and its own change; not additive"
            columns={SOURCE_COLUMNS}
            rows={v.sources}
            rowKey={(s) => s.key}
            density="compact"
          />
        ) : (
          <p className={styles.muted}>
            No recorded source priced this asset at either board.
          </p>
        )}
        {v.notObserved.length > 0 ? (
          <p className={styles.muted}>Not recorded at either board: {v.notObserved.join(", ")}.</p>
        ) : null}
      </section>

      <section aria-labelledby="vm-unobserved">
        <h3 id="vm-unobserved" className={styles.sectionTitle}>
          Not recorded per board
        </h3>
        <p className={styles.muted}>
          The ledger does not store these for past boards, so they are not shown as history —
          and are not re-derived from today&rsquo;s settings.
        </p>
        <dl className={styles.facts}>
          {v.unobserved.map((u) => (
            <div key={u.key} className={styles.fact}>
              <dt>{u.label}</dt>
              <dd>
                <NotRecorded />
              </dd>
            </div>
          ))}
        </dl>
        {v.unrecordedToday.length > 0 ? (
          <p className={styles.muted}>
            On today&rsquo;s board, with no per-board history kept:{" "}
            {v.unrecordedToday.map((u) => `${u.label} (${u.roleLabel})`).join(", ")}.
          </p>
        ) : null}
        {v.currentQuarantined || v.currentFlags.length > 0 ? (
          <p className={styles.muted}>
            Today&rsquo;s board flags this value
            {v.currentQuarantined ? " as quarantined" : ""}
            {v.currentFlags.length > 0 ? ` (${v.currentFlags.join(", ")})` : ""}; earlier flags are
            not recorded.
          </p>
        ) : null}
      </section>
    </div>
  );
}

/** Fetching wrapper: loading, failure with retry, then the view. */
export default function ValueMovementDetail({ playerKey, customMix = false }) {
  const [attempt, setAttempt] = useState(0);
  const [result, setResult] = useState({ key: null, status: "loading" });
  const requestKey = `${playerKey ?? ""}#${attempt}`;

  useEffect(() => {
    if (!playerKey) return undefined;
    const ctl = new AbortController();
    fetch(valueMovementUrl(playerKey), {
      credentials: "same-origin",
      cache: "no-store",
      signal: ctl.signal,
    })
      .then(async (res) => {
        const body = await res.json().catch(() => null);
        if (!res.ok || !body) {
          setResult({ key: requestKey, status: "error", kind: classifyFailure(res.status) });
        } else {
          setResult({ key: requestKey, status: "ok", payload: body });
        }
      })
      .catch((err) => {
        if (err?.name === "AbortError") return;
        setResult({ key: requestKey, status: "error", kind: "network" });
      });
    return () => ctl.abort();
  }, [playerKey, requestKey]);

  if (!playerKey) {
    return <p className={styles.muted}>{FAILURE_COPY.not_found}</p>;
  }
  if (result.key !== requestKey || result.status === "loading") {
    return (
      <div role="status" aria-label="Loading why the value moved">
        <SkeletonText lines={4} />
      </div>
    );
  }
  if (result.status === "error") {
    const retryable = result.kind !== "auth" && result.kind !== "not_found";
    return (
      <div className={styles.failure}>
        <p className={styles.muted}>{FAILURE_COPY[result.kind] || FAILURE_COPY.error}</p>
        {retryable ? (
          <Button size="sm" variant="secondary" onClick={() => setAttempt((n) => n + 1)}>
            Try again
          </Button>
        ) : null}
      </div>
    );
  }
  return <ValueMovementDetailView payload={result.payload} customMix={customMix} />;
}
