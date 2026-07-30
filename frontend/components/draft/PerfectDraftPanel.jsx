"use client";

/**
 * Perfect Draft — the recommended combination of rookies for a budget.
 *
 * Presentation only.  Every number here comes from `lib/perfect-draft.js`
 * (the solve) or the backend roster context (values, waiver levels, the cut
 * ladder); this file formats and arranges, it does not compute.
 *
 * Failure posture: this is an add-on surface bolted onto someone else's page,
 * so it VANISHES on any non-ok response rather than rendering an error —
 * matching `BdvmTradePanel`.  The flag being off, the roster snapshot being
 * absent, or the user viewing a league whose rosters are not loaded are all
 * configuration states, not failures worth shouting about mid-draft.
 */

import { useMemo, useState } from "react";

import {
  Badge,
  Banner,
  CollapsiblePanel,
  DataTable,
  InfoTip,
  SegmentedControl,
  Select,
  StatTile,
} from "@/components/ds";
import { useRosterContext } from "@/components/useRosterContext";
import { optimizeDraft, priceBand, STRATEGIES } from "@/lib/perfect-draft";

import styles from "@/app/draft/draft.module.css";

const STRATEGY_LABELS = {
  balanced: "Balanced",
  winNow: "Win now",
  longTerm: "Long-term",
};

const fmt$ = (n) =>
  Number.isFinite(Number(n)) ? `$${Math.round(Number(n))}` : "—";
const fmtVal = (n) =>
  Number.isFinite(Number(n)) ? Math.round(Number(n)).toLocaleString() : "—";

/** How the live price sits against the model's ceiling. */
export function bidStanding(price, planMaxBid) {
  const p = Number(price);
  const m = Number(planMaxBid);
  if (!Number.isFinite(p) || !Number.isFinite(m) || m <= 0) return null;
  if (p > m) return { tone: "negative", label: "Above max" };
  if (p >= m * 0.9) return { tone: "warning", label: "Near max" };
  return { tone: "positive", label: "Below max" };
}

/** Plain-language shape of a plan, for the summary line. */
export function planShape(plan) {
  const players = plan?.players || [];
  if (players.length === 0) return "no rookies";
  if (players.length === 1) return "a single target";
  const spend = players.reduce((s, p) => s + (Number(p.price) || 0), 0);
  const top = Math.max(...players.map((p) => Number(p.price) || 0));
  if (spend > 0 && top / spend >= 0.6) return "star-focused";
  if (players.length >= 4) return "depth-focused";
  return "balanced value";
}

