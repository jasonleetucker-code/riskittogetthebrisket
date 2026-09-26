"use client";

/**
 * TradeWarRoom — the roster-aware Analyze Trade surface on /trade
 * (#792 / #1173 / #843 / #842, Lane 6 — PSI Direction A).
 *
 * Answers, for the selected team, in this order:
 *   1. the recommendation, its confidence, the strongest reasons for and
 *      against, and the most important uncertainty;
 *   2. three DIFFERENT questions, never one gauge:
 *        MARKET       what does the market charge?        (canonical + KTC VA)
 *        ROSTER       what does my actual team gain/lose? (#1173 best-ball)
 *        FEASIBILITY  can it legally fit, what must go?   (#843 capacity)
 *   3. Roster Construction Impact — lineup-entry changes, promoted/displaced
 *      players, redundancy, depth, forced cuts, roster slots;
 *   4. details, collapsed: KTC VA, projection basis, assumptions, what is not
 *      included and why.
 *
 * DISPLAY ONLY: every number is `POST /api/trade/analyze`'s, formatted by
 * `lib/trade-war-room.js`.  Missing renders as words, never 0.
 *
 * REQUEST SAFETY (same pattern as Game Day): one request per question, keyed
 * by (league, team, mode, trade); a newer question aborts the older one and a
 * late answer for an old key can never publish.  While a new answer computes,
 * the previous one stays visible, dimmed and marked as updating — but ONLY
 * when just the assets changed.  A different league, team or mode blanks it:
 * a Team-context verdict must never sit under an Asset-only toggle.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { Badge, Banner, CollapsiblePanel, SegmentedControl, SkeletonText } from "@/components/ds";
import {
  DIRECTION_WORDS,
  FEASIBILITY_WORDS,
  RECOMMENDATION_LABELS,
  RECOMMENDATION_TONES,
  ROLE_WORDS,
  analyzeRequestKey,
  formatPctPoint,
  formatPpg,
  formatSignedPpg,
  formatSignedValue,
  formatValue,
  rosterImpactRows,
  unavailableText,
  validAnalyzePayload,
} from "@/lib/trade-war-room";
import styles from "./war-room.module.css";

const DEBOUNCE_MS = 700;

const CONTEXT_OPTIONS = [
  { value: "team", label: "Team context" },
  { value: "asset", label: "Asset only" },
];

function directionTone(direction) {
  if (direction === "favors") return "positive";
  if (direction === "opposes") return "negative";
  return "neutral";
}

function LensState({ lens }) {
  if (!lens) return <span className={styles.lensMuted}>Unavailable</span>;
  if (!lens.available) {
    return <span className={styles.lensMuted}>{unavailableText(lens.unavailableReason)}</span>;
  }
  return (
    <Badge tone={directionTone(lens.direction)} className={styles.lensBadge}>
      {DIRECTION_WORDS[lens.direction] || "Neutral"}
    </Badge>
  );
}

function MarketAnswer({ lens }) {
  const d = lens?.detail || {};
  const gap = formatSignedValue(d.vaAdjustedGap);
  return (
    <div className={styles.answer} data-lens="market">
      <p className={styles.answerQuestion}>
        <span className={styles.answerLabel}>Market</span> What does the market charge?
      </p>
      <p className={styles.answerHeadline}>
        {gap ? (
          <>
            <span className={styles.bigNum}>{gap}</span>{" "}
            <span className={styles.unit}>after KTC Value Adjustment</span>
          </>
        ) : (
          <span className={styles.lensMuted}>{unavailableText(lens?.unavailableReason)}</span>
        )}
      </p>
      {gap ? (
        <p className={styles.answerNote}>
          You get {formatValue(d.receivingValue) ?? "—"} · you give {formatValue(d.sendingValue) ?? "—"}{" "}
          (raw {formatSignedValue(d.rawGap) ?? "—"})
        </p>
      ) : null}
      <LensState lens={lens} />
    </div>
  );
}

function RosterAnswer({ lens }) {
  const d = lens?.detail || {};
  const ppg = formatSignedPpg(d.ppg);
  const partial = lens?.unavailableReason === "partial_projection_coverage";
  return (
    <div className={styles.answer} data-lens="roster">
      <p className={styles.answerQuestion}>
        <span className={styles.answerLabel}>Roster</span> What does my team gain or lose?
      </p>
      <p className={styles.answerHeadline}>
        {ppg && (lens?.available || partial) ? (
          <>
            <span className={styles.bigNum}>{ppg}</span>{" "}
            <span className={styles.unit}>best-ball pts / week{partial ? " (partial)" : ""}</span>
          </>
        ) : (
          <span className={styles.lensMuted}>{unavailableText(lens?.unavailableReason)}</span>
        )}
      </p>
      {ppg && d.ppgBeforeCleanup != null ? (
        <p className={styles.answerNote}>
          {formatSignedPpg(d.ppgBeforeCleanup)} before the required cut · {ppg} once the roster is legal
        </p>
      ) : ppg && d.standardError != null ? (
        <p className={styles.answerNote}>Expected legal-lineup scoring, ± {formatPpg(d.standardError)} simulation error</p>
      ) : null}
      <LensState lens={lens} />
    </div>
  );
}

function FeasibilityAnswer({ lens }) {
  const d = lens?.detail || {};
  const state = d.state;
  return (
    <div className={styles.answer} data-lens="feasibility">
      <p className={styles.answerQuestion}>
        <span className={styles.answerLabel}>Feasibility</span> Can it legally fit?
      </p>
      <p className={styles.answerHeadline}>
        {state && FEASIBILITY_WORDS[state] ? (
          <span className={styles.feasHeadline}>{FEASIBILITY_WORDS[state]}</span>
        ) : (
          <span className={styles.lensMuted}>{unavailableText(lens?.unavailableReason)}</span>
        )}
      </p>
      {d.rosterLimit != null ? (
        <p className={styles.answerNote}>
          Roster {d.sizeBefore ?? "—"} → {d.sizeAfter ?? "—"} of {d.rosterLimit}
          {d.forcedDrops?.length
            ? ` · likely cut: ${d.forcedDrops.map((x) => x.name).join(", ")}${d.candidatesTied ? " (close call)" : ""}`
            : ""}
          {" · picks don't use roster spots"}
        </p>
      ) : null}
      <LensState lens={lens} />
    </div>
  );
}

function ReasonList({ title, items, tone }) {
  if (!items?.length) return null;
  return (
    <div className={styles.reasons} data-tone={tone}>
      <h4 className={styles.reasonsTitle}>{title}</h4>
      <ul className={styles.reasonsList}>
        {items.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    </div>
  );
}

function RosterImpact({ lens }) {
  const d = lens?.detail;
  if (!d || d.ppg == null) return null;
  const rows = rosterImpactRows(d);
  const before = d.before || {};
  const after = d.after || {};
  const depth = d.depth || {};
  return (
    <section className={styles.impact} aria-labelledby="war-room-impact">
      <h3 id="war-room-impact" className={styles.sectionTitle}>
        Roster construction impact
      </h3>
      {lens?.unavailableReason === "partial_projection_coverage" ? (
        <p className={styles.note}>
          Partial: a traded player has no league-scored projection, so these numbers cover the projected players only
          and do not count toward the recommendation.
        </p>
      ) : null}
      <dl className={styles.facts}>
        <div>
          <dt>Expected lineup</dt>
          <dd>
            {formatPpg(before.expectedLineupPpg) ?? "—"} → {formatPpg(after.expectedLineupPpg) ?? "—"} pts/wk
          </dd>
        </div>
        <div>
          <dt>Redundant production</dt>
          <dd>
            {formatPpg(before.redundantPpg) ?? "—"} → {formatPpg(after.redundantPpg) ?? "—"} pts/wk
          </dd>
        </div>
        <div>
          <dt>If a starter misses a week</dt>
          <dd>
            {depth.meanLossDeltaPpg == null
              ? "—"
              : depth.meanLossDeltaPpg === 0
                ? "No change vs today"
                : `${formatPpg(Math.abs(depth.meanLossDeltaPpg))} pts/wk ${
                    depth.meanLossDeltaPpg > 0 ? "more" : "fewer"
                  } lost than today`}
          </dd>
        </div>
        <div>
          <dt>Shape</dt>
          <dd>
            {d.shape?.label || "—"} ({d.shape?.playersIn ?? 0} in, {d.shape?.playersOut ?? 0} out)
          </dd>
        </div>
      </dl>
      {rows.length ? (
        <div className={styles.tableWrap}>
          <table className={styles.table}>
            <caption className={styles.srOnly}>
              Lineup entry: how often each affected player makes the optimal legal lineup, before and after
            </caption>
            <thead>
              <tr>
                <th scope="col">Player</th>
                <th scope="col">Move</th>
                <th scope="col" className={styles.num}>
                  Proj
                </th>
                <th scope="col" className={styles.num}>
                  Lineup before
                </th>
                <th scope="col" className={styles.num}>
                  Lineup after
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((p) => (
                <tr key={`${p.role}-${p.playerId}`} data-role={p.role}>
                  <th scope="row" className={styles.playerCell}>
                    <span className={styles.playerName}>{p.name}</span>
                    {p.position ? <span className={styles.playerPos}>{p.position}</span> : null}
                  </th>
                  <td>{ROLE_WORDS[p.role] || p.role}</td>
                  <td className={styles.num}>{formatPpg(p.projectedPpg) ?? "No projection"}</td>
                  <td className={styles.num}>{formatPctPoint(p.lineupEntryPctBefore) ?? "—"}</td>
                  <td className={styles.num}>{formatPctPoint(p.lineupEntryPctAfter) ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </section>
  );
}

function Details({ analysis, raw }) {
  const market = analysis.lenses?.market?.detail || {};
  const roster = analysis.lenses?.roster?.detail || {};
  const basis = roster.basis || {};
  const ts = roster.teamStrength;
  return (
    <CollapsiblePanel title="How this was decided" defaultCollapsed className={styles.details}>
      <div className={styles.detailsBody}>
        <section>
          <h4 className={styles.detailsTitle}>Market — KTC Value Adjustment</h4>
          <p>
            Adjusted totals: you get {formatValue(market.receivingAdjusted) ?? "—"}, you give{" "}
            {formatValue(market.sendingAdjusted) ?? "—"} ({market.magnitude || "—"} gap). KTC VA is a
            separate market lens; roster fit never changes an asset&apos;s value.
          </p>
        </section>
        {basis.source ? (
          <section>
            <h4 className={styles.detailsTitle}>Roster — projection basis</h4>
            <p>
              {basis.description || basis.source}. Source: {basis.source}; {basis.draws ?? "—"} simulated weeks
              {basis.pointsModel?.source ? `; weekly variance: ${basis.pointsModel.source}` : ""}.
            </p>
            {roster.assumptions?.length ? (
              <ul className={styles.detailsList}>
                {roster.assumptions.map((a) => (
                  <li key={a}>{a}</li>
                ))}
              </ul>
            ) : null}
          </section>
        ) : null}
        {ts ? (
          <section>
            <h4 className={styles.detailsTitle}>Team Strength (context, not a vote)</h4>
            <p>
              {formatValue(ts.before) ?? "—"} → {formatValue(ts.after) ?? "—"} ({formatSignedValue(ts.delta) ?? "—"}).
              It sums the same canonical values the market lens uses, so it explains the roster but is not counted
              again.
            </p>
          </section>
        ) : null}
        <section>
          <h4 className={styles.detailsTitle}>Not included yet</h4>
          <ul className={styles.detailsList}>
            {(analysis.unavailableDimensions || []).map((d) => (
              <li key={d.dimension}>
                <strong>{d.dimension}</strong> — {d.notes}
              </li>
            ))}
          </ul>
        </section>
        {raw?.unresolvedIn?.length || raw?.unresolvedOut?.length ? (
          <section>
            <h4 className={styles.detailsTitle}>Not priced</h4>
            <p>{[...(raw.unresolvedIn || []), ...(raw.unresolvedOut || [])].join(", ")}</p>
          </section>
        ) : null}
      </div>
    </CollapsiblePanel>
  );
}

export default function TradeWarRoom({ request, leagueKey = "", useTeamContext = true, onTeamContextChange }) {
  const [state, setState] = useState({
    status: "idle",
    payload: null,
    error: null,
    key: "",
    contextKey: "",
  });
  const controllerRef = useRef(null);
  const key = useMemo(
    () => analyzeRequestKey(request, leagueKey, useTeamContext),
    [request, leagueKey, useTeamContext],
  );
  const contextKey = JSON.stringify([leagueKey, request?.teamName || "", useTeamContext !== false]);
  const ready = Boolean(
    request &&
      (request.playersIn.length || request.picksIn.length) &&
      (request.playersOut.length || request.picksOut.length),
  );

  useEffect(() => {
    if (!ready) {
      controllerRef.current?.abort();
      setState({ status: "idle", payload: null, error: null, key: "", contextKey: "" });
      return undefined;
    }
    setState((prev) =>
      prev.payload && prev.contextKey === contextKey
        ? { ...prev, status: "updating", key }
        : { status: "loading", payload: null, error: null, key, contextKey },
    );
    const timer = setTimeout(async () => {
      controllerRef.current?.abort();
      const controller = new AbortController();
      controllerRef.current = controller;
      try {
        const body = {
          teamName: request.teamName,
          playersIn: request.playersIn,
          playersOut: request.playersOut,
          picksIn: request.picksIn,
          picksOut: request.picksOut,
          useTeamContext: useTeamContext !== false,
        };
        if (leagueKey) body.leagueKey = leagueKey;
        const res = await fetch("/api/trade/analyze", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: controller.signal,
        });
        const data = await res.json().catch(() => ({}));
        if (controller.signal.aborted || controllerRef.current !== controller) return;
        if (!res.ok) {
          setState({
            status: "error",
            payload: null,
            error: data?.error || `HTTP ${res.status}`,
            key,
            contextKey,
          });
          return;
        }
        if (!validAnalyzePayload(data, { leagueKey, useTeamContext })) {
          setState({ status: "error", payload: null, error: "invalid_analysis", key, contextKey });
          return;
        }
        setState({ status: "ok", payload: data, error: null, key, contextKey });
      } catch (err) {
        if (controller.signal.aborted || controllerRef.current !== controller) return;
        setState({
          status: "error",
          payload: null,
          error: String(err?.message || err),
          key,
          contextKey,
        });
      }
    }, DEBOUNCE_MS);
    return () => clearTimeout(timer);
    // `request` identity is folded into `key`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, ready]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  const toggle = (
    <SegmentedControl
      label="Analysis mode"
      options={CONTEXT_OPTIONS}
      value={useTeamContext !== false ? "team" : "asset"}
      onChange={(v) => onTeamContextChange?.(v === "team")}
      className={styles.mode}
    />
  );

  if (!ready) {
    return (
      <section className={styles.room} aria-labelledby="war-room-title" data-war-room="idle">
        <header className={styles.head}>
          <h2 id="war-room-title" className={styles.title}>
            Trade War Room
          </h2>
          {toggle}
        </header>
        <p className={styles.note}>
          {request
            ? "Add assets to both sides to see what this trade does to your roster."
            : "Pick your team to see what this trade does to your roster."}
        </p>
      </section>
    );
  }

  const payload = state.payload;
  const analysis = payload?.analysis;
  const stale = state.status === "updating";

  return (
    <section
      className={styles.room}
      aria-labelledby="war-room-title"
      aria-busy={state.status === "loading" || stale || undefined}
      data-war-room={state.status}
    >
      <header className={styles.head}>
        <h2 id="war-room-title" className={styles.title}>
          Trade War Room
        </h2>
        {toggle}
      </header>
      {useTeamContext === false ? (
        <p className={styles.modeNote}>
          Asset-Only: roster fit, lineup impact and roster capacity are not included in this analysis.
        </p>
      ) : null}
      <p role="status" className={styles.status}>
        {state.status === "loading" ? "Analyzing this trade…" : stale ? "Updating for your latest change…" : ""}
      </p>

      {state.status === "error" ? (
        <Banner tone="warning">
          Analysis unavailable right now ({state.error}). The trade values above are unaffected.
        </Banner>
      ) : null}

      {!analysis && state.status === "loading" ? <SkeletonText lines={4} /> : null}

      {analysis ? (
        <div className={`${styles.body} ${stale ? styles.stale : ""}`.trim()}>
          <div className={styles.verdict} data-recommendation={analysis.recommendation}>
            <p className={styles.verdictEyebrow}>For {payload.team?.name || request.teamName}</p>
            <p className={styles.verdictLine}>
              <Badge tone={RECOMMENDATION_TONES[analysis.recommendation]} className={styles.verdictBadge}>
                {RECOMMENDATION_LABELS[analysis.recommendation]}
              </Badge>
              <span className={styles.confidence}>
                {String(analysis.confidence || "").toLowerCase()} confidence
              </span>
            </p>
            {analysis.topUncertainty ? (
              <p className={styles.topUncertainty}>
                <span className={styles.answerLabel}>Biggest uncertainty</span> {analysis.topUncertainty}
              </p>
            ) : null}
          </div>

          <div className={styles.answers}>
            <MarketAnswer lens={analysis.lenses?.market} />
            <RosterAnswer lens={analysis.lenses?.roster} />
            <FeasibilityAnswer lens={analysis.lenses?.feasibility} />
          </div>

          <div className={styles.reasonGrid}>
            <ReasonList title="Why" items={analysis.reasonsFor} tone="positive" />
            <ReasonList title="Against" items={analysis.reasonsAgainst} tone="negative" />
            <ReasonList title="Uncertain" items={analysis.uncertainty} tone="neutral" />
          </div>

          <RosterImpact lens={analysis.lenses?.roster} />
          <Details analysis={analysis} raw={payload} />
        </div>
      ) : null}
    </section>
  );
}
