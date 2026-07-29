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
 *   1. The four bid pills — Recommended is the one accented number.
 *   2. Warnings ("likely outbid", pacing, marginal upgrade) as Banners.
 *   3. Contention — the FAAB v2 sealed-auction read: the clearing price,
 *      the projected top rival, and the per-opponent estimate table.
 *   4. Everything else behind disclosures: the factor breakdown (the
 *      user does not need eleven rows of arithmetic by default) and the
 *      league's historical FAAB context.
 *   5. A freshness footer, because a bid recommendation resting on
 *      day-old rosters should say so.
 *
 * Response shape: ``src/trade/faab_recommender.py::recommend_faab`` plus
 * the FAAB v2 additions stamped by
 * ``server.py::post_waiver_faab_recommend`` (``contention``,
 * ``inputsAsOf``, ``staleInputs``).  Every v2 block is optional — an
 * older backend simply renders the v1 panel.
 */

import { useEffect, useMemo, useState } from "react";
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
    headerInfo: "Their average winning bid ÷ the league median, clamped to 0.5-2.0×.",
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
          label="Rival read"
          value="Estimate"
          meta="winning bids only"
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

// ── Panel ────────────────────────────────────────────────────────

export default function FaabRecommendation({
  addPlayer,
  dropPlayer,
  leagueKey,
  ownerId,
  selectedTeam,
  leagueFaab,
}) {
  const [state, setState] = useState("idle"); // idle | loading | done | error
  const [data, setData] = useState(null);
  const [err, setErr] = useState("");
  const { settings } = useSettings();
  const valuationMode = settings?.valuationMode || "market";

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
  }, [addPlayer?.name, dropPlayer?.name, leagueKey, ownerId, valuationMode]);

  if (state === "idle") return null;

  if (state === "loading") {
    return (
      <Panel title="Recommended FAAB bid" headingLevel={3}>
        <div className={styles.faabPanel} aria-busy="true">
          <div className={styles.bidRow}>
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} height={64} />
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
    <Panel
      className="waivers-bid-desk"
      title="Recommended FAAB bid"
      headingLevel={3}
      actions={
        <Badge tone={CONFIDENCE_TONE[confidence] || "neutral"}>
          {CONFIDENCE_LABEL[confidence] || confidence}
        </Badge>
      }
    >
      <div className={styles.faabPanel}>
        <div className={styles.bidRow}>
          <StatTile label="Conservative" value={fmtBid(data?.conservative)} />
          <StatTile
            className={styles.bidPrimary}
            label="Recommended"
            value={fmtBid(data?.standard)}
            size="lg"
          />
          <StatTile label="Aggressive" value={fmtBid(data?.aggressive)} />
          <StatTile
            label="Max"
            value={fmtBid(data?.max)}
            meta="your remaining"
          />
        </div>

        {data?.explanation ? (
          <p className={styles.explanation}>{data.explanation}</p>
        ) : null}

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
