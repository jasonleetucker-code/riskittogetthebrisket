"use client";

/**
 * FaabRecommendation — the bid desk for the manual add/drop calculator.
 *
 * Calls ``POST /api/waiver/faab-recommend`` when an add is selected (with
 * an optional drop side) and renders the backend's recommendation
 * verbatim.  **No bid math happens here** — every number on screen is a
 * field the recommender stamped; this component only decides what is
 * prominent and what is disclosed.
 *
 * Reading order, most-actionable first:
 *   1. TWO SEPARATED GROUPS, because they are different quantities and
 *      conflating them is what the engine redesign existed to fix:
 *        • "What the player is worth" — the objective ceiling.  A
 *          function of the player and the league FORMAT.  It does not
 *          move when you spend, and it is the same number for every
 *          team in the league.
 *        • "What you should bid" — the ladder.  A function of the
 *          ceiling, YOUR balance, your roster, the week, and the price
 *          the claim is expected to clear at.  Almost always far below
 *          the ceiling, because bidding the ceiling captures zero
 *          surplus by construction.
 *   2. Warnings ("likely outbid", pacing, marginal upgrade) as Banners.
 *   3. FAAB Bid Predictor — the sealed-auction read: clearing price,
 *      projected top rival, and the per-opponent estimate table.
 *   4. Everything else behind disclosures: the factor breakdown (the
 *      user does not need eleven rows of arithmetic by default) and the
 *      league's historical FAAB context.
 *   5. A freshness footer, because a bid recommendation resting on
 *      day-old rosters should say so.
 *
 * Response shape: ``src/trade/faab_recommender.py::recommend_faab``
 * (which now delegates to ``src/trade/faab_engine.py``) plus the FAAB v2
 * additions stamped by ``server.py::post_waiver_faab_recommend``
 * (``contention``, ``inputsAsOf``, ``staleInputs``).
 *
 * EVERY new block is optional and every legacy key still resolves:
 * ``bids.recommended`` falls back to ``standard``, ``bids.maxRational``
 * to ``max``, and the objective group hides itself entirely when the
 * backend did not stamp one.  An older backend therefore renders the v1
 * panel unchanged rather than a grid of em dashes.
 *
 * **No bid math happens in this file.**  Percentages that arrive
 * pre-computed (``pctOfOriginalBudget``, ``pctOfRemaining``) are
 * rendered, not recomputed; the only arithmetic here is
 * ``winProbability`` 0..1 → a percent label, which is unit formatting.
 */

import { useEffect, useId, useMemo, useState } from "react";
import {
  Badge,
  Banner,
  Button,
  DataTable,
  Panel,
  Skeleton,
  StatTile,
} from "@/components/ds";
import styles from "@/app/waivers/waivers.module.css";
import { useSettings } from "@/components/useSettings";
import { withValuationMode } from "@/lib/valuation-mode";

function fmtBid(n) {
  if (n == null || !Number.isFinite(Number(n))) return "—";
  return `$${Math.round(Number(n)).toLocaleString()}`;
}

/** A percentage the backend already computed (36.0 → "36%"). */
function fmtPct(n, digits = 0) {
  if (n == null || !Number.isFinite(Number(n))) return null;
  return `${Number(n).toFixed(digits)}%`;
}

/** ``winProbability`` arrives as 0..1; this is unit formatting, not math. */
function fmtProbability(p) {
  if (p == null || !Number.isFinite(Number(p))) return null;
  return `${Math.round(Number(p) * 100)}%`;
}

/**
 * Risk posture — how far up the engine's bid curve to sit.
 *
 * Exported so the page's selector, the prop chain, and the request body
 * cannot drift into three different vocabularies.  The values are the
 * engine's own (``config/trade/faab.json`` → ``bidPolicy.riskPosture``);
 * anything else is treated as "balanced" server-side, so the component
 * normalises before sending rather than letting a typo read as a
 * silently ignored choice.
 */
export const RISK_POSTURES = ["conservative", "balanced", "aggressive"];
export const DEFAULT_RISK_POSTURE = "balanced";

