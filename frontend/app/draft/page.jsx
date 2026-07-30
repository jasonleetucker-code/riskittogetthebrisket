"use client";

// The board's own stylesheet — see draft.css for why it is not in
// globals.css.  Route-scoped, so only /draft pays for it.
import "./draft.css";

import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useRouter } from "next/navigation";
import { useAuthContext } from "@/app/AppShellWrapper";
import { useApp } from "@/components/AppShell";
import { useLeague } from "@/components/useLeague";

import {
  buildTeamIndexLookup,
  useSleeperDraftSync,
} from "@/components/useSleeperDraftSync";
import {
  DRAFT_STORAGE_KEY,
  DEFAULT_AGGRESSION,
  DEFAULT_ENFORCE_PCT,
  DEFAULT_POSITION_MINS,
  TAG_AVOID,
  TAG_TARGET,
  TARGET_BOARD_MAX,
  TIER_DEFS,
  addPlayer,
  addToParSheet,
  addToTargetBoard,
  bestValueOnBoard,
  bidStatus,
  clearParSheet,
  clearTargetBoard,
  computeDraftReview,
  computeDraftStats,
  computeHistorySeries,
  computeRosterBreakdown,
  createDefaultWorkspace,
  cycleTag,
  draftReviewToCsv,
  hydrateWorkspace,
  mergeDraftCapitalTeams,
  moveInParSheet,
  moveTargetInBoard,
  nextBestTargets,
  nominationCandidates,
  playerRecommendation,
  playerSlug,
  recordNomination,
  recordPick,
  removeFromParSheet,
  removeFromTargetBoard,
  removeNomination,
  removePick,
  removePlayer,
  replacePlayerPool,
  rescaleValuesToBudget,
  setPlayerTag,
  undoLastNomination,
  undoLastPick,
  updateParSheetFairValue,
  updatePlayerPreDraft,
  updateSettings,
  updateTeam,
} from "@/lib/draft-logic";
import { classifyPos } from "@/lib/dynasty-data";
import { useBdvmEndpoint } from "@/components/useBdvm";
import {
  buildBdvmIndex,
  buildBdvmPickRows,
  bdvmEntryForRow,
  bdvmSignalEdgeCss,
  formatBdvmGap,
  formatBdvmValue,
} from "@/lib/bdvm";
import {
  Badge,
  Banner,
  Button,
  CollapsiblePanel,
  HelpModal,
  InfoTip,
  Icon,
  Modal,
  PageHeader,
  Panel,
  SkeletonTable,
  StatTile,
  ValueBasisNote,
} from "@/components/ds";
import styles from "./draft.module.css";

// Code-split so the Perfect Draft panel and its optimizer stay OUT of the
// initial /draft chunk — this page is already one of the heaviest routes in the
// app and `check-bundle-sizes.mjs` guards it (main sits 2.2 KB under budget
// before this feature even lands).
//
// React.lazy rather than next/dynamic, and the difference is measured, not
// stylistic: next/dynamic pulled Next's loadable runtime into the shared graph
// and moved ~8 KB out of the common chunk into EVERY page's own chunk, pushing
// /waivers over its budget as collateral. React.lazy uses webpack's plain
// dynamic import and leaves the other routes alone.
//
// No fallback content: the panel renders nothing until its own fetch settles,
// so a placeholder would only add a flash of layout.
const PerfectDraftPanel = lazy(() =>
  import("@/components/draft/PerfectDraftPanel").then((m) => ({
    default: m.PerfectDraftPanel,
  })),
);

const TIER_LABELS = Object.fromEntries(TIER_DEFS.map((t) => [t.key, t.label]));

// Per-row market value: KTC dollar for offense rookies, IDPTradeCalc
// dollar for IDP rookies.  Mirrors the vendor split used by
// nominationCandidates / bestValueOnBoard so the rookie board's
// "Market" column tells the same story as those panels.
function marketDollarFor(player) {
  if (!player) return null;
  const isIdp =
    player.assetClass === "idp" ||
    (player.assetClass !== "offense" && classifyPos(player.pos) === "idp");
  const v = isIdp ? player.idpTradeCalcDollar : player.ktcDollar;
  return Number.isFinite(Number(v)) && Number(v) > 0 ? Number(v) : null;
}

// One constant, rendered by BOTH the auth-resolving skeleton header and
// the settled header, so the two can never drift back into different
// heights.  See the skeleton's comment for what that drift cost.
const DRAFT_PAGE_EYEBROW = "My Team";
const DRAFT_PAGE_TITLE = "Draft Board";
const DRAFT_PAGE_DESCRIPTION =
  "Live inflation-aware auction dashboard — every pick you record moves the per-player bid ceiling immediately.";

// Short labels + CSS classes for the recommendation chip on each row.
// Kept in one place so the color language is consistent between the
// board, the Next Best Target sidebar, and the draft modal.
const REC_CHIP = {
  lock: { text: "LOCK", cls: "draft-rec-lock" },
  steal: { text: "STEAL", cls: "draft-rec-steal" },
  push: { text: "PUSH", cls: "draft-rec-push" },
  buy: { text: "BUY", cls: "draft-rec-buy" },
  spend: { text: "SPEND", cls: "draft-rec-spend" },
  avoid: { text: "AVOID", cls: "draft-rec-avoid" },
  neutral: { text: "—", cls: "draft-rec-neutral" },
};

/* ── Utility formatters ───────────────────────────────────────────── */

function fmt$(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n < 0 ? "−" : "";
  return `${sign}$${Math.round(Math.abs(n)).toLocaleString()}`;
}

function fmtPct(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${(n * 100).toFixed(1)}%`;
}

function fmtMultiplier(n) {
  if (n == null || !Number.isFinite(n)) return "—";
  return `${n.toFixed(2)}×`;
}

/* ── Live Sleeper sync toggle ─────────────────────────────────────── */

function LiveSyncToggle({
  enabled,
  onToggle,
  status,
  error,
  lastSyncAt,
  latestPickNo,
}) {
  // Colored status dot maps directly to the hook's derived status.
  //   connected → green   stale → amber   error → red
  //   complete  → cyan    idle → grey
  const dotColor = !enabled
    ? "#666"
    : status === "connected"
      ? "var(--green, #4ade80)"
      : status === "stale"
        ? "#f59e0b"
        : status === "error"
          ? "#ef4444"
          : status === "complete"
            ? "var(--cyan)"
            : "#888";
  const label = !enabled
    ? "Live sync: OFF"
    : status === "connected"
      ? `Live · pick ${latestPickNo || 0}`
      : status === "stale"
        ? "Live · waiting"
        : status === "error"
          ? "Live · error"
          : status === "complete"
            ? "Live · complete"
            : "Live · idle";
  const title = !enabled
    ? "Auto-import picks from your Sleeper auction draft. OFF — toggle to start polling."
    : error
      ? `Live sync error: ${error}`
      : lastSyncAt
        ? `Last sync ${Math.round((Date.now() - lastSyncAt) / 1000)}s ago`
        : "Live sync ON";
  return (
    <button
      type="button"
      className="button"
      onClick={onToggle}
      title={title}
      style={{
        borderColor: enabled ? "var(--green, #4ade80)" : undefined,
        color: enabled ? "var(--green, #4ade80)" : undefined,
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
      }}
    >
      <span
        aria-hidden="true"
        style={{
          display: "inline-block",
          width: 8,
          height: 8,
          borderRadius: "50%",
          backgroundColor: dotColor,
          boxShadow:
            enabled && status === "connected"
              ? `0 0 4px ${dotColor}`
              : undefined,
        }}
      />
      {label}
    </button>
  );
}

/* ── Inflation stats strip ────────────────────────────────────────── */

function StatsStrip({ stats, historySeries }) {
  const stat = (label, value, title, extra = null) => (
    <StatTile
      key={label}
      label={label}
      value={value}
      meta={extra}
      title={title || undefined}
    />
  );

  // Top rival ceiling — the real competitor cap driving myWinningBid.
  // Surfacing it in the strip teaches the user "this is the number to
  // beat, not some hypothetical".
  return (
    <div className={styles.statsStrip}>
      {stat(
        "Inflation",
        fmtMultiplier(stats.inflation),
        "RemainingLeague$ / (TotalAuction$ − Σ soldPreDraft). >1.00 means the remaining market is cheaper than projected; <1.00 means the remaining market got hot.  Sparkline shows trajectory over picks.",
        <InflationSparkline series={historySeries} width={138} height={28} />,
      )}
      {stat(
        "My remaining",
        fmt$(stats.myRemaining),
        `Starting ${fmt$(stats.myStarting)} − spent ${fmt$(stats.mySpent)} · ${stats.myRookiesBought} rookie${
          stats.myRookiesBought === 1 ? "" : "s"
        } bought`,
      )}
      {stat(
        "Budget advantage",
        fmtMultiplier(stats.budgetAdvantage),
        `My remaining / avg per other team (${fmt$(stats.avgPerOtherTeam)}). Above 1.0 = I can afford to outbid the field average.`,
      )}
      {stat(
        "Top rival ceiling",
        fmt$(stats.topCompetitorMax),
        `The richest OTHER team's remaining dollars. Bid $1 above this to lock a player — anything more is overpay.`,
      )}
      {stat(
        "Board drafted",
        `${stats.totalPicksMade} of ${stats.rookiePoolSize}`,
        `${Math.round(
          (stats.draftProgress || 0) * 100,
        )}% of the rookie pool is gone. There is no cap on how many rookies you may draft — your constraint is dollars, not slots.`,
      )}
      {stat(
        "League $ left",
        fmt$(stats.remainingLeague),
        `Total auction $ still unspent across all teams. Starts at ${fmt$(
          stats.totalBudget,
        )}; drops as picks are recorded.`,
      )}
    </div>
  );
}

/* ── Team budgets panel ───────────────────────────────────────────── */

