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

import { useDeferredValue, useMemo, useState } from "react";

import {
  Badge,
  Banner,
  Button,
  CollapsiblePanel,
  DataTable,
  InfoTip,
  SegmentedControl,
  Select,
  StatTile,
} from "@/components/ds";
import { useRosterContext } from "@/components/useRosterContext";
import {
  applyDraftProgress,
  contestedPrice,
  draftPhase,
  evaluateBid,
  releaseCost,
  optimizeDraft,
  planPositionBalance,
  priceBand,
  priceSigmaByTier,
  realizedResults,
  STRATEGIES,
} from "@/lib/perfect-draft";

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
  // `myTeamIdx` lives under `settings` — every other reader in the app uses
  // `workspace.settings.myTeamIdx` (draft-logic.js, page.jsx). Reading it off
  // the root returned undefined, so `myTeamName` was always "", the roster
  // context was requested with no team, the server answered `context: null`,
  // and the panel silent-vanished BEFORE its own team selector could render —
  // making the feature unreachable in the browser while every unit test
  // passed, because the test fixture used the flat shape.
  const myTeamIdx = workspace?.settings?.myTeamIdx ?? workspace?.myTeamIdx ?? 0;
  const myTeamName = workspace?.teams?.[myTeamIdx]?.name || "";
  const [teamName, setTeamName] = useState(myTeamName);
  const [strategy, setStrategy] = useState("balanced");
  const [priceBasis, setPriceBasis] = useState("fair");
  // Live bidding: which rookie is on the block, and where the bidding is now.
  const [bidTarget, setBidTarget] = useState("");
  const [bidAmount, setBidAmount] = useState("");
  const { teams, context, failure, loading, refetch } = useRosterContext({
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
        // Computed on every board render since it was written and, until now,
        // read by nothing: the richest rival's budget weighted by that rival's
        // demonstrated interest in this player's tier.
        bayesianTopCompetitor: p.bayesianTopCompetitor,
        tier: p.tier,
      }))
      .map((p) => ({ ...p, price: contestedPrice(p, priceBasis) }));
  }, [stats?.enrichedPlayers, priceBasis]);

  const rookiesBought = Number(stats?.myRookiesBought) || 0;

  // Price uncertainty, learned from this draft's own realized sales. Before any
  // pick lands this is entirely the declared prior; each recorded sale shrinks
  // it toward what the room is actually doing. `measured` says which regime
  // we're in so the UI can decline to present an assumption as an observation.
  const priceSigmas = useMemo(
    () =>
      priceSigmaByTier({
        tierPriceRatios: stats?.tierPriceRatios || {},
        allPriceRatios: stats?.allPriceRatios || [],
      }),
    [stats?.tierPriceRatios, stats?.allPriceRatios],
  );
  // Tier keys share an object with the `measured` / `sampleCount` metadata, so
  // resolve through a numeric check rather than key presence — a player whose
  // tier string collided with a metadata key would otherwise pick up `true` as
  // a sigma of 1.0.
  const priceSigmaFor = useMemo(
    () => (p) => {
      const s = Number(priceSigmas[p?.tier]);
      return Number.isFinite(s) ? s : priceSigmas.global;
    },
    [priceSigmas],
  );

  // The roster context describes the roster as it stood BEFORE the draft, and
  // neither its open spots nor its cut ladder move when a rookie sells. Advance
  // both past what has already been bought so the recommendation below is the
  // REMAINING plan — otherwise roster room is double-counted and the ladder
  // re-offers cuts those purchases already consumed.
  //
  // `waiverLadder` is what tells it WHICH rungs those were. Without it the
  // function consumes the backend's ECC head while the solve below charges the
  // release-cheapest, and this is the only production call site — so omitting
  // it leaves the shared-consumption-order fix inert on the live page.
  const progress = useMemo(
    () =>
      applyDraftProgress({
        openRosterSpots: context?.openRosterSpots || 0,
        cutLadder: context?.cutLadder?.rungs || [],
        waiverLadder: context?.waiverLadder || null,
        rookiesBought,
      }),
    [context?.openRosterSpots, context?.cutLadder?.rungs, context?.waiverLadder, rookiesBought],
  );

  const solveInput = useMemo(
    () =>
      context
        ? {
            rookies,
            budget: stats?.myRemaining || 0,
            cutLadder: progress.cutLadder,
            openRosterSpots: progress.openRosterSpots,
            waiverValues: context.waiverValues || {},
            waiverLadder: context.waiverLadder || null,
            strategy,
            priceSigmaFor,
          }
        : null,
    [context, rookies, stats?.myRemaining, progress, strategy, priceSigmaFor],
  );

  // The solve is ~140ms at a full budget, and live Sleeper picks can arrive in
  // bursts. Deferring lets React keep the board interactive and paint the
  // previous plan while the next one computes, instead of blocking on every
  // recorded pick.
  const deferredInput = useDeferredValue(solveInput);
  const recalculating = solveInput !== deferredInput;
  const result = useMemo(
    () => (deferredInput ? optimizeDraft(deferredInput) : null),
    [deferredInput],
  );

  // "The bidding is at $X — do I go?" Both branches come free from the same
  // solve computeMaxBid already performs; nothing new is modelled here.
  //
  // Memoized, and it has to be: evaluateBid runs two knapsacks plus a scan
  // over every dollar of the budget — the same ~300 ms shape as the main
  // solve. Recomputing it on every render would re-solve on every keystroke
  // in the bid box. Declared here, above the early returns, because a hook
  // after a conditional return is a hook-order violation.
  // Deferred for the same reason the main solve is: evaluateBid runs a
  // knapsack plus a scan over every dollar of the budget, and the bid box is
  // a text input. Memoizing alone was not enough — `bidAmount` is a dependency,
  // so each keystroke still invalidated it and re-solved synchronously.
  const deferredBidAmount = useDeferredValue(bidAmount);
  const liveBid = useMemo(
    () =>
      deferredInput && bidTarget && deferredBidAmount !== ""
        ? evaluateBid(deferredInput, bidTarget, deferredBidAmount)
        : null,
    [deferredInput, bidTarget, deferredBidAmount],
  );

  const phase = draftPhase(stats);
  const realized = useMemo(
    () =>
      context
        ? realizedResults({
            stats,
            waiverValues: context.waiverValues || {},
            waiverLadder: context.waiverLadder || null,
            cutLadder: context.cutLadder?.rungs || [],
            openRosterSpots: context.openRosterSpots || 0,
            strategy,
          })
        : null,
    [context, stats, strategy],
  );

  // Silent vanish — never a generic error on an add-on panel.
  if (failure || (!loading && !context)) return null;
  if (!result) return null;

  const { plan, alternatives, confidence, nearTies, meta } = result;
  const cutRungs = deferredInput?.cutLadder ?? progress.cutLadder;
  const openSpots = deferredInput?.openRosterSpots ?? progress.openRosterSpots;

  // A live bid ends when the player is sold, and selling him removes him from
  // `rookies` (filtered on !drafted). Left alone, `bidTarget` kept his id and
  // the panel printed a blank name beside "max $0 / Let him go" — advice about
  // an auction that had already closed.
  const bidTargetRookie = rookies.find((r) => r.id === bidTarget) || null;
  const bidTargetName = bidTargetRookie?.name || "";
  const bidTargetSold = Boolean(bidTarget) && !bidTargetRookie;

  // The cuts the plan was CHARGED for, in the order it was charged for them.
  //
  // Under the ladder model the charge is the cheapest releases by
  // `releaseCost`, which is not the backend's ECC ordering — so showing the
  // ladder's own order beside a cost taken from a different ordering would
  // name a player the plan never released. Legal because the backend's rungs
  // are jointly droppable, so any subset of them is a legal cut-set.
  // Read from the DEFERRED input, not live context: `plan` comes from the
  // deferred solve, so pairing its rookies against live open-spot counts would
  // mislabel the cut column for the whole duration of every recalculation.
  const usingLadder =
    Array.isArray(deferredInput?.waiverLadder) && deferredInput.waiverLadder.length > 0;
  const chargedCuts = usingLadder
    ? [...cutRungs].sort((a, b) => releaseCost(a) - releaseCost(b))
    : cutRungs;

  // Pair each recommended rookie with the specific roster player it
  // displaces. The i-th rookie past the open spots takes the i-th rung, so
  // no cut is ever counted twice.
  const rows = plan.players.map((p, i) => {
    const cutIdx = i - openSpots;
    const cut = cutIdx >= 0 ? chargedCuts[cutIdx] : null;
    const cutCost = cut ? (usingLadder ? releaseCost(cut) : Number(cut.effectiveCutCost) || 0) : 0;
    // `replacementForgone` is this rookie's rung of the waiver ladder — the
    // free agent his roster spot gives up. Present only under the ladder
    // model; without it the subtraction is already inside `surplus`.
    const forgone = Number(p.replacementForgone) || 0;
    const net = (Number(p.surplus) || 0) - forgone - cutCost;
    const band = priceBand(p.price, priceSigmaFor(p));
    return {
      ...p,
      cut,
      cutCost,
      forgone,
      net,
      band,
      perDollar: p.price > 0 ? net / p.price : null,
      standing: bidStanding(p.price, p.planMaxBid),
    };
  });

  // Positional consequence of the plan, reported rather than optimized —
  // see planPositionBalance for why that boundary is deliberate.
  const balance = context
    ? planPositionBalance(plan, {
        rosterByPosition: context.rosterByPosition,
        startersByPosition: context.startersByPosition,
      })
    : null;

  const totals = rows.reduce(
    (acc, r) => ({
      surplus: acc.surplus + (Number(r.surplus) || 0),
      forgone: acc.forgone + r.forgone,
      cut: acc.cut + r.cutCost,
      spend: acc.spend + (Number(r.price) || 0),
    }),
    { surplus: 0, forgone: 0, cut: 0, spend: 0 },
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
        meta={
          meta.budgetHeadroomAtP75 == null
            ? `${fmt$(meta.budgetRemaining)} left over`
            : `${fmt$(meta.budgetRemaining)} left over · ${
                meta.budgetHeadroomAtP75 < 0
                  ? `${fmt$(-meta.budgetHeadroomAtP75)} short`
                  : `${fmt$(meta.budgetHeadroomAtP75)} spare`
              } if bids run high`
        }
      />
      <StatTile label="Rookies" value={String(plan.players.length)} />
      <StatTile
        label="Net roster value"
        value={fmtVal(plan.netValue)}
        meta={
          totals.forgone > 0
            ? `${fmtVal(totals.surplus)} added − ${fmtVal(totals.forgone)} off waivers − ${fmtVal(totals.cut)} released`
            : `${fmtVal(totals.surplus)} added − ${fmtVal(totals.cut)} released`
        }
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

  const phaseLabel =
    phase === "pre"
      ? "Opening plan"
      : phase === "complete"
        ? "Draft complete"
        : "Live — remaining plan";
  const phaseTone = phase === "live" ? "accent" : phase === "complete" ? "neutral" : "outline";

  const subtitle = (() => {
    if (progress.ladderExhausted) {
      return "No roster room left to model — every open spot is used and the cut ladder is spent";
    }
    if (plan.players.length === 0) {
      return phase === "complete"
        ? "Draft complete"
        : "No remaining rookie improves this roster enough to be worth his price";
    }
    const lead = phase === "pre" ? "Best use of" : "Best use of your remaining";
    return `${lead} ${fmt$(meta.budget)}: ${plan.players.length} rookie${
      plan.players.length === 1 ? "" : "s"
    }, ${fmtVal(plan.netValue)} net roster value`;
  })();

  return (
    <CollapsiblePanel
      // Stable E2E hook beside the ds classes, so the copy inside can keep
      // evolving without touching the spec. The panel silent-vanishes on any
      // non-ok response, which is DOM-identical to a regression — a spec needs
      // something specific to assert on.
      className="perfect-draft-panel"
      title="Perfect Draft"
      subtitle={subtitle}
      defaultCollapsed={false}
    >
      <div className={styles.pageActions}>
        <Badge tone={phaseTone}>{phaseLabel}</Badge>
        {/* Automatic-update status. The plan recomputes from live workspace
            state on every recorded pick, price and budget change; this says so
            rather than leaving the user to wonder whether it is stale. */}
        <span className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
          {recalculating
            ? "Recalculating…"
            : `Updates automatically · ${rookiesBought} bought · ${fmt$(
                stats?.mySpent || 0,
              )} spent`}
        </span>
        <Button size="sm" variant="ghost" onClick={refetch}>
          Refresh roster
        </Button>
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
        <SegmentedControl
          label="Prices"
          value={priceBasis}
          onChange={setPriceBasis}
          options={[
            { value: "fair", label: "Fair value" },
            { value: "contested", label: "Beat the room" },
          ]}
        />
      </div>

      {summary}

      {realized && realized.count > 0 ? (
        <p className="muted">
          <strong>Bought so far:</strong> {realized.count} rookie
          {realized.count === 1 ? "" : "s"} for {fmt$(realized.spend)} —{" "}
          {fmtVal(realized.netValue)} net roster value added (
          {fmtVal(realized.grossSurplus)} added −{" "}
          {fmtVal(realized.displacement)} released). The plan below covers what
          is left.
        </p>
      ) : null}

      {progress.ladderExhausted ? (
        <Banner tone="warning" title="No modelled roster room left">
          Your open spots are used and the cut ladder is spent, so there is
          nothing left to price a further addition against. Deeper cuts exist —
          they are just past anything this model will recommend.
        </Banner>
      ) : null}

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

      <div className={styles.pageActions}>
        <Select
          aria-label="Live bid — player on the block"
          value={bidTarget}
          onChange={(e) => setBidTarget(e.target.value)}
        >
          <option value="">Player on the block…</option>
          {rookies.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </Select>
        <label style={{ display: "flex", alignItems: "center", gap: "0.4rem" }}>
          <span className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
            Current bid $
          </span>
          <input
            className="ds-input"
            type="number"
            min="0"
            style={{ width: "5rem" }}
            value={bidAmount}
            onChange={(e) => setBidAmount(e.target.value)}
            aria-label="Current bid"
            disabled={!bidTarget}
          />
        </label>
        {bidTargetSold ? (
          <span className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
            Sold — pick the next player on the block.
          </span>
        ) : liveBid ? (
          <span style={{ fontSize: "var(--font-size-2xs)" }}>
            <Badge
              tone={
                liveBid.verdict === "go"
                  ? "positive"
                  : liveBid.verdict === "limit"
                    ? "warning"
                    : "negative"
              }
            >
              {liveBid.verdict === "go"
                ? "Keep bidding"
                : liveBid.verdict === "limit"
                  ? "At your limit"
                  : "Let him go"}
            </Badge>{" "}
            <span className="muted">
              max {fmt$(liveBid.planMaxBid)} ·{" "}
              {liveBid.gain == null
                ? "no plan at this price"
                : `${liveBid.gain >= 0 ? "+" : ""}${fmtVal(liveBid.gain)} vs walking away`}
            </span>
          </span>
        ) : null}
      </div>

      {!bidTargetSold && liveBid && liveBid.verdict === "stop" && liveBid.pivot?.players?.length ? (
        <p className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
          If you lose {bidTargetName}, the best remaining plan is{" "}
          {liveBid.pivot.players.map((q) => q.name).join(", ")}.
        </p>
      ) : null}

      {balance ? (
        <p className="muted" style={{ fontSize: "var(--font-size-2xs)" }}>
          <strong>Positional shape.</strong>{" "}
          {Object.keys(balance.needs).length === 0 ? (
            <>
              This roster already covers every starting slot, so no rookie is
              needed to fill one — the plan above is chosen purely on value.
            </>
          ) : (
            <>
              Short of starters at{" "}
              {Object.entries(balance.needs)
                .map(([pos, n]) => `${pos} (${n})`)
                .join(", ")}
              .{" "}
              {balance.filled.length > 0
                ? `The plan adds ${balance.filled.join(", ")}. `
                : ""}
              {Object.keys(balance.unmet).length > 0
                ? `It still leaves ${Object.keys(balance.unmet).join(", ")} short.`
                : "That covers every gap."}
            </>
          )}{" "}
          <InfoTip label="Why this is not in the score">
            <p>
              The plan is chosen on value alone, and the positional consequence
              is reported beside it rather than folded in. Turning a positional
              minimum into part of the objective would need the optimizer to
              track how many of each position a plan holds, which is exactly
              the state explosion the one-number-per-plan-size design avoids —
              and it would mean inventing a rate at which a filled starting
              slot is worth giving up board value. That rate is a judgement,
              so it is left to you.
            </p>
          </InfoTip>
        </p>
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
            this plan still comes out best, counting both how much sources
            disagree about each rookie and the chance that bidding pushes the
            plan past your budget.
          </p>
          <p>
            {priceSigmas.measured
              ? `The price range comes from the ${priceSigmas.sampleCount} sales recorded so far in this draft.`
              : "The price range is a starting assumption until sales are recorded — it will tighten or widen to match this room as picks land."}
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