const RISK_POSTURE_LABEL = {
  conservative: "Conservative",
  balanced: "Balanced",
  aggressive: "Aggressive",
};

export const RISK_POSTURE_OPTIONS = RISK_POSTURES.map((value) => ({
  value,
  label: RISK_POSTURE_LABEL[value],
}));

const CONFIDENCE_TONE = {
  high: "positive",
  medium: "warning",
  low: "neutral",
};

const CONFIDENCE_LABEL = {
  high: "High confidence",
  medium: "Medium confidence",
  low: "Low confidence",
};

/** Warnings the recommender phrases as hard stops get the negative tone;
 *  everything else (pacing, contention ceiling) is a warning. */
function warningTone(text) {
  const t = String(text || "").toLowerCase();
  if (t.includes("don't bid") || t.includes("worth more")) return "negative";
  return "warning";
}

const NEED_TONE = {
  need: "negative",
  neutral: "neutral",
  surplus: "positive",
};

const NEED_LABEL = {
  need: "Needs the position",
  neutral: "Neutral",
  surplus: "Has surplus",
};

const INPUT_LABELS = {
  rosters: "Rosters",
  leagueAnalytics: "League history",
  trending: "Trending",
  intel: "Intel",
};

function relativeAge(iso) {
  if (!iso) return null;
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return null;
  const mins = Math.max(0, Math.round((Date.now() - then) / 60000));
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

// ── Contention (FAAB v2) ─────────────────────────────────────────

const RIVAL_COLUMNS = [
  {
    key: "teamName",
    header: "Rival",
    accessor: (r) => r.teamName || r.ownerId,
    // Flags are self-describing labels, not tooltip triggers: a tooltip
    // needs a focusable child, and three per row across a full league
    // would add ~30 tab stops to a read-only table.  The prose
    // explanation lives in the notes list below, which the recommender
    // generates for exactly these conditions.
    render: (r) => (
      <span className={styles.rivalName}>
        <span className={styles.playerName}>{r.teamName || r.ownerId}</span>
        <span className={styles.rivalFlags}>
          {r.balanceUnknown ? <Badge tone="outline">no balance</Badge> : null}
          {r.lowSample ? <Badge tone="outline">thin history</Badge> : null}
          {r.intelLevel && r.intelLevel !== "none" ? (
            <Badge tone="accent">intel</Badge>
          ) : null}
        </span>
      </span>
    ),
  },
  {
    key: "expBid",
    header: "Est. bid",
    numeric: true,
    sortable: true,
    accessor: (r) => r.expBid,
    render: (r) => fmtBid(r.expBid),
    headerInfo: "Estimated bid: their value read × aggression × need × intel, capped by their remaining FAAB.",
  },
  {
    key: "faabRemaining",
    header: "Their FAAB",
    numeric: true,
    sortable: true,
    accessor: (r) => r.faabRemaining,
    render: (r) => (r.faabRemaining == null ? "—" : fmtBid(r.faabRemaining)),
  },
  {
    key: "needLevel",
    header: "Positional need",
    hideBelow: "md",
    accessor: (r) => r.needLevel,
    render: (r) => (
      <Badge tone={NEED_TONE[r.needLevel] || "neutral"}>
        {NEED_LABEL[r.needLevel] || r.needLevel}
      </Badge>
    ),
  },
  {
    key: "aggression",
    header: "Aggression",
    numeric: true,
    sortable: true,
    hideBelow: "lg",
    accessor: (r) => r.aggression,
    render: (r) => `${Number(r.aggression ?? 1).toFixed(2)}×`,
    headerInfo: "Historical waiver-bid tendency from resolved attempts when available; older history falls back to winning bids. Clamped to 0.5–2.0×.",
  },
];

function ContentionSection({ contention }) {
  const rivals = Array.isArray(contention?.perOpponent) ? contention.perOpponent : [];
  const notes = Array.isArray(contention?.notes) ? contention.notes : [];

  if (contention?.skipped) {
    return (
      <div className={styles.contention}>
        <Banner tone="info" title="Rival contention not modeled">
          {notes[0] ||
            "Contention needs your team selected and visible rival FAAB balances."}
        </Banner>
      </div>
    );
  }

  return (
    <div className={styles.contention}>
      <div className={styles.clearingRow}>
        <StatTile
          label="Clearing price"
          value={fmtBid(contention?.clearing)}
          meta="what should win it"
          size="lg"
        />
        <StatTile
          label="Projected top rival"
          value={fmtBid(contention?.topRival)}
          meta={rivals.length ? `of ${rivals.length} rivals` : "no rivals modeled"}
        />
        <StatTile
          label="FAAB bid predictor"
          value="Estimate"
          meta="resolved history + roster context"
        />
      </div>

      {rivals.length > 0 ? (
        <DataTable
          caption="Estimated rival bids for this player, highest first"
          columns={RIVAL_COLUMNS}
          rows={rivals}
          rowKey={(r) => r.ownerId}
          density="compact"
          defaultSort={{ key: "expBid", direction: "desc" }}
          rowClassName={(r) => (r.balanceUnknown ? styles.rosteredRow : "")}
        />
      ) : null}

      {notes.length > 0 ? (
        <ul className={styles.notes}>
          {notes.map((n, i) => (
            <li key={`note-${i}`} className={styles.note}>
              {n}
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

// ── Disclosures ──────────────────────────────────────────────────

function FactorDisclosure({ factors }) {
  const [open, setOpen] = useState(false);
  if (!factors.length) return null;
  const missingCount = factors.filter((f) => f.missing).length;
  return (
    <div className={styles.disclosure}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((s) => !s)}
        aria-expanded={open}
      >
        {open ? "Hide" : "Show"} the {factors.length} factors behind this bid
        {missingCount > 0 ? ` (${missingCount} missing)` : ""}
      </Button>
      {open ? (
        <ul className={styles.disclosureList}>
          {factors.map((f, i) => (
            <li key={`f-${i}`} className={styles.factorRow}>
              <span
                className={f.missing ? styles.factorLabelMissing : styles.factorLabel}
              >
                {f.label}
              </span>
              <span className={styles.factorValue}>{f.contribution}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function LeagueFaabContext({ analytics, addPlayer, selectedTeam, recommendation }) {
  const [open, setOpen] = useState(true);
  const budget = analytics?.leagueBudget;
  const remaining = selectedTeam?.faabRemaining;
  const avg = analytics?.leagueAvgWinningBid;
  const median = analytics?.leagueMedianWinningBid;
  const totalBids = analytics?.totalBidsAnalyzed || 0;

  // Position bucket, with the IDP roll-ups the analytics block uses.
  const position = recommendation?.resolvedAddPosition || addPlayer?.pos;
  const posStats = useMemo(() => {
    if (!position || !analytics?.positionBids) return null;
    const p = String(position).toUpperCase();
    const bids = analytics.positionBids;
    if (bids[p]) return bids[p];
    if (["DT", "DE", "EDGE", "NT"].includes(p)) return bids.DL || null;
    if (["ILB", "OLB", "MLB"].includes(p)) return bids.LB || null;
    if (["CB", "S", "FS", "SS"].includes(p)) return bids.DB || null;
    return null;
  }, [analytics, position]);

  const playerHistory = useMemo(() => {
    const pid = addPlayer?.raw?.playerId || addPlayer?.playerId;
    if (!pid || !analytics?.playerHistory) return [];
    const entries = analytics.playerHistory[String(pid)] || [];
    return Array.isArray(entries) ? entries.slice(0, 5) : [];
  }, [analytics, addPlayer]);

  const pct = (b) =>
    budget > 0 && Number.isFinite(b) ? `${Math.round((b / budget) * 100)}% of budget` : null;

  return (
    <div className={styles.disclosure}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setOpen((s) => !s)}
        aria-expanded={open}
      >
        {open ? "Hide" : "Show"} league FAAB history
      </Button>
      {open ? (
        <div className={styles.contextGrid} style={{ marginTop: "var(--space-2)" }}>
          <StatTile
            label="Your remaining FAAB"
            value={remaining != null ? fmtBid(remaining) : fmtBid(budget)}
            meta={
              budget > 0 && remaining != null
                ? `${Math.round((remaining / budget) * 100)}% of ${fmtBid(budget)}`
                : remaining == null
                  ? "league budget"
                  : null
            }
          />
          <StatTile
            label="League average bid"
            value={avg ? fmtBid(avg) : "—"}
            meta={pct(avg)}
          />
          <StatTile
            label="League median bid"
            value={median ? fmtBid(median) : "—"}
            meta={totalBids > 0 ? `${totalBids} bids analyzed` : "no history yet"}
          />
          {posStats && posStats.count > 0 ? (
            <div className={styles.contextBlock}>
              <span className={styles.contextLabel}>
                Comparable {String(position).toUpperCase()} bids ({posStats.count})
              </span>
              <span className={styles.contextValue}>
                {fmtBid(posStats.min)}–{fmtBid(posStats.max)}, average{" "}
                {fmtBid(posStats.avg)}
                {pct(posStats.avg) ? ` (${pct(posStats.avg)})` : ""}
              </span>
            </div>
          ) : null}
          {playerHistory.length > 0 ? (
            <div className={styles.contextBlock}>
              <span className={styles.contextLabel}>
                {addPlayer?.name || "This player"} — past league waivers
              </span>
              <ul className={styles.historyList}>
                {playerHistory.map((h, i) => (
                  <li key={`ph-${i}`} className={styles.historyRow}>
                    <span className={styles.playerMeta}>
                      {h?.season || "—"}
                      {h?.type === "free_agent" ? " · FA pickup" : ""}
                    </span>
                    <span className={styles.historyBid}>{fmtBid(h?.bid || 0)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {!posStats && playerHistory.length === 0 ? (
            <div className={styles.contextBlock}>
              <span className={styles.contextValue}>
                No historical bids for{" "}
                {String(position || "this player").toUpperCase()} yet.
              </span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function FreshnessFooter({ inputsAsOf, staleInputs }) {
  const entries = Object.entries(inputsAsOf || {});
  if (!entries.length) return null;
  const stale = new Set(staleInputs || []);
  return (
    <div className={styles.freshness}>
      {entries.map(([key, iso]) => {
        const age = relativeAge(iso);
        return (
          <span key={key} className={styles.freshnessItem}>
            <span>{INPUT_LABELS[key] || key}:</span>
            <span className={styles.freshnessValue}>
              {age || "unavailable"}
            </span>
            {stale.has(key) ? <Badge tone="warning">stale</Badge> : null}
          </span>
        );
      })}
    </div>
  );
}

// ── The two groups ───────────────────────────────────────────────
//
// Kept as separate sections with their own headings rather than one
// tile strip: the whole point of the engine redesign is that "what he
// is worth" and "what you should pay" are different numbers, and a
// single undifferentiated row of pills is what made the old panel read
// as though the ceiling were a bid.

/** What the player is worth — budget-independent, league-format derived. */
function ObjectiveGroup({ objective, headingId }) {
  if (!objective || typeof objective !== "object") return null;
  const dollars = objective.dollars;
  const budget = objective.originalBudget;
  const pct = fmtPct(objective.pctOfOriginalBudget, 1);
  const surplus = objective.surplusOverReplacement;

  return (
    <section className={styles.bidGroup} aria-labelledby={headingId}>
      <div className={styles.bidGroupHead}>
        <h4 id={headingId} className={styles.bidGroupTitle}>
          What the player is worth
        </h4>
        <p className={styles.bidGroupNote}>
          Budget-independent. A league-format value: the same number for every
          team in the league, and it does not move when you spend.
        </p>
      </div>
      <div className={styles.objectiveRow}>
        <StatTile
          size="lg"
          label="Objective FAAB value"
          value={fmtBid(dollars)}
          meta={
            budget != null
              ? `${pct || "—"} of the original ${fmtBid(budget)} budget`
              : pct
                ? `${pct} of the original budget`
                : null
          }
        />
        <StatTile
          label="Surplus over replacement"
          value={
            surplus == null || !Number.isFinite(Number(surplus))
              ? "—"
              : Math.round(Number(surplus)).toLocaleString()
          }
          meta="board value above a free add"
        />
      </div>
    </section>
  );
}

/** What YOU should bid — the ladder, plus the reads that qualify it. */
function BidGroup({ data, confidence, headingId }) {
  const bids = data?.bids && typeof data.bids === "object" ? data.bids : null;
  // Legacy keys are still stamped by the backend and still correct, so
  // they are the fallback rather than a second source of truth.
  const recommended = bids?.recommended ?? data?.standard;
  const conservative = bids?.conservative ?? data?.conservative;
  const aggressive = bids?.aggressive ?? data?.aggressive;
  const maxRational = bids?.maxRational ?? data?.max;
  const clearing = bids?.clearing;

  const winPct = fmtProbability(data?.winProbability);
  const pctOriginal = fmtPct(data?.pctOfOriginalBudget, 1);
  const pctRemaining = fmtPct(data?.pctOfRemaining, 1);
  const posture = data?.riskPosture;

  // Confidence and posture are BADGES in the group head, not rows in
  // the meta strip: "Aggressive" as a posture and "Aggressive" as a
  // rung on the ladder are different things, and rendering both as
  // plain text in the same group made them indistinguishable.
  const meta = [
    { key: "original", label: "Of original budget", value: pctOriginal },
    {
      key: "remaining",
      label: "Of remaining budget",
      // null (not missing) is the backend saying "your balance is 0 or
      // unknown", which must not render as 0%.
      value: pctRemaining || (data?.pctOfRemaining === null ? "n/a" : null),
    },
  ].filter((m) => m.value);

  return (
    <section className={styles.bidGroup} aria-labelledby={headingId}>
      <div className={styles.bidGroupHead}>
        <h4 id={headingId} className={styles.bidGroupTitle}>
          What you should bid
        </h4>
        <span className={styles.bidGroupBadges}>
          {posture ? (
            <Badge tone="outline">
              {`${RISK_POSTURE_LABEL[posture] || posture} posture`}
            </Badge>
          ) : null}
          <Badge tone={CONFIDENCE_TONE[confidence] || "neutral"}>
            {CONFIDENCE_LABEL[confidence] || confidence}
          </Badge>
        </span>
      </div>
      <p className={styles.bidGroupNote}>
        Your balance, your roster, the week, and the price this claim is
        expected to clear at — normally well below what he is worth.
      </p>

      <div className={styles.bidLadder}>
        <StatTile
          className={styles.bidPrimary}
          size="lg"
          label="Recommended"
          value={fmtBid(recommended)}
          meta={winPct ? `${winPct} chance of winning` : null}
        />
        <StatTile label="Conservative" value={fmtBid(conservative)} />
        <StatTile label="Aggressive" value={fmtBid(aggressive)} />
        <StatTile
          label="Max rational"
          value={fmtBid(maxRational)}
          meta="worth- and balance-capped"
        />
        <StatTile
          label="Est. market-clearing"
          value={fmtBid(clearing)}
          meta="what it should take to win"
        />
      </div>

      {meta.length > 0 ? (
        <dl className={styles.bidMetaRow}>
          {meta.map((m) => (
            <div key={m.key} className={styles.bidMetaItem}>
              <dt className={styles.bidMetaLabel}>{m.label}</dt>
              <dd className={styles.bidMetaValue}>{m.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {data?.explanation ? (
        <p className={styles.explanation}>{data.explanation}</p>
      ) : null}
    </section>
  );
}

// ── Panel ────────────────────────────────────────────────────────

export default function FaabRecommendation({
  addPlayer,
  dropPlayer,
  leagueKey,
  ownerId,
  selectedTeam,
  leagueFaab,
  riskPosture = DEFAULT_RISK_POSTURE,
}) {
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const { settings } = useSettings();
  const valuationMode = settings?.valuationMode || "market";
  const headingBaseId = useId();
  // Never ship an unrecognised posture: the engine falls back to
  // "balanced" on an unknown string, so a typo would silently mean
  // "balanced" while the UI claimed otherwise.
  const posture = RISK_POSTURES.includes(riskPosture)
    ? riskPosture
    : DEFAULT_RISK_POSTURE;

  useEffect(() => {
    if (!addPlayer?.name) {
      setState("idle");
      setData(null);
      return;
    }
    let cancelled = false;
    setState("loading");
    setErr("");
    (async () => {
      try {
        const res = await fetch("/api/waiver/faab-recommend", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          // A bid is derived from a value, and the same player is
          // worth a different number under each board.
          body: JSON.stringify(
            withValuationMode({
              leagueKey,
              addPlayerName: addPlayer.name,
              dropPlayerName: dropPlayer?.name || undefined,
              teamOwnerId: ownerId || undefined,
              // How far up the bid curve to sit.  The engine reads this
              // as ``bidPolicy.riskPosture`` and stamps the posture it
              // actually used back on the response, which is what the
              // bid group renders — so a posture the backend ignored
              // shows up as a visible disagreement rather than silently
              // doing nothing.
              riskPosture: posture,
            }),
          ),
        });
        if (cancelled) return;
        if (!res.ok) {
          const txt = await res.text().catch(() => "");
          setErr(`API ${res.status}: ${txt.slice(0, 120)}`);
          setState("error");
          return;
        }
        const json = await res.json();
        if (cancelled) return;
        setData(json);
        setState("done");
      } catch (exc) {
        if (cancelled) return;
        setErr(String(exc?.message || exc));
        setState("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  // ``valuationMode`` is a dependency because it is a fetch INPUT:
  // ``withValuationMode`` reads it from localStorage, which React
  // cannot observe.  Without it a bid computed on the market board
  // would stay on screen after the user switches to the adjusted one.
  // ``posture`` is a fetch input for the same reason — a stale ladder
  // under a freshly-chosen posture is the toggle looking broken.
  }, [
    addPlayer?.name,
    dropPlayer?.name,
    leagueKey,
    ownerId,
    valuationMode,
    posture,
  ]);

  if (state === "idle") return null;

  if (state === "loading") {
    return (
      <Panel title="Recommended FAAB bid" headingLevel={3}>
        <div className={styles.faabPanel} aria-busy="true">
          {/* Stub the settled height: two group headings + the
              five-tile ladder, not the old four-pill row. */}
          <Skeleton height={20} />
          <div className={styles.objectiveRow}>
            {[0, 1].map((i) => (
              <Skeleton key={`obj-${i}`} height={64} />
            ))}
          </div>
          <Skeleton height={20} />
          <div className={styles.bidLadder}>
            {[0, 1, 2, 3, 4].map((i) => (
              <Skeleton key={`bid-${i}`} height={64} />
            ))}
          </div>
          <Skeleton height={16} />
        </div>
      </Panel>
    );
  }

  if (state === "error") {
    return (
      <Panel title="Recommended FAAB bid" headingLevel={3}>
        <Banner tone="negative" title="FAAB recommender unavailable">
          {err}
        </Banner>
      </Panel>
    );
  }

  const factors = Array.isArray(data?.factors) ? data.factors : [];
  const warnings = Array.isArray(data?.warnings) ? data.warnings : [];
  const confidence = data?.confidence || "low";
  const contention = data?.contention;

  return (
    <Panel className="waivers-bid-desk" title="Recommended FAAB bid" headingLevel={3}>
      <div className={styles.faabPanel}>
        <ObjectiveGroup
          objective={data?.objective}
          headingId={`${headingBaseId}-worth`}
        />

        <BidGroup
          data={data}
          confidence={confidence}
          headingId={`${headingBaseId}-bid`}
        />

        {warnings.map((w, i) => (
          <Banner key={`warn-${i}`} tone={warningTone(w)}>
            {w}
          </Banner>
        ))}

        {contention ? <ContentionSection contention={contention} /> : null}

        <FactorDisclosure factors={factors} />

        {leagueFaab ? (
          <LeagueFaabContext
            analytics={leagueFaab}
            addPlayer={addPlayer}
            selectedTeam={selectedTeam}
            recommendation={data}
          />
        ) : null}

        <FreshnessFooter
          inputsAsOf={data?.inputsAsOf}
          staleInputs={data?.staleInputs}
        />
      </div>
    </Panel>
  );
}