function TeamPanel({
  stats,
  workspace,
  onSettings,
  onTeam,
  onLoadCapital,
  capitalStatus,
}) {
  const confirmAndLoad = () => {
    const hasPicks = (workspace.picks || []).length > 0;
    if (hasPicks) {
      const ok =
        typeof window !== "undefined" &&
        window.confirm(
          "The draft is already in progress.  Loading fresh budgets from Draft Capital will reset every team's Initial $ to their carry-over balances — your picks stay, but any manual budget edits will be overwritten.  Continue?",
        );
      if (!ok) return;
      onLoadCapital({ force: true });
    } else {
      onLoadCapital({ force: true });
    }
  };

  return (
    <Panel className="draft-team-panel">
      <div className="draft-panel-header">
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            gap: 10,
          }}
        >
          <div>
            <h3 style={{ margin: "0 0 4px" }}>Teams & budgets</h3>
            <div className="muted" style={{ fontSize: "0.72rem" }}>
              Budgets pre-fill from the live Draft Capital feed. Edit any row to
              match your carry-over balances; click{" "}
              <strong>Load from Draft Capital</strong> to re-pull.
            </div>
          </div>
          <button
            className="button"
            onClick={confirmAndLoad}
            disabled={capitalStatus.loading}
            title="Re-pull per-team auction $ from /api/draft-capital"
            // ``nowrap`` is load-bearing, not cosmetic: the label swaps
            // "Loading…" -> "↻ Load from Draft Capital" when the feed
            // lands, and the longer label wrapped onto a second line
            // (35px -> 52px).  That grew the header and pushed the
            // ~440px team list below it down 20px — the single largest
            // layout shift on the site (CLS 0.33 on /draft).
            style={{
              borderColor: "var(--cyan)",
              color: "var(--cyan)",
              whiteSpace: "nowrap",
              // 223px is the measured settled width of the long label.
              // ``nowrap`` alone only fixed the button's HEIGHT — the
              // width still changed between states, which re-wrapped
              // the sibling description text next to it and moved the
              // team list anyway.  Pinning the width makes the whole
              // header row geometry identical in both states.
              minWidth: 224,
            }}
          >
            {capitalStatus.loading ? "Loading…" : "↻ Load from Draft Capital"}
          </button>
        </div>
        {/* Status line slot — height reserved.
            All three blocks below are absent until the Draft Capital
            feed resolves, and then exactly one of them appears.  That
            insertion grew this header ~20px and pushed the ~440px team
            list down by the same amount: the whole of /draft's 0.33
            CLS.  Reserving one line's worth up front makes the arrival
            a repaint instead of a reflow.

            ``flow-root`` is the load-bearing half.  ``minHeight`` alone
            reserved the BOX but not the SPACING: each block below carries
            its own ``marginTop``, and with no padding, border or BFC on
            this slot that margin COLLAPSED THROUGH and pushed the slot
            itself down 4px the moment a status line arrived.  A 4px
            header growth reads as trivial and is not — it moves the
            ~490px team list under it, and an A/B against this exact
            build measured it at 0.24 of /draft's 0.315 CLS.  A BFC keeps
            the child's margin inside the reserved height. */}
        <div style={{ minHeight: 26, display: "flow-root" }}>
          {capitalStatus.info && (
            <div
              className="muted"
              style={{
                fontSize: "0.72rem",
                marginTop: 6,
                color: "var(--green)",
              }}
            >
              {capitalStatus.info}
            </div>
          )}
          {capitalStatus.error && (
            <div
              style={{
                fontSize: "0.72rem",
                marginTop: 6,
                color: "var(--red)",
              }}
            >
              Draft Capital error: {capitalStatus.error}
            </div>
          )}
          {capitalStatus.source?.season && !capitalStatus.error && (
            <div
              className="muted"
              style={{ fontSize: "0.68rem", marginTop: 4 }}
            >
              Source: {capitalStatus.source.season} Draft Capital · $
              {capitalStatus.source.totalBudget} total
            </div>
          )}
        </div>
      </div>
      <div className="draft-team-list">
        <div className="draft-team-row draft-team-row-head">
          <span>Mine</span>
          <span>Team</span>
          <span>Initial</span>
          <span>Spent</span>
          <span>Remaining</span>
          <span title="Rookies bought so far — informational, not a limit">
            Rookies
          </span>
          <span>
            Eff $
            <InfoTip label="Eff $">
              The most this team can bid on a single player: its remaining
              dollars. Nothing is held back for future picks, because nothing
              obliges a team to buy another rookie.
            </InfoTip>
          </span>
          <span>
            Over%
            <InfoTip label="Over%">
              <p>
                Overpay index — how much a team has paid above what the board
                said an asset was worth at the moment it was bought.
              </p>
              <p>
                Above 0 is an overpayer, below 0 a value hunter, around 0
                market-rational.
              </p>
            </InfoTip>
          </span>
        </div>
        {stats.teamStats.map((t) => {
          const effLow = t.effectiveBudget < 5;
          const overpayClass =
            t.overpayIndex == null
              ? "muted"
              : t.overpayIndex > 0.1
                ? "draft-money-overpay"
                : t.overpayIndex < -0.1
                  ? "draft-money-value"
                  : "draft-money";
          const overpayText =
            t.overpayIndex == null
              ? "—"
              : `${t.overpayIndex > 0 ? "+" : ""}${(t.overpayIndex * 100).toFixed(0)}%`;
          return (
            <div
              key={t.idx}
              className={`draft-team-row${t.isMine ? " draft-team-mine" : ""}`}
            >
              <label className="draft-radio">
                <input
                  type="radio"
                  name="myTeam"
                  checked={t.isMine}
                  onChange={() => onSettings({ myTeamIdx: t.idx })}
                />
              </label>
              <input
                className="draft-inline-input"
                value={workspace.teams[t.idx]?.name ?? ""}
                onChange={(e) => onTeam(t.idx, { name: e.target.value })}
                placeholder={`Team ${t.idx + 1}`}
              />
              <input
                className="draft-inline-input draft-money-input"
                type="number"
                min="0"
                value={workspace.teams[t.idx]?.initialBudget ?? 0}
                onChange={(e) =>
                  onTeam(t.idx, {
                    initialBudget: Math.max(0, Number(e.target.value) || 0),
                  })
                }
              />
              <span className="draft-money">{fmt$(t.spent)}</span>
              <span
                className={`draft-money${
                  t.remaining < t.initialBudget * 0.25 ? " draft-money-low" : ""
                }`}
              >
                {fmt$(t.remaining)}
              </span>
              <span
                className="draft-money"
                title={`${t.rookiesBought} rookie${
                  t.rookiesBought === 1 ? "" : "s"
                } bought so far — informational, not a limit`}
              >
                {t.rookiesBought}
              </span>
              <span
                className={`draft-money${effLow ? " draft-money-low" : ""}`}
                title="Effective $: what this team can actually bid on a single player — its remaining dollars, with nothing held back."
              >
                {fmt$(t.effectiveBudget)}
              </span>
              <span
                className={overpayClass}
                style={{
                  fontFamily: "var(--mono, monospace)",
                  textAlign: "right",
                  fontSize: "0.76rem",
                }}
                title={
                  t.overpayIndex == null
                    ? "No picks yet"
                    : `Paid ${fmt$(t.spent)} vs expected ${fmt$(t.preDraftSum)}`
                }
              >
                {overpayText}
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

/* ── Bid-tuning sliders ───────────────────────────────────────────── */

function BidKnobs({ settings, onSettings }) {
  const aggression = Number.isFinite(settings.aggression)
    ? settings.aggression
    : DEFAULT_AGGRESSION;
  const enforcePct = Number.isFinite(settings.enforcePct)
    ? settings.enforcePct
    : DEFAULT_ENFORCE_PCT;
  return (
    <Panel className="draft-knobs">
      <h3>Bid knobs</h3>
      <div className="draft-knob-row">
        <label>
          <span>
            Aggression{" "}
            <span className="muted" style={{ fontSize: "0.7rem" }}>
              — how much of the budget advantage to spend on stars
            </span>
          </span>
          <div className="draft-knob-control">
            <input
              type="range"
              min="0"
              max="0.3"
              step="0.01"
              value={aggression}
              onChange={(e) =>
                onSettings({ aggression: Number(e.target.value) })
              }
            />
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={aggression}
              onChange={(e) =>
                onSettings({ aggression: Number(e.target.value) })
              }
              className="draft-knob-number"
            />
          </div>
        </label>
      </div>
      <div className="draft-knob-row">
        <label>
          <span>
            Enforce % of fair{" "}
            <span className="muted" style={{ fontSize: "0.7rem" }}>
              — bid up to this fraction of fair to keep prices honest
            </span>
          </span>
          <div className="draft-knob-control">
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={enforcePct}
              onChange={(e) =>
                onSettings({ enforcePct: Number(e.target.value) })
              }
            />
            <input
              type="number"
              min="0"
              max="1"
              step="0.05"
              value={enforcePct}
              onChange={(e) =>
                onSettings({ enforcePct: Number(e.target.value) })
              }
              className="draft-knob-number"
            />
          </div>
        </label>
      </div>
    </Panel>
  );
}

/* ── Draft-pick modal ─────────────────────────────────────────────── */

/**
 * One-line before → after preview for the bid simulator.  Color-
 * codes the delta: green when the change improves my position
 * (more $, higher BA), red when it hurts.  For
 * inflation the sign is inverted (lower inflation means my
 * money buys more later, so a negative delta renders green).
 */
function SimRow({ label, before, after, formatter, rawDelta = false }) {
  const delta = (Number(after) || 0) - (Number(before) || 0);
  let direction = 0;
  if (Math.abs(delta) > 0.001) direction = delta > 0 ? 1 : -1;
  const cls = rawDelta
    ? "draft-sim-delta-muted"
    : direction > 0
      ? "draft-sim-delta-up"
      : direction < 0
        ? "draft-sim-delta-down"
        : "";
  const signPrefix = delta > 0 ? "+" : delta < 0 ? "−" : "";
  const magnitude = formatter(Math.abs(delta));
  const deltaText = direction === 0 ? "" : `(${signPrefix}${magnitude})`;
  return (
    <div className="draft-sim-row">
      <span className="muted">{label}</span>
      <span className="draft-money">{formatter(before)}</span>
      <span className="draft-sim-arrow">→</span>
      <span className="draft-money">{formatter(after)}</span>
      <span className={`draft-sim-delta ${cls}`}>{deltaText}</span>
    </div>
  );
}

function DraftModal({ player, workspace, stats, onClose, onSubmit }) {
  const existingPick = player?.pick;
  const [teamIdx, setTeamIdx] = useState(
    existingPick?.teamIdx ?? workspace.settings?.myTeamIdx ?? 0,
  );
  const [amount, setAmount] = useState(existingPick?.amount ?? "");
  const [liveBid, setLiveBid] = useState("");
  const liveStatus = useMemo(
    () => bidStatus(player, liveBid),
    [player, liveBid],
  );

  // Bid simulator: project the workspace forward with this pick
  // applied so the user can see the downstream effect before
  // committing.  Uses the SAME math path as the rest of the app
  // (computeDraftStats(recordPick(...))) so numbers match the live
  // board exactly post-commit.  Skips computation when amount is 0
  // or the pick is just being re-recorded unchanged (existing edit
  // that didn't move the needle).
  const simulated = useMemo(() => {
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0 || !player) return null;
    if (
      existingPick &&
      existingPick.teamIdx === Number(teamIdx) &&
      existingPick.amount === amt
    ) {
      return null;
    }
    const nextWs = recordPick(workspace, {
      playerId: player.id,
      teamIdx: Number(teamIdx),
      amount: amt,
    });
    return computeDraftStats(nextWs);
  }, [workspace, player, teamIdx, amount, existingPick]);

  // The amount field takes initial focus so the user can start typing
  // straight away.  ds Modal handles the trap/restore around it.
  const amountRef = useRef(null);

  if (!player) return null;

  function submit(e) {
    e?.preventDefault();
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0) {
      onClose();
      return;
    }
    onSubmit({ playerId: player.id, teamIdx: Number(teamIdx), amount: amt });
  }

  return (
    <Modal
      open
      onClose={onClose}
      initialFocus={amountRef}
      title={`${existingPick ? "Edit pick" : "Mark drafted"}: ${player.name}`}
    >
      <form onSubmit={submit}>
        <div className="draft-modal-body">
          <div className="draft-modal-refs">
            <div>
              <span className="muted">Tier · PreDraft $</span>
              <span className="draft-money">
                <span
                  className={`draft-tier-chip draft-tier-${player.tier}`}
                  style={{ marginRight: 6 }}
                >
                  {player.tier}
                </span>
                {fmt$(player.preDraft)}
              </span>
            </div>
            <div>
              <span className="muted">Inflated fair</span>
              <span className="draft-money">{fmt$(player.inflatedFair)}</span>
            </div>
            <div>
              <span className="muted">Win at</span>
              <span className="draft-money draft-money-win">
                {fmt$(player.myWinningBid)}
              </span>
            </div>
            <div>
              <span className="muted">My max bid (theoretical)</span>
              <span className="draft-money">{fmt$(player.myMaxBid)}</span>
            </div>
            <div>
              <span className="muted">Enforce up to</span>
              <span className="draft-money">{fmt$(player.enforceUpTo)}</span>
            </div>
            <div>
              <span className="muted">Top rival ceiling</span>
              <span className="draft-money">
                {fmt$(stats.topCompetitorMax)}
              </span>
            </div>
          </div>

          <label className="draft-modal-field">
            <span>Drafted to</span>
            <select
              className="select"
              value={teamIdx}
              onChange={(e) => setTeamIdx(Number(e.target.value))}
            >
              {workspace.teams.map((t, i) => (
                <option key={i} value={i}>
                  {t.name || `Team ${i + 1}`}
                  {i === workspace.settings?.myTeamIdx ? " (mine)" : ""}
                </option>
              ))}
            </select>
          </label>

          <label className="draft-modal-field">
            <span>Final price $</span>
            <input
              ref={amountRef}
              id="draft-modal-amount"
              type="number"
              className="input"
              min="0"
              value={amount}
              onChange={(e) => setAmount(e.target.value)}
              placeholder="e.g. 120"
            />
          </label>

          {(() => {
            // Overpay warning: red banner when the amount is going on
            // MY team AND exceeds myWinningBid.  No warning when
            // recording picks on rival teams (they overpaid, not me).
            const amt = Math.max(0, Number(amount) || 0);
            const isMine = Number(teamIdx) === workspace.settings?.myTeamIdx;
            const myCeiling = Number.isFinite(player.myWinningBid)
              ? player.myWinningBid
              : player.myMaxBid;
            if (amt > 0 && isMine && amt > myCeiling) {
              const diff = amt - myCeiling;
              return (
                <div className="draft-modal-warn">
                  <strong>Overpay.</strong> ${amt} is ${diff} above your winning
                  bid (${myCeiling}). The top rival can only bid $
                  {fmt$(stats.topCompetitorMax)} — you don't need to pay more
                  than ${myCeiling} to lock this player.
                </div>
              );
            }
            return null;
          })()}

          {/* Bid simulator — before/after preview of the key numbers
              this pick would change.  Surfaces "if I commit this, my
              BA drops from 5.85× to 3.24×" BEFORE you click Record,
              so regrets become rare. */}
          {simulated && (
            <div className="draft-modal-sim">
              <div
                className="muted"
                style={{ fontSize: "0.68rem", marginBottom: 4 }}
              >
                If recorded:
              </div>
              <div className="draft-sim-grid">
                <SimRow
                  label="League $ left"
                  before={stats.remainingLeague}
                  after={simulated.remainingLeague}
                  formatter={fmt$}
                />
                <SimRow
                  label="My remaining"
                  before={stats.myRemaining}
                  after={simulated.myRemaining}
                  formatter={fmt$}
                />
                <SimRow
                  label="My BA"
                  before={stats.budgetAdvantage}
                  after={simulated.budgetAdvantage}
                  formatter={(n) => `${n.toFixed(2)}×`}
                  rawDelta
                />
                <SimRow
                  label="Inflation"
                  before={stats.inflation}
                  after={simulated.inflation}
                  formatter={(n) => `${n.toFixed(2)}×`}
                  rawDelta
                />
                <SimRow
                  label="Top rival $"
                  before={stats.topCompetitorMax}
                  after={simulated.topCompetitorMax}
                  formatter={fmt$}
                />
                <SimRow
                  label="Rookies bought"
                  before={stats.myRookiesBought}
                  after={simulated.myRookiesBought}
                  formatter={(n) => `${n}`}
                  rawDelta
                />
              </div>
            </div>
          )}

          <div className="draft-modal-live">
            <div className="muted" style={{ fontSize: "0.72rem" }}>
              Or simulate a live bid to see the recommendation:
            </div>
            <div className="draft-live-row">
              <input
                type="number"
                className="input"
                min="0"
                value={liveBid}
                onChange={(e) => setLiveBid(e.target.value)}
                placeholder="Live bid $"
              />
              <span
                className={`draft-live-badge draft-live-${liveStatus.level}`}
              >
                {liveStatus.label || "—"}
              </span>
            </div>
          </div>

          {/* Nomination logger — record that a rival nominated this
              player (without recording a pick).  Drives the Bayesian
              tier-interest priors.  ``nominatedBy`` shows the current
              logged nominator, if any, with an undo option. */}
          {!player.drafted && (
            <div className="draft-modal-nom">
              <div
                className="muted"
                style={{ fontSize: "0.72rem", marginBottom: 4 }}
              >
                Who nominated this player?
                {(() => {
                  const existing = (workspace.nominations || []).find(
                    (n) => n.playerId === player.id,
                  );
                  if (!existing) return null;
                  const teamName =
                    workspace.teams[existing.nominatingTeamIdx]?.name ||
                    `Team ${existing.nominatingTeamIdx + 1}`;
                  return (
                    <span
                      style={{
                        marginLeft: 6,
                        color: "var(--cyan)",
                        fontSize: "0.7rem",
                      }}
                    >
                      · logged: {teamName}
                    </span>
                  );
                })()}
              </div>
              <div className="draft-live-row">
                <select
                  className="select"
                  defaultValue=""
                  onChange={(e) => {
                    const idx = Number(e.target.value);
                    if (!Number.isInteger(idx)) return;
                    onSubmit({
                      _nominate: true,
                      playerId: player.id,
                      teamIdx: idx,
                    });
                    e.target.value = "";
                  }}
                >
                  <option value="" disabled>
                    Select nominator…
                  </option>
                  {workspace.teams.map((t, i) =>
                    i === workspace.settings?.myTeamIdx ? null : (
                      <option key={i} value={i}>
                        {t.name || `Team ${i + 1}`}
                      </option>
                    ),
                  )}
                </select>
                {(workspace.nominations || []).some(
                  (n) => n.playerId === player.id,
                ) && (
                  <button
                    type="button"
                    className="button"
                    style={{ fontSize: "0.7rem", padding: "2px 8px" }}
                    onClick={() =>
                      onSubmit({
                        _removeNomination: true,
                        playerId: player.id,
                      })
                    }
                    title="Clear the logged nomination"
                  >
                    Clear nom
                  </button>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="draft-modal-footer">
          {existingPick && (
            <button
              type="button"
              className="button button-danger"
              onClick={() => {
                onSubmit({ _remove: true, playerId: player.id });
              }}
            >
              Clear pick
            </button>
          )}
          <button type="button" className="button" onClick={onClose}>
            Cancel
          </button>
          {(() => {
            const amt = Math.max(0, Number(amount) || 0);
            const isMine = Number(teamIdx) === workspace.settings?.myTeamIdx;
            const myCeiling = Number.isFinite(player.myWinningBid)
              ? player.myWinningBid
              : player.myMaxBid;
            const danger = amt > 0 && isMine && amt > myCeiling;
            return (
              <button
                type="submit"
                className="button"
                style={{
                  borderColor: danger ? "var(--red)" : "var(--cyan)",
                  color: danger ? "var(--red)" : "var(--cyan)",
                }}
                title={
                  danger
                    ? "You're about to overpay — double-check before committing."
                    : ""
                }
              >
                {existingPick
                  ? "Save"
                  : danger
                    ? "Record (overpay!)"
                    : "Record pick"}
              </button>
            );
          })()}
        </div>
      </form>
    </Modal>
  );
}

/* ── Rookie board ─────────────────────────────────────────────────── */

/**
 * Inline quick-record row rendered beneath a player on the board.
 * Two fields — team + amount — with Enter to commit, Esc to bail.
 * Way faster than opening the full draft modal when you just need
 * to log a sale.
 */
function QuickRecordRow({
  player,
  workspace,
  onSubmit,
  onCancel,
  colSpan = 14,
}) {
  const myTeamIdx = workspace?.settings?.myTeamIdx ?? 0;
  const [teamIdx, setTeamIdx] = useState(myTeamIdx);
  const [amount, setAmount] = useState("");
  const amountRef = useRef(null);

  useEffect(() => {
    if (amountRef.current) amountRef.current.focus();
  }, []);

  function handleKey(e) {
    if (e.key === "Enter") {
      e.preventDefault();
      const amt = Math.max(0, Number(amount) || 0);
      if (amt <= 0) return;
      onSubmit?.(player.id, Number(teamIdx), amt);
    } else if (e.key === "Escape") {
      e.preventDefault();
      onCancel?.();
    }
  }

  return (
    <tr className="draft-quick-row">
      <td colSpan={colSpan}>
        <div className="draft-quick-inner">
          <span className="muted" style={{ fontSize: "0.7rem" }}>
            Quick record <strong>{player.name}</strong>
          </span>
          <select
            className="select"
            value={teamIdx}
            onChange={(e) => setTeamIdx(Number(e.target.value))}
            onKeyDown={handleKey}
            style={{ fontSize: "0.74rem", padding: "2px 6px" }}
          >
            {workspace.teams.map((t, i) => (
              <option key={i} value={i}>
                {t.name || `Team ${i + 1}`}
                {i === myTeamIdx ? " (mine)" : ""}
              </option>
            ))}
          </select>
          <input
            ref={amountRef}
            type="number"
            className="input"
            min="1"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            onKeyDown={handleKey}
            placeholder="$"
            style={{
              width: 70,
              fontSize: "0.74rem",
              padding: "2px 6px",
            }}
          />
          <button
            type="button"
            className="button"
            style={{
              fontSize: "0.7rem",
              padding: "2px 8px",
              borderColor: "var(--cyan)",
              color: "var(--cyan)",
            }}
            onClick={() => {
              const amt = Math.max(0, Number(amount) || 0);
              if (amt > 0) onSubmit?.(player.id, Number(teamIdx), amt);
            }}
          >
            Save ⏎
          </button>
          <button
            type="button"
            className="button-reset muted"
            style={{ fontSize: "0.7rem", cursor: "pointer" }}
            onClick={onCancel}
          >
            Esc
          </button>
        </div>
      </td>
    </tr>
  );
}

// Exported for tests only (same pattern as ``describeCustomMix`` on
// the rankings page): the draft board's sortable-header semantics are
// a11y-critical and need coverage without mounting the whole 5k-line
// page and its localStorage/Sleeper-sync hook graph.
export function RookieBoard({
  stats,
  workspace,
  marketDollars,
  onDraft,
  onEditPreDraft,
  onRemovePlayer,
  onCycleTag,
  searchInputRef,
  selectedPlayerId,
  onSelectRow,
  quickRecordingId,
  onQuickOpen,
  onQuickSubmit,
  onQuickCancel,
  needSet,
  showDrafted,
  onShowDraftedChange,
  query,
  onQueryChange,
  tagFilter,
  onTagFilterChange,
  onAdd,
  bdvmIndex,
}) {
  const [sort, setSort] = useState({ col: "myWinningBid", asc: false });

  // Tag tabs — quick filter so the user can focus on targets during
  // live drafting without scrolling past everything.
  const tagCounts = useMemo(() => {
    let target = 0;
    let avoid = 0;
    let untagged = 0;
    for (const p of stats.enrichedPlayers) {
      if (p.drafted) continue;
      if (p.userTag === TAG_TARGET) target += 1;
      else if (p.userTag === TAG_AVOID) avoid += 1;
      else untagged += 1;
    }
    return { target, avoid, untagged, all: target + avoid + untagged };
  }, [stats.enrichedPlayers]);

  const filtered = useMemo(() => {
    let list = stats.enrichedPlayers;
    if (!showDrafted) list = list.filter((p) => !p.drafted);

    // Tag filter applies only to undrafted rows; drafted rows still
    // surface when ``showDrafted`` is on so history stays visible.
    if (tagFilter === "target") {
      list = list.filter((p) => p.drafted || p.userTag === TAG_TARGET);
    } else if (tagFilter === "avoid") {
      list = list.filter((p) => p.drafted || p.userTag === TAG_AVOID);
    } else if (tagFilter === "untagged") {
      list = list.filter((p) => p.drafted || !p.userTag);
    }

    const q = (query || "").trim().toLowerCase();
    if (q) list = list.filter((p) => p.name.toLowerCase().includes(q));
    const dir = sort.asc ? 1 : -1;
    return [...list].sort((a, b) => {
      switch (sort.col) {
        case "rank":
          return (a.rank - b.rank) * dir;
        case "name":
          return a.name.localeCompare(b.name) * dir;
        case "preDraft":
          return (a.preDraft - b.preDraft) * dir;
        case "inflatedFair":
          return (a.inflatedFair - b.inflatedFair) * dir;
        case "enforceUpTo":
          return (a.enforceUpTo - b.enforceUpTo) * dir;
        case "myMaxBid":
          return (a.myMaxBid - b.myMaxBid) * dir;
        case "myWinningBid":
          return (a.myWinningBid - b.myWinningBid) * dir;
        case "final":
          return ((a.pick?.amount ?? -1) - (b.pick?.amount ?? -1)) * dir;
        case "gap": {
          // BDVM fundamental gap — unpriced rows sink regardless of
          // direction (same null handling as the rankings page).
          const ga = bdvmEntryForRow(bdvmIndex, a)?.gap;
          const gb = bdvmEntryForRow(bdvmIndex, b)?.gap;
          if (ga == null && gb == null) return 0;
          if (ga == null) return 1;
          if (gb == null) return -1;
          return (ga - gb) * dir;
        }
        default:
          return 0;
      }
    });
  }, [stats.enrichedPlayers, sort, query, showDrafted, tagFilter, bdvmIndex]);

  // Tier-separator rows — only when the current sort groups by tier
  // naturally (rank or preDraft descending/ascending).  Scatter sorts
  // (win bid, fair) skip the dividers to avoid noise.
  const showTierDividers =
    (sort.col === "rank" && sort.asc) || (sort.col === "preDraft" && !sort.asc);

  const teamName = (idx) => workspace.teams[idx]?.name || `Team ${idx + 1}`;

  // Sortable header.  The draft board keeps its own hand-rolled
  // ``.draft-table`` (migrating it to the ds DataTable is a separate
  // job), so it borrows the ds table's SORT SEMANTICS directly: a real
  // <button> inside the <th>, aria-sort on the <th>, and the shared
  // .ds-table__sort glyph that rotates off aria-sort.  Before this the
  // header was a bare <th onClick> with an ASCII ▲/▼ — not focusable,
  // not activatable, announcing nothing, so the nine sortable columns
  // of the draft board were mouse-only.
  function th(label, col, width) {
    const active = sort.col === col;
    const ariaSort = active
      ? sort.asc
        ? "ascending"
        : "descending"
      : undefined;
    return (
      <th style={{ width }} aria-sort={ariaSort}>
        <button
          type="button"
          className="ds-table__sort"
          onClick={() =>
            setSort((s) =>
              s.col === col ? { col, asc: !s.asc } : { col, asc: false },
            )
          }
        >
          <span>{label}</span>
          <Icon name="chevron-down" size={8} className="ds-table__sort-glyph" />
        </button>
      </th>
    );
  }

  const tagTab = (key, label, count, color) => {
    const active = tagFilter === key;
    return (
      <button
        type="button"
        className={`draft-tag-tab${active ? " draft-tag-tab-active" : ""}`}
        style={{
          borderColor: active ? color : "var(--border)",
          color: active ? color : "var(--muted)",
        }}
        onClick={() => onTagFilterChange(key)}
      >
        {label}
        <span className="draft-tag-tab-count">{count}</span>
      </button>
    );
  };

  return (
    <Panel flush className="draft-board-panel">
      <div className="draft-board-head">
        <h3 style={{ margin: 0 }}>Rookie board</h3>
        <div className="draft-board-controls">
          <input
            ref={searchInputRef}
            className="input"
            placeholder="Search player… (press / )"
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            style={{ width: 200 }}
          />
          <label className="draft-check">
            <input
              type="checkbox"
              checked={showDrafted}
              onChange={(e) => onShowDraftedChange(e.target.checked)}
            />
            Show drafted
          </label>
          <AddPlayerInline onAdd={onAdd} />
        </div>
      </div>
      <div className="draft-tag-tabs">
        {tagTab("all", "All", tagCounts.all, "var(--cyan)")}
        {tagTab("target", "Targets", tagCounts.target, "var(--green)")}
        {tagTab("avoid", "Avoid", tagCounts.avoid, "var(--red)")}
        {tagTab("untagged", "Untagged", tagCounts.untagged, "var(--muted)")}
      </div>
      <div className="draft-table-wrap">
        <table className="draft-table">
          <thead>
            <tr>
              {th("#", "rank", 40)}
              <th style={{ width: 44 }}>
                Tier
                <InfoTip label="Tier">
                  Banded by PreDraft dollars — S is $60+, A $25–59, B $8–24,
                  C $3–7, D $1–2.
                </InfoTip>
              </th>
              <th
                style={{ width: 70 }}
                title="Click to cycle: neutral → target → avoid → neutral"
              >
                Tag
              </th>
              <th style={{ width: 86 }} title="Draft-time recommendation">
                Rec
              </th>
              {th("Player", "name")}
              {th("PreDraft", "preDraft", 82)}
              <th style={{ width: 76, textAlign: "right" }}>
                Market
                <InfoTip label="Market">
                  What the retail market says — KTC for offense, IDP TradeCalc
                  for defenders — converted to the same $1200 scale as our
                  PreDraft column so the two are directly comparable.
                </InfoTip>
              </th>
              {bdvmIndex ? th("Fund gap", "gap", 76) : null}
              {th("Fair", "inflatedFair", 70)}
              {th("Enforce", "enforceUpTo", 70)}
              {th("Win at", "myWinningBid", 80)}
              {th("Max Bid", "myMaxBid", 80)}
              {th("Final", "final", 100)}
              <th style={{ width: 180 }}>Drafted to</th>
              <th style={{ width: 110 }}></th>
            </tr>
          </thead>
          <tbody>
            {(() => {
              const rendered = [];
              let lastTier = null;
              for (const p of filtered) {
                if (showTierDividers && p.tier !== lastTier) {
                  const info = stats.tierStats?.[p.tier];
                  rendered.push(
                    <tr key={`tier-${p.tier}`} className="draft-tier-divider">
                      <td colSpan={14 + (bdvmIndex ? 1 : 0)}>
                        <span
                          className={`draft-tier-chip draft-tier-${p.tier}`}
                          style={{ marginRight: 8 }}
                        >
                          {p.tier}
                        </span>
                        <strong>{TIER_LABELS[p.tier] || p.tier} tier</strong>
                        {info && (
                          <span
                            className="muted"
                            style={{ marginLeft: 8, fontSize: "0.72rem" }}
                          >
                            {info.remaining} of {info.total} left
                            {info.heat != null &&
                              info.confidence > 0 &&
                              ` · heat ${info.heat.toFixed(2)}×`}
                          </span>
                        )}
                      </td>
                    </tr>,
                  );
                  lastTier = p.tier;
                }
                const capped = p.myWinningBid < p.theoreticalMaxBid;
                const rec = playerRecommendation(p, stats);
                const recInfo = rec ? REC_CHIP[rec.level] : null;
                rendered.push(
                  <tr
                    key={p.id}
                    onClick={() => onSelectRow?.(p.id)}
                    className={`draft-row${p.drafted ? " draft-row-drafted" : ""}${
                      p.mine ? " draft-row-mine" : ""
                    }${p.userTag === TAG_TARGET ? " draft-row-target" : ""}${
                      p.userTag === TAG_AVOID ? " draft-row-avoid" : ""
                    }${p.id === selectedPlayerId ? " draft-row-selected" : ""}`}
                  >
                    <td className="draft-money">{p.rank}</td>
                    <td>
                      <span
                        className={`draft-tier-chip draft-tier-${p.tier}`}
                        title={`${TIER_LABELS[p.tier] || p.tier} tier`}
                      >
                        {p.tier}
                      </span>
                      {p.pos && needSet?.has(p.pos) && (
                        <span
                          className="draft-need-chip-row"
                          title={`${p.pos} is a roster need`}
                        >
                          NEED
                        </span>
                      )}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`draft-tag-chip${p.userTag ? ` draft-tag-${p.userTag}` : ""}`}
                        onClick={() => onCycleTag(p.id)}
                        disabled={p.drafted}
                        title={
                          p.userTag === TAG_TARGET
                            ? "Target — click to cycle to avoid"
                            : p.userTag === TAG_AVOID
                              ? "Avoid — click to clear"
                              : "Click to mark target"
                        }
                      >
                        {p.userTag === TAG_TARGET
                          ? "★"
                          : p.userTag === TAG_AVOID
                            ? "⊘"
                            : "+"}
                      </button>
                    </td>
                    <td>
                      {recInfo ? (
                        <span
                          className={`draft-rec-chip ${recInfo.cls}`}
                          title={rec.rationale || rec.label}
                        >
                          {recInfo.text}
                        </span>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                    <td>{p.name}</td>
                    <td>
                      <input
                        type="number"
                        className="draft-inline-input draft-money-input"
                        min="0"
                        value={p.preDraft}
                        onChange={(e) =>
                          onEditPreDraft(p.id, Number(e.target.value) || 0)
                        }
                        disabled={p.drafted}
                      />
                    </td>
                    <td
                      className="draft-money"
                      title={(() => {
                        const isIdp =
                          p.assetClass === "idp" ||
                          (p.assetClass !== "offense" &&
                            classifyPos(p.pos) === "idp");
                        const m =
                          marketDollarFor(p) ??
                          (isIdp
                            ? marketDollars?.idp?.get(
                                String(p.name).toLowerCase(),
                              )
                            : marketDollars?.ktc?.get(
                                String(p.name).toLowerCase(),
                              ));
                        if (!Number.isFinite(Number(m)) || Number(m) <= 0) {
                          return "No market value for this rookie";
                        }
                        return `${isIdp ? "IDPTradeCalc" : "KTC"} $${Math.round(m)}`;
                      })()}
                    >
                      {(() => {
                        const isIdp =
                          p.assetClass === "idp" ||
                          (p.assetClass !== "offense" &&
                            classifyPos(p.pos) === "idp");
                        const m =
                          marketDollarFor(p) ??
                          (isIdp
                            ? marketDollars?.idp?.get(
                                String(p.name).toLowerCase(),
                              )
                            : marketDollars?.ktc?.get(
                                String(p.name).toLowerCase(),
                              ));
                        return Number.isFinite(Number(m)) && Number(m) > 0
                          ? fmt$(m)
                          : "—";
                      })()}
                    </td>
                    {bdvmIndex ? (
                      <td className="draft-money">
                        {(() => {
                          // BDVM fundamental gap — display-only join, same
                          // idiom as the rankings page column. Rows the
                          // fundamental board declines to price show a
                          // muted dash, never a fabricated number.
                          const entry = bdvmEntryForRow(bdvmIndex, p);
                          if (!entry || entry.gap == null) {
                            return (
                              <span
                                className="muted"
                                title={
                                  entry?.signalReason ||
                                  "not priced by the fundamental board"
                                }
                              >
                                —
                              </span>
                            );
                          }
                          const css = bdvmSignalEdgeCss(entry.signal);
                          const title =
                            `${entry.signal}: ${entry.signalReason} — fundamental ` +
                            `${formatBdvmValue(entry.fundamental)} vs market ` +
                            `${formatBdvmValue(entry.marketValue)}`;
                          return css ? (
                            <span className={`edge-label ${css}`} title={title}>
                              {formatBdvmGap(entry.gap)}
                            </span>
                          ) : (
                            <span title={title}>
                              {formatBdvmGap(entry.gap)}
                            </span>
                          );
                        })()}
                      </td>
                    ) : null}
                    <td className="draft-money">{fmt$(p.inflatedFair)}</td>
                    <td className="draft-money">{fmt$(p.enforceUpTo)}</td>
                    <td
                      className="draft-money draft-money-win"
                      title={
                        capped
                          ? `Capped by top rival ceiling (${fmt$(
                              stats.topCompetitorMax,
                            )} + $1). Theoretical max was ${fmt$(
                              p.theoreticalMaxBid,
                            )}.`
                          : `Limited by my theoretical max (${fmt$(
                              p.theoreticalMaxBid,
                            )})`
                      }
                    >
                      {fmt$(p.myWinningBid)}
                      {capped && (
                        <span
                          style={{
                            marginLeft: 4,
                            fontSize: "0.64rem",
                            color: "var(--green)",
                          }}
                        >
                          ✓
                        </span>
                      )}
                    </td>
                    <td
                      className="draft-money draft-money-max"
                      title="Theoretical max bid if forced all the way to the ceiling."
                    >
                      {fmt$(p.myMaxBid)}
                    </td>
                    <td className="draft-money">
                      {p.drafted ? fmt$(p.pick.amount) : "—"}
                      {p.drafted && p.valueVsFair != null && (
                        <span
                          className={`draft-vs-fair ${
                            p.valueVsFair > 0
                              ? "draft-vs-fair-win"
                              : p.valueVsFair < 0
                                ? "draft-vs-fair-lose"
                                : ""
                          }`}
                          title={`Inflated fair ${fmt$(
                            p.inflatedFair,
                          )} − final ${fmt$(p.pick.amount)}`}
                        >
                          {p.valueVsFair > 0 ? "+" : ""}
                          {fmt$(p.valueVsFair)}
                        </span>
                      )}
                    </td>
                    <td>
                      {p.drafted ? (
                        <span
                          className={`draft-tag${p.mine ? " draft-tag-mine" : ""}`}
                        >
                          {teamName(p.pick.teamIdx)}
                        </span>
                      ) : (
                        <span className="muted" style={{ fontSize: "0.72rem" }}>
                          —
                        </span>
                      )}
                    </td>
                    <td>
                      <div className="draft-row-actions">
                        <button
                          className="button"
                          style={{ fontSize: "0.72rem", padding: "3px 8px" }}
                          onClick={() => onDraft(p)}
                        >
                          {p.drafted ? "Edit" : "Draft"}
                        </button>
                        {!p.drafted && (
                          <>
                            <button
                              className="button"
                              style={{
                                fontSize: "0.68rem",
                                padding: "2px 6px",
                                borderColor: "var(--cyan)",
                                color: "var(--cyan)",
                              }}
                              onClick={() => onQuickOpen?.(p.id)}
                              title="Quick record (Q when selected)"
                            >
                              Q
                            </button>
                            <button
                              className="button-reset draft-remove-btn"
                              onClick={() => {
                                if (
                                  typeof window !== "undefined" &&
                                  window.confirm(
                                    `Remove ${p.name} from the board?`,
                                  )
                                ) {
                                  onRemovePlayer(p.id);
                                }
                              }}
                              title="Remove from board"
                            >
                              ×
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>,
                );
                // Inline quick-record row — only rendered when this
                // specific player is in quick-record mode.  Keeps the
                // UI flat when nothing is being quick-recorded.
                if (quickRecordingId === p.id) {
                  rendered.push(
                    <QuickRecordRow
                      key={`qr-${p.id}`}
                      player={p}
                      workspace={workspace}
                      onSubmit={onQuickSubmit}
                      onCancel={onQuickCancel}
                      colSpan={14 + (bdvmIndex ? 1 : 0)}
                    />,
                  );
                }
              }
              return rendered;
            })()}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={14 + (bdvmIndex ? 1 : 0)}
                  className="muted"
                  style={{ padding: 14, textAlign: "center" }}
                >
                  No rookies match.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

/* ── Next Best Target sidebar ─────────────────────────────────────── */

/**
 * Top-N EV-ranked undrafted targets, always visible.  Answers "what
 * should I focus on right now?" without the user having to scroll
 * or re-sort.  Clicking a row opens the draft modal pre-loaded with
 * that player; clicking the star cycles the tag.
 */
/* ── Inflation sparkline ──────────────────────────────────────────── */

/**
 * Tiny SVG sparkline of inflation (y-axis) over picks (x-axis).
 * Renders inline in the stats strip so the user can see "inflation
 * has been climbing 3 picks straight" at a glance without scrolling
 * back through the pick log.
 *
 * Draws a horizontal reference line at 1.00×; the main path is a
 * polyline over the ``series``, color-coded by the most recent
 * direction (green = above 1.0, red = below, muted when flat).
 */
function InflationSparkline({ series, width = 140, height = 36 }) {
  if (!Array.isArray(series) || series.length < 2) {
    return (
      <span className="muted" style={{ fontSize: "0.68rem" }}>
        (sparkline populates after first pick)
      </span>
    );
  }
  const values = series.map((s) => s.inflation);
  const minV = Math.min(0.7, ...values);
  const maxV = Math.max(1.3, ...values);
  const range = Math.max(0.01, maxV - minV);
  const padX = 2;
  const padY = 2;
  const w = width - padX * 2;
  const h = height - padY * 2;

  const pts = values.map((v, i) => {
    const x = padX + (i / Math.max(1, series.length - 1)) * w;
    const y = padY + h - ((v - minV) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  // Reference line at 1.00×.
  const refY = padY + h - ((1 - minV) / range) * h;

  const last = values[values.length - 1];
  const color =
    last > 1.03 ? "var(--green)" : last < 0.97 ? "var(--red)" : "var(--muted)";

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="draft-sparkline"
      role="img"
      aria-label={`Inflation trajectory, currently ${last.toFixed(2)}×`}
    >
      <line
        x1={padX}
        y1={refY}
        x2={width - padX}
        y2={refY}
        stroke="rgba(153,166,200,0.3)"
        strokeWidth="0.5"
        strokeDasharray="2 2"
      />
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle
        cx={padX + w}
        cy={refY - ((last - 1) / range) * h}
        r="2"
        fill={color}
      />
    </svg>
  );
}

/* ── Target Board — my explicit short-list ───────────────────────── */

/**
 * The user's committed short-list board.  Shows each entry with
 * live predraft / fair / winning bid / paid numbers, plus an
 * aggregate footer with the portfolio cost vs my remaining $.
 *
 * Headlines:
 *   - Portfolio cost now  = Σ winning bids of remaining targets
 *                             + Σ paid on targets already won
 *   - Buffer              = my remaining $ − cost of remaining
 *                             (no per-opening reserve — see draft-logic.js)
 *
 * Negative buffer renders red with "SHORT $N — trim a target".
 */
/* ── Par Sheet ────────────────────────────────────────────────────── */

/**
 * Pre-draft "shopping list" with a per-row personal Fair Value.  As
 * picks land, each row classifies into target / won / lost.  Footer
 * shows committed FV, banked surplus, and how much headroom remains
 * against my budget if I hit every target at FV.
 *
 * Free-text adds are accepted: the row's id is the slug of the typed
 * name, so it auto-matches a future pick recorded under the same
 * slug (the rookie pool seeds use the same slug rule).  Quick-add
 * suggestions surface from the existing player pool when the typed
 * text matches a pool name; clicking a suggestion pre-fills the FV
 * with that player's preDraft $ — which the user can then override.
 */
function ParSheet({
  stats,
  workspace,
  onAdd,
  onRemove,
  onEditFV,
  onMove,
  onClear,
  onDraft,
}) {
  const [name, setName] = useState("");
  const [fv, setFv] = useState("");
  const [editingId, setEditingId] = useState(null);
  const [editingValue, setEditingValue] = useState("");
  const psStats = stats.parSheetStats || {
    rows: [],
    totals: {
      committedFV: 0,
      wonFV: 0,
      wonPaid: 0,
      lostFV: 0,
      targetCount: 0,
      wonCount: 0,
      lostCount: 0,
      surplus: 0,
    },
    headroom: 0,
    status: "idle",
    statusLabel: "",
  };
  const rows = psStats.rows;

  // Quick-add suggestions: pool players whose name fuzzy-matches the
  // typed text.  Excludes anything already on the par sheet.  Limit
  // the dropdown to a handful so it stays compact.
  const sheetIds = useMemo(() => new Set(rows.map((r) => r.id)), [rows]);
  const suggestions = useMemo(() => {
    const q = name.trim().toLowerCase();
    if (q.length < 2) return [];
    return stats.enrichedPlayers
      .filter((p) => !sheetIds.has(p.id) && p.name.toLowerCase().includes(q))
      .slice(0, 6);
  }, [name, sheetIds, stats.enrichedPlayers]);

  const submitAdd = (overrideName, overrideFV) => {
    const finalName = String(overrideName ?? name).trim();
    if (!finalName) return;
    const fvNum = Number(overrideFV ?? fv);
    onAdd({
      name: finalName,
      fairValue: Number.isFinite(fvNum) ? Math.max(0, fvNum) : 0,
    });
    setName("");
    setFv("");
  };

  const beginEditFV = (row) => {
    setEditingId(row.id);
    setEditingValue(String(row.fairValue || 0));
  };
  const commitEditFV = () => {
    if (!editingId) return;
    const v = Number(editingValue);
    onEditFV(editingId, Number.isFinite(v) ? Math.max(0, v) : 0);
    setEditingId(null);
    setEditingValue("");
  };
  const cancelEditFV = () => {
    setEditingId(null);
    setEditingValue("");
  };

  const statusClass =
    psStats.status === "short"
      ? "draft-tb-status-short"
      : psStats.status === "tight"
        ? "draft-tb-status-tight"
        : psStats.status === "on_track" || psStats.status === "done"
          ? "draft-tb-status-ok"
          : "draft-tb-status-idle";

  const totals = psStats.totals;
  const surplus = totals.surplus || 0;
  const surplusClass =
    surplus > 0 ? "draft-vs-fair-win" : surplus < 0 ? "draft-vs-fair-lose" : "";

  return (
    <Panel className="draft-target-board draft-par-sheet">
      <div className="draft-tb-head">
        <div>
          <h3 style={{ margin: "0 0 2px" }}>
            Par Sheet{" "}
            <span className="muted" style={{ fontSize: "0.72rem" }}>
              ({rows.length} {rows.length === 1 ? "row" : "rows"} ·{" "}
              {totals.targetCount} open · {totals.wonCount} won ·{" "}
              {totals.lostCount} lost)
            </span>
          </h3>
          <div className="muted" style={{ fontSize: "0.7rem" }}>
            Pre-draft shopping list with your own fair value · surplus on
            bargains rolls into headroom you can spend elsewhere
          </div>
        </div>
        <div className="draft-tb-actions">
          {rows.length > 0 && (
            <button
              className="button"
              style={{ fontSize: "0.7rem", padding: "3px 8px" }}
              onClick={() => {
                if (
                  typeof window !== "undefined" &&
                  window.confirm("Clear the entire par sheet?")
                ) {
                  onClear();
                }
              }}
              title="Clear every row on the par sheet"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {rows.length === 0 && (
        <div
          className="muted"
          style={{ fontSize: "0.76rem", padding: "6px 0 4px" }}
        >
          Type a player and your fair-value $ below to start your par sheet. As
          picks land, each row marks itself "Won" (with surplus vs your FV) or
          "Lost". Bottom-line headroom shows what you have left if you hit every
          open row at your FV.
        </div>
      )}

      {rows.length > 0 && (
        <div className="draft-tb-grid draft-ps-grid">
          <div className="draft-tb-row draft-ps-row draft-tb-row-head">
            <span>#</span>
            <span>Player</span>
            <span>FV</span>
            <span>Paid</span>
            <span>Δ</span>
            <span>Status</span>
            <span></span>
          </div>
          {rows.map((row, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === rows.length - 1;
            const drafted = row.status !== "target";
            const status =
              row.status === "won"
                ? {
                    label: `Won $${row.paid}`,
                    cls: "draft-tb-status-won",
                  }
                : row.status === "lost"
                  ? { label: "Lost", cls: "draft-tb-status-lost" }
                  : { label: "Open", cls: "draft-tb-status-open" };
            const surplusRow = row.surplus;
            const enriched = row.enriched;
            const isEditing = editingId === row.id;
            return (
              <div
                key={row.id}
                className={`draft-tb-row draft-ps-row${
                  drafted ? " draft-tb-row-drafted" : ""
                }${row.mine ? " draft-tb-row-mine" : ""}`}
              >
                <span className="draft-tb-idx">#{idx + 1}</span>
                <span className="draft-tb-name-cell">
                  {enriched && (
                    <span
                      className={`draft-tier-chip draft-tier-${enriched.tier}`}
                      style={{ marginRight: 4 }}
                    >
                      {enriched.tier}
                    </span>
                  )}
                  <span
                    className="draft-nbt-name"
                    onClick={() => {
                      if (enriched && !drafted) onDraft(enriched);
                    }}
                    title={
                      enriched
                        ? "Open draft modal"
                        : "Not in rookie pool yet — sync rookies to enable quick-draft"
                    }
                    style={!enriched ? { cursor: "default" } : undefined}
                  >
                    {row.name}
                  </span>
                </span>
                <span className="draft-money">
                  {isEditing ? (
                    <input
                      type="number"
                      className="input draft-money-input"
                      autoFocus
                      value={editingValue}
                      min="0"
                      onChange={(e) => setEditingValue(e.target.value)}
                      onBlur={commitEditFV}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitEditFV();
                        if (e.key === "Escape") cancelEditFV();
                      }}
                      style={{ width: 56, fontSize: "0.78rem" }}
                    />
                  ) : (
                    <button
                      type="button"
                      className="button-reset draft-ps-fv-edit"
                      onClick={() => beginEditFV(row)}
                      title="Click to edit fair value"
                    >
                      {fmt$(row.fairValue)}
                    </button>
                  )}
                </span>
                <span className="draft-money">
                  {row.status === "won" ? fmt$(row.paid) : "—"}
                </span>
                <span className="draft-money">
                  {row.status === "won" && Number.isFinite(surplusRow) ? (
                    <span
                      className={
                        surplusRow > 0
                          ? "draft-vs-fair-win"
                          : surplusRow < 0
                            ? "draft-vs-fair-lose"
                            : ""
                      }
                      title={`Fair ${fmt$(row.fairValue)} − paid ${fmt$(row.paid)}`}
                    >
                      {surplusRow > 0 ? "+" : ""}
                      {fmt$(surplusRow)}
                    </span>
                  ) : (
                    "—"
                  )}
                </span>
                <span className={`draft-tb-status ${status.cls}`}>
                  {status.label}
                </span>
                <span className="draft-tb-controls">
                  <button
                    className="button-reset draft-tb-ctrl"
                    onClick={() => onMove(row.id, "up")}
                    disabled={isFirst}
                    title="Move up"
                  >
                    ▲
                  </button>
                  <button
                    className="button-reset draft-tb-ctrl"
                    onClick={() => onMove(row.id, "down")}
                    disabled={isLast}
                    title="Move down"
                  >
                    ▼
                  </button>
                  <button
                    className="button-reset draft-tb-ctrl draft-tb-ctrl-remove"
                    onClick={() => onRemove(row.id)}
                    title="Remove from par sheet"
                  >
                    ×
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div className={`draft-tb-summary ${statusClass}`}>
        <div className="draft-tb-summary-line">
          <span className="muted">FV Σ (open)</span>
          <span className="draft-money">{fmt$(totals.committedFV)}</span>
          <span className="muted">FV Σ (won)</span>
          <span className="draft-money">{fmt$(totals.wonFV)}</span>
          <span className="muted">Paid Σ (won)</span>
          <span className="draft-money">{fmt$(totals.wonPaid)}</span>
          <span className="muted">Surplus banked</span>
          <span className={`draft-money ${surplusClass}`}>
            {surplus > 0 ? "+" : ""}
            {fmt$(surplus)}
          </span>
        </div>
        <div className="draft-tb-summary-line">
          <span className="muted">My remaining</span>
          <span className="draft-money">{fmt$(stats.myRemaining)}</span>
          <span className="muted">− open FV</span>
          <span className="draft-money">{fmt$(totals.committedFV)}</span>
          <strong>=</strong>
          <span className="draft-money draft-tb-buffer">
            {fmt$(psStats.headroom)}
          </span>
          <span className="muted" style={{ marginLeft: 6 }}>
            headroom
          </span>
        </div>
        <div className="draft-tb-status-line">{psStats.statusLabel}</div>
      </div>

      <div className="draft-tb-add draft-ps-add">
        <input
          type="text"
          className="input"
          placeholder="Player name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitAdd();
          }}
          style={{ flex: "1 1 180px", maxWidth: 220 }}
        />
        <input
          type="number"
          className="input"
          placeholder="Fair $"
          value={fv}
          min="0"
          onChange={(e) => setFv(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submitAdd();
          }}
          style={{ width: 80 }}
        />
        <button
          type="button"
          className="button"
          onClick={() => submitAdd()}
          disabled={!name.trim()}
          style={{ fontSize: "0.72rem", padding: "3px 10px" }}
        >
          Add
        </button>
        {suggestions.length > 0 && (
          <div className="draft-tb-suggest">
            {suggestions.map((p) => (
              <button
                key={p.id}
                type="button"
                className="button draft-tb-suggest-btn"
                onClick={() => submitAdd(p.name, p.preDraft)}
                title={`Pre-fill ${p.name} with PreDraft ${fmt$(p.preDraft)}`}
                style={{ fontSize: "0.72rem", padding: "3px 8px" }}
              >
                <span
                  className={`draft-tier-chip draft-tier-${p.tier}`}
                  style={{ marginRight: 4 }}
                >
                  {p.tier}
                </span>
                {p.name} ({fmt$(p.preDraft)})
              </button>
            ))}
          </div>
        )}
      </div>
    </Panel>
  );
}

/* ── Target Board ─────────────────────────────────────────────────── */

function TargetBoard({
  stats,
  workspace,
  onAdd,
  onRemove,
  onMove,
  onClear,
  onDraft,
}) {
  const [search, setSearch] = useState("");
  const tbStats = stats.targetBoardStats;
  const slots = tbStats.slots;
  const undraftedCandidates = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return [];
    const boardIds = new Set(slots.map((s) => s.id));
    return stats.enrichedPlayers
      .filter(
        (p) =>
          !p.drafted && !boardIds.has(p.id) && p.name.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [search, stats.enrichedPlayers, slots]);

  const statusClass =
    tbStats.portfolioStatus === "short"
      ? "draft-tb-status-short"
      : tbStats.portfolioStatus === "tight"
        ? "draft-tb-status-tight"
        : tbStats.portfolioStatus === "on_track"
          ? "draft-tb-status-ok"
          : "draft-tb-status-idle";

  return (
    <Panel className="draft-target-board">
      <div className="draft-tb-head">
        <div>
          <h3 style={{ margin: "0 0 2px" }}>
            Target Board{" "}
            <span className="muted" style={{ fontSize: "0.72rem" }}>
              ({slots.length} of {TARGET_BOARD_MAX})
            </span>
          </h3>
          <div className="muted" style={{ fontSize: "0.7rem" }}>
            Live fair + win bid · paid if won · buffer vs my budget
          </div>
        </div>
        <div className="draft-tb-actions">
          {slots.length > 0 && (
            <button
              className="button"
              style={{ fontSize: "0.7rem", padding: "3px 8px" }}
              onClick={() => {
                if (
                  typeof window !== "undefined" &&
                  window.confirm("Clear all Target Board entries?")
                ) {
                  onClear();
                }
              }}
              title="Clear every target on the board"
            >
              Clear
            </button>
          )}
        </div>
      </div>

      {slots.length === 0 && (
        <div
          className="muted"
          style={{ fontSize: "0.76rem", padding: "6px 0 4px" }}
        >
          Pick up to {TARGET_BOARD_MAX} rookies to track closely. The board will
          show what each costs now, what you paid (if won), and how the full
          portfolio fits your remaining budget.
        </div>
      )}

      {slots.length > 0 && (
        <div className="draft-tb-grid">
          <div className="draft-tb-row draft-tb-row-head">
            <span>#</span>
            <span>Player</span>
            <span>PD</span>
            <span>Fair</span>
            <span>Win</span>
            <span>Paid</span>
            <span>Status</span>
            <span></span>
          </div>
          {slots.map((p, idx) => {
            const isFirst = idx === 0;
            const isLast = idx === slots.length - 1;
            const status = p.drafted
              ? p.mine
                ? {
                    label: `Won $${p.pick.amount}`,
                    cls: "draft-tb-status-won",
                  }
                : { label: "Lost", cls: "draft-tb-status-lost" }
              : {
                  label: `Win at $${p.myWinningBid}`,
                  cls: "draft-tb-status-open",
                };
            const paidDelta =
              p.drafted && p.mine && Number.isFinite(p.valueVsFair)
                ? p.valueVsFair
                : null;
            return (
              <div
                key={p.id}
                className={`draft-tb-row${p.drafted ? " draft-tb-row-drafted" : ""}${p.mine ? " draft-tb-row-mine" : ""}`}
              >
                <span className="draft-tb-idx">#{idx + 1}</span>
                <span className="draft-tb-name-cell">
                  <span
                    className={`draft-tier-chip draft-tier-${p.tier}`}
                    style={{ marginRight: 4 }}
                  >
                    {p.tier}
                  </span>
                  <span
                    className="draft-nbt-name"
                    onClick={() => onDraft(p)}
                    title="Open draft modal"
                  >
                    {p.name}
                  </span>
                </span>
                <span className="draft-money">{fmt$(p.preDraft)}</span>
                <span className="draft-money">{fmt$(p.inflatedFair)}</span>
                <span className="draft-money draft-money-win">
                  {fmt$(p.myWinningBid)}
                </span>
                <span className="draft-money">
                  {p.drafted && p.mine ? fmt$(p.pick.amount) : "—"}
                  {paidDelta != null && (
                    <span
                      className={
                        paidDelta > 0
                          ? "draft-vs-fair-win"
                          : paidDelta < 0
                            ? "draft-vs-fair-lose"
                            : ""
                      }
                      style={{
                        marginLeft: 4,
                        fontSize: "0.66rem",
                        fontWeight: 600,
                      }}
                      title={`Inflated fair ${fmt$(
                        p.inflatedFair,
                      )} − paid ${fmt$(p.pick.amount)}`}
                    >
                      {paidDelta > 0 ? "+" : ""}
                      {fmt$(paidDelta)}
                    </span>
                  )}
                </span>
                <span className={`draft-tb-status ${status.cls}`}>
                  {status.label}
                </span>
                <span className="draft-tb-controls">
                  <button
                    className="button-reset draft-tb-ctrl"
                    onClick={() => onMove(p.id, "up")}
                    disabled={isFirst}
                    title="Move up"
                  >
                    ▲
                  </button>
                  <button
                    className="button-reset draft-tb-ctrl"
                    onClick={() => onMove(p.id, "down")}
                    disabled={isLast}
                    title="Move down"
                  >
                    ▼
                  </button>
                  <button
                    className="button-reset draft-tb-ctrl draft-tb-ctrl-remove"
                    onClick={() => onRemove(p.id)}
                    title="Remove from board"
                  >
                    ×
                  </button>
                </span>
              </div>
            );
          })}
        </div>
      )}

      <div className={`draft-tb-summary ${statusClass}`}>
        <div className="draft-tb-summary-line">
          <span className="muted">PreDraft Σ</span>
          <span className="draft-money">
            {fmt$(tbStats.totals.preDraftSum)}
          </span>
          <span className="muted">Fair Σ</span>
          <span className="draft-money">{fmt$(tbStats.totals.fairSum)}</span>
          <span className="muted">Win Σ (open)</span>
          <span className="draft-money">
            {fmt$(tbStats.totals.remainingWinBid)}
          </span>
          <span className="muted">Paid Σ (won)</span>
          <span className="draft-money">{fmt$(tbStats.totals.paidSum)}</span>
        </div>
        <div className="draft-tb-summary-line">
          <span className="muted">My remaining</span>
          <span className="draft-money">{fmt$(stats.myRemaining)}</span>
          <span className="muted">− buys at win</span>
          <span className="draft-money">
            {fmt$(tbStats.totals.remainingWinBid)}
          </span>
          <strong>=</strong>
          <span className="draft-money draft-tb-buffer">
            {fmt$(tbStats.portfolioBuffer)}
          </span>
        </div>
        <div className="draft-tb-status-line">
          {tbStats.portfolioStatusLabel}
        </div>
      </div>

      {slots.length < TARGET_BOARD_MAX && (
        <div className="draft-tb-add">
          <input
            type="text"
            className="input"
            placeholder="Add target (type a name)…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{ flex: 1, maxWidth: 260 }}
          />
          {undraftedCandidates.length > 0 && (
            <div className="draft-tb-suggest">
              {undraftedCandidates.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className="button draft-tb-suggest-btn"
                  onClick={() => {
                    onAdd(p.id);
                    setSearch("");
                  }}
                  style={{ fontSize: "0.72rem", padding: "3px 8px" }}
                >
                  <span
                    className={`draft-tier-chip draft-tier-${p.tier}`}
                    style={{ marginRight: 4 }}
                  >
                    {p.tier}
                  </span>
                  {p.name} ({fmt$(p.inflatedFair)})
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </Panel>
  );
}

/* ── Nomination optimizer sidebar ─────────────────────────────────── */

/**
 * "Good to nominate" list.  Players I don't want (or am happy
 * without) whose expected clearing price is high enough to drain
 * rival budgets.  Companion to ``NextBestTargets``; both live just
 * above the rookie board so decisions are in peripheral vision.
 */
function NominationCandidates({ stats, onDraft, onCycleTag }) {
  const list = useMemo(
    () => nominationCandidates(stats, { limit: 10 }),
    [stats],
  );

  if (list.length === 0) {
    return (
      <Panel className="draft-nbt">
        <h3 style={{ margin: "0 0 4px" }}>Good to nominate</h3>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          No vendor overrates — either every rookie's vendor price and our board
          agree, or KTC / IDPTradeCalc values are missing from the live
          contract.
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="draft-nbt">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>Good to nominate</h3>
        <span className="muted" style={{ fontSize: "0.68rem" }}>
          Top 10 rookies KTC / IDPTC overrates vs our board (% gap)
        </span>
      </div>
      <div className="draft-nbt-list">
        {list.map(
          (
            {
              player,
              gap,
              gapPct,
              ourDollar,
              vendorDollar,
              vendorLabel,
              rationale,
            },
            i,
          ) => (
            <div
              key={player.id}
              className={`draft-nbt-row${player.userTag === TAG_AVOID ? " draft-nbt-avoid" : ""}`}
              title={rationale}
            >
              <span className="draft-nbt-rank">#{i + 1}</span>
              <button
                type="button"
                className={`draft-tag-chip${
                  player.userTag ? ` draft-tag-${player.userTag}` : ""
                }`}
                onClick={() => onCycleTag(player.id)}
                title="Cycle tag"
              >
                {player.userTag === TAG_TARGET
                  ? "★"
                  : player.userTag === TAG_AVOID
                    ? "⊘"
                    : "+"}
              </button>
              <span
                className={`draft-tier-chip draft-tier-${player.tier}`}
                title={`${TIER_LABELS[player.tier] || player.tier} tier`}
              >
                {player.tier}
              </span>
              <span className="draft-nbt-name" onClick={() => onDraft(player)}>
                {player.name}
              </span>
              <span
                className="muted"
                style={{ fontSize: "0.68rem" }}
                title="Our board's pre-draft fair price"
              >
                ours {fmt$(ourDollar)}
              </span>
              <span
                className="muted"
                style={{ fontSize: "0.68rem" }}
                title={`${vendorLabel}'s market value at the same scale`}
              >
                {vendorLabel.toLowerCase()} {fmt$(vendorDollar)}
              </span>
              <span
                className="draft-rec-chip"
                style={{
                  background: "rgba(34, 211, 238, 0.18)",
                  color: "var(--cyan, #22d3ee)",
                  fontWeight: 600,
                }}
                title={`${vendorLabel} overrates by ${Math.round(gapPct * 100)}% (+$${Math.round(gap)}) — leaguemates following ${vendorLabel} will overpay`}
              >
                +{Math.round(gapPct * 100)}%
              </span>
            </div>
          ),
        )}
      </div>
    </Panel>
  );
}

/**
 * "Best value on the board" list — mirror of NominationCandidates.
 * Surfaces undrafted rookies our board values much HIGHER than the
 * vendor (KTC for offense, IDPTC for IDP).  Sorted by percentage gap
 * above the vendor price so cheap discounts outrank big-dollar but
 * proportionally smaller mismatches.
 */
function BestValueOnBoard({ stats, onDraft, onCycleTag }) {
  const list = useMemo(() => bestValueOnBoard(stats, { limit: 10 }), [stats]);

  if (list.length === 0) {
    return (
      <Panel className="draft-nbt">
        <h3 style={{ margin: "0 0 4px" }}>Best value on the board</h3>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          No vendor underrates — either every rookie's vendor price and our
          board agree, or KTC / IDPTradeCalc values are missing from the live
          contract.
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="draft-nbt">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>Best value on the board</h3>
        <span className="muted" style={{ fontSize: "0.68rem" }}>
          Top 10 rookies KTC / IDPTC underrates vs our board (% gap)
        </span>
      </div>
      <div className="draft-nbt-list">
        {list.map(
          (
            {
              player,
              gap,
              gapPct,
              ourDollar,
              vendorDollar,
              vendorLabel,
              rationale,
            },
            i,
          ) => (
            <div
              key={player.id}
              className={`draft-nbt-row${player.userTag === TAG_TARGET ? " draft-nbt-target" : ""}`}
              title={rationale}
            >
              <span className="draft-nbt-rank">#{i + 1}</span>
              <button
                type="button"
                className={`draft-tag-chip${
                  player.userTag ? ` draft-tag-${player.userTag}` : ""
                }`}
                onClick={() => onCycleTag(player.id)}
                title="Cycle tag"
              >
                {player.userTag === TAG_TARGET
                  ? "★"
                  : player.userTag === TAG_AVOID
                    ? "⊘"
                    : "+"}
              </button>
              <span
                className={`draft-tier-chip draft-tier-${player.tier}`}
                title={`${TIER_LABELS[player.tier] || player.tier} tier`}
              >
                {player.tier}
              </span>
              <span className="draft-nbt-name" onClick={() => onDraft(player)}>
                {player.name}
              </span>
              <span
                className="muted"
                style={{ fontSize: "0.68rem" }}
                title="Our board's pre-draft fair price"
              >
                ours {fmt$(ourDollar)}
              </span>
              <span
                className="muted"
                style={{ fontSize: "0.68rem" }}
                title={`${vendorLabel}'s market value at the same scale`}
              >
                {vendorLabel.toLowerCase()} {fmt$(vendorDollar)}
              </span>
              <span
                className="draft-rec-chip"
                style={{
                  background: "rgba(74, 222, 128, 0.18)",
                  color: "var(--green, #4ade80)",
                  fontWeight: 600,
                }}
                title={`${vendorLabel} underrates by ${Math.round(gapPct * 100)}% (+$${Math.round(gap)} board edge) — leaguemates following ${vendorLabel} will let this clear cheap`}
              >
                −{Math.round(gapPct * 100)}%
              </span>
            </div>
          ),
        )}
      </div>
    </Panel>
  );
}

function NextBestTargets({ stats, onDraft, onCycleTag, workspace }) {
  const top = useMemo(() => nextBestTargets(stats, { limit: 5 }), [stats]);

  if (top.length === 0) {
    return (
      <Panel className="draft-nbt">
        <h3 style={{ margin: "0 0 4px" }}>Next Best Targets</h3>
        <div className="muted" style={{ fontSize: "0.72rem" }}>
          Nothing to flag yet — tag a few players as <strong>★ target</strong>{" "}
          to seed EV ranking.
        </div>
      </Panel>
    );
  }

  return (
    <Panel className="draft-nbt">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <h3 style={{ margin: 0 }}>Next Best Targets</h3>
        <span className="muted" style={{ fontSize: "0.68rem" }}>
          EV = (fair − winBid) × tag weight + scarcity boost
        </span>
      </div>
      <div className="draft-nbt-list">
        {top.map(({ player, ev, rec }, i) => {
          const recInfo = rec ? REC_CHIP[rec.level] : null;
          return (
            <div
              key={player.id}
              className={`draft-nbt-row${player.userTag === TAG_TARGET ? " draft-nbt-target" : ""}`}
              title={rec?.rationale || rec?.label || ""}
            >
              <span className="draft-nbt-rank">#{i + 1}</span>
              <button
                type="button"
                className={`draft-tag-chip${
                  player.userTag ? ` draft-tag-${player.userTag}` : ""
                }`}
                onClick={() => onCycleTag(player.id)}
                title="Cycle tag"
              >
                {player.userTag === TAG_TARGET
                  ? "★"
                  : player.userTag === TAG_AVOID
                    ? "⊘"
                    : "+"}
              </button>
              <span
                className={`draft-tier-chip draft-tier-${player.tier}`}
                title={`${TIER_LABELS[player.tier] || player.tier} tier`}
              >
                {player.tier}
              </span>
              <span className="draft-nbt-name" onClick={() => onDraft(player)}>
                {player.name}
              </span>
              <span className="draft-money draft-money-win">
                {fmt$(player.myWinningBid)}
              </span>
              <span className="muted" style={{ fontSize: "0.68rem" }}>
                fair {fmt$(player.inflatedFair)}
              </span>
              {recInfo && (
                <span className={`draft-rec-chip ${recInfo.cls}`}>
                  {recInfo.text}
                </span>
              )}
              <span className="muted" style={{ fontSize: "0.66rem" }}>
                EV {ev.toFixed(0)}
              </span>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function AddPlayerInline({ onAdd }) {
  const [name, setName] = useState("");
  const [pd, setPd] = useState("");
  function submit(e) {
    e?.preventDefault();
    if (!name.trim()) return;
    onAdd({ name: name.trim(), preDraft: Number(pd) || 0 });
    setName("");
    setPd("");
  }
  return (
    <form className="draft-add-inline" onSubmit={submit}>
      <input
        className="input"
        placeholder="Add rookie…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        style={{ width: 140 }}
      />
      <input
        className="input"
        type="number"
        placeholder="$"
        value={pd}
        onChange={(e) => setPd(e.target.value)}
        min="0"
        style={{ width: 60 }}
      />
      <button
        type="submit"
        className="button"
        style={{ fontSize: "0.72rem", padding: "3px 8px" }}
      >
        +
      </button>
    </form>
  );
}

/* ── Main page ────────────────────────────────────────────────────── */

/* ── Glossary / how-it-works reference ────────────────────────────── */

/**
 * Collapsible reference block rendered at the bottom of the page.
 * Uses native ``<details>`` so state isn't needed and the section
 * survives tab closes + page reloads cleanly.  Copy is kept punchy
 * so the glossary reads fast during a live draft — long enough to
 * answer "what does this column mean?" without becoming a wall of
 * text.
 *
 * Everything here is a VERBAL description of logic defined
 * elsewhere; if a formula changes in draft-logic.js, update the
 * matching entry here so the reference stays honest.
 */
/* ── Post-draft review panel ──────────────────────────────────────── */

/**
 * Modal that shows the "how did this draft go" recap: my picks +
 * deltas, portfolio ratio, best steal / worst overpay, per-team
 * rankings, CSV export.  Computed from the current workspace state
 * via ``computeDraftReview``.
 *
 * Can be opened mid-draft (shows partial data) or post-draft (the
 * full accounting).
 */
function DraftReviewPanel({ workspace, stats, onClose }) {
  const review = useMemo(
    () => computeDraftReview(workspace, stats),
    [workspace, stats],
  );

  const downloadCsv = () => {
    const csv = draftReviewToCsv(review);
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `draft-review-${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <Modal open onClose={onClose} title="Draft review">
      <div className="draft-modal-body">
        {review.myPicks.length === 0 ? (
          <div className="muted" style={{ fontSize: "0.82rem" }}>
            No picks recorded yet. Run the draft — this panel populates with
            every pick you made, the delta vs fair at the time, and a
            portfolio-value rollup.
          </div>
        ) : (
          <>
            {/* Portfolio headline */}
            <div className="draft-review-portfolio">
              <div>
                <div className="muted" style={{ fontSize: "0.7rem" }}>
                  You paid
                </div>
                <div className="draft-review-big">
                  {fmt$(review.portfolio.paid)}
                </div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: "0.7rem" }}>
                  Fair value received
                </div>
                <div className="draft-review-big draft-money-win">
                  {fmt$(review.portfolio.fairValue)}
                </div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: "0.7rem" }}>
                  Portfolio ratio
                </div>
                <div
                  className="draft-review-big"
                  style={{
                    color:
                      review.portfolio.ratio > 1.05
                        ? "var(--green)"
                        : review.portfolio.ratio < 0.95
                          ? "var(--red)"
                          : "var(--cyan)",
                  }}
                >
                  {review.portfolio.ratio.toFixed(2)}×
                </div>
              </div>
              <div>
                <div className="muted" style={{ fontSize: "0.7rem" }}>
                  Delta
                </div>
                <div
                  className="draft-review-big"
                  style={{
                    color:
                      review.portfolio.delta > 0
                        ? "var(--green)"
                        : "var(--red)",
                  }}
                >
                  {review.portfolio.delta > 0 ? "+" : ""}
                  {fmt$(review.portfolio.delta)}
                </div>
              </div>
            </div>

            {/* Steal + overpay callouts */}
            {review.bestSteal && (
              <div className="draft-review-callout">
                <span className="draft-rec-chip draft-rec-lock">
                  BEST STEAL
                </span>
                <span>
                  <strong>{review.bestSteal.playerName}</strong> — paid{" "}
                  {fmt$(review.bestSteal.paid)}, fair{" "}
                  {fmt$(review.bestSteal.fair)}{" "}
                  <span className="draft-vs-fair-win">
                    (+{fmt$(review.bestSteal.valueVsFair)})
                  </span>
                </span>
              </div>
            )}
            {review.worstOverpay && review.worstOverpay.valueVsFair < 0 && (
              <div className="draft-review-callout">
                <span className="draft-rec-chip draft-rec-avoid">
                  WORST OVERPAY
                </span>
                <span>
                  <strong>{review.worstOverpay.playerName}</strong> — paid{" "}
                  {fmt$(review.worstOverpay.paid)}, fair{" "}
                  {fmt$(review.worstOverpay.fair)}{" "}
                  <span className="draft-vs-fair-lose">
                    ({fmt$(review.worstOverpay.valueVsFair)})
                  </span>
                </span>
              </div>
            )}

            {/* My picks table */}
            <h4 style={{ margin: "10px 0 4px" }}>
              My roster ({review.myPicks.length} picks)
            </h4>
            <div className="draft-review-table-wrap">
              <table className="draft-review-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Player</th>
                    <th>Tier</th>
                    <th style={{ textAlign: "right" }}>Paid</th>
                    <th style={{ textAlign: "right" }}>Fair</th>
                    <th style={{ textAlign: "right" }}>Δ</th>
                  </tr>
                </thead>
                <tbody>
                  {review.myPicks.map((r) => (
                    <tr key={r.playerId}>
                      <td>{r.playerName}</td>
                      <td>
                        <span
                          className={`draft-tier-chip draft-tier-${r.tier}`}
                        >
                          {r.tier}
                        </span>
                      </td>
                      <td className="draft-money">{fmt$(r.paid)}</td>
                      <td className="draft-money">{fmt$(r.fair)}</td>
                      <td
                        className={`draft-money ${
                          r.valueVsFair > 0
                            ? "draft-vs-fair-win"
                            : r.valueVsFair < 0
                              ? "draft-vs-fair-lose"
                              : ""
                        }`}
                      >
                        {r.valueVsFair > 0 ? "+" : ""}
                        {fmt$(r.valueVsFair)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* Per-team rankings */}
            <h4 style={{ margin: "14px 0 4px" }}>League draft efficiency</h4>
            <div className="draft-review-table-wrap">
              <table className="draft-review-table">
                <thead>
                  <tr>
                    <th style={{ textAlign: "left" }}>Team</th>
                    <th style={{ textAlign: "right" }}>Picks</th>
                    <th style={{ textAlign: "right" }}>Paid</th>
                    <th style={{ textAlign: "right" }}>Fair</th>
                    <th style={{ textAlign: "right" }}>Ratio</th>
                  </tr>
                </thead>
                <tbody>
                  {review.teamRankings.map((t, i) => (
                    <tr
                      key={t.idx}
                      className={t.isMine ? "draft-row-mine" : ""}
                    >
                      <td>
                        <span
                          className="muted"
                          style={{ fontSize: "0.7rem", marginRight: 4 }}
                        >
                          #{i + 1}
                        </span>
                        <strong>{t.name}</strong>
                        {t.isMine && (
                          <span
                            className="draft-tag draft-tag-mine"
                            style={{ marginLeft: 6, fontSize: "0.62rem" }}
                          >
                            mine
                          </span>
                        )}
                      </td>
                      <td className="draft-money">{t.count}</td>
                      <td className="draft-money">{fmt$(t.paid)}</td>
                      <td className="draft-money">{fmt$(t.fair)}</td>
                      <td
                        className="draft-money"
                        style={{
                          color:
                            t.ratio > 1.05
                              ? "var(--green)"
                              : t.ratio < 0.95
                                ? "var(--red)"
                                : "var(--cyan)",
                          fontWeight: 700,
                        }}
                      >
                        {t.ratio.toFixed(2)}×
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      <div className="draft-modal-footer">
        {review.rows.length > 0 && (
          <Button onClick={downloadCsv}>Export CSV</Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </div>
    </Modal>
  );
}

// ~360 lines of genuinely useful reference — every column defined,
// every recommendation level explained, the inflation model, the
// keyboard shortcuts.  It used to render as an <details open> at the
// bottom of the page, so every draft session ended in a wall of ten
// section headings below the board you were actually using.
//
// Same content, same ten collapsible sections, now behind a "How this
// dashboard works" button in the page header — where you look when you
// have a question, rather than permanently under the answer.
function DraftGlossary() {
  const Section = ({ title, children }) => (
    <details className="draft-gloss-section">
      <summary>{title}</summary>
      <div className="draft-gloss-body">{children}</div>
    </details>
  );
  return (
    <HelpModal title="How this draft dashboard works" label="How this works">
      <div className="draft-gloss-inner">

          <Section title="The rookie board, column by column">
            <p>
              Every undrafted rookie shows up on the main board with these
              live-updating numbers:
            </p>
            <ul>
              <li>
                <strong>#</strong> — your personal rank (the order you care
                about, inherited from the seed list; edit PreDraft $ to re-sort
                by dollar value).
              </li>
              <li>
                <strong>Tier</strong> — S (≥ $60 PreDraft) · A ($25–59) · B
                ($8–24) · C ($3–7) · D ($1–2). Tier scarcity drives the PUSH
                recommendation.
              </li>
              <li>
                <strong>Tag</strong> — click to cycle: neutral → ★ target → ⊘
                avoid → neutral. Drives the recommendation engine.
              </li>
              <li>
                <strong>Rec</strong> — LOCK / STEAL / PUSH / BUY / SPEND / AVOID
                / neutral. See the "Recommendation levels" section below.
              </li>
              <li>
                <strong>PreDraft $</strong> — your static projection (editable
                inline). Anchors every other number.
              </li>
              <li>
                <strong>Fair</strong> — PreDraft $ × inflation × tier heat. What
                the player is worth at this moment in the draft.
              </li>
              <li>
                <strong>Enforce</strong> — 80% of Fair by default. If a rival is
                bidding below this, push up to keep the market honest (drains
                their budget even if you don't ultimately win).
              </li>
              <li>
                <strong>Win at</strong> — lowest $ you'd actually need to lock
                the player. Capped at the top rival's remaining budget + $1.
                The headline number for bidding decisions.
              </li>
              <li>
                <strong>Max Bid</strong> — theoretical max if rivals forced your
                ceiling. Usually ≥ "Win at". Treat it as the hard stop.
              </li>
              <li>
                <strong>Final</strong> — what the player actually sold for (and
                green/red delta vs Fair once recorded).
              </li>
            </ul>
          </Section>

          <Section title="How prices adjust as the draft unfolds">
            <p>
              Two multipliers on top of PreDraft $ move "Fair" around. Both
              update after every pick you record.
            </p>
            <ul>
              <li>
                <strong>Global inflation</strong> = remaining league $ ÷ (total
                budget − sum of PreDraft $ already sold). Above 1.00× =
                remaining market is cheaper than projected; below = market got
                hot.
              </li>
              <li>
                <strong>Tier heat</strong> = total $ paid in tier ÷ total
                PreDraft $ of players sold in that tier. Blended with 1.00×
                under a sample-size confidence weight (3 picks in a tier = full
                trust). A hot S tier marks up remaining S players even if global
                inflation is flat.
              </li>
              <li>
                <strong>No phase multiplier.</strong> Max Bid used to be scaled
                by up to 1.5× as your six &quot;slots&quot; filled up. This
                league has no per-team rookie cap, so that term is gone. Budget
                advantage already carries the &quot;I&apos;m rich, bid up&quot;
                signal.
              </li>
            </ul>
          </Section>

          <Section title="Competitor ceiling (why 'Win at' is usually lower than Max Bid)">
            <p>
              In a real auction you only need to pay ONE dollar above the
              next-highest bidder. Knowing that ceiling saves real money:
            </p>
            <ul>
              <li>
                <strong>Effective budget</strong> per team = its remaining $.
                Nothing is held back: a team may spend everything on one rookie,
                because nothing obliges it to buy another.
              </li>
              <li>
                <strong>Top rival ceiling</strong> (shown in the stats strip) =
                max effective budget across all other teams. "Win at" = min(Max
                Bid, ceiling + $1).
              </li>
              <li>
                <strong>Bayesian ceiling</strong> — if you log nominations (see
                next section), each team's ceiling for a given tier decays based
                on how many players they've nominated in that tier. Lowers "Win
                at" below the naive ceiling when rivals have signalled
                disinterest.
              </li>
            </ul>
          </Section>

          <Section title="Recommendation levels">
            <p>
              Every undrafted player gets one label based on tag + market state.
              Labels update live; the tooltip on each chip explains the trigger.
            </p>
            <ul>
              <li>
                <strong className="draft-rec-chip draft-rec-lock">LOCK</strong>{" "}
                — target + rivals collapsed. Top rival can't afford past 30% of
                PreDraft $. Bid their ceiling + $1 and you own it.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-steal">
                  STEAL
                </strong>{" "}
                — same collapse, untagged player. Opportunistic grab at
                fire-sale prices.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-push">PUSH</strong>{" "}
                — target + tier drying up (&lt;30% of tier players remaining).
                Last shot; don't wait.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-buy">BUY</strong> —
                target, normal market. Bid to your Win-at number.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-spend">
                  SPEND
                </strong>{" "}
                — target, 60%+ of the board already drafted, and you still hold
                1.25× the average rival&apos;s money. Time to splash before $
                becomes unusable.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-avoid">
                  AVOID
                </strong>{" "}
                — you flagged them as ⊘.
              </li>
              <li>
                <strong className="draft-rec-chip draft-rec-neutral">
                  neutral
                </strong>{" "}
                — no strong signal.
              </li>
            </ul>
          </Section>

          <Section title="Target Board (top of page)">
            <p>
              Your explicit "these are my 6" short-list. Track whatever subset
              of your targets is most important for portfolio accounting — you
              can still have 20+ players tagged as targets overall.
            </p>
            <ul>
              <li>
                Each entry shows PreDraft $, live Fair, Win-at, and Paid (if you
                won them).
              </li>
              <li>
                <strong>Buffer</strong> = my remaining $ − sum of Win-at for
                undrafted targets. Nothing is reserved for further rookies,
                because nothing obliges you to draft any.
              </li>
              <li>
                <strong>On track (green)</strong>: buffer ≥ $10.{" "}
                <strong>Tight (cyan)</strong>: 0 ≤ buffer &lt; $10.{" "}
                <strong>Short (red)</strong>: buffer &lt; 0 — you can't afford
                your own list, trim or lower a ceiling.
              </li>
            </ul>
          </Section>

          <Section title="Teams & budgets panel">
            <ul>
              <li>
                <strong>Initial / Spent / Remaining</strong> — standard auction
                accounting. Initial is editable (Draft Capital pre-fills it).
              </li>
              <li>
                <strong>Rookies</strong> — how many rookies that team has
                bought so far. Informational: there is no cap on how many
                rookies a team may draft.
              </li>
              <li>
                <strong>Eff $</strong> — effective budget, i.e. remaining $ (see
                Competitor ceiling). Red when &lt; $5.
              </li>
              <li>
                <strong>Over%</strong> — (Σ paid − Σ PreDraft $ at pick time) ÷
                Σ PreDraft. Red &gt; +10% (overpayer), green &lt; −10% (value
                hunter). Shows who's chasing and likely to overpay again.
              </li>
            </ul>
          </Section>

          <Section title="Nominations + Bayesian inference (optional)">
            <p>
              Teams usually nominate players they DON'T want — either to drain
              rival budgets or to price-anchor a tier. Logging nominations makes
              this signal usable:
            </p>
            <ul>
              <li>
                In the draft modal for any undrafted player: "Who nominated this
                player?" → pick the team.
              </li>
              <li>
                Each nomination multiplies that team's tier interest by{" "}
                <strong>0.8</strong> (floor 0.2). After 3 S-tier noms: S
                interest ≈ 0.51.
              </li>
              <li>
                Bayesian top-competitor ceiling per player reweights each
                rival's effective budget by their tier interest for THAT
                player's tier. Lower ceiling → lower Win-at.
              </li>
              <li>
                Noms are optional — no nominations logged means the Bayesian
                ceiling collapses to the naive one. Log what you see; skip what
                you don't.
              </li>
            </ul>
          </Section>

          <Section title="Next Best Targets + Good to Nominate sidebars">
            <ul>
              <li>
                <strong>Next Best Targets</strong> — top 5 undrafted rookies by
                EV = max(0, Fair − Win-at) × tag weight + tier scarcity boost.
                Targets get a 1.5× tag weight; Avoid players are excluded.
              </li>
              <li>
                <strong>Good to Nominate</strong> — top 5 drain candidates.
                Score = min(Fair, top rival ceiling) × tag weight × (1 − risk of
                accidentally winning). Target-tagged players are NEVER in this
                list (never nominate your own targets).
              </li>
            </ul>
          </Section>

          <Section title="Inflation sparkline, progress bar, triage mode">
            <ul>
              <li>
                <strong>Sparkline</strong> (in the Inflation stat card) —
                inflation trajectory over picks. Dashed reference line at 1.00×;
                current value dot color-coded green (&gt; 1.03) / red (&lt;
                0.97) / muted.
              </li>
              <li>
                <strong>Progress bar</strong> (top of page) — picks recorded /
                the size of the rookie pool. Drives
                peripheral awareness of draft phase.
              </li>
              <li>
                <strong>Late-draft triage</strong> — when board progress crosses
                70%, the board auto-filters to your Targets and pops a banner.
                One-shot fire per session; dismiss restores the full view.
              </li>
            </ul>
          </Section>

          <Section title="Keyboard shortcuts">
            <p>Click any row to select it (cyan outline), then:</p>
            <ul>
              <li>
                <kbd>/</kbd> focus search · <kbd>?</kbd> open this help ·{" "}
                <kbd>Esc</kbd> close help
              </li>
              <li>
                <kbd>j</kbd>/<kbd>↓</kbd> next undrafted · <kbd>k</kbd>/
                <kbd>↑</kbd> previous
              </li>
              <li>
                <kbd>D</kbd> open draft modal · <kbd>N</kbd> cycle tag (neutral
                → target → avoid)
              </li>
              <li>
                <kbd>T</kbd> toggle target (never flips to avoid) · <kbd>B</kbd>{" "}
                add to Target Board
              </li>
            </ul>
            <p className="muted" style={{ fontSize: "0.72rem" }}>
              Shortcuts are suppressed while typing in any input / textarea /
              select, so name searches don't collide.
            </p>
          </Section>

          <Section title="Bid simulator (in the draft modal)">
            <p>
              Typing a team + amount in the draft modal previews the exact state
              after the pick lands — League $, My Remaining, BA, Inflation, Top
              Rival $, Rookies bought — with arrow deltas so you can see "this pick
              drops my BA from 5.85× to 3.24×" BEFORE committing.
            </p>
          </Section>

          <Section title="Data sources + persistence">
            <ul>
              <li>
                Team budgets + owned-pick counts auto-load from
                ``/api/draft-capital`` on first visit. Click "Load from Draft
                Capital" in the Teams panel to re-pull.
              </li>
              <li>
                Every edit (picks, tags, Target Board, nominations, knobs)
                persists to localStorage under ``next_draft_board_v1``. Refresh
                mid-draft and your state survives.
              </li>
              <li>
                Undo Last removes the newest pick; Reset wipes the whole
                workspace back to defaults.
              </li>
            </ul>
          </Section>

      </div>
    </HelpModal>
  );
}

export default function DraftDashboardPage() {
  const router = useRouter();
  const { authenticated, checking } = useAuthContext();
  // Only for the value-basis disclosure. The draft board prices off
  // /api/draft-capital and its own workspace, but the player values it
  // shows alongside come from the same contract every other page reads,
  // so the same lens applies and the same silence applied here too.
  const { rawData } = useApp();
  // League-scoped draft workspace — a draft-in-progress lives per
  // league, keyed by ``DRAFT_STORAGE_KEY__<leagueKey>``.  Switching
  // leagues mid-draft doesn't destroy the prior league's board.
  // Falls back to the legacy unsuffixed key when no league is
  // resolved yet (cold boot) so pre-migration state still hydrates.
  const { selectedLeagueKey } = useLeague();
  const draftStorageKey = useMemo(
    () =>
      selectedLeagueKey
        ? `${DRAFT_STORAGE_KEY}__${selectedLeagueKey}`
        : DRAFT_STORAGE_KEY,
    [selectedLeagueKey],
  );

  const [workspace, setWorkspace] = useState(() => createDefaultWorkspace());
  // Live vendor-dollar map keyed by lowercase name, sourced directly
  // from /api/draft-capital.  Mirrors what the auto-sync writes onto
  // the workspace, but is independent of workspace state so the
  // Market column always shows current values even if the workspace
  // hydrates from stale localStorage before the auto-sync writes back.
  const [marketDollars, setMarketDollars] = useState({
    ktc: new Map(),
    idp: new Map(),
  });
  const [hydrated, setHydrated] = useState(false);
  const [modalPlayer, setModalPlayer] = useState(null);
  const [showDrafted, setShowDrafted] = useState(false);
  const [query, setQuery] = useState("");
  const [tagFilter, setTagFilter] = useState("all"); // all | target | avoid | untagged
  // BDVM fundamental values — optional flag-gated enrichment, same
  // posture as the rankings gap column: the Fund gap column and the
  // pick-value panel exist only while /api/bdvm/values answers ok and
  // vanish silently on any 503 (flag off, no snapshot, wrong league).
  const { data: bdvmData, failure: bdvmFailure } =
    useBdvmEndpoint("/api/bdvm/values");
  const bdvmIndex = useMemo(
    () =>
      !bdvmFailure && bdvmData?.status === "ok"
        ? buildBdvmIndex(bdvmData)
        : null,
    [bdvmData, bdvmFailure],
  );
  const bdvmPickRows = useMemo(
    () =>
      !bdvmFailure && bdvmData?.status === "ok"
        ? buildBdvmPickRows(bdvmData, "balanced")
        : [],
    [bdvmData, bdvmFailure],
  );
  // Late-draft triage mode: when board progress crosses 0.7, auto-
  // flip the board filter to "Targets" so I see only the players I
  // still want.  Tracked so a user who manually changes the filter
  // AFTER auto-switch isn't fought by the effect every re-render.
  const [triageApplied, setTriageApplied] = useState(false);
  const [triageDismissed, setTriageDismissed] = useState(false);
  const searchInputRef = useRef(null);
  const [selectedPlayerId, setSelectedPlayerId] = useState(null);
  const [helpOpen, setHelpOpen] = useState(false);
  const [reviewOpen, setReviewOpen] = useState(false);
  const [syncOpen, setSyncOpen] = useState(false);
  const [syncBusy, setSyncBusy] = useState(false);
  const [syncError, setSyncError] = useState("");
  const [syncPreview, setSyncPreview] = useState(null);
  const [quickRecordingId, setQuickRecordingId] = useState(null);
  // Alert layer state — ephemeral, not persisted.
  const [alerts, setAlerts] = useState([]);
  const previousStatsRef = useRef(null);
  const seenAlertsRef = useRef(new Set());
  // Roster gap awareness — the user's current Sleeper roster + an
  // ``allPlayersArray`` (from /api/data) so we can look up positions.
  const [rosterPlayers, setRosterPlayers] = useState(null);
  const [allPlayersArray, setAllPlayersArray] = useState(null);
  // Sleeper teams for live-draft team mapping — Sleeper picks come
  // back with ``ownerId``/``rosterId``; we resolve those to a
  // workspace.teams idx via name-match against this list.
  const [sleeperTeams, setSleeperTeams] = useState(null);
  // Per-league localStorage flag — survives ``Reset`` (which wipes
  // workspace) but stays scoped so toggling sync on the rookie draft
  // doesn't bleed into the startup draft.  Defaults OFF; the user
  // opts in via the toggle.
  const liveSyncStorageKey = useMemo(
    () => `next_draft_live_sync__${selectedLeagueKey || "default"}`,
    [selectedLeagueKey],
  );
  const [liveSyncEnabled, setLiveSyncEnabledState] = useState(false);
  useEffect(() => {
    try {
      const raw = localStorage.getItem(liveSyncStorageKey);
      setLiveSyncEnabledState(raw === "1");
    } catch {
      setLiveSyncEnabledState(false);
    }
  }, [liveSyncStorageKey]);
  const setLiveSyncEnabled = useCallback(
    (v) => {
      setLiveSyncEnabledState(v);
      try {
        localStorage.setItem(liveSyncStorageKey, v ? "1" : "0");
      } catch {
        /* ignore */
      }
    },
    [liveSyncStorageKey],
  );
  const [capitalStatus, setCapitalStatus] = useState({
    loading: false,
    error: "",
    info: "",
    source: null, // { season, totalBudget, fetchedAt }
  });

  // Gate on auth: unauthenticated users bounce to /login with a return path.
  useEffect(() => {
    if (checking) return;
    if (authenticated === false) {
      router.push("/login?next=/draft");
    }
  }, [checking, authenticated, router]);

  // Hydrate workspace from localStorage when the active league
  // changes (or on mount).  Reads the league-scoped key first and
  // falls back to the legacy unsuffixed key — migration path so
  // pre-multi-league state carries over into the default league's
  // placeholder on the first load.
  useEffect(() => {
    setHydrated(false);
    try {
      let raw = localStorage.getItem(draftStorageKey);
      if (!raw && draftStorageKey !== DRAFT_STORAGE_KEY) {
        // Legacy fallback: user had a workspace saved pre-migration
        // under the unsuffixed key.  Adopt it as the current league's
        // workspace.  Next persist write will land at the scoped key.
        raw = localStorage.getItem(DRAFT_STORAGE_KEY);
      }
      if (raw) {
        const parsed = JSON.parse(raw);
        setWorkspace(hydrateWorkspace(parsed));
      } else {
        setWorkspace(createDefaultWorkspace());
      }
    } catch {
      /* ignore */
    }
    setHydrated(true);
  }, [draftStorageKey]);

  // Persist on every change.
  useEffect(() => {
    if (!hydrated) return;
    try {
      localStorage.setItem(draftStorageKey, JSON.stringify(workspace));
    } catch {
      /* ignore */
    }
  }, [workspace, hydrated, draftStorageKey]);

  // Auto-sync the rookie pool from /api/draft-capital on every page
  // load.  The server's per-pick payload now carries every field the
  // workspace needs (rookieName, rookiePos, rookieKtcValue → preDraft,
  // rookieKtcDollar, rookieIdpDollar) all on the same $1200 scale
  // derived from the sheet's Hill-curve formula applied to OUR /
  // KTC / IDPTradeCalc values respectively.  Calling
  // ``replacePlayerPool`` swaps the player array in one shot while
  // preserving user tags, target board, and recorded picks (which
  // are matched by name-derived id).  Runs once after hydration; the
  // manual "Sync from contract" button is still available for
  // mid-session refreshes.
  const autoSyncRanRef = useRef(false);
  useEffect(() => {
    if (!hydrated || autoSyncRanRef.current) return;
    autoSyncRanRef.current = true;
    let cancelled = false;
    (async () => {
      try {
        const capitalRes = await fetch("/api/draft-capital", {
          cache: "no-store",
        });
        if (!capitalRes.ok) return;
        if (cancelled) return;
        const capitalData = await capitalRes.json();
        const picks = Array.isArray(capitalData?.picks)
          ? capitalData.picks
          : [];
        if (picks.length === 0) return;

        const sortedPicks = [...picks].sort(
          (a, b) => (a?.overallPick || 0) - (b?.overallPick || 0),
        );
        const incoming = [];
        const ktcMap = new Map();
        const idpMap = new Map();
        for (const pk of sortedPicks) {
          if (!pk?.rookieName) continue;
          const preDraft = Number(pk.rookieKtcValue);
          if (!Number.isFinite(preDraft) || preDraft <= 0) continue;
          const nameLc = String(pk.rookieName).toLowerCase();
          const ktc = Number(pk.rookieKtcDollar);
          const idp = Number(pk.rookieIdpDollar);
          if (Number.isFinite(ktc) && ktc > 0) ktcMap.set(nameLc, ktc);
          if (Number.isFinite(idp) && idp > 0) idpMap.set(nameLc, idp);
          // ``rookieBoardValue`` is the raw 0-9999 board value the $
          // ladder was derived from.  Perfect Draft needs it because net
          // roster value is measured against a displaced player in value
          // units, and the $ ladder is not convertible back.
          const boardValue = Number(pk.rookieBoardValue);
          incoming.push({
            name: String(pk.rookieName),
            preDraft,
            pos: String(pk.rookiePos || "").toUpperCase() || undefined,
            ktcDollar: Number.isFinite(ktc) && ktc > 0 ? ktc : null,
            idpTradeCalcDollar: Number.isFinite(idp) && idp > 0 ? idp : null,
            boardValue:
              Number.isFinite(boardValue) && boardValue > 0 ? boardValue : null,
          });
        }
        // Publish the vendor-dollar map immediately so the Market
        // column has data even before the workspace replace lands.
        if (!cancelled && (ktcMap.size > 0 || idpMap.size > 0)) {
          setMarketDollars({ ktc: ktcMap, idp: idpMap });
        }
        if (incoming.length === 0) return;

        if (cancelled) return;
        setWorkspace((ws) => {
          if (!ws) return ws;
          // Skip re-render if the incoming pool exactly matches what's
          // already in the workspace (same names, same preDraft, same
          // vendor dollars).  Avoids a needless write to localStorage
          // when nothing changed between page loads.
          const existing = Array.isArray(ws.players) ? ws.players : [];
          const sameLength = existing.length === incoming.length;
          const allMatch =
            sameLength &&
            existing.every((p, i) => {
              const inc = incoming[i];
              return (
                p.name === inc.name &&
                Number(p.preDraft) === Number(inc.preDraft) &&
                Number(p.ktcDollar ?? null) === Number(inc.ktcDollar ?? null) &&
                Number(p.idpTradeCalcDollar ?? null) ===
                  Number(inc.idpTradeCalcDollar ?? null)
              );
            });
          if (allMatch) return ws;
          const { workspace: next } = replacePlayerPool(ws, incoming);
          return next;
        });
      } catch {
        /* network blip — user can still hit "Sync from contract" manually */
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [hydrated]);

  const stats = useMemo(() => computeDraftStats(workspace), [workspace]);
  // Retrospective inflation trajectory — O(N²) in pick count, but
  // N caps at ~72 so negligible.  Feeds the sparkline in the stats
  // strip and any future "how did we get here" retrospectives.
  const historySeries = useMemo(
    () => computeHistorySeries(workspace),
    [workspace],
  );

  // Roster gap: breakdown of the user's current Sleeper NFL roster
  // into positional counts.  ``needPositions`` flags positions below
  // the per-position minimum so target/rec UI can render a NEED chip.
  const rosterBreakdown = useMemo(
    () => computeRosterBreakdown(rosterPlayers || [], allPlayersArray || []),
    [rosterPlayers, allPlayersArray],
  );
  const needSet = useMemo(
    () => new Set(rosterBreakdown.needPositions),
    [rosterBreakdown.needPositions],
  );

  // Alert layer — detect threshold crossings between stat snapshots
  // and push one-shot alerts.  ``seenAlertsRef`` dedupes per event
  // key; ``previousStatsRef`` carries the prior snapshot so we can
  // compare.  Alerts persist in component state until dismissed (or
  // until an auto-fade we may add later).  Keep the effect cheap —
  // it runs on every stats change.
  useEffect(() => {
    const prev = previousStatsRef.current;
    const cur = stats;
    if (!prev) {
      previousStatsRef.current = cur;
      return;
    }

    const seen = seenAlertsRef.current;
    const push = (id, message, level = "info") => {
      if (seen.has(id)) return null;
      seen.add(id);
      return { id, message, level, ts: Date.now() };
    };
    const newAlerts = [];

    // 1. Tier drying up: remainingRatio just crossed below 0.3.
    for (const [tierKey, tierData] of Object.entries(cur.tierStats || {})) {
      const prevTier = prev.tierStats?.[tierKey];
      if (!prevTier) continue;
      if (
        prevTier.remainingRatio >= 0.3 &&
        tierData.remainingRatio < 0.3 &&
        tierData.remaining > 0
      ) {
        const myInTier = cur.enrichedPlayers.filter(
          (p) => !p.drafted && p.userTag === TAG_TARGET && p.tier === tierKey,
        );
        const suffix =
          myInTier.length > 0
            ? ` — ${myInTier.length} of yours still in: ${myInTier
                .map((p) => p.name)
                .slice(0, 3)
                .join(", ")}`
            : "";
        const alert = push(
          `tier-scarcity-${tierKey}`,
          `Tier ${tierKey} drying up — ${tierData.remaining} of ${tierData.total} left${suffix}`,
          myInTier.length > 0 ? "warn" : "info",
        );
        if (alert) newAlerts.push(alert);
      }
    }

    // 2. Overpay on the most recent pick (≥40% over preDraft, with a
    // $10 floor so $1 throw-ins don't trigger "overpay" alerts).
    if (cur.totalPicksMade > prev.totalPicksMade) {
      const sorted = [...(workspace.picks || [])].sort(
        (a, b) => (b.ts || 0) - (a.ts || 0),
      );
      const newest = sorted[0];
      if (newest) {
        const preDraft = Math.max(0, Number(newest.preDraftAtPick) || 0);
        const paid = Math.max(0, Number(newest.amount) || 0);
        const delta = paid - preDraft;
        if (preDraft >= 10 && delta >= preDraft * 0.4) {
          const player = cur.enrichedPlayers.find(
            (p) => p.id === newest.playerId,
          );
          const teamName =
            cur.teamStats[newest.teamIdx]?.name || `Team ${newest.teamIdx + 1}`;
          const alert = push(
            `overpay-${newest.playerId}`,
            `${player?.name || newest.playerId} went to ${teamName} for $${paid} (+$${delta} over fair) — ${player?.tier || "?"} tier heating up`,
            "warn",
          );
          if (alert) newAlerts.push(alert);
        }
      }
    }

    // 3. Target Board buffer crossed below zero.
    const prevBuf = prev.targetBoardStats?.portfolioBuffer ?? 0;
    const curBuf = cur.targetBoardStats?.portfolioBuffer ?? 0;
    if (prevBuf >= 0 && curBuf < 0) {
      const alert = push(
        `tb-short-${cur.totalPicksMade}`,
        `Target Board buffer dropped to $${Math.round(curBuf)} — trim a target or lower a ceiling`,
        "danger",
      );
      if (alert) newAlerts.push(alert);
    }

    // 4. Win-at just dropped substantially on an undrafted target.
    const prevById = new Map(prev.enrichedPlayers.map((p) => [p.id, p]));
    for (const cp of cur.enrichedPlayers) {
      if (cp.drafted) continue;
      if (cp.userTag !== TAG_TARGET) continue;
      const pp = prevById.get(cp.id);
      if (!pp || pp.drafted) continue;
      const drop = pp.myWinningBid - cp.myWinningBid;
      if (drop >= 10 && drop >= pp.myWinningBid * 0.25) {
        const alert = push(
          `winbid-drop-${cp.id}-${cp.myWinningBid}`,
          `${cp.name} Win-at dropped $${pp.myWinningBid} → $${cp.myWinningBid}`,
          "info",
        );
        if (alert) newAlerts.push(alert);
      }
    }

    if (newAlerts.length > 0) {
      setAlerts((prior) => [...prior, ...newAlerts]);
    }
    previousStatsRef.current = cur;
  }, [stats, workspace.picks]);

  const dismissAlert = useCallback(
    (id) => setAlerts((as) => as.filter((a) => a.id !== id)),
    [],
  );
  const clearAllAlerts = useCallback(() => setAlerts([]), []);

  // Late-draft triage: when board progress crosses 0.7, auto-flip
  // the tag filter to "target" so only players I still want appear
  // on the board.  Only fires ONCE (via triageApplied) so a user
  // who manually changes the filter after the flip isn't fought by
  // the effect.  triageDismissed lets the user opt out explicitly.
  const LATE_DRAFT_THRESHOLD = 0.7;
  useEffect(() => {
    if (triageApplied || triageDismissed) return;
    if ((stats.draftProgress || 0) >= LATE_DRAFT_THRESHOLD) {
      setTagFilter("target");
      setTriageApplied(true);
    }
  }, [stats.draftProgress, triageApplied, triageDismissed]);

  // Pull per-team auction $ budgets from /api/draft-capital.  The
  // dashboard needs this to mirror real carry-over balances without
  // forcing the user to re-enter every team's budget by hand.  When
  // ``quiet`` is true we don't flash a status banner on success —
  // used for the silent auto-populate on first page load.
  const fetchDraftCapital = useCallback(
    async ({ quiet = false, force = false } = {}) => {
      setCapitalStatus((s) => ({ ...s, loading: true, error: "", info: "" }));
      try {
        // Scope the draft-capital fetch to the active league so
        // per-team auction budgets come from the right Sleeper
        // league.  Backend validates + 503s with a clean error
        // when the requested league's data isn't loaded.
        const url = selectedLeagueKey
          ? `/api/draft-capital?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
          : "/api/draft-capital";
        const res = await fetch(url, { cache: "no-store" });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const data = await res.json();
        if (data?.error) throw new Error(data.error);
        const teamTotals = Array.isArray(data?.teamTotals)
          ? data.teamTotals
          : [];
        if (teamTotals.length === 0) {
          throw new Error("Draft capital feed had no team totals.");
        }
        // Raw picks array — retained for callers; no longer used to
        // derive a per-team rookie cap (there isn't one).  Per-team slot
        // counts (how many rookie picks each team currently owns).
        // Feeds into the slot-adjusted effectiveBudget calculation
        // so MaxBid / WinningBid reflect real opponent bidding power.
        const picksArray = Array.isArray(data?.picks) ? data.picks : [];

        setWorkspace((ws) => {
          // Force = "Load from Draft Capital" button: overwrite every
          // row unconditionally.  Sync = auto-refresh: only rewrite
          // rows the user hasn't manually edited (feedBudget !==
          // initialBudget flags a manual override, which we preserve).
          const {
            workspace: next,
            matched,
            added,
          } = mergeDraftCapitalTeams(ws, teamTotals, {
            picks: picksArray,
            mode: force ? "force" : "sync",
          });
          if (!quiet) {
            setCapitalStatus((s) => ({
              ...s,
              info: `Loaded ${matched} team budgets${
                added > 0 ? ` (${added} new)` : ""
              }${picksArray.length > 0 ? ` · ${picksArray.length} picks tracked` : ""}.`,
            }));
          }
          return next;
        });

        setCapitalStatus((s) => ({
          ...s,
          loading: false,
          source: {
            season: data.season,
            totalBudget: data.totalBudget,
            fetchedAt: new Date().toISOString(),
          },
        }));
      } catch (err) {
        setCapitalStatus((s) => ({
          ...s,
          loading: false,
          error: err?.message || "Failed to load draft capital.",
        }));
      }
    },
    [selectedLeagueKey],
  );

  // Auto-sync team budgets from the live Draft Capital feed on every
  // page mount.  Runs in "sync" mode so rows the user has manually
  // edited (initialBudget !== feedBudget) are preserved; all other
  // rows snap to the latest feed.  "Load from Draft Capital" still
  // exists for a hard reset that overwrites every row.
  useEffect(() => {
    if (!hydrated || authenticated !== true) return;
    fetchDraftCapital({ quiet: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hydrated, authenticated]);

  // Auto-fetch the Sleeper teams list on mount.  Independent of the
  // manual "Sync rookies" path (which also reads /api/data) so the
  // live-sync hook can resolve picks to workspace team idx as soon
  // as the toggle flips on — no extra click required.  Each live pick
  // also arrives pre-stamped with ``playerName`` server-side, so we
  // don't need playersArray here.
  useEffect(() => {
    if (!hydrated || authenticated !== true) return;
    // Reset to null at the start of every league-key fetch.  The
    // live-sync handler keys its readiness gate off "sleeperTeams !==
    // null", so leaving the old league's array in state during a
    // switch would treat the new league's incoming picks as if the
    // team map were ready (against stale data) and silently drop
    // them.
    setSleeperTeams(null);
    let cancelled = false;
    const url = selectedLeagueKey
      ? `/api/data?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
      : "/api/data";
    fetch(url, { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled || !data) return;
        const teams = data?.sleeper?.teams || [];
        setSleeperTeams(teams);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [hydrated, authenticated, selectedLeagueKey]);

  const onSettings = useCallback(
    (patch) => setWorkspace((ws) => updateSettings(ws, patch)),
    [],
  );
  const onTeam = useCallback(
    (idx, patch) => setWorkspace((ws) => updateTeam(ws, idx, patch)),
    [],
  );
  const onEditPreDraft = useCallback(
    (id, v) => setWorkspace((ws) => updatePlayerPreDraft(ws, id, v)),
    [],
  );
  const onAdd = useCallback((p) => setWorkspace((ws) => addPlayer(ws, p)), []);
  const onRemovePlayer = useCallback(
    (id) => setWorkspace((ws) => removePlayer(ws, id)),
    [],
  );
  const onCycleTag = useCallback(
    (id) =>
      setWorkspace((ws) => {
        const current = ws.tags?.[id] || null;
        return setPlayerTag(ws, id, cycleTag(current));
      }),
    [],
  );
  const onToggleTarget = useCallback(
    (id) =>
      setWorkspace((ws) => {
        const current = ws.tags?.[id] || null;
        // Toggle: target ↔ neutral (never flips to avoid via T key).
        return setPlayerTag(ws, id, current === TAG_TARGET ? null : TAG_TARGET);
      }),
    [],
  );
  const onAddToBoard = useCallback(
    (id) => setWorkspace((ws) => addToTargetBoard(ws, id)),
    [],
  );
  const onRemoveFromBoard = useCallback(
    (id) => setWorkspace((ws) => removeFromTargetBoard(ws, id)),
    [],
  );
  const onMoveInBoard = useCallback(
    (id, direction) =>
      setWorkspace((ws) => moveTargetInBoard(ws, id, direction)),
    [],
  );
  const onClearBoard = useCallback(
    () => setWorkspace((ws) => clearTargetBoard(ws)),
    [],
  );
  const onAddToParSheet = useCallback(
    ({ name, fairValue }) =>
      setWorkspace((ws) => addToParSheet(ws, { name, fairValue })),
    [],
  );
  const onRemoveFromParSheet = useCallback(
    (id) => setWorkspace((ws) => removeFromParSheet(ws, id)),
    [],
  );
  const onEditParSheetFV = useCallback(
    (id, fairValue) =>
      setWorkspace((ws) => updateParSheetFairValue(ws, id, fairValue)),
    [],
  );
  const onMoveInParSheet = useCallback(
    (id, direction) => setWorkspace((ws) => moveInParSheet(ws, id, direction)),
    [],
  );
  const onClearParSheet = useCallback(
    () => setWorkspace((ws) => clearParSheet(ws)),
    [],
  );
  const onRecordNomination = useCallback(
    (playerId, nominatingTeamIdx) =>
      setWorkspace((ws) =>
        recordNomination(ws, {
          playerId,
          nominatingTeamIdx: Number(nominatingTeamIdx),
        }),
      ),
    [],
  );
  const onRemoveNomination = useCallback(
    (playerId) => setWorkspace((ws) => removeNomination(ws, playerId)),
    [],
  );
  const onUndoLastNomination = useCallback(
    () => setWorkspace((ws) => undoLastNomination(ws)),
    [],
  );

  // Quick-record: fast inline pick-recording on the selected row.
  // Takes a team idx + amount, applies recordPick, closes the form.
  // Separate from the full draft-modal submit path so the UI can
  // render a compact inline form without the modal overhead.
  const recordQuickPick = useCallback((playerId, teamIdx, amount) => {
    if (!playerId) return;
    const amt = Math.max(0, Number(amount) || 0);
    if (amt <= 0) return;
    setWorkspace((ws) =>
      recordPick(ws, {
        playerId,
        teamIdx: Number(teamIdx),
        amount: amt,
      }),
    );
    setQuickRecordingId(null);
  }, []);

  // Live Sleeper auction sync: a pick arrives from the polling hook
  // and we auto-record it on the workspace.  Resolves Sleeper
  // ownerId → workspace teamIdx via name-match against ``sleeperTeams``
  // (built from the /api/data sleeper.teams block, which carries the
  // same display names the workspace teams were merged from).
  // Conflicts (a manual entry that disagrees with the live feed) are
  // overwritten silently when amount + team match, or pushed to the
  // alert stack with a descriptive message when they don't — letting
  // the user hit "↶ Undo last" if Sleeper is wrong.
  const teamLookupRef = useRef({ byOwner: new Map(), byRoster: new Map() });
  useEffect(() => {
    teamLookupRef.current = buildTeamIndexLookup(
      workspace?.teams || [],
      sleeperTeams || [],
    );
  }, [workspace?.teams, sleeperTeams]);
  // ``sleeperTeams === null`` means the /api/data fetch is still in
  // flight; an empty array means it loaded and the league has no
  // Sleeper roster data.  The handler distinguishes "not yet" (retry)
  // from "really empty" (skip + alert) via this ref.  Strict tracking
  // (always set, never one-way) so a league switch correctly flips
  // it back to false until the new league's fetch resolves.
  const sleeperTeamsLoadedRef = useRef(false);
  useEffect(() => {
    sleeperTeamsLoadedRef.current = sleeperTeams !== null;
  }, [sleeperTeams]);

  const handleLivePick = useCallback((pick) => {
    if (!pick) return true;
    // Transient: the sleeper.teams fetch hasn't resolved yet on
    // first load.  Return false so the hook holds the cursor and
    // re-delivers this pick on the next poll.  Without this guard
    // a pick that lands during initial hydration would be silently
    // dropped because the owner-id lookup is empty.
    if (!sleeperTeamsLoadedRef.current) return false;

    const playerName = String(pick.playerName || "").trim();
    const sleeperPlayerId = String(pick.playerId || "");
    const amount = Math.max(0, Number(pick.amount) || 0);

    // Resolve team idx: prefer ownerId (the human winner); fall
    // back to rosterId (covers commish picks / co-managers where
    // picked_by may be blank).
    const lookup = teamLookupRef.current || {};
    let teamIdx = null;
    const ownerId = String(pick.ownerId || "");
    if (ownerId && lookup.byOwner?.has(ownerId)) {
      teamIdx = lookup.byOwner.get(ownerId);
    } else if (lookup.byRoster && Number.isFinite(Number(pick.rosterId))) {
      const ri = Number(pick.rosterId);
      if (lookup.byRoster.has(ri)) teamIdx = lookup.byRoster.get(ri);
    }

    if (!Number.isInteger(teamIdx)) {
      // No team match — push an alert so the user knows a pick
      // landed they need to record manually.
      const msg = playerName
        ? `Live pick ${playerName} for $${amount}: couldn't map Sleeper team — record manually`
        : `Live pick (Sleeper id ${sleeperPlayerId}) for $${amount}: couldn't map Sleeper team — record manually`;
      setAlerts((prior) => [
        ...prior,
        {
          id: `live-unmapped-${pick.pickNo}`,
          message: msg,
          level: "warn",
          ts: Date.now(),
        },
      ]);
      return true;
    }

    // Resolve workspace player: match by name slug.  If the player
    // isn't in the workspace pool, surface an alert so the user
    // knows they need a "Sync rookies" or to add the player.
    const slug = playerName ? playerSlug(playerName) : "";
    setWorkspace((ws) => {
      const players = Array.isArray(ws?.players) ? ws.players : [];
      const row = slug ? players.find((p) => p.id === slug) : null;
      if (!row) {
        setAlerts((prior) => [
          ...prior,
          {
            id: `live-unknown-${pick.pickNo}`,
            message: playerName
              ? `Live pick ${playerName} for $${amount} — not in rookie pool; click "Sync rookies"`
              : `Live pick (Sleeper id ${sleeperPlayerId}) for $${amount} — player not in pool`,
            level: "warn",
            ts: Date.now(),
          },
        ]);
        return ws;
      }
      // Conflict detection: existing pick with different amount or
      // team idx.  Keep recordPick's de-dupe (Sleeper wins) and
      // push a banner so the user can sanity-check + undo if needed.
      const existing = (ws.picks || []).find((p) => p.playerId === row.id);
      const conflict =
        existing &&
        (existing.teamIdx !== teamIdx ||
          Math.abs((existing.amount || 0) - amount) > 0);
      if (conflict) {
        const prevTeamName =
          ws.teams?.[existing.teamIdx]?.name || `Team ${existing.teamIdx + 1}`;
        const newTeamName = ws.teams?.[teamIdx]?.name || `Team ${teamIdx + 1}`;
        setAlerts((prior) => [
          ...prior,
          {
            id: `live-conflict-${pick.pickNo}-${row.id}`,
            message: `Live sync corrected ${row.name}: $${existing.amount} → $${amount}${
              existing.teamIdx !== teamIdx
                ? ` · ${prevTeamName} → ${newTeamName}`
                : ""
            } — hit ↶ Undo last to revert`,
            level: "warn",
            ts: Date.now(),
          },
        ]);
      }
      return recordPick(ws, {
        playerId: row.id,
        teamIdx,
        amount,
      });
    });
    return true;
  }, []);

  const liveSync = useSleeperDraftSync({
    leagueKey: selectedLeagueKey,
    enabled: liveSyncEnabled && hydrated && authenticated === true,
    onPickArrived: handleLivePick,
  });

  // Pre-draft sync: fetch /api/data, shape rookies, show a preview
  // modal.  User confirms → replacePlayerPool applies; cancels →
  // workspace is untouched.  Rescales to $1200 so the column sum
  // stays close to the league budget even when the source values
  // are on a different scale.
  const fetchSyncPreview = useCallback(async () => {
    setSyncBusy(true);
    setSyncError("");
    try {
      // Pass leagueKey so the backend serves the right league's
      // sleeper block and 503s cleanly when the requested league
      // isn't loaded yet.
      const url = selectedLeagueKey
        ? `/api/data?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
        : "/api/data";
      // Fetch /api/data and /api/draft-capital in parallel — the
      // draft-capital response carries per-slot dollar values from
      // the workbook, which we use as each rookie's preDraft (the
      // consensus 1.01 rookie inherits pick 1.01's dollar value, etc.)
      // instead of rescaling raw blended values across the top 72.
      const [res, capitalRes] = await Promise.all([
        fetch(url, { cache: "no-store" }),
        fetch("/api/draft-capital", { cache: "no-store" }).catch(() => null),
      ]);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      // capitalRes can be null (network failure) or a non-ok response
      // — fall back to the rescale path in either case so sync still
      // works when the workbook isn't available.
      const capitalData =
        capitalRes && capitalRes.ok ? await capitalRes.json() : null;
      // Prefer the contract's ``playersArray`` (full view).  Fall
      // back to the legacy ``players`` dict — the runtime view
      // (``view=app``) strips playersArray but keeps the dict, and
      // some deploy paths cache that view as the default.  Both
      // shapes carry the same per-row fields (``rookie``,
      // ``assetClass``, ``canonicalSiteValues``, ``values``).
      let pa = Array.isArray(data?.playersArray) ? data.playersArray : [];
      if (
        pa.length === 0 &&
        data?.players &&
        typeof data.players === "object"
      ) {
        pa = Object.values(data.players);
      }
      setAllPlayersArray(pa);

      // Rookies only, sorted by consensus value (values.full) desc.
      // Also capture per-source vendor values so the
      // ``nominationCandidates`` ranker can compute vendor-vs-our-board
      // discrepancies (the gap drives the "good to nominate" list —
      // biggest overrates first).  KTC for offense, IDPTradeCalc for
      // IDP, on the same 0-9999 scale.
      // The raw contract stamps the blended value as ``values.overall``
      // and ``rankDerivedValue``; the synthetic ``values.full`` is only
      // added downstream by ``buildRows`` in dynasty-data.js, so the
      // sync (which reads /api/data directly) must consult the real
      // contract fields.  Falling back through the chain
      // values.overall → rankDerivedValue → values.displayValue keeps
      // the sync resilient to either field renames or sparse rows.
      const readBlendedValue = (p) => {
        const candidates = [
          p?.values?.overall,
          p?.rankDerivedValue,
          p?.values?.displayValue,
          p?.values?.finalAdjusted,
          p?.values?.full,
        ];
        for (const v of candidates) {
          const n = Number(v);
          if (Number.isFinite(n) && n > 0) return n;
        }
        return 0;
      };
      // Server-side rookie pool (preferred): the /api/draft-capital
      // picks array now carries ``rookieName`` + ``rookieKtcValue``
      // (our preDraft \$) + ``rookieKtcDollar`` + ``rookieIdpDollar``,
      // sourced from latest_contract_data.playersArray sorted by
      // ``rankDerivedValue`` and filtered to has-Sleeper-ID.  Using
      // it directly keeps a single source of truth for the rookie
      // pool and matches what the rookie panel on /draft renders.
      const serverPool = (() => {
        const picks = Array.isArray(capitalData?.picks)
          ? capitalData.picks
          : [];
        if (picks.length === 0) return null;
        const sorted = [...picks].sort(
          (a, b) => (a?.overallPick || 0) - (b?.overallPick || 0),
        );
        const out = [];
        for (const pk of sorted) {
          if (!pk?.rookieName) continue;
          const dollar = Number(pk.rookieKtcValue);
          if (!Number.isFinite(dollar) || dollar <= 0) continue;
          out.push({
            name: String(pk.rookieName),
            preDraft: dollar,
            pos: String(pk.rookiePos || "").toUpperCase() || null,
            ktcDollar: Number.isFinite(Number(pk.rookieKtcDollar))
              ? Number(pk.rookieKtcDollar)
              : null,
            idpTradeCalcDollar: Number.isFinite(Number(pk.rookieIdpDollar))
              ? Number(pk.rookieIdpDollar)
              : null,
            boardValue: Number.isFinite(Number(pk.rookieBoardValue))
              ? Number(pk.rookieBoardValue)
              : null,
          });
        }
        return out.length > 0 ? out : null;
      })();

      const rookies = serverPool
        ? serverPool.map((r) => ({
            name: r.name,
            rawValue: r.preDraft,
            // The server has already converted KTC/IDPTC raw values
            // to dollars via the same Hill formula; pass them through.
            ktcRawValue: null,
            idpTradeCalcRawValue: null,
            pos: r.pos,
            assetClass: null,
            preDraftFromServer: r.preDraft,
            ktcDollarFromServer: r.ktcDollar,
            idpTradeCalcDollarFromServer: r.idpTradeCalcDollar,
          }))
        : pa
            .filter((p) => p?.rookie === true)
            .filter(
              (p) => p?.assetClass === "offense" || p?.assetClass === "idp",
            )
            .map((p) => ({
              name: p.displayName || p.canonicalName || "",
              rawValue: readBlendedValue(p),
              // KTC TE++ is the canonical KTC retail signal (per the
              // 2026-04-28 registry change in #393).  Prefer the raw
              // scrape from ``rawSourceValues.ktcSfTep`` so rookie
              // dollar values match what keeptradecut.com displays
              // for the TE++ board.  Falls back to
              // ``canonicalSiteValues.ktcSfTep`` (post PR #406 this
              // equals the raw scrape verbatim — KTC is exempt from
              // the blend-time TE multiplier), then to the legacy
              // ``ktc`` key for pre-#393 fixtures.
              ktcRawValue:
                (typeof p?.rawSourceValues?.ktcSfTep === "number"
                  ? p.rawSourceValues.ktcSfTep
                  : null) ??
                (typeof p?.canonicalSiteValues?.ktcSfTep === "number"
                  ? p.canonicalSiteValues.ktcSfTep
                  : null) ??
                (typeof p?.canonicalSiteValues?.ktc === "number"
                  ? p.canonicalSiteValues.ktc
                  : null),
              idpTradeCalcRawValue:
                typeof p?.canonicalSiteValues?.idpTradeCalc === "number"
                  ? p.canonicalSiteValues.idpTradeCalc
                  : null,
              pos: String(p?.position || p?.pos || "").toUpperCase(),
              assetClass: p?.assetClass,
            }))
            .filter((p) => p.name && p.rawValue > 0)
            .sort((a, b) => b.rawValue - a.rawValue)
            .slice(0, 72);

      if (rookies.length === 0) {
        // Diagnostic: report what we DID find so the operator can
        // tell whether playersArray was missing, the contract had no
        // rookies, or the assetClass/values filter wiped them out.
        const totalPlayers = pa.length;
        const rookieCount = pa.filter((p) => p?.rookie === true).length;
        const offIdpCount = pa.filter(
          (p) => p?.assetClass === "offense" || p?.assetClass === "idp",
        ).length;
        throw new Error(
          `No rookies found in /api/data (players=${totalPlayers}, ` +
            `rookie=${rookieCount}, offense+idp=${offIdpCount}).  Check ` +
            `the backend contract — playersArray/players may be empty or ` +
            `missing rookie/assetClass stamps.`,
        );
      }

      // Per-slot dollar values from the draft-capital workbook,
      // ordered by overallPick.  ``originalDollarValue`` is the
      // unaveraged per-slot price (e.g. 1.01 → $147, 1.02 → $112)
      // — distinct from ``dollarValue`` which spreads expansion-pair
      // picks evenly.  When the workbook isn't reachable, fall back
      // to rescaling raw blended values so sync still works.
      const slotDollarsByPick = (() => {
        const picks = Array.isArray(capitalData?.picks)
          ? capitalData.picks
          : [];
        if (picks.length === 0) return null;
        const sorted = [...picks].sort(
          (a, b) => (a?.overallPick || 0) - (b?.overallPick || 0),
        );
        return sorted
          .map((p) => Number(p?.originalDollarValue ?? p?.dollarValue))
          .filter((n) => Number.isFinite(n) && n > 0);
      })();
      const scaled =
        slotDollarsByPick && slotDollarsByPick.length >= rookies.length
          ? rookies.map((_, i) => slotDollarsByPick[i])
          : rescaleValuesToBudget(
              rookies.map((r) => r.rawValue),
              1200,
            );

      // Per-vendor dollar values — slot-based when the workbook is
      // available, rescaled-to-$1200 otherwise.  The vendor's #N rookie
      // gets the dollar value of pick N: if KTC ranks Carnell Tate #2,
      // KTC values him at pick 1.02's price ($112).  This makes the
      // ``vendorDollar - preDraft`` gap an honest "how many more dollars
      // would a vendor-following leaguemate spend at this slot than my
      // board does" rather than a comparison of two different
      // rescaling schemes.
      const vendorDollarsByName = (rawKey) => {
        const ranked = rookies.filter(
          (r) => Number.isFinite(r[rawKey]) && r[rawKey] > 0,
        );
        if (ranked.length === 0) return new Map();
        const sorted = [...ranked].sort((a, b) => b[rawKey] - a[rawKey]);
        const m = new Map();
        if (slotDollarsByPick && slotDollarsByPick.length >= sorted.length) {
          sorted.forEach((r, i) => m.set(r.name, slotDollarsByPick[i]));
        } else {
          const scaledVendor = rescaleValuesToBudget(
            sorted.map((r) => r[rawKey]),
            1200,
          );
          sorted.forEach((r, i) => m.set(r.name, scaledVendor[i]));
        }
        return m;
      };
      const ktcDollarsByName = vendorDollarsByName("ktcRawValue");
      const idpTradeCalcDollarsByName = vendorDollarsByName(
        "idpTradeCalcRawValue",
      );

      const incoming = rookies.map((r, i) => ({
        name: r.name,
        // Server-provided preDraft (Hill-curve dollar from our value)
        // wins when present; otherwise fall back to slot-mapped scaled[i].
        preDraft: Number.isFinite(Number(r.preDraftFromServer))
          ? Number(r.preDraftFromServer)
          : scaled[i],
        pos: r.pos,
        assetClass: r.assetClass,
        // Per-vendor market dollar values on the same $1200 scale.
        // Server-provided values win when present (single source of
        // truth); otherwise compute client-side from raw vendor values.
        ktcDollar: Number.isFinite(Number(r.ktcDollarFromServer))
          ? Number(r.ktcDollarFromServer)
          : (ktcDollarsByName.get(r.name) ?? null),
        idpTradeCalcDollar: Number.isFinite(
          Number(r.idpTradeCalcDollarFromServer),
        )
          ? Number(r.idpTradeCalcDollarFromServer)
          : (idpTradeCalcDollarsByName.get(r.name) ?? null),
      }));

      // Dry-run against current workspace to show a preview diff.
      const dry = replacePlayerPool(workspace, incoming);
      setSyncPreview({ incoming, dry });
      setSyncOpen(true);
    } catch (err) {
      setSyncError(err?.message || "Sync failed.");
    } finally {
      setSyncBusy(false);
    }
  }, [workspace, selectedLeagueKey]);

  const closeSyncPreview = useCallback(() => {
    setSyncOpen(false);
    setSyncPreview(null);
  }, []);

  const applySyncPreview = useCallback(() => {
    if (!syncPreview) return;
    setWorkspace(() => syncPreview.dry.workspace);
    setSyncOpen(false);
    setSyncPreview(null);
  }, [syncPreview]);

  // Roster gap: whenever selectedTeamIdx (from fetchDraftCapital
  // metadata) and sleeperTeams are resolved, capture the user's
  // current NFL roster so ``computeRosterBreakdown`` has data to
  // work with.  Wired to the same /api/data fetch as the sync
  // feature — no extra network call needed.
  useEffect(() => {
    if (!allPlayersArray) return;
    const myTeamIdx = workspace?.settings?.myTeamIdx ?? 0;
    const myTeamName = workspace?.teams?.[myTeamIdx]?.name || "";
    // Sleeper teams are under the cached /api/data response
    // (rawData.sleeper.teams in other pages) but here we pull the
    // latest fetched snapshot's sleeper section via the
    // playersArray fetch side-effect.  Defer to the user's
    // currently selected team identity by NAME.
    try {
      const url = selectedLeagueKey
        ? `/api/data?leagueKey=${encodeURIComponent(selectedLeagueKey)}`
        : "/api/data";
      fetch(url, { cache: "force-cache" })
        .then((r) => r.json())
        .then((data) => {
          const teams = data?.sleeper?.teams || [];
          // Capture the full Sleeper teams list so the live-draft
          // sync hook can resolve ``picked_by`` (Sleeper user_id) to
          // a workspace team idx by name match.
          setSleeperTeams(teams);
          const mine = teams.find(
            (t) =>
              String(t.name || "").toLowerCase() === myTeamName.toLowerCase(),
          );
          if (mine) setRosterPlayers(mine.players || []);
        })
        .catch(() => {});
    } catch {
      /* ignore */
    }
  }, [
    allPlayersArray,
    workspace?.settings?.myTeamIdx,
    workspace?.teams,
    selectedLeagueKey,
  ]);

  // Global keyboard shortcuts.  Must be declared AFTER the callbacks
  // it depends on (onCycleTag / onToggleTarget / onAddToBoard) —
  // React evaluates a useEffect's dependency array at render time,
  // which would TDZ on the forward-referenced useCallback consts if
  // this block lived higher in the function.  Skipped entirely when
  // focus is in an input/textarea/select so typing player names or
  // budgets doesn't hijack the shortcuts.  Covers:
  //   /      — focus search
  //   ?      — toggle help modal
  //   Esc    — close modal / help
  //   j/↓    — select next undrafted row
  //   k/↑    — select prev undrafted row
  //   D      — open draft modal for selected
  //   N      — cycle tag on selected
  //   T      — toggle target tag (neutral ↔ target) on selected
  //   B      — add selected to Target Board
  useEffect(() => {
    function onKey(e) {
      const tag = (e.target?.tagName || "").toLowerCase();
      const editable =
        tag === "input" || tag === "textarea" || tag === "select";
      if (editable) return;

      if (e.key === "/") {
        e.preventDefault();
        searchInputRef.current?.focus();
        return;
      }
      if (e.key === "?") {
        e.preventDefault();
        setHelpOpen((o) => !o);
        return;
      }
      if (e.key === "Escape") {
        if (helpOpen) setHelpOpen(false);
        return;
      }

      const undrafted = stats.enrichedPlayers.filter((p) => !p.drafted);
      if (undrafted.length === 0) return;

      const idx = selectedPlayerId
        ? undrafted.findIndex((p) => p.id === selectedPlayerId)
        : -1;

      if (e.key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        const next =
          undrafted[Math.min(idx + 1, undrafted.length - 1)] || undrafted[0];
        setSelectedPlayerId(next.id);
        return;
      }
      if (e.key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        const next = undrafted[Math.max(idx - 1, 0)] || undrafted[0];
        setSelectedPlayerId(next.id);
        return;
      }

      if (!selectedPlayerId) return;
      const selected = undrafted.find((p) => p.id === selectedPlayerId);
      if (!selected) return;

      if (e.key === "d" || e.key === "D") {
        e.preventDefault();
        setModalPlayer(selected);
        return;
      }
      if (e.key === "n" || e.key === "N") {
        e.preventDefault();
        onCycleTag(selected.id);
        return;
      }
      if (e.key === "t" || e.key === "T") {
        e.preventDefault();
        onToggleTarget(selected.id);
        return;
      }
      if (e.key === "b" || e.key === "B") {
        e.preventDefault();
        onAddToBoard(selected.id);
        return;
      }
      if (e.key === "q" || e.key === "Q") {
        // Speed-mode quick-record: toggles an inline form on the
        // selected row.  Cancels if already open on the same row.
        e.preventDefault();
        setQuickRecordingId((cur) =>
          cur === selected.id ? null : selected.id,
        );
        return;
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [
    helpOpen,
    selectedPlayerId,
    stats.enrichedPlayers,
    onCycleTag,
    onToggleTarget,
    onAddToBoard,
  ]);

  const handleModalSubmit = useCallback((payload) => {
    if (payload?._remove) {
      setWorkspace((ws) => removePick(ws, payload.playerId));
    } else if (payload?._nominate) {
      // Nomination logger — record + keep modal open so the user
      // can continue setting up (e.g. still intends to bid on
      // this player themselves).  No ``setModalPlayer(null)``.
      setWorkspace((ws) =>
        recordNomination(ws, {
          playerId: payload.playerId,
          nominatingTeamIdx: payload.teamIdx,
        }),
      );
      return;
    } else if (payload?._removeNomination) {
      setWorkspace((ws) => removeNomination(ws, payload.playerId));
      return;
    } else {
      setWorkspace((ws) => recordPick(ws, payload));
    }
    setModalPlayer(null);
  }, []);

  function handleReset() {
    if (
      typeof window !== "undefined" &&
      window.confirm(
        "Reset the draft board? This clears every pick and restores default values.",
      )
    ) {
      setWorkspace(createDefaultWorkspace());
    }
  }

  if (checking || authenticated == null) {
    return (
      <main className={`main-shell ${styles.page}`}>
        {/* Same three constants as the settled header below — they are
            constants, not data, so rendering them here is the honest
            value rather than a placeholder.  Omitting the description
            made the header 45px while auth resolved and 87px afterwards
            (it wraps to two lines at the 60ch measure), dropping 42px of
            content on top of every band below it — the actual bulk of
            /draft's 0.32 CLS, which the band reservations underneath
            could not reach.  Shared constants rather than duplicated
            literals so the two headers cannot drift back into different
            heights when the copy is next revised. */}
        <PageHeader
          eyebrow={DRAFT_PAGE_EYEBROW}
          title={DRAFT_PAGE_TITLE}
          description={DRAFT_PAGE_DESCRIPTION}
        />
        {/* Mirrors the SETTLED board's top-of-page bands, not a generic
            table.  The real board renders a progress bar (26px), then
            the stats strip (105px), then the teams/knobs grid — and
            none of it exists while auth is resolving.  A generic
            skeleton here meant ~131px of content appeared ABOVE the
            team list when the board mounted, pushing the whole page
            down: /draft's 0.32 CLS.  Heights are the measured settled
            values. */}
        <div style={{ minHeight: 26 }} aria-hidden="true" />
        <div style={{ minHeight: 105 }} aria-hidden="true" />
        <Panel>
          <SkeletonTable rows={10} columns={5} />
        </Panel>
      </main>
    );
  }
  if (authenticated === false) {
    return null;
  }

  // Re-enrich the modal player against current stats each render so the
  // modal's reference prices stay in sync with live inflation as other
  // picks are recorded.
  const modalPlayerEnriched = modalPlayer
    ? stats.enrichedPlayers.find((p) => p.id === modalPlayer.id) || null
    : null;

  return (
    <main className={`main-shell ${styles.page} draft-page`}>
      <PageHeader
        eyebrow={DRAFT_PAGE_EYEBROW}
        title={DRAFT_PAGE_TITLE}
        description={DRAFT_PAGE_DESCRIPTION}
        actions={
          <div className={styles.pageActions}>
            <DraftGlossary />
            <LiveSyncToggle
              enabled={liveSyncEnabled}
              onToggle={() => setLiveSyncEnabled(!liveSyncEnabled)}
              status={liveSync.status}
              error={liveSync.error}
              lastSyncAt={liveSync.lastSyncAt}
              latestPickNo={liveSync.latestPickNo}
            />
            <Button
              size="sm"
              onClick={fetchSyncPreview}
              disabled={syncBusy}
              loading={syncBusy}
              title="Pull current rookie values from our live consensus rankings"
            >
              Sync rookies
            </Button>
            <Button
              size="sm"
              onClick={() => setReviewOpen(true)}
              disabled={(workspace.picks || []).length === 0}
              title="Show the post-draft review (deltas, rankings, CSV)"
            >
              Review
            </Button>
            <Button
              size="sm"
              onClick={() => setHelpOpen(true)}
              title="Keyboard shortcuts (?)"
              aria-label="Keyboard shortcuts"
            >
              Shortcuts
            </Button>
            <Button
              size="sm"
              onClick={() => setWorkspace((ws) => undoLastPick(ws))}
              disabled={(workspace.picks || []).length === 0}
              title="Undo the most recent pick"
            >
              Undo last
            </Button>
            <Button size="sm" variant="danger" onClick={handleReset}>
              Reset
            </Button>
          </div>
        }
      />

      <ValueBasisNote contract={rawData} />

      {syncError ? (
        <Banner
          tone="negative"
          title="Sync error"
          onDismiss={() => setSyncError("")}
        >
          {syncError}
        </Banner>
      ) : null}

      {/* Alert stack — sticky banners for threshold-crossing events.
          Render newest-first so the latest signal is always on top.
          Color-coded: danger (red) for budget collapse, warn (cyan)
          for tier / overpay events, info (blush) for favorable
          moves.  Each has an X to dismiss; "Clear all" wipes the
          whole stack. */}
      {alerts.length > 0 && (
        <div className="draft-alert-stack">
          <div className={styles.signalHead}>
            <span className={styles.signalTitle}>Signals</span>
            {alerts.length > 1 && (
              <Button variant="ghost" size="sm" onClick={clearAllAlerts}>
                Clear all
              </Button>
            )}
          </div>
          {alerts
            .slice()
            .reverse()
            .slice(0, 5)
            .map((a) => (
              <div key={a.id} className={`draft-alert draft-alert-${a.level}`}>
                <span className="draft-alert-msg">{a.message}</span>
                <button
                  type="button"
                  className="button-reset draft-alert-close"
                  onClick={() => dismissAlert(a.id)}
                  aria-label="Dismiss"
                >
                  ×
                </button>
              </div>
            ))}
        </div>
      )}

      {/* Roster-gap strip — surfaces positional shortages vs my
          current NFL roster.  Hidden until /api/data has resolved
          and we've mapped the user's team. */}
      {rosterPlayers && rosterBreakdown.needPositions.length > 0 && (
        <div className={styles.needStrip}>
          <span>Roster needs:</span>
          {rosterBreakdown.needPositions.map((pos) => (
            <Badge key={pos} tone="warning">
              {pos} −{rosterBreakdown.shortages[pos]}
            </Badge>
          ))}
          <span>positions below threshold, factored into target priority</span>
        </div>
      )}

      {/* Draft progress bar — rookies sold vs the size of the rookie
          pool.  (It used to divide by a 12-teams x 6-slots constant,
          which described a per-team pick cap this league does not have.)
          Sits above the stats strip so the user has constant
          peripheral awareness of "how far in are we?" — which drives
          every late-draft decision. */}
      <div
        className={styles.progress}
        role="group"
        aria-label={`${stats.totalPicksMade} of ${stats.rookiePoolSize} rookies drafted`}
      >
        <div className={styles.progressTrack}>
          <div
            className={styles.progressFill}
            style={{ width: `${Math.min(100, stats.draftProgress * 100)}%` }}
          />
        </div>
        <div className={styles.progressLabels}>
          <span>
            Pick <strong>{stats.totalPicksMade}</strong> of{" "}
            <strong>{stats.rookiePoolSize}</strong>
          </span>
          <span>{Math.round(stats.draftProgress * 100)}% through draft</span>
        </div>
      </div>

      <StatsStrip stats={stats} historySeries={historySeries} />

      <div className={styles.topGrid}>
        <TeamPanel
          stats={stats}
          workspace={workspace}
          onSettings={onSettings}
          onTeam={onTeam}
          onLoadCapital={fetchDraftCapital}
          capitalStatus={capitalStatus}
        />
        <BidKnobs settings={workspace.settings || {}} onSettings={onSettings} />
      </div>

      {/* Late-draft triage banner — visible once the auto-filter
          fires.  Tells the user what just happened and offers an
          "escape hatch" back to the full view.  Dismiss persists
          within the session; reload resets to auto-behavior. */}
      {triageApplied && !triageDismissed ? (
        <Banner
          tone="warning"
          title="Late-draft triage"
          onDismiss={() => setTriageDismissed(true)}
        >
          {Math.round((stats.draftProgress || 0) * 100)}% of the board is gone
          — auto-filtered to your Targets so you only see players you still
          want.{" "}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setTagFilter("all");
              setTriageDismissed(true);
            }}
          >
            Show all
          </Button>
        </Banner>
      ) : null}

      <ParSheet
        stats={stats}
        workspace={workspace}
        onAdd={onAddToParSheet}
        onRemove={onRemoveFromParSheet}
        onEditFV={onEditParSheetFV}
        onMove={onMoveInParSheet}
        onClear={onClearParSheet}
        onDraft={(p) => setModalPlayer(p)}
      />

      <TargetBoard
        stats={stats}
        workspace={workspace}
        onAdd={onAddToBoard}
        onRemove={onRemoveFromBoard}
        onMove={onMoveInBoard}
        onClear={onClearBoard}
        onDraft={(p) => setModalPlayer(p)}
      />

      <div className={styles.sidebarGrid}>
        <NextBestTargets
          stats={stats}
          onDraft={(p) => setModalPlayer(p)}
          onCycleTag={onCycleTag}
          workspace={workspace}
        />
        <NominationCandidates
          stats={stats}
          onDraft={(p) => setModalPlayer(p)}
          onCycleTag={onCycleTag}
        />
        <BestValueOnBoard
          stats={stats}
          onDraft={(p) => setModalPlayer(p)}
          onCycleTag={onCycleTag}
        />
      </div>

      <Suspense fallback={null}>
        <PerfectDraftPanel stats={stats} workspace={workspace} />
      </Suspense>

      <RookieBoard
        stats={stats}
        workspace={workspace}
        marketDollars={marketDollars}
        onDraft={(p) => setModalPlayer(p)}
        onEditPreDraft={onEditPreDraft}
        onRemovePlayer={onRemovePlayer}
        onCycleTag={onCycleTag}
        searchInputRef={searchInputRef}
        selectedPlayerId={selectedPlayerId}
        onSelectRow={setSelectedPlayerId}
        quickRecordingId={quickRecordingId}
        onQuickOpen={(id) => setQuickRecordingId(id)}
        onQuickSubmit={recordQuickPick}
        onQuickCancel={() => setQuickRecordingId(null)}
        needSet={needSet}
        showDrafted={showDrafted}
        onShowDraftedChange={setShowDrafted}
        query={query}
        onQueryChange={setQuery}
        tagFilter={tagFilter}
        onTagFilterChange={setTagFilter}
        onAdd={onAdd}
        bdvmIndex={bdvmIndex}
      />

      {bdvmPickRows.length > 0 && (
        <CollapsiblePanel
          title="Fundamental pick values (BDVM)"
          subtitle="Rookie-pick EV in the balanced strategy currency — hit rate and outcome spread from the fundamental model, market anchor beside it"
          defaultCollapsed
        >
          <div className="draft-table-wrap">
            <table className="draft-table">
              <thead>
                <tr>
                  <th style={{ textAlign: "left" }}>Pick</th>
                  <th style={{ width: 90, textAlign: "right" }}>EV</th>
                  <th
                    style={{ width: 80, textAlign: "right" }}
                    title="Probability the pick returns a startable player"
                  >
                    Hit %
                  </th>
                  <th style={{ width: 90, textAlign: "right" }}>Median</th>
                  <th style={{ width: 90, textAlign: "right" }}>Ceiling</th>
                  <th style={{ width: 100, textAlign: "right" }}>Market</th>
                </tr>
              </thead>
              <tbody>
                {bdvmPickRows.map((row) => (
                  <tr key={row.name}>
                    <td>{row.name}</td>
                    <td className="draft-money">{formatBdvmValue(row.ev)}</td>
                    <td className="draft-money">
                      {row.pHit == null
                        ? "—"
                        : `${Math.round(row.pHit * 100)}%`}
                    </td>
                    <td className="draft-money">
                      {formatBdvmValue(row.median)}
                    </td>
                    <td className="draft-money">
                      {formatBdvmValue(row.ceiling)}
                    </td>
                    <td
                      className="draft-money"
                      title={row.marketSource || undefined}
                    >
                      {formatBdvmValue(row.marketValue)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p
            className="muted"
            style={{
              margin: "var(--space-2) 0 0",
              fontSize: "var(--font-size-2xs)",
            }}
          >
            Fundamental (projection-driven) values — compared against the
            market, never merged into the auction math above.
          </p>
        </CollapsiblePanel>
      )}

      {modalPlayerEnriched && (
        <DraftModal
          player={modalPlayerEnriched}
          workspace={workspace}
          stats={stats}
          onClose={() => setModalPlayer(null)}
          onSubmit={handleModalSubmit}
        />
      )}

      {syncOpen && syncPreview && (
        <Modal
          open
          onClose={closeSyncPreview}
          title="Sync rookies from consensus rankings"
        >
          <div className="draft-modal-body">
            <div className="muted" style={{ fontSize: "0.78rem" }}>
              Pulled top <strong>{syncPreview.incoming.length}</strong> rookies
              from ``/api/data``, rescaled their consensus values to total
              $1,200. Applying will:
            </div>
            <ul style={{ fontSize: "0.82rem", margin: "8px 0" }}>
              <li>
                <strong>Kept:</strong> {syncPreview.dry.kept} rookies already on
                your board (tags + Target Board slots preserved)
              </li>
              <li>
                <strong>Added:</strong> {syncPreview.dry.added} new rookies
              </li>
              <li>
                <strong>Dropped:</strong> {syncPreview.dry.dropped} rookies no
                longer in the top {syncPreview.incoming.length}
              </li>
              {syncPreview.dry.orphanedPicks.length > 0 && (
                <li style={{ color: "var(--red)" }}>
                  <strong>
                    {syncPreview.dry.orphanedPicks.length} recorded pick
                    {syncPreview.dry.orphanedPicks.length === 1 ? "" : "s"}
                  </strong>{" "}
                  reference dropped players — those picks will be removed.
                  Cancel if that's not what you want.
                </li>
              )}
            </ul>
            <div
              className="muted"
              style={{ fontSize: "0.72rem", marginTop: 6 }}
            >
              New rookie list (first 10 of {syncPreview.incoming.length}):
              <div style={{ marginTop: 4 }}>
                {syncPreview.incoming.slice(0, 10).map((p, i) => (
                  <div
                    key={p.name}
                    style={{
                      display: "grid",
                      gridTemplateColumns: "24px 1fr 48px 48px",
                      gap: 6,
                      padding: "2px 0",
                      fontSize: "0.76rem",
                    }}
                  >
                    <span>#{i + 1}</span>
                    <span>{p.name}</span>
                    <span className="muted">{p.pos || "—"}</span>
                    <span className="draft-money">{fmt$(p.preDraft)}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
          <div className="draft-modal-footer">
            <Button onClick={closeSyncPreview}>Cancel</Button>
            <Button variant="primary" onClick={applySyncPreview}>
              Apply sync
            </Button>
          </div>
        </Modal>
      )}

      {reviewOpen && (
        <DraftReviewPanel
          workspace={workspace}
          stats={stats}
          onClose={() => setReviewOpen(false)}
        />
      )}

      {helpOpen && (
        <Modal
          open
          onClose={() => setHelpOpen(false)}
          title="Keyboard shortcuts"
        >
          <div className="draft-modal-body">
            <table className="draft-help-table">
              <tbody>
                <tr>
                  <td>
                    <kbd>/</kbd>
                  </td>
                  <td>Focus search</td>
                </tr>
                <tr>
                  <td>
                    <kbd>?</kbd>
                  </td>
                  <td>Open this help</td>
                </tr>
                <tr>
                  <td>
                    <kbd>Esc</kbd>
                  </td>
                  <td>Close modal / help</td>
                </tr>
                <tr>
                  <td>
                    <kbd>j</kbd> / <kbd>↓</kbd>
                  </td>
                  <td>Select next undrafted player</td>
                </tr>
                <tr>
                  <td>
                    <kbd>k</kbd> / <kbd>↑</kbd>
                  </td>
                  <td>Select previous undrafted player</td>
                </tr>
                <tr>
                  <td>
                    <kbd>D</kbd>
                  </td>
                  <td>Open Draft modal for selected</td>
                </tr>
                <tr>
                  <td>
                    <kbd>N</kbd>
                  </td>
                  <td>Cycle tag (neutral → target → avoid) on selected</td>
                </tr>
                <tr>
                  <td>
                    <kbd>T</kbd>
                  </td>
                  <td>Toggle target tag (neutral ↔ target) on selected</td>
                </tr>
                <tr>
                  <td>
                    <kbd>B</kbd>
                  </td>
                  <td>Add selected to Target Board</td>
                </tr>
                <tr>
                  <td>
                    <kbd>Q</kbd>
                  </td>
                  <td>
                    Quick-record pick on selected (inline form; Enter saves, Esc
                    cancels)
                  </td>
                </tr>
              </tbody>
            </table>
            <div
              className="muted"
              style={{ fontSize: "0.72rem", marginTop: 8 }}
            >
              Shortcuts are inactive while typing in any input, textarea, or
              select. Click a row on the Rookie Board to select it (keyboard
              shortcuts target the selected row).
            </div>
          </div>
          <div className="draft-modal-footer">
            <Button onClick={() => setHelpOpen(false)}>Close</Button>
          </div>
        </Modal>
      )}
    </main>
  );
}