export function PerfectDraftPanel({ stats, workspace }) {
  const myTeamName = workspace?.teams?.[workspace?.myTeamIdx]?.name || "";
  const [teamName, setTeamName] = useState(myTeamName);
  const [strategy, setStrategy] = useState("balanced");
  const { teams, context, failure, loading } = useRosterContext({
    teamName: teamName || myTeamName,
  });

  // Available rookies with their live expected price. `inflatedFair` is the
  // board's own live price model (preDraft x tier-adjusted inflation) — the
  // optimizer reuses it rather than introducing a second price concept.
  const rookies = useMemo(() => {
    const rows = stats?.enrichedPlayers || [];
    return rows
      .filter((p) => !p.drafted)
      .map((p) => ({
        id: p.id,
        name: p.name,
        pos: p.pos || "",
        boardValue: Number(p.boardValue) || null,
        price: Math.max(1, Number(p.inflatedFair) || Number(p.preDraft) || 0),
        marketDispersionCV: p.marketDispersionCV,
        singleSource: p.singleSource,
        tier: p.tier,
      }));
  }, [stats?.enrichedPlayers]);

  const result = useMemo(() => {
    if (!context) return null;
    return optimizeDraft({
      rookies,
      budget: stats?.myRemaining || 0,
      cutLadder: context.cutLadder?.rungs || [],
      openRosterSpots: context.openRosterSpots || 0,
      waiverValues: context.waiverValues || {},
      strategy,
    });
  }, [context, rookies, stats?.myRemaining, strategy]);

  // Silent vanish — never a generic error on an add-on panel.
  if (failure || (!loading && !context)) return null;
  if (!result) return null;

  const { plan, alternatives, confidence, nearTies, meta } = result;
  const cutRungs = context.cutLadder?.rungs || [];
  const openSpots = context.openRosterSpots || 0;

  // Pair each recommended rookie with the specific roster player it
  // displaces. The i-th rookie past the open spots takes the i-th rung, so
  // no cut is ever counted twice.
  const rows = plan.players.map((p, i) => {
    const cutIdx = i - openSpots;
    const cut = cutIdx >= 0 ? cutRungs[cutIdx] : null;
    const cutCost = cut ? Number(cut.effectiveCutCost) || 0 : 0;
    const net = (Number(p.surplus) || 0) - cutCost;
    const band = priceBand(p.price, 0.35);
    return {
      ...p,
      cut,
      cutCost,
      net,
      band,
      perDollar: p.price > 0 ? net / p.price : null,
      standing: bidStanding(p.price, p.planMaxBid),
    };
  });

  const totals = rows.reduce(
    (acc, r) => ({
      surplus: acc.surplus + (Number(r.surplus) || 0),
      cut: acc.cut + r.cutCost,
      spend: acc.spend + (Number(r.price) || 0),
    }),
    { surplus: 0, cut: 0, spend: 0 },
  );

  const columns = [
    {
      key: "name",
      header: "Rookie",
      accessor: (r) => r.name,
      render: (r) => (
        <span>
          <strong>{r.name}</strong>{" "}
          <span className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
            {r.pos}
          </span>
        </span>
      ),
    },
    {
      key: "boardValue",
      header: "Value",
      numeric: true,
      accessor: (r) => r.boardValue,
      render: (r) => fmtVal(r.boardValue),
      hideBelow: "md",
      headerInfo: "Our blended dynasty value for this rookie (0-9999 scale).",
    },
    {
      key: "price",
      header: "Exp. cost",
      numeric: true,
      accessor: (r) => r.price,
      render: (r) => (
        <span title={`Likely range ${fmt$(r.band.low)}–${fmt$(r.band.high)}`}>
          {fmt$(r.price)}
        </span>
      ),
      headerInfo:
        "This rookie's sheet value adjusted by live auction inflation and tier heat — the same price model the board's Fair column uses.",
    },
    {
      key: "planMaxBid",
      header: "Max bid",
      numeric: true,
      accessor: (r) => r.planMaxBid,
      render: (r) => (
        <span>
          {fmt$(r.planMaxBid)}{" "}
          {r.standing ? (
            <Badge tone={r.standing.tone}>{r.standing.label}</Badge>
          ) : null}
        </span>
      ),
      headerInfo:
        "The most you should pay before your best plan WITHOUT this rookie becomes the better draft. It is not his value — it is the point at which the money is better spent elsewhere.",
    },
    {
      key: "cut",
      header: "Likely cut",
      accessor: (r) => r.cut?.name || "",
      render: (r) =>
        r.cut ? (
          <span>
            {r.cut.name}
            {r.cut.valueBasis === "assumedWaiver" ? (
              <>
                {" "}
                <Badge tone="outline">unpriced</Badge>
              </>
            ) : null}
          </span>
        ) : (
          <span className="muted">open spot</span>
        ),
      hideBelow: "sm",
      headerInfo:
        "The rostered player you would release to make room. Each recommended rookie displaces a DIFFERENT player, cheapest first.",
    },
    {
      key: "cutCost",
      header: "Cut cost",
      numeric: true,
      accessor: (r) => r.cutCost,
      render: (r) => (r.cut ? fmtVal(r.cutCost) : "0"),
      hideBelow: "lg",
      headerInfo:
        "What releasing that player really costs: his value above the best replacement available at his position, scaled by how scarce that position is.",
    },
    {
      key: "net",
      header: "Net added",
      numeric: true,
      accessor: (r) => r.net,
      render: (r) => <strong>{fmtVal(r.net)}</strong>,
      headerInfo:
        "Rookie value over replacement, minus the effective cost of the roster player he displaces. This is the number the optimizer maximizes.",
    },
    {
      key: "perDollar",
      header: "Per $",
      numeric: true,
      accessor: (r) => r.perDollar,
      render: (r) => (r.perDollar == null ? "—" : Math.round(r.perDollar)),
      hideBelow: "lg",
    },
  ];

  const confidencePct =
    confidence == null ? null : Math.round(confidence * 100);

  const summary = (
    <div className={styles.statsStrip}>
      <StatTile label="Budget" value={fmt$(meta.budget)} />
      <StatTile
        label="Plan spend"
        value={fmt$(totals.spend)}
        meta={`${fmt$(meta.budgetRemaining)} left over`}
      />
      <StatTile label="Rookies" value={String(plan.players.length)} />
      <StatTile
        label="Net roster value"
        value={fmtVal(plan.netValue)}
        meta={`${fmtVal(totals.surplus)} added − ${fmtVal(totals.cut)} released`}
      />
      <StatTile
        label="Per dollar"
        value={
          totals.spend > 0 ? Math.round(plan.netValue / totals.spend) : "—"
        }
      />
      <StatTile
        label="Confidence"
        value={confidencePct == null ? "—" : `${confidencePct}%`}
        meta={planShape(plan)}
      />
    </div>
  );

  return (
    <CollapsiblePanel
      title="Perfect Draft"
      subtitle={
        plan.players.length === 0
          ? "No rookie currently improves this roster enough to be worth its price"
          : `Best use of ${fmt$(meta.budget)}: ${plan.players.length} rookie${
              plan.players.length === 1 ? "" : "s"
            }, ${fmtVal(plan.netValue)} net roster value`
      }
      defaultCollapsed={false}
    >
      <div className={styles.pageActions}>
        {teams.length > 1 ? (
          <Select
            aria-label="Team to optimize"
            value={teamName || myTeamName}
            onChange={(e) => setTeamName(e.target.value)}
          >
            {teams.map((t) => (
              <option key={t.ownerId || t.name} value={t.name}>
                {t.name}
              </option>
            ))}
          </Select>
        ) : null}
        <SegmentedControl
          label="Strategy"
          value={strategy}
          onChange={setStrategy}
          options={STRATEGIES.map((s) => ({
            value: s,
            label: STRATEGY_LABELS[s] || s,
          }))}
        />
      </div>

      {summary}

      {nearTies.length > 0 ? (
        <Banner tone="warning" title="Close call">
          {nearTies.length === 1
            ? "Another plan wins almost as often once projection and price uncertainty are taken into account — either is defensible."
            : `${nearTies.length} other plans win nearly as often once projection and price uncertainty are taken into account.`}
        </Banner>
      ) : null}

      {plan.players.length === 0 ? (
        <p className="muted">
          Every available rookie either costs more than he adds, or does not
          beat what you could add off waivers at his position. Holding the
          budget is the better play right now.
        </p>
      ) : (
        <>
          {/* No wrapping Panel: this already sits inside a CollapsiblePanel,
              and the design system forbids a second container primitive.
              DataTable brings its own .ds-table-wrap scroller. */}
          <DataTable
            caption="Recommended rookies, the roster player each would displace, and the maximum worth bidding"
            columns={columns}
            rows={rows}
            rowKey={(r) => r.id}
          />

          <div className={styles.signalStack}>
            {rows.map((r) =>
              r.pivot?.players?.length ? (
                <p key={r.id} className="muted">
                  <strong>{r.name}</strong> — pursue to {fmt$(r.planMaxBid)}. If
                  he goes higher, the money is better spent on{" "}
                  {r.pivot.players
                    .map((q) => `${q.name} (${fmt$(q.price)})`)
                    .join(" + ")}
                  .
                </p>
              ) : null,
            )}
          </div>
        </>
      )}

      {alternatives.starFocused || alternatives.depthFocused ? (
        <div className={styles.signalStack}>
          <div className={styles.signalHead}>
            <span className={styles.signalTitle}>Other shapes</span>
          </div>
          {alternatives.starFocused ? (
            <p className="muted">
              <strong>Star-focused</strong> — {alternatives.starFocused.k} rookie
              {alternatives.starFocused.k === 1 ? "" : "s"} for{" "}
              {fmt$(alternatives.starFocused.spend)}, net{" "}
              {fmtVal(alternatives.starFocused.netValue)}.
            </p>
          ) : null}
          {alternatives.depthFocused ? (
            <p className="muted">
              <strong>Depth-focused</strong> — {alternatives.depthFocused.k}{" "}
              rookies for {fmt$(alternatives.depthFocused.spend)}, net{" "}
              {fmtVal(alternatives.depthFocused.netValue)}.
            </p>
          ) : null}
        </div>
      ) : null}

      <p className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
        Perfect Draft compares each available rookie&apos;s value with the value
        of the roster player you would likely have to release, then searches for
        the combination of rookies that produces the greatest total roster
        improvement without exceeding your remaining budget.{" "}
        <InfoTip label="How this is calculated">
          <p>
            A rookie&apos;s gain is measured over the best player available at
            his position — an empty roster spot is worth what you could stream
            into it, not zero. The cost of a cut is measured the same way, so
            both sides are comparable.
          </p>
          <p>
            You have {openSpots} open roster spot{openSpots === 1 ? "" : "s"};
            rookies beyond that displace a rostered player, each a different
            one, cheapest first.
          </p>
          <p>
            Prices are the board&apos;s live inflation-adjusted values and are
            uncertain — confidence is the share of simulated scenarios in which
            this plan still comes out best.
          </p>
          {meta.strategy !== "balanced" ? (
            <p>
              Win-now and long-term apply a small experience-based tilt. It is a
              heuristic, not a measured projection: the underlying board already
              prices age and career length.
            </p>
          ) : null}
        </InfoTip>
      </p>
    </CollapsiblePanel>
  );
}

export default PerfectDraftPanel;
